"""Test every claim the tool descriptions make, against real SUMO runs.

    python test_claims.py          # about 3 minutes; prints PASS/FAIL per claim, exit code 1 if any fail

A description is a promise to the model. If a sentence in a docstring is not tested here, it is a guess.
The second half tests what api_shaped_tools.py's docstrings (copied from TraCI) leave out or get wrong.
"""
import os, sys, json, math
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import sumo_agent_tools as T
import api_shaped_tools as A
import traci, sumolib

RESULTS = []


def claim(text):
    def wrap(f):
        try:
            detail = f()
            RESULTS.append((True, text, detail or ''))
        except AssertionError as e:
            RESULTS.append((False, text, str(e)))
        except Exception as e:
            RESULTS.append((False, text, f'{type(e).__name__}: {e}'))
        finally:
            if T._LIVE.get('on'):
                T.stop_live()
        return f
    return wrap


# ---------------------------------------------------------------- engineer-shaped tools
@claim('list_intersections names the 6 signals by cross streets; a short name resolves, an ambiguous one lists all')
def _():
    txt = T.list_intersections()
    assert txt.startswith('6 signals'), txt[:40]
    tid, name = T._resolve('Fowler & McKinley')
    assert name == 'E Fowler Ave & McKinley Dr', name
    try:
        T._resolve('Fowler')
        raise AssertionError('"Fowler" alone should be ambiguous')
    except ValueError as e:
        assert 'matches 4 signals' in str(e) and 'McKinley' in str(e), str(e)[:120]
    return name


@claim('advance runs forward by the given seconds, relative to now')
def _():
    T.start_live()
    T.advance(120)
    T.advance(50)
    t = traci.simulation.getTime()
    assert t == 170, t
    return f'120 s then 50 s -> {t:.0f} s'


@claim('advance: change in vehicles in the network = entered - left')
def _():
    T.start_live()
    T.advance(1200)
    txt = T.advance(300)
    a, b = txt.split('network ')[1].split(' vehicles')[0].split(' -> ')
    dep, arr = int(txt.split(': ')[1].split(' entered')[0]), int(txt.split(' entered, ')[1].split(' left')[0])
    assert int(b) - int(a) == dep - arr, txt
    return txt[:120]


@claim('get_approach_state reports "no vehicles (speed not measured)" on an empty block, not the speed limit')
def _():
    T.start_live()
    T.advance(1)
    txt = T.get_approach_state('Leroy Collins & Alumni', 'WB')
    assert 'no vehicles (speed not measured)' in txt, txt
    return txt[:110]


@claim('readings outside the analysis hour carry a WARM-UP or AFTER-PEAK warning; inside it they do not')
def _():
    T.start_live()
    T.advance(1)
    early = T.get_approach_state('Fowler & 30th', 'WB')
    early_c = T.get_corridor_state('WB')
    T.advance(899)
    peak = T.get_approach_state('Fowler & 30th', 'WB')
    T.advance(3600)
    T.advance(1)                    # 4501 s
    after = T.get_approach_state('Fowler & 30th', 'WB')
    assert 'WARM-UP WARNING' in early and 'WARM-UP WARNING' in early_c, early
    assert 'WARNING' not in peak and 'AFTER-PEAK WARNING' in after, (peak, after)
    return early[early.index('WARM-UP'):][:40] + ' | ' + after[after.index('AFTER-PEAK'):][:40]


@claim('get_approach_state states the spillback verdict either way, with the share of storage')
def _():
    T.start_live()
    T.advance(1800)
    txt = T.get_approach_state('Fowler & 30th', 'WB')
    assert 'No spillback: the queue fills' in txt or 'SPILLBACK: the queue fills' in txt, txt
    return txt[txt.index('pillback'):][:60]


@claim('start_live(gui=True) on a computer without a screen says to use gui=false, at once')
def _():
    if not sys.platform.startswith('linux'):
        return 'skipped: not Linux'
    saved = {k: os.environ.pop(k, None) for k in ('DISPLAY', 'WAYLAND_DISPLAY')}
    try:
        txt = T.start_live(gui=True)
    finally:
        os.environ.update({k: v for k, v in saved.items() if v})
    assert txt.startswith('Error: sumo-gui needs a screen') and 'gui=false' in txt, txt
    return txt[:70]


