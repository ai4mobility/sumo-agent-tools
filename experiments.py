"""Every measured number in the companion "Building SUMO Tools for AI Agents" -> numbers_sumo_tools.json.

    python build_fowler.py            # once: network, count stations, synthetic demand
    python experiments.py             # about 15 minutes on a laptop; runs SUMO a few hundred times
    python experiments.py e1 e2       # only some sections

Sections
  e0  the scenario (network, demand, counts)
  e1  speed at zero density: averaging lane speeds vs the vehicles' own speeds
  e2  what a queue is: back of queue over the block vs a 150-m detector; snapshot vs per-cycle maximum
  e3  conservation: delay of finished trips vs delay of everyone, as demand grows
  e4  one run is not evidence: 10 seeds, three plans
  e5  rules, not advice: timing minimums broken by Webster as it comes
  e6  calibration: GEH at 16 stations for three demands; edgeData "entered" vs loop counts
  e7  efficiency: tokens and calls
  e8  with and without the GUI: run times, and a screenshot
  e9  API traps (also checked by test_claims.py)
"""
import os, sys, json, time, math, statistics, subprocess
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import sumo_agent_tools as T
import api_shaped_tools as A
import traci, sumolib

OUT = os.path.join(HERE, 'numbers_sumo_tools.json')
N = json.load(open(OUT)) if os.path.exists(OUT) else {}
MPH, FT = T.MPH, T.FT


def tok():
    from tokenizers import Tokenizer
    from huggingface_hub import hf_hub_download
    return Tokenizer.from_file(hf_hub_download('Qwen/Qwen2.5-1.5B-Instruct', 'tokenizer.json'))


def ntok(t, s):
    return len(t.encode(s).ids)


def e0():
    net = T._net()
    sys.path.insert(0, HERE)
    import build_fowler as B
    field, labels = T._field_counts()
    d = {'edges': len(net.getEdges()), 'lanes': sum(e.getLaneNumber() for e in net.getEdges()),
         'signals': len(net.getTrafficLights()), 'intersections': list(T._intersections()),
         'osm_bytes': os.path.getsize(f'{T.SCEN}/fowler.osm.xml'),
         'osm_bbox': [-82.434, 28.049, -82.399, 28.061], 'clip_box': [-82.4320, 28.0500, -82.4025, 28.0600],
         'candidate_routes': sum(1 for l in open(f'{T.SCEN}/candidates.rou.xml') if '<route ' in l),
         'stations': len(field), 'field_counts': field, 'station_labels': labels,
         'true_entries_vph': B.TRUE_ENTRIES, 'trips': {k: sum(1 for l in open(p) if '<vehicle ' in l)
                                                      for k, p in T.SCENARIO['demands'].items()}}
    for dname in ('EB', 'WB'):
        path = T._fowler_path(dname)
        d[f'fowler_{dname}_mi'] = sum(e.getLength() for e in path) / 1609.344
        d[f'fowler_{dname}_freeflow_min'] = sum(e.getLength() / e.getSpeed() for e in path) / 60
        d[f'fowler_{dname}_segments'] = [s for s, _ in T._segments(dname)]
    d['list_intersections'] = T.list_intersections()
    N['e0'] = d


def _live(seed=1, gui=False):
    T.start_live(gui=gui, seed=seed)


