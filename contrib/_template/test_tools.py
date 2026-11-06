"""Tests for the template tool: one test per rule in KNOWLEDGE.md, and one that compares the plain version with
the engineer's. They run one live simulation (demand 'demand', seed 1), so everyone gets the same answers:

    python contrib/<you>/test_tools.py          # or: python contrib/check.py contrib/<you>

Each test is a function whose name starts with test_. A test passes when it runs without an AssertionError.
Write each assert with a message (after the comma) that shows what the tool returned, so a failure explains itself.
Tests run in the order they are written; teardown() runs once at the end.
"""
import os, sys
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE); sys.path.insert(0, os.path.join(HERE, '..', '..'))
import traci
import tools as M
import sumo_agent_tools as T


def at(t):
    """The live simulation at time t (s). Started once and reused: reading tools do not change it, and SUMO is
    deterministic for a given demand and seed. A later test can go forward in time, never back."""
    if not T._LIVE.get('on') or traci.simulation.getTime() > t:
        T.start_live(demand='demand', seed=1)
    now = traci.simulation.getTime()
    if now < t:
        T.advance(int(t - now))


def lines(txt):
    return [l.strip() for l in txt.split('\n')[2:]]          # one line per lane, median first


def test_warmup_warning():
    at(300)
    out = M.lane_use('Fowler & McKinley', 'WB')
    assert 'WARM-UP WARNING' in out, out[:300]
    at(1800)
    assert 'WARNING' not in M.lane_use('Fowler & McKinley', 'WB')


def test_lanes_from_median_named_by_movement():
    at(1800)
    out = lines(M.lane_use('Bruce B Downs & Pine', 'NB'))
    assert out[-1].startswith('5 (curb): right-turn lane'), out
    tid, _ = T._resolve('Bruce B Downs & Pine')
    curb = T._approaches(tid)['NB'].getLanes()[0]               # SUMO lane index 0
    assert curb.getIndex() == 0 and {c.getDirection() for c in curb.getOutgoing()} == {'r'}, 'index 0 is the curb lane'
    sb = lines(M.lane_use('Bruce B Downs & Pine', 'SB'))
    assert sb[0].startswith('1 (median side): left-turn lane'), sb


def test_lane_without_movement_not_counted():
    at(1800)
    out = M.lane_use('Fowler & Leroy Collins', 'EB')
    assert '3 of 5 lanes serve a movement (3 through lanes)' in out, out
    tid, _ = T._resolve('Fowler & Leroy Collins')
    dead = [l.getIndex() for l in T._approaches(tid)['EB'].getLanes() if not l.getOutgoing()]
    assert dead == [3, 4], dead
    assert sum('no movement' in l for l in lines(out)) == 2, out


def test_empty_lane_has_no_speed():
    at(1800)
    out = lines(M.lane_use('Bruce B Downs & Pine', 'SB'))
    assert out[2].endswith('through lane: no vehicles (speed not measured)'), out
    tid, _ = T._resolve('Bruce B Downs & Pine')
    lane = T._approaches(tid)['SB'].getLanes()[2].getID()        # the same lane, by SUMO's index
    assert traci.lane.getLastStepVehicleNumber(lane) == 0
    assert abs(traci.lane.getLastStepMeanSpeed(lane) - traci.lane.getMaxSpeed(lane)) < 0.01, \
        'SUMO reports the speed limit on an empty lane'


def test_stopped_is_sumo_halting():
    at(1800)
    for where, app in [('Bruce B Downs & Pine', 'SB'), ('Bruce B Downs & Pine', 'NB'), ('Fowler & Bull Run', 'EB'),
                       ('Fowler & Leroy Collins', 'WB')]:
        tid, _ = T._resolve(where)
        lanes = sorted(T._approaches(tid)[app].getLanes(), key=lambda l: -l.getIndex())
        for line, lane in zip(lines(M.lane_use(where, app)), lanes):
            if ' stopped' in line:
                said = int(line.split(', ')[1].split(' stopped')[0])
                assert said == traci.lane.getLastStepHaltingNumber(lane.getID()), (where, app, line)


def test_reads_only():
    at(1800)
    t, n = traci.simulation.getTime(), traci.vehicle.getIDCount()
    M.lane_use('Fowler & McKinley', 'WB')
    assert (traci.simulation.getTime(), traci.vehicle.getIDCount()) == (t, n)


def test_wrong_approach_says_which_exist():
    at(1800)
    out = M.lane_use('Fowler & McKinley', 'SB')
    assert out.startswith('Error:') and "['EB', 'NB', 'WB']" in out, out


def test_plain_vs_lane_use():
    # Bruce B Downs & Pine SB at 1800 s: the plain getters say three lanes run at 20.12 m/s (45 mph) with nobody
    # halting, which reads as free flow. Two are empty through lanes, one serves no movement at all, and the queue
    # is 6 stopped vehicles in the left-turn lane, which SUMO calls lane 4 because it counts from the curb.
    at(1800)
    plain = M.lane_use_plain('Bruce B Downs & Pine', 'SB').split('\n')
    assert plain[1].endswith('halting 0, mean speed 20.12 m/s') and plain[4].endswith('halting 6, mean speed 0.00 m/s'), plain
    mine = lines(M.lane_use('Bruce B Downs & Pine', 'SB'))
    assert mine[0] == '1 (median side): left-turn lane: 6 vehicles, 6 stopped, 0 mph space-mean speed', mine
    assert mine[1].startswith('2: no movement') and 'no vehicles (speed not measured)' in mine[2], mine


def teardown():
    T.stop_live()


if __name__ == '__main__':
    tests = [(n, f) for n, f in list(globals().items()) if n.startswith('test_') and callable(f)]
    bad = 0
    for n, f in tests:
        try:
            f(); print('PASS', n)
        except Exception as e:
            bad += 1; print('FAIL', n, '\n    ', type(e).__name__, str(e)[:400])
    teardown()
    print(f'{len(tests) - bad} of {len(tests)} pass')
    sys.exit(1 if bad else 0)