@claim('queue rule: slower than 5 km/h and within 10 m of the queue ahead, in any lane')
def _():
    v = [(0.5, 5, 0.0), (8.0, 5, 0.5), (20.0, 5, 1.0), (40.0, 5, 0.0), (12.0, 5, 3.0)]
    back, n = T._queue_back(v)       # 0.5..5.5, 8..13, then 20 is 7 m behind 13 -> in; 40 is 15 m behind 25 -> out
    assert (round(back, 1), n) == (25.0, 3), (back, n)
    return f'back {back} m, {n} vehicles'


@claim('the back of queue uses the same thresholds as SUMO\'s E2 detector: on a single-lane approach they agree')
def _():
    T.start_live()
    T.advance(900)
    tid, _ = T._resolve('Leroy Collins & Alumni')
    edge = T._approaches(tid)['SB']
    dets = [d for d in traci.lanearea.getIDList() if traci.lanearea.getLaneID(d).rsplit('_', 1)[0] == edge.getID()]
    agree = n = 0
    for _ in range(900):
        traci.simulationStep()
        lane_ids = {traci.lanearea.getLaneID(d): d for d in dets}
        for lane, det in lane_ids.items():
            veh = [(edge.getLength() - traci.vehicle.getLanePosition(x), traci.vehicle.getLength(x), traci.vehicle.getSpeed(x))
                   for x in traci.lane.getLastStepVehicleIDs(lane)]
            ours, _ = T._queue_back(veh)
            e2 = traci.lanearea.getJamLengthMeters(det)
            pos_end = traci.lanearea.getPosition(det) + traci.lanearea.getLength(det)
            if 0 < ours < traci.lanearea.getLength(det) - 10:
                n += 1
                agree += abs((ours - (edge.getLength() - pos_end)) - e2) <= 7.5 or abs(ours - e2) <= 7.5
    assert n > 50 and agree / n >= 0.8, (agree, n)
    return f'{agree} of {n} lane-seconds within one car length (7.5 m)'


@claim('set_signal_timing rejects a green below the pedestrian minimum and changes nothing')
def _():
    T.start_live()
    T.advance(10)
    tid, _ = T._resolve('Fowler & McKinley')
    before = [p.duration for p in traci.trafficlight.getAllProgramLogics(tid)[0].phases]
    r = T.set_signal_timing('Fowler & McKinley', {'4': 15})
    after = [p.duration for p in traci.trafficlight.getAllProgramLogics(tid)[0].phases]
    assert r.startswith('Rejected') and 'crosswalk' in r and before == after, r
    return r[:140]


@claim('set_signal_timing applies a plan that meets every minimum')
def _():
    T.start_live()
    T.advance(10)
    tid, _ = T._resolve('Fowler & McKinley')
    r = T.set_signal_timing('Fowler & McKinley', {'0': 40})
    assert 'new plan' in r and traci.trafficlight.getAllProgramLogics(tid)[0].phases[0].duration == 40, r
    return r


@claim('get_signal_plan flags a yellow shorter than the ITE change interval')
def _():
    T.start_live()
    r = T.get_signal_plan('Leroy Collins & Alumni')
    assert 'SHORTER THAN ITE' in r, r
    return [l for l in r.splitlines() if 'ITE' in l][0].strip()


@claim('take_screenshot without the GUI returns an error, not a crash')
def _():
    T.start_live()
    r = T.run_tool('take_screenshot', {})
    assert r.startswith('Error: no GUI'), r
    return r


@claim('webster_timing: the script\'s raw plan breaks minimums; the checked plan breaks none')
def _():
    T.webster_timing()
    raw, chk = T._plan_problems('webster_raw'), T._plan_problems('webster')
    assert raw and not chk, (len(raw), chk)
    return f'raw {len(raw)} problems, checked 0'


@claim('compare_plans: blocked without an engineer\'s approval; one seed and rule-breaking plans are rejected')
def _():
    keep = open(T.APPROVAL).read() if os.path.exists(T.APPROVAL) else None
    if keep:
        os.remove(T.APPROVAL)
    try:
        assert T.compare_plans('webster').startswith('Blocked')
        assert T.compare_plans('webster', seeds=1).startswith('Rejected')
        json.dump({'demand': 'demand', 'engineer': 'test'}, open(T.APPROVAL, 'w'))
        r = T.compare_plans('webster_raw', seeds=2)
        assert r.startswith('Rejected') and 'crosswalk' in r, r
    finally:
        os.remove(T.APPROVAL)
        if keep:
            open(T.APPROVAL, 'w').write(keep)
    return 'blocked / rejected as described'


@claim('check_calibration: random demand fails, demand rebuilt from counts with the prior passes (1 seed)')
def _():
    r1 = T.check_calibration('random', seeds=1)
    r2 = T.check_calibration('demand', seeds=1)
    assert 'FAIL' in r1 and 'PASS' in r2, (r1[:90], r2[:90])
    return r1.split(':')[1].split(';')[0].strip() + ' | ' + r2.split(':')[1].split(';')[0].strip()