def e1_e2():
    """One live run (seed 1), sampled every second of the analysis hour."""
    _live(1)
    T.advance(T.WARMUP)
    seg_label, seg_edges = [s for s in T._segments('WB') if s[0].startswith('McKinley')][0]
    lanes = [l.getID() for e in seg_edges for l in e.getLanes()]
    tid, name = T._resolve('Fowler & 30th')
    app_edge = T._approaches(tid)['WB']
    dets = [d for d in traci.lanearea.getIDList() if traci.lanearea.getLaneID(d).rsplit('_', 1)[0] == app_edge.getID()]
    s1, s2, best, snap = [], [], None, None
    for k in range(T.END - T.WARMUP):
        traci.simulationStep()
        T._probe_step()
        t = traci.simulation.getTime()
        if k % 10 == 0:                              # e1: every 10 s
            naive = statistics.mean(A.get_lane_mean_speed(l) for l in lanes)
            sp = [traci.vehicle.getSpeed(v) for l in lanes for v in traci.lane.getLastStepVehicleIDs(l)]
            empty = sum(A.get_lane_vehicle_number(l) == 0 for l in lanes)
            true = statistics.mean(sp) if sp else None
            s1.append((t, naive, true, empty, len(sp)))
            if true is not None and (best is None or naive - true > best[1] - best[2]):
                best = (t, naive, true, empty, len(sp),
                        [(l, A.get_lane_vehicle_number(l), A.get_lane_mean_speed(l), traci.lane.getMaxSpeed(l)) for l in lanes])
        veh, store, _ = T._approach_vehicles(app_edge)          # e2: every second
        back, nq = T._queue_back(veh)
        e2max = max(A.get_jam_length_meters(d) for d in dets)
        halting = sum(traci.lane.getLastStepHaltingNumber(l.getID()) for l in app_edge.getLanes())
        s2.append((t, back, nq, e2max, halting))
        if snap is None or back > snap['back_m']:
            snap = {'t': t, 'back_m': back, 'n_queued': nq, 'e2_max_m': e2max,
                    'vehicles': [(round(d, 1), round(L, 1), round(v, 2)) for d, L, v in veh]}
    T.stop_live()
    # e1 summary
    ok = [x for x in s1 if x[2] is not None]
    gap = [(n - t) / MPH for _, n, t, _, _ in ok]
    N['e1'] = {
        'segment': f'Fowler WB, {seg_label}', 'lanes': len(lanes), 'samples': len(s1), 'samples_with_vehicles': len(ok),
        'naive_mean_mph': statistics.mean(n for _, n, _, _, _ in ok) / MPH,
        'true_mean_mph': statistics.mean(t for _, _, t, _, _ in ok) / MPH,
        'gap_mean_mph': statistics.mean(gap), 'gap_max_mph': max(gap),
        'share_samples_naive_ge30_true_lt15': sum(1 for _, n, t, _, _ in ok if n / MPH >= 30 and t / MPH < 15) / len(ok),
        'share_lane_samples_empty': sum(e for *_, e, _ in s1) / (len(s1) * len(lanes)),
        'worst': {'t': best[0], 'naive_mph': best[1] / MPH, 'true_mph': best[2] / MPH, 'empty_lanes': best[3],
                  'vehicles': best[4], 'lanes': [(l, n, round(v / MPH, 1), round(m / MPH, 1)) for l, n, v, m in best[5]]},
        'series': [(t, round(n / MPH, 1), None if tr is None else round(tr / MPH, 1)) for t, n, tr, _, _ in s1],
    }
    # e2 summary: per-cycle maxima vs one-second snapshots
    cyc = 90
    by = {}
    for t, b, nq, e2, h in s2:
        by.setdefault(int((t - T.WARMUP) // cyc), []).append((b, e2))
    cmax = [max(b for b, _ in v) for v in by.values() if len(v) == cyc]
    snaps = [b for _, b, _, _, _ in s2]
    beyond = sum(1 for _, b, _, e2, _ in s2 if b > 150)
    N['e2'] = {
        'approach': f'{name}, WB', 'storage_ft': T._upstream_chain(app_edge)[1] / FT, 'detector_m': 150,
        'detector_lanes': len(dets), 'cycle_s': cyc, 'cycles': len(cmax),
        'snapshot_mean_ft': statistics.mean(snaps) / FT, 'cycle_max_mean_ft': statistics.mean(cmax) / FT,
        'cycle_max_p95_ft': sorted(cmax)[int(0.95 * len(cmax)) - 1] / FT, 'max_ft': max(snaps) / FT,
        'share_snapshots_below_half_cycle_max': statistics.mean(
            1.0 if b < 0.5 * max(x for x, _ in by[int((t - T.WARMUP) // cyc)]) else 0.0
            for t, b, *_ in s2 if int((t - T.WARMUP) // cyc) in by and len(by[int((t - T.WARMUP) // cyc)]) == cyc),
        'seconds_queue_beyond_detector': beyond, 'seconds': len(s2),
        'e2_max_m': max(e2 for *_, e2, _ in s2), 'back_max_m': max(snaps),
        'snapshot': snap,
        'series': [(t, round(b / FT), round(e2 / FT)) for t, b, _, e2, _ in s2[::5]],
    }


def e3():
    rows = []
    for sc in (0.6, 0.8, 1.0, 1.2, 1.4, 1.6):
        r = T._run('existing', 1, 'demand', scale=sc)
        rows.append({k: r[k] for k in ('scale', 'loaded', 'inserted', 'waiting_to_enter', 'teleports', 'cohort',
                                       'cohort_unfinished', 'delay_s_per_veh', 'naive_delay_s_per_veh', 'naive_vehicles')})
        print('e3', sc, round(r['naive_delay_s_per_veh'], 1), round(r['delay_s_per_veh'], 1), flush=True)
    N['e3'] = {'plan': 'existing', 'seed': 1, 'rows': rows}


def e4_e5(seeds=10):
    res = {p: [T._run(p, s) for s in range(1, seeds + 1)] for p in ('existing', 'webster_raw', 'webster')}
    out = {}
    for p, rs in res.items():
        out[p] = {k: [r[k] for r in rs] for k in ('delay_s_per_veh', 'naive_delay_s_per_veh', 'fowler_EB_min',
                                                   'fowler_WB_min', 'teleports', 'cohort_unfinished')}
    for alt in ('webster_raw', 'webster'):
        diff = [a - b for a, b in zip(out[alt]['delay_s_per_veh'], out['existing']['delay_s_per_veh'])]
        m, sd = statistics.mean(diff), statistics.stdev(diff)
        hw = T._T975[seeds] * sd / math.sqrt(seeds)
        a_, b_ = out[alt]['delay_s_per_veh'], out['existing']['delay_s_per_veh']
        unpaired_wrong = sum((x > y) != (m > 0) for x in a_ for y in b_)       # one run each, different seeds
        out[f'{alt}_vs_existing'] = {'diff': diff, 'mean': m, 'sd': sd, 'ci95': [m - hw, m + hw],
                                     'seeds_worse': sum(d > 0 for d in diff), 'seeds_better': sum(d < 0 for d in diff),
                                     'unpaired_pairs': len(a_) * len(b_), 'unpaired_wrong_way': unpaired_wrong,
                                     'pct': 100 * m / statistics.mean(b_)}
    N['e4'] = {'seeds': seeds, **out}
    # e5: what the checks catch
    T.webster_timing()
    raw = T._plan_problems('webster_raw')
    names = T._intersections()
    cyc = {}
    for plan in ('webster_raw', 'webster'):
        for tl in sumolib.xml.parse(T._plan_file(plan), 'tlLogic'):
            cyc.setdefault(plan, {})[next(k for k, v in names.items() if v == tl.id)] = sum(float(p.duration) for p in tl.phase)
    existing = {}
    for tl in T._net().getTrafficLights():
        ph = [(p.duration, p.state) for p in list(tl.getPrograms().values())[0].getPhases()]
        existing[next(k for k, v in names.items() if v == tl.getID())] = {
            'cycle': sum(d for d, _ in ph),
            'fails': [f'{r}: {h:.0f} s, needs {n} s' for r, h, n, ok in T._checks(tl.getID(), ph) if not ok],
            'short_yellows': [f'phase {i}: {d:.0f} s < ITE {T._change_need(tl.getID(), s, ph[i - 1][1]):.1f} s'
                              for i, (d, s) in enumerate(ph) if 'y' in s and d < T._change_need(tl.getID(), s, ph[i - 1][1]) - 0.05]}
    crosswalk_raw = [p for p in raw if 'crosswalk' in p]
    shortest_ped = min(raw, key=lambda p: float(p.split(' s < ')[0].split()[-1]) if 'crosswalk' in p else 1e9)
    N['e5'] = {'raw_problems': len(raw), 'raw_crosswalk': len(crosswalk_raw),
               'raw_min_green': sum('green' in p for p in raw), 'raw_yellow': sum('yellow' in p for p in raw),
               'raw_list': raw, 'checked_problems': len(T._plan_problems('webster')), 'cycles': cyc,
               'existing': existing, 'webster_text': T.webster_timing(),
               'agents_m4_reused': {'note': 'recorded runs, agents_m4/numbers.json (Qwen2.5-1.5B, 3 seeds per condition)',
                                    'A_submitted_breaking': 1, 'B_submitted_breaking': 1, 'C_submitted_breaking': 0,
                                    'runs_per_condition': 3, 'ped_min_s': 21, 'crossing_ft': 48}}


def e6():
    out = {}
    for dem in ('random', 'demand_lp', 'demand'):
        txt = T.check_calibration(dem, seeds=3)
        out[dem] = json.load(open(os.path.join(T.RUNS, f'calibration_{dem}.json')))
        out[dem]['text'] = txt
        print('e6', dem, out[dem]['geh_under_5'], flush=True)
    # edgeData 'entered' vs loop counts at the 10 entry stations
    d = os.path.join(T.RUNS, 'edgedata_check')
    os.makedirs(d, exist_ok=True)
    open(f'{d}/ed.add.xml', 'w').write(f'<additional><edgeData id="h" file="{d}/ed_out.xml" begin="{T.WARMUP}" '
                                        f'end="{T.END}"/></additional>')
    T._sumo('-n', T.SCENARIO['net'], '-r', T.SCENARIO['demands']['demand'], '-a', f'{d}/ed.add.xml', '--end', T.END,
            '--seed', 1, '--no-step-log', '--no-warnings')
    ed = {e.id: (int(float(e.entered)), int(float(e.departed))) for iv in sumolib.xml.parse(f'{d}/ed_out.xml', 'interval')
          for e in iv.edge}
    field, labels = T._field_counts()
    sys.path.insert(0, HERE)
    import build_fowler as B
    entries = list(B.TRUE_ENTRIES)
    loops = T._run('existing', 1, 'demand', stations=True)['station_counts']
    out['entry_stations'] = [{'station': labels[e], 'edgedata_entered': ed.get(e, (0, 0))[0],
                              'edgedata_departed': ed.get(e, (0, 0))[1], 'loop_count': round(loops[e]),
                              'field': field[e]} for e in entries]
    N['e6'] = out


def e7():
    t = tok()
    names = T._intersections()
    ids = list(names.values())
    tools_engineer = sum(ntok(t, x['name'] + ' ' + x['description'] + json.dumps(x['input_schema'])) for x in T.TOOLS)
    api_funcs = [A.list_traffic_lights, A.get_lane_mean_speed, A.get_lane_vehicle_number, A.get_lane_occupancy,
                 A.get_jam_length_meters, A.simulation_step, A.set_phase_duration, A.get_signal_program, A.run_simulation]
    tools_api = sum(ntok(t, f.__name__ + ' ' + ' '.join(f.__doc__.split())) for f in api_funcs)
    # corridor question both ways (live, at 1800 s)
    _live(1)
    T.advance(1800)
    lanes = [l.getID() for e in T._fowler_path('WB') for l in e.getLanes()]
    dump = json.dumps({l: {'vehicles': A.get_lane_vehicle_number(l), 'mean_speed_mps': round(A.get_lane_mean_speed(l), 2)}
                       for l in lanes})
    corridor = T.get_corridor_state('WB')
    T.stop_live()
    trip = os.path.join(T.RUNS, 'demand_existing_s1_x1', 'tripinfo.xml')
    trip_text = open(trip).read()
    compare_text = (N.get('e4_compare_text') or '')
    N['e7'] = {**N.get('e7', {}),
        'tokenizer': 'Qwen2.5-1.5B-Instruct (as in the earlier agents material)',
        'id_tokens': {i: ntok(t, i) for i in ids}, 'name_tokens': {n: ntok(t, n) for n in names},
        'id_tokens_total': sum(ntok(t, i) for i in ids), 'name_tokens_total': sum(ntok(t, n) for n in names),
        'corridor_lanes': len(lanes), 'corridor_calls_api': 2 * len(lanes), 'corridor_calls_engineer': 1,
        'corridor_dump_tokens': ntok(t, dump), 'corridor_tool_tokens': ntok(t, corridor), 'corridor_text': corridor,
        'tripinfo_bytes': len(trip_text), 'tripinfo_tokens': ntok(t, trip_text),
        'tripinfo_vehicles': trip_text.count('<tripinfo '),
        'tool_descriptions_tokens_engineer': tools_engineer, 'tools_engineer': len(T.TOOLS),
        'tool_descriptions_tokens_api': tools_api, 'tools_api': len(api_funcs),
    }


def e7_compare():
    """compare_plans needs an engineer's approval: record one for the example, then remove it."""
    T.check_calibration('demand', seeds=3)
    T.approve_calibration('demand', 'Example Engineer (recorded for the companion)')
    txt = T.compare_plans('webster', seeds=10)
    rej = T.compare_plans('webster_raw', seeds=10)
    one = T.compare_plans('webster', seeds=1)
    os.remove(T.APPROVAL)
    blocked = T.compare_plans('webster', seeds=10)
    t = tok()
    N['e7']['compare_text'], N['e7']['compare_tokens'] = txt, ntok(t, txt)
    N['e7']['reject_text'], N['e7']['one_seed_text'], N['e7']['blocked_text'] = rej, one, blocked


def e8():
    """Run times with and without the GUI (timing.py), and the two TMC screenshots (gui_view.py)."""
    xv = [] if os.environ.get('DISPLAY') else ['xvfb-run', '-a', '-s', '-screen 0 1600x900x24']
    subprocess.run([sys.executable, os.path.join(HERE, 'timing.py')], check=True, capture_output=True)
    subprocess.run(xv + [sys.executable, os.path.join(HERE, 'gui_view.py')], check=True, capture_output=True)
    res = json.load(open(os.path.join(T.RUNS, 'timing.json')))
    res['sim_seconds'] = 1800
    res['note'] = ('wall-clock seconds on a 2-core cloud machine; sumo-gui drew to a virtual screen (Xvfb) without '
                   'a graphics card, so on a laptop it is usually faster than this')
    N['e8'] = res


def e9():
    """API traps, measured."""
    out = {}
    _live(1)
    traci.simulationStep()
    lane = '-111773847_0'
    out['empty_lane'] = {'lane': lane, 'vehicles': A.get_lane_vehicle_number(lane),
                         'mean_speed_mps': A.get_lane_mean_speed(lane), 'limit_mps': traci.lane.getMaxSpeed(lane)}
    A.simulation_step(100)
    t100 = traci.simulation.getTime()
    A.simulation_step(120)
    t120 = traci.simulation.getTime()
    A.simulation_step(50)
    out['simulation_step'] = {'after_100': t100, 'after_120': t120, 'after_50_called_at_120': traci.simulation.getTime()}
    T.advance(1380)                                   # to 1500 s
    best = None
    for l in traci.lane.getIDList():                  # a lane whose vehicles are all fully on it
        if l.startswith(':') or traci.lane.getLength(l) < 60:
            continue
        vs = traci.lane.getLastStepVehicleIDs(l)
        if len(vs) >= 5 and all(traci.vehicle.getLanePosition(v) >= traci.vehicle.getLength(v) for v in vs):
            cover = sum(traci.vehicle.getLength(v) for v in vs) / traci.lane.getLength(l)
            if best is None or cover > best[1]:
                best = (l, cover, A.get_lane_occupancy(l), len(vs), traci.lane.getLength(l))
    out['occupancy'] = {'lane': best[0], 'returned': best[2], 'vehicles': best[3], 'lane_length_m': best[4],
                        'vehicle_length_share': best[1], 'docstring_unit': '%', 'time_s': traci.simulation.getTime()}
    tid, _ = T._resolve('Fowler & McKinley')
    for _ in range(200):                                      # wait for the start of phase 0
        if traci.trafficlight.getPhase(tid) == 0 and traci.trafficlight.getSpentDuration(tid) == 0:
            break
        traci.simulationStep()
    A.set_phase_duration(tid, 60)
    first = traci.trafficlight.getNextSwitch(tid) - traci.simulation.getTime()
    while traci.trafficlight.getPhase(tid) == 0:
        traci.simulationStep()
    while traci.trafficlight.getPhase(tid) != 0:
        traci.simulationStep()
    second = traci.trafficlight.getNextSwitch(tid) - traci.simulation.getTime()
    out['set_phase_duration'] = {'set_to': 60, 'this_phase_s': first, 'next_cycle_same_phase_s': second + 1,
                                 'program_value_s': traci.trafficlight.getAllProgramLogics(tid)[0].phases[0].duration}
    t_end_before = traci.simulation.getTime()
    T.stop_live()
    out['sumolib_programs'] = {'readNet_default': len(A.get_signal_program(T.SCENARIO['net'], tid)),
                               'withPrograms': len(list(T._net().getTLS(tid).getPrograms().values())[0].getPhases())}
    # --end is ignored when TraCI drives SUMO
    traci.start([os.path.join(T.BIN, 'sumo'), '-n', T.SCENARIO['net'], '-r', T.SCENARIO['demands']['demand'],
                 '--end', '300', '--no-step-log', '--no-warnings'])
    for _ in range(400):
        traci.simulationStep()
    out['end_ignored'] = {'end_option_s': 300, 'reached_s': traci.simulation.getTime()}
    traci.close()
    N['e9'] = out


def e2b():
    """The detector that SUMO's helper placed on the e2 approach, and the e2 snapshot again with lane numbers."""
    tid, name = T._resolve('Fowler & 30th')
    edge = T._approaches(tid)['WB']
    dets = [d for d in sumolib.xml.parse(T.SCENARIO['detectors'], 'laneAreaDetector')
            if d.lane.rsplit('_', 1)[0] == edge.getID()]
    allL = [float(d.length) for d in sumolib.xml.parse(T.SCENARIO['detectors'], 'laneAreaDetector')]
    det_m = max(float(d.length) for d in dets)
    ser = N['e2']['series']
    N['e2b'] = {'stop_line_edge_m': edge.getLength(), 'detector_m': det_m, 'detectors_all': len(allL),
                'detectors_short': sum(l < 150 for l in allL), 'detector_min_m': min(allL),
                'detector_median_m': statistics.median(allL),
                'samples': len(ser), 'samples_beyond_detector': sum(1 for _, b, _ in ser if b * FT > det_m)}
    t_snap = N['e2']['snapshot']['t']
    T.start_live(seed=1)
    while traci.simulation.getTime() < t_snap:
        traci.simulationStep()
    chain, store = T._upstream_chain(edge)
    veh = []
    for e, off in chain:
        for lane in e.getLanes():
            for v in traci.lane.getLastStepVehicleIDs(lane.getID()):
                d = off + lane.getLength() - traci.vehicle.getLanePosition(v)
                veh.append((round(d, 1), round(traci.vehicle.getLength(v), 1), round(traci.vehicle.getSpeed(v), 2),
                            e.getLaneNumber() - 1 - lane.getIndex()))      # 0 = leftmost lane
    back, nq = T._queue_back([(d, L, v) for d, L, v, _ in veh])
    T.stop_live()
    N['e2b'].update({'snap_t': t_snap, 'snap_back_m': back, 'snap_n': nq, 'snap_vehicles': veh,
                     'snap_matches_e2': abs(back - N['e2']['snapshot']['back_m']) < 0.15, 'storage_m': store})


SECTIONS = {'e0': e0, 'e1': e1_e2, 'e2': e1_e2, 'e3': e3, 'e4': e4_e5, 'e5': e4_e5, 'e6': e6, 'e7': e7,
            'e7c': e7_compare, 'e8': e8, 'e9': e9, 'e2b': e2b}

if __name__ == '__main__':
    want = sys.argv[1:] or ['e0', 'e1', 'e3', 'e4', 'e6', 'e7', 'e7c', 'e8', 'e9']
    done = set()
    for k in want:
        f = SECTIONS[k]
        if f in done:
            continue
        t0 = time.time()
        f()
        done.add(f)
        print(f'{k} done in {time.time() - t0:.0f} s', flush=True)
        json.dump(N, open(OUT, 'w'), indent=1, default=str)