@claim('every tool has a description and a JSON schema; run_tool turns errors into text')
def _():
    assert all(t['description'] and t['input_schema']['type'] == 'object' for t in T.TOOLS)
    assert T.run_tool('no_such_tool', {}).startswith('Error: there is no tool')
    no_sim = T.run_tool('advance', {'seconds': 10})
    assert no_sim.startswith('Error: No live simulation') and 'You can start one yourself' in no_sim, no_sim
    return f'{len(T.TOOLS)} tools'


# ---------------------------------------------------------------- what the API docstrings leave out
@claim('API trap: an empty lane reports the speed limit as its "average speed"')
def _():
    T.start_live()
    traci.simulationStep()
    lane = '-111773847_0'
    n, v, lim = A.get_lane_vehicle_number(lane), A.get_lane_mean_speed(lane), traci.lane.getMaxSpeed(lane)
    assert n == 0 and v == lim, (n, v, lim)
    return f'{n} vehicles, "average speed" {v / T.MPH:.0f} mph = the limit'


@claim('API trap: lane occupancy is a fraction (0-1), although the docstring says %')
def _():
    T.start_live()
    T.advance(1500)
    for l in traci.lane.getIDList():
        vs = traci.lane.getLastStepVehicleIDs(l)
        if l.startswith(':') or len(vs) < 5 or traci.lane.getLength(l) < 60:
            continue
        if all(traci.vehicle.getLanePosition(x) >= traci.vehicle.getLength(x) for x in vs):
            share = sum(traci.vehicle.getLength(x) for x in vs) / traci.lane.getLength(l)
            occ = A.get_lane_occupancy(l)
            assert abs(occ - share) < 0.01 and occ <= 1, (occ, share)
            return f'{l}: returned {occ:.3f}; vehicles cover {share:.1%} of the lane'
    raise AssertionError('no suitable lane found')


@claim('API trap: simulationStep(t) runs to the ABSOLUTE time t; a past t does nothing')
def _():
    T.start_live()
    A.simulation_step(120)
    t = A.simulation_step(50)
    assert t == 120, t
    return 'at 120 s, simulation_step(50) -> still 120 s'


@claim('API trap: setPhaseDuration changes this phase once; the next cycle is back to the plan')
def _():
    T.start_live()
    tid, _ = T._resolve('Fowler & McKinley')
    while not (traci.trafficlight.getPhase(tid) == 0 and traci.trafficlight.getSpentDuration(tid) == 0):
        traci.simulationStep()
    A.set_phase_duration(tid, 60)
    first = traci.trafficlight.getNextSwitch(tid) - traci.simulation.getTime()
    while traci.trafficlight.getPhase(tid) == 0:
        traci.simulationStep()
    while traci.trafficlight.getPhase(tid) != 0:
        traci.simulationStep()
    second = traci.trafficlight.getNextSwitch(tid) - traci.simulation.getTime() + 1
    assert first == 60 and second == 35, (first, second)
    return f'this phase {first:.0f} s, next cycle {second:.0f} s'


@claim('API trap: sumolib.net.readNet reads no signal plans unless withPrograms=True')
def _():
    tid = T._resolve('Fowler & McKinley')[0]
    n = len(A.get_signal_program(T.SCENARIO['net'], tid))
    assert n == 0, n
    return 'readNet(net) -> 0 phases'


@claim('API trap: --end is ignored when TraCI drives SUMO')
def _():
    traci.start([os.path.join(T.BIN, 'sumo'), '-n', T.SCENARIO['net'], '-r', T.SCENARIO['demands']['demand'],
                 '--end', '300', '--no-step-log', '--no-warnings'])
    for _ in range(400):
        traci.simulationStep()
    t = traci.simulation.getTime()
    traci.close()
    assert t == 400, t
    return '--end 300, reached 400 s'


if __name__ == '__main__':
    bad = 0
    for ok, text, detail in RESULTS:
        bad += not ok
        print(('PASS ' if ok else 'FAIL ') + text + (f'\n       {detail}' if detail else ''))
    print(f'\n{len(RESULTS) - bad} of {len(RESULTS)} claims pass')
    json.dump([{'ok': ok, 'claim': t, 'detail': str(d)} for ok, t, d in RESULTS],
              open(os.path.join(HERE, 'claims_result.json'), 'w'), indent=1)
    sys.exit(1 if bad else 0)
