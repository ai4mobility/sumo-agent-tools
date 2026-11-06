"""Check a whole study before its answer goes out: sanity checks, then traffic-theory checks.

A simulation tool checks one result as it writes it (a warm-up warning, a verdict either way). Some checks need all
the results of a study at once: did the agent read during the peak at all, do the vehicle counts add up across
calls, does the answer agree with its own evidence, and does the evidence agree with traffic flow theory. No single
tool sees all of that. The harness does, because it keeps the log of every call. check_study reads that log.

Two kinds of checks:

  SANITY CHECKS (must pass). From the log alone, in a fraction of a second. If one fails, gate() turns the failures
  into a message that the harness sends back to the model instead of letting the answer out. The message says what
  evidence is missing, never what the answer should be.

  THEORY AND REPLAY CHECKS (must be explained). The checker replays the run in SUMO (same demand, same seed, the
  same signal changes at the same times), with its own loop detectors at the stop line, and measures every approach
  the agent read over the whole analysis hour. It compares what it measures with HCM capacity and deterministic
  queueing, and with the answer. A miss here is not automatically an error: it is a question for the engineer
  ("the left turn is over capacity: does the answer say so?"). These go to the operator, not back to the model.

    python check_study.py walkthrough/qwen_run_G.json              # the report for a recorded run
    python check_study.py walkthrough/qwen_run_G.json --no-replay  # sanity checks only (no SUMO, under a second)
    python check_study.py walkthrough/qwen_run_G.json --json out.json

In a harness, before an answer goes out:

    feedback = gate(log)     # None when every sanity check passes
    if feedback:             # send it to the model as the next message instead of returning the answer

A log is the walkthrough format (walkthrough/qwen_run_*.json) or {"question", "answer", "calls": [{"name",
"arguments", "result"}, ...]}: what any harness, MCP client included, already has. The values below are examples,
like the timing values in sumo_agent_tools.py: use your agency's.
"""
import os, re, sys, json, math, shutil, statistics, tempfile
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import sumo_agent_tools as T

MIN_READINGS = 3       # readings of an approach inside the analysis hour, at least MIN_GAP_S apart
MIN_GAP_S = 300        # a queue at a signal rises and falls every cycle: readings 5 min apart see different cycles
SAT_FLOW = 1900        # HCM base saturation flow, veh/h/lane (cars, 12-ft lanes, before any adjustment)
LOST_S = 4.0           # HCM lost time per phase: effective green = green + yellow - 4 s
SPACING_M = 7.5        # a stopped SUMO car takes its length (5 m) plus the gap it keeps (2.5 m)
JAM_VPMPL = 1609.344 / SPACING_M     # jam density, veh/mi/lane (215)
SPEED_MARGIN = 1.25    # no reading faster than 1.25 x the speed limit
GROWTH_BAND = 0.30     # measured queue growth within 30% of what queueing theory predicts
SPILL = 0.85           # the toolkit's spillback flag: the queue fills over 85% of the storage
LOOP_PERIOD_S = 300    # the checker's stop-line loops count in 5-min intervals (SUMO starts them at 0 s)
WARMUP, END = T.WARMUP, T.END
FT, MPH = T.FT, T.MPH
# Words that show the answer says something about growth or capacity (the theory checks ask for this)
_EXPLAINED = re.compile(r'grow|over capacity|overcapacity|oversaturat|over-saturat|left.turn|does not clear|'
                        r"doesn't clear|cannot clear|keeps? (getting )?longer|v/c|degree of saturation", re.I)


# ------------------------------------------------------------------------------------------------------
# Reading the log
# ------------------------------------------------------------------------------------------------------
_APPROACH = re.compile(
    r'^(?P<name>.+?), (?P<app>EB|WB|NB|SB) at (?P<t>\d+) s: (?P<veh>\d+) vehicles on (?P<store>[\d,]+) ft of storage, '
    r'(?P<stopped>\d+) stopped; back of queue (?P<back>[\d,]+) ft \((?P<nq>\d+) vehicles\); '
    r'(?:no vehicles \(speed not measured\)|(?P<mph>\d+) mph space-mean speed); (?P<dens>\d+) veh/mi/lane;')
_SHARE = re.compile(r'(?:SPILLBACK|No spillback): the queue fills (\d+)% of the storage')
_ADVANCE = re.compile(
    r'^Time (?P<t>\d+) s \([^)]*\)\. In the last (?P<dt>\d+) s: (?P<dep>\d+) entered, (?P<arr>\d+) left; network '
    r'(?P<n0>\d+) -> (?P<n1>\d+) vehicles \((?P<d>[+-]\d+) = (?P<dep2>\d+) - (?P<arr2>\d+)\)\. Waiting to enter: '
    r'(?P<wait>\d+)\. Teleports: (?P<tel>\d+)\.')
_CORRIDOR = re.compile(r'^Fowler Ave (?P<dir>EB|WB) at (?P<t>\d+) s')
_COMPARE_WORDS = re.compile(r'\b(better|worse|improv\w*|reduc\w*|less delay|more delay|fewer|outperform\w*)\b', re.I)
_NEG = re.compile(r"\b(no|not|never|none|without|below|under)\b|n't", re.I)
_int = lambda s: int(s.replace(',', ''))


def load_log(log):
    """A run log as {'question', 'answer', 'calls', 'run'}. Accepts a path, the walkthrough format, or the plain
    format. Calls the harness refused before they ran (check != 'ok') are kept and marked ran=False."""
    d = json.load(open(log)) if isinstance(log, str) else log
    if 'calls' in d:
        calls = [dict(c) for c in d['calls']]
    else:
        calls = [dict(c) for s in d.get('steps', []) for c in s.get('calls', [])]
    for c in calls:
        c['arguments'] = c.get('arguments') or {}
        c['ran'] = c.get('check', 'ok') == 'ok'
        c['result'] = str(c.get('result', ''))
    return {'question': d.get('question', ''), 'answer': d.get('answer') or '', 'calls': calls, 'run': d.get('run')}


def segments(log):
    """Split the log into simulations: each successful start_live begins a new one (and closes the last).
    Each segment: demand, seed, and its advances, readings and signal changes in the order they happened."""
    segs = []
    for c in log['calls']:
        name, res = c['name'], c['result']
        if not c['ran']:
            continue
        if name == 'start_live' and res.startswith('Started'):
            a = c['arguments']
            segs.append({'demand': a.get('demand', 'demand'), 'seed': int(a.get('seed', 1)), 'events': [],
                         'readings': [], 'advances': [], 't': 0})
            continue
        if not segs:
            continue                    # before any simulation: these calls returned errors
        s = segs[-1]
        if name == 'advance':
            m = _ADVANCE.match(res)
            if m:
                adv = {k: int(v) for k, v in m.groupdict().items()}
                s['advances'].append(adv)
                s['events'].append(('advance', adv))
                s['t'] = adv['t']
        elif name == 'get_approach_state':
            m = _APPROACH.match(res)
            if m:
                g = m.groupdict()
                sh = _SHARE.search(res)
                r = {'tool': name, 'name': g['name'], 'app': g['app'], 't': int(g['t']), 'veh': int(g['veh']),
                     'store_ft': _int(g['store']), 'stopped': int(g['stopped']), 'back_ft': _int(g['back']),
                     'nq': int(g['nq']), 'mph': int(g['mph']) if g['mph'] else None, 'dens': int(g['dens']),
                     'share_printed': int(sh.group(1)) / 100 if sh else None, 'text': res}
                r['share_ft'] = r['back_ft'] / r['store_ft'] if r['store_ft'] else 0.0    # from the rounded feet
                r['share'] = r['share_printed'] if r['share_printed'] is not None else r['share_ft']
                s['readings'].append(r)
                s['events'].append(('reading', r))
        elif name == 'get_corridor_state':
            m = _CORRIDOR.match(res)
            if m:
                r = {'tool': name, 'name': f'Fowler Ave {m.group("dir")}', 'app': m.group('dir'), 't': int(m.group('t')),
                     'text': res}
                s['readings'].append(r)
                s['events'].append(('reading', r))
        elif name == 'set_signal_timing' and ': new plan' in res:
            s['events'].append(('timing', c['arguments']))
    return segs


def spill_claim(answer):
    """What the answer says about spillback: True, False or None (says nothing). The last sentence that mentions
    spillback decides; a negation (no, not, below...) before the word turns it to False. A simple rule: a second
    model or the engineer reads answers better, which is why the theory checks go to the engineer."""
    claim = None
    for s in re.split(r'(?<=[.!?])\s+', answer or ''):
        if re.search(r'spill', s, re.I):
            before = re.split(r'spill', s, maxsplit=1, flags=re.I)[0]
            claim = not _NEG.search(before)
    return claim


def _label(r):
    return f'{r["name"]} {r["app"]}'


def _check(name, kind, status, finding, fix=None, **data):
    return {'check': name, 'kind': kind, 'status': status, 'finding': finding, 'fix': fix, 'data': data}


# ------------------------------------------------------------------------------------------------------
# Sanity checks: from the log alone
# ------------------------------------------------------------------------------------------------------
def _last_seg_time(segs):
    return segs[-1]['t'] if segs else None


def check_period(log, segs):
    rd = [r for s in segs for r in s['readings']]
    if not rd:
        return _check('period', 'sanity', 'FAIL', 'The log has no reading of the traffic at all: the answer rests on '
                      'no evidence.', 'Start the simulation (start_live), advance into the analysis hour '
                      f'({WARMUP}-{END} s), and read the approach the question is about.')
    inside = [r for r in rd if WARMUP <= r['t'] <= END]
    outside = [r for r in rd if not WARMUP <= r['t'] <= END]
    times = ', '.join(f'{r["t"]:,} s' for r in outside)
    if not inside:
        now = _last_seg_time(segs)
        how = (f'Advance to a time between {WARMUP} and {END} s and read again.' if now is not None and now < WARMUP else
               f'Time cannot go back: call start_live, advance to a time between {WARMUP} and {END} s, and read again.')
        return _check('period', 'sanity', 'FAIL',
                      f'None of the {len(rd)} reading(s) is inside the analysis hour ({WARMUP}-{END} s): {times}. '
                      'The question is about the peak, so the answer rests on no peak evidence.',
                      f'None of your readings is inside the analysis hour ({WARMUP}-{END} s), and the question is about '
                      f'the peak: yours {"is" if len(rd) == 1 else "are"} at {times}. {how}', inside=0, outside=[r['t'] for r in outside])
    note = f'; {len(outside)} outside it ({times}) cannot support a peak-hour answer' if outside else ''
    return _check('period', 'sanity', 'PASS', f'{len(inside)} of {len(rd)} readings are inside the analysis hour{note}.',
                  inside=len(inside), outside=[r['t'] for r in outside])


def _spread(times, gap=MIN_GAP_S):
    kept = []
    for t in sorted(times):
        if not kept or t - kept[-1] >= gap:
            kept.append(t)
    return kept


def check_repeats(log, segs):
    by = {}
    for s in segs:
        for r in s['readings']:
            if r['tool'] == 'get_approach_state':
                by.setdefault(_label(r), []).append(r['t'])
    if not by:
        return _check('repeats', 'sanity', 'N/A', 'No approach was read.')
    short, rows = [], []
    for lab, ts in by.items():
        kept = _spread([t for t in ts if WARMUP <= t <= END])
        rows.append(f'{lab}: {len(kept)}')
        if len(kept) < MIN_READINGS:
            short.append((lab, len(kept)))
    if short:
        lab, k = short[0]
        return _check('repeats', 'sanity', 'FAIL',
                      f'{lab} was read {k} time{"" if k == 1 else "s"} inside the hour (readings less than '
                      f'{MIN_GAP_S // 60} min apart count once; needs {MIN_READINGS}). A queue at a signal rises and falls every cycle: one reading is a snapshot of '
                      'one moment of one cycle.',
                      f'Read {lab} at least {MIN_READINGS} times inside the analysis hour, at least {MIN_GAP_S // 60} '
                      'minutes apart (advance between readings): a queue at a signal rises and falls every cycle, so '
                      'one reading is one moment of one cycle.', counts=dict(rows=rows))
    return _check('repeats', 'sanity', 'PASS', 'Readings inside the hour, 5+ min apart: ' + '; '.join(rows) + '.')


def check_ledger(log, segs):
    bad = []
    for i, s in enumerate(segs):
        prev_t, prev_n = 0, 0
        for a in s['advances']:
            if a['d'] != a['dep'] - a['arr'] or a['n1'] != a['n0'] + a['d'] or a['dep2'] != a['dep'] or a['arr2'] != a['arr']:
                bad.append(f'at {a["t"]:,} s the ledger does not add up ({a["n0"]} -> {a["n1"]}, {a["d"]:+d} = '
                           f'{a["dep"]} - {a["arr"]})')
            if a['n0'] != prev_n:
                bad.append(f'at {a["t"] - a["dt"]:,} s the network starts with {a["n0"]} vehicles, but the call before '
                           f'ended with {prev_n}')
            if a['t'] - a['dt'] != prev_t:
                bad.append(f'the interval ending at {a["t"]:,} s does not start where the last one ended ({prev_t:,} s)')
            prev_t, prev_n = a['t'], a['n1']
    n = sum(len(s['advances']) for s in segs)
    if not n:
        return _check('ledger', 'sanity', 'N/A', 'No advance call to check.')
    if bad:
        return _check('ledger', 'sanity', 'FAIL', 'Vehicles are not conserved across the calls: ' + '; '.join(bad[:3]) + '.',
                      'The vehicle counts across your advance calls do not add up (' + bad[0] + '). Do not use this '
                      'run; start a new one.')
    tot_in = sum(a['dep'] for s in segs for a in s['advances'])
    tot_out = sum(a['arr'] for s in segs for a in s['advances'])
    return _check('ledger', 'sanity', 'PASS', f'{n} advance calls chain and add up: entered {tot_in:,}, left '
                  f'{tot_out:,}, and each call starts where the last one ended.')


def check_teleports(log, segs):
    tel = sum(a['tel'] for s in segs for a in s['advances'])
    wait = max([a['wait'] for s in segs for a in s['advances']] or [0])
    if not any(s['advances'] for s in segs):
        return _check('teleports', 'sanity', 'N/A', 'No advance call to check.')
    msg = []
    if tel:
        msg.append(f'SUMO teleported {tel} vehicle(s): something jammed for 300 s, and queues and delays after that '
                   'are not physical')
    if wait > 20:
        msg.append(f'up to {wait} vehicles could not enter at the network edge: less traffic got in than the demand')
    if msg:
        return _check('teleports', 'sanity', 'FAIL', '; '.join(msg).capitalize() + '.',
                      '; '.join(msg).capitalize() + '. Say so in the answer, or find and fix the jam first.',
                      teleports=tel, waiting=wait)
    return _check('teleports', 'sanity', 'PASS', 'No teleports and no vehicles stuck at the network edge (most '
                  f'waiting at once: {wait}).', teleports=0, waiting=wait)


def _limits():
    """{'<intersection name> <app>': (speed limit m/s, lanes at the stop line)} from the network."""
    out = {}
    for name, tid in T._intersections().items():
        for b, e in T._approaches(tid).items():
            out[f'{name} {b}'] = (e.getSpeed(), e.getLaneNumber())
    return out


def check_physics(log, segs):
    rd = [r for s in segs for r in s['readings'] if r['tool'] == 'get_approach_state']
    if not rd:
        return _check('physics', 'sanity', 'N/A', 'No approach reading to check.')
    lim, bad = _limits(), []
    for r in rd:
        at = f'{_label(r)} at {r["t"]:,} s'
        if r['back_ft'] > r['store_ft'] + 1:
            bad.append(f'{at}: queue {r["back_ft"]:,} ft is longer than the block ({r["store_ft"]:,} ft)')
        if r['nq'] > r['veh'] or r['stopped'] > r['veh']:
            bad.append(f'{at}: more vehicles queued or stopped than on the block')
        if r['dens'] > JAM_VPMPL * 1.05:
            bad.append(f'{at}: density {r["dens"]} veh/mi/lane is above jam density ({JAM_VPMPL:.0f})')
        speed, lanes = lim.get(_label(r), (None, None))
        if r['mph'] is not None and speed and r['mph'] > SPEED_MARGIN * speed / MPH:
            bad.append(f'{at}: {r["mph"]} mph on a {speed / MPH:.0f}-mph street')
        back_m = r['back_ft'] * FT
        if r['nq'] and back_m > r['nq'] * (5 + T.QUEUE_GAP_M) + 1:       # each queued car: 5 m + at most a 10-m gap
            bad.append(f'{at}: {r["nq"]} queued vehicles cannot reach back {r["back_ft"]:,} ft')
        if r['nq'] and lanes and back_m < math.ceil(r['nq'] / lanes) * 5 * 0.95:
            bad.append(f'{at}: {r["nq"]} queued vehicles do not fit in {r["back_ft"]:,} ft on {lanes} lanes')
        if r['share_printed'] is not None and abs(r['share_printed'] - r['share_ft']) > 0.011:
            bad.append(f'{at}: the result says {r["share_printed"]:.0%} of storage, but {r["back_ft"]:,} of '
                       f'{r["store_ft"]:,} ft is {r["share_ft"]:.0%}')
    if bad:
        return _check('physics', 'sanity', 'FAIL', 'Readings that cannot be true: ' + '; '.join(bad[:3]) + '.',
                      'Some readings cannot be true (' + bad[0] + '). Do not use them; report the problem.')
    return _check('physics', 'sanity', 'PASS', f'{"The" if len(rd) == 1 else "All " + str(len(rd))} approach reading{"s are" if len(rd) > 1 else " is"} physically possible (queue within '
                  'the block, density below jam, speeds below the limit, queued vehicles fit the queue length).')


def check_answer(log, segs):
    q = log['question'] + ' ' + log['answer']
    if not re.search(r'spill', q, re.I):
        return _check('answer', 'sanity', 'N/A', 'The question is not about spillback.')
    claim = spill_claim(log['answer'])
    rd = [r for s in segs for r in s['readings'] if r['tool'] == 'get_approach_state']
    use = [r for r in rd if WARMUP <= r['t'] <= END] or rd
    if claim is None:
        return _check('answer', 'sanity', 'FAIL', 'The answer does not say whether the approach spills back.',
                      'Your answer does not say whether the approach spills back. Say yes or no, with the share of '
                      'storage the queue fills.', claim=None)
    if not use:
        return _check('answer', 'sanity', 'FAIL', f'The answer says "{"spillback" if claim else "no spillback"}" with '
                      'no reading behind it.', 'Your answer has no reading behind it. Read the approach first.',
                      claim=claim)
    worst = max(use, key=lambda r: r['share'])
    seen = worst['share'] > SPILL
    which = 'inside the hour' if use is not rd else 'in the log'
    if claim != seen:
        return _check('answer', 'sanity', 'FAIL',
                      f'The answer says "{"spillback" if claim else "no spillback"}", but its readings {which} show at '
                      f'most {worst["share"]:.0%} of storage ({worst["back_ft"]:,} of {worst["store_ft"]:,} ft at '
                      f'{worst["t"]:,} s); the flag is {SPILL:.0%}.',
                      f'Your answer says "{"spillback" if claim else "no spillback"}", but your readings show the queue '
                      f'filling at most {worst["share"]:.0%} of storage, and spillback means more than {SPILL:.0%}. '
                      'The verdict must follow from the readings.', claim=claim, evidence=seen)
    return _check('answer', 'sanity', 'PASS',
                  f'The answer\'s "{"spillback" if claim else "no spillback"}" agrees with its readings {which} (at most '
                  f'{worst["share"]:.0%} of storage).', claim=claim, evidence=seen)


def check_compare(log, segs):
    changed = any(e[0] == 'timing' for s in segs for e in s['events'])
    claims = bool(_COMPARE_WORDS.search(log['answer']))
    if not (changed and claims):
        return _check('compare', 'sanity', 'N/A', 'The answer compares no timing plans.')
    ok = any(c['name'] == 'compare_plans' and ' vs existing' in c['result'] for c in log['calls'])
    if ok:
        return _check('compare', 'sanity', 'PASS', 'The comparison rests on compare_plans (paired seeds, confidence '
                      'interval).')
    return _check('compare', 'sanity', 'FAIL', 'The answer compares timing plans from one live simulation. One run of '
                  'each plan pointed the wrong way in 15 of 100 pairs on this network.',
                  'Your answer compares timing plans from one live simulation, which is an anecdote: single runs point '
                  'the wrong way about 1 time in 7 here. Use compare_plans, which runs both plans on the same seeds and '
                  'gives a confidence interval.')


SANITY = [check_period, check_repeats, check_ledger, check_teleports, check_physics, check_answer, check_compare]


# ------------------------------------------------------------------------------------------------------
# The replay: the checker's own measurements over the whole analysis hour
# ------------------------------------------------------------------------------------------------------
def _approach_setup(label):
    """Everything the replay needs to know about one approach: stop-line edge, block, lanes per movement."""
    name, app = label.rsplit(' ', 1)
    tid, _ = T._resolve(name)
    edge = T._approaches(tid)[app]
    chain, store = T._upstream_chain(edge)
    mov_links, lane_mov, to_mov = {}, {}, {}
    for c in T._net().getTLS(tid).getConnections():
        a, b, idx = c[0], c[1], c[2]
        if a.getEdge() != edge:
            continue
        m = T._links(tid)[idx][1]
        mov_links.setdefault(m, []).append(idx)
        lane_mov.setdefault(a.getID(), set()).add(m)
        to_mov[b.getEdge().getID()] = m
    groups = {}
    for lane, ms in lane_mov.items():
        groups.setdefault('+'.join(sorted(ms)), []).append(lane)
    return {'label': label, 'tid': tid, 'edge': edge, 'chain': chain, 'chain_ids': {e.getID() for e, _ in chain},
            'store_m': store, 'mov_links': mov_links, 'groups': groups, 'to_mov': to_mov}


def replay(log, out_dir=None):
    """Rerun the last simulation in the log with the same demand, seed and signal changes, to the end of the
    analysis hour (or to the log's last time, if later). Measures, with the checker's own code and loop detectors:
    the vehicle ledger of every advance interval; for each approach read: the back of queue every second of the hour
    (the tool's queue rule), arrivals by movement (from each vehicle's route), departures by lane (loops at the stop
    line), and the signal indication of each movement every second. Returns a dict (see the keys below)."""
    import traci, sumolib
    segs = segments(log)
    if not segs:
        return None
    seg = segs[-1]
    labels = sorted({_label(r) for r in seg['readings'] if r['tool'] == 'get_approach_state'})
    aps = [_approach_setup(l) for l in labels]
    own_dir = out_dir is None                  # its own folder, so two checks can run at once
    if own_dir:
        os.makedirs(T.RUNS, exist_ok=True)
        out_dir = tempfile.mkdtemp(prefix='check_', dir=T.RUNS)
    os.makedirs(out_dir, exist_ok=True)
    loops, e1_out = os.path.join(out_dir, 'stopline.add.xml'), os.path.join(out_dir, 'stopline_out.xml')
    with open(loops, 'w') as f:
        f.write('<additional>\n')
        for k, ap in enumerate(aps):
            for lane in ap['edge'].getLanes():
                f.write(f'  <inductionLoop id="chk{k}|{lane.getID()}" lane="{lane.getID()}" pos="{lane.getLength() - 0.5:.2f}" '
                        f'period="{LOOP_PERIOD_S}" file="{e1_out}"/>\n')   # intervals run from 0 s
        f.write('</additional>\n')
    cmd = [os.path.join(T.BIN, 'sumo'), '-n', T.SCENARIO['net'], '-r', T.SCENARIO['demands'][seg['demand']],
           '-a', T.SCENARIO['detectors'] + ',' + loops, '--seed', str(seg['seed']), '--no-step-log', '--no-warnings',
           '--time-to-teleport', '300']        # start_live's command, plus the checker's loops (they do not move cars)
    T.stop_live()
    traci.start(cmd, stdout=open(os.devnull, 'w'), numRetries=60)
    T._LIVE.update(on=True, gui=False, demand=seg['demand'], seed=seg['seed'], teleports=0,
                   probe={d: {'in': {}, 'done': []} for d in ('EB', 'WB')})      # so set_signal_timing can run
    meas = {'demand': seg['demand'], 'seed': seg['seed'], 'intervals': [], 'readings': [], 'approaches': {}}
    for ap in aps:
        meas['approaches'][ap['label']] = {'store_m': ap['store_m'], 'queue': [], 'arrivals': {}, 'signal': {},
                                           'groups': ap['groups'], 'seen': {}}
    t_end = max(END, seg['t'])
    state = {'dep': 0, 'arr': 0, 'tel': 0}

    def step():
        traci.simulationStep()
        state['dep'] += traci.simulation.getDepartedNumber()
        state['arr'] += traci.simulation.getArrivedNumber()
        state['tel'] += traci.simulation.getStartingTeleportNumber()
        t = traci.simulation.getTime()
        if not WARMUP <= t <= END:
            return
        for ap in aps:
            m = meas['approaches'][ap['label']]
            for e, _ in ap['chain']:
                for v in traci.edge.getLastStepVehicleIDs(e.getID()):
                    if v in m['seen']:
                        continue
                    r = traci.vehicle.getRoute(v)
                    i = r.index(ap['edge'].getID()) if ap['edge'].getID() in r else -1
                    mv = ap['to_mov'].get(r[i + 1], 'other') if 0 <= i < len(r) - 1 else 'other'
                    m['seen'][v] = mv
                    if t > WARMUP:
                        m['arrivals'][mv] = m['arrivals'].get(mv, 0) + 1
            veh, _, _ = T._approach_vehicles(ap['edge'])
            back, nq = T._queue_back(veh)
            m['queue'].append((t, back, nq))
            st = traci.trafficlight.getRedYellowGreenState(ap['tid'])
            for mv, idx in ap['mov_links'].items():
                cs = [st[i] for i in idx if i < len(st)]
                m['signal'].setdefault(mv, []).append('G' if any(c in 'Gg' for c in cs) else 'y' if 'y' in cs else 'r')

    def run_to(t_target):
        while traci.simulation.getTime() < t_target:
            step()

    try:
        for kind, ev in seg['events']:
            if kind == 'advance':
                t0 = traci.simulation.getTime()
                n0 = traci.vehicle.getIDCount()
                state.update(dep=0, arr=0, tel=0)
                run_to(ev['t'])
                meas['intervals'].append({'t': ev['t'], 'dt': ev['t'] - t0, 'dep': state['dep'], 'arr': state['arr'],
                                          'tel': state['tel'], 'n0': n0, 'n1': traci.vehicle.getIDCount()})
            elif kind == 'timing':
                meas.setdefault('timing', []).append((traci.simulation.getTime(), T.set_signal_timing(**ev)))
            elif kind == 'reading' and ev['tool'] == 'get_approach_state':
                ap = next(a for a in aps if a['label'] == _label(ev))
                veh, _, _ = T._approach_vehicles(ap['edge'])
                back, nq = T._queue_back(veh)
                meas['readings'].append({'label': ev['label'] if 'label' in ev else _label(ev),
                                         't': traci.simulation.getTime(), 'back_ft': round(back / FT), 'nq': nq,
                                         'veh': len(veh)})
        run_to(t_end)
    finally:
        traci.close()
        T._LIVE['on'] = False
    for iv in sumolib.xml.parse(e1_out, 'interval'):
        if float(iv.begin) < WARMUP or float(iv.end) > END:
            continue                                  # keep the analysis hour only
        k, lane = iv.id.split('|')
        m = meas['approaches'][aps[int(k[3:])]['label']]
        m.setdefault('departures', {})[lane] = m.setdefault('departures', {}).get(lane, 0) + int(iv.nVehContrib)
    for m in meas['approaches'].values():
        del m['seen']
    if own_dir:
        shutil.rmtree(out_dir, ignore_errors=True)
    return meas


# ------------------------------------------------------------------------------------------------------
# Theory and replay checks: the checker's measurements against the log, the answer and traffic flow theory
# ------------------------------------------------------------------------------------------------------
def check_reproduce(log, segs, meas):
    if meas is None:
        return _check('replay', 'replay', 'N/A', 'No simulation in the log to replay.')
    seg, bad = segs[-1], []
    for a, b in zip(seg['advances'], meas['intervals']):
        if (a['dep'], a['arr'], a['tel']) != (b['dep'], b['arr'], b['tel']):
            bad.append(f'interval to {a["t"]:,} s: log {a["dep"]} in / {a["arr"]} out, replay {b["dep"]} / {b["arr"]}')
    reads = [r for r in seg['readings'] if r['tool'] == 'get_approach_state']
    for a, b in zip(reads, meas['readings']):
        if abs(a['back_ft'] - b['back_ft']) > 1 or a['nq'] != b['nq']:
            bad.append(f'{_label(a)} at {a["t"]:,} s: log {a["back_ft"]:,} ft ({a["nq"]} veh), replay '
                       f'{b["back_ft"]:,} ft ({b["nq"]} veh)')
    if bad:
        return _check('replay', 'replay', 'FAIL', 'The replay does not reproduce the run, so the checks below do not '
                      'apply to it: ' + '; '.join(bad[:3]) + '.')
    return _check('replay', 'replay', 'PASS', f'The replay (demand "{meas["demand"]}", seed {meas["seed"]}) reproduces '
                  f'the run exactly: the vehicles entering and leaving in all {len(meas["intervals"])} advance intervals, and '
                  f'the queue in {len(meas["readings"])} reading{"s" * (len(meas["readings"]) != 1)}, match the log.')


def _cycles(queue, signal):
    """Split the hour into signal cycles at each onset of green and keep each cycle's longest queue."""
    out, cur = [], []
    for k, (t, back, nq) in enumerate(queue):
        if k and signal[k] == 'G' and signal[k - 1] != 'G' and cur:
            out.append(max(cur, key=lambda x: x[1]))
            cur = []
        cur.append((t, back, nq))
    if cur:
        out.append(max(cur, key=lambda x: x[1]))
    return out


def _slope(pts):
    """Least-squares slope, per hour, of (t s, y) points."""
    if len(pts) < 3:
        return 0.0
    tm, ym = statistics.mean(t for t, _ in pts), statistics.mean(y for _, y in pts)
    sxx = sum((t - tm) ** 2 for t, _ in pts)
    return 3600 * sum((t - tm) * (y - ym) for t, y in pts) / sxx if sxx else 0.0


def movement_table(m):
    """Per lane group of one approach, for the analysis hour: lanes, green, effective green, HCM capacity,
    demand (arrivals), departures (stop-line loops) and X = demand / capacity."""
    rows = []
    hour = END - WARMUP
    for g, lanes in m['groups'].items():
        movs = g.split('+')
        sig = [('G' if any(m['signal'][mv][k] == 'G' for mv in movs) else
                'y' if any(m['signal'][mv][k] == 'y' for mv in movs) else 'r') for k in range(len(m['queue']))]
        green, yellow = sig.count('G'), sig.count('y')
        onsets = sum(1 for k in range(1, len(sig)) if sig[k] == 'G' and sig[k - 1] != 'G') + (sig[:1] == ['G'])
        g_eff = max(green + yellow - LOST_S * onsets, 0)
        cap = SAT_FLOW * len(lanes) * g_eff / hour
        demand = sum(m['arrivals'].get(mv, 0) for mv in movs) * 3600 / hour
        dep = sum(m.get('departures', {}).get(l, 0) for l in lanes) * 3600 / hour
        rows.append({'group': g, 'lanes': len(lanes), 'green_s': green, 'onsets': onsets, 'g_eff_s': g_eff,
                     'capacity': cap, 'demand': demand, 'departures': dep, 'X': demand / cap if cap else float('inf'),
                     'green_per_cycle': green / onsets if onsets else 0})
    return rows


_MOV = {'s': 'through', 'l': 'left turn', 'r': 'right turn'}
_mname = lambda g: ' + '.join(_MOV.get(x, x) for x in g.split('+'))


def check_whole_hour(log, segs, meas):
    if meas is None or not meas['approaches']:
        return _check('whole hour', 'replay', 'N/A', 'No approach to measure.')
    claim = spill_claim(log['answer'])
    rows, bad = [], []
    for lab, m in meas['approaches'].items():
        main = max(m['groups'], key=lambda g: len(m['groups'][g])).split('+')[0]
        cyc = _cycles(m['queue'], m['signal'][main])
        worst = max(cyc, key=lambda x: x[1])
        share = worst[1] / m['store_m']
        logged = [r['share'] for s in segs for r in s['readings'] if r['tool'] == 'get_approach_state'
                  and _label(r) == lab and WARMUP <= r['t'] <= END]
        seen = f'the log\'s readings inside the hour saw at most {max(logged):.0%}' if logged else \
            'the log has no reading inside the hour'
        rows.append(f'{lab}: the longest queue of the {len(cyc)} cycles is {worst[1] / FT:,.0f} ft '
                    f'({share:.0%} of storage) at {worst[0]:,.0f} s; {seen}')
        if claim is not None and claim != (share > SPILL):
            bad.append(lab)
    if claim is None:
        return _check('whole hour', 'replay', 'EXPLAIN', '; '.join(rows) + '. The answer gives no verdict to compare.')
    if bad:
        return _check('whole hour', 'replay', 'FAIL', '; '.join(rows) + f'. Measured every second, the hour says '
                      f'"{"spillback" if not claim else "no spillback"}": the answer is wrong for this run.')
    return _check('whole hour', 'replay', 'PASS', '; '.join(rows) + f'. The answer\'s verdict '
                  f'("{"spillback" if claim else "no spillback"}") holds for every cycle of the hour.')


def check_capacity(log, segs, meas):
    """HCM capacity: c = s x lanes x g/C. Two tests: no lane group serves more than its capacity (a count or a
    simulator that discharges faster than drivers do), and X = demand / capacity: over 1, the queue grows."""
    if meas is None or not meas['approaches']:
        return _check('capacity', 'theory', 'N/A', 'No approach to measure.')
    over, fast, rows = [], [], []
    for lab, m in meas['approaches'].items():
        for r in movement_table(m):
            rows.append(f'{lab} {_mname(r["group"])} ({r["lanes"]} lane{"s" * (r["lanes"] > 1)}, '
                        f'{r["green_per_cycle"]:.0f} s green per cycle): demand {r["demand"]:,.0f} veh/h, capacity '
                        f'{r["capacity"]:,.0f}, X = {r["X"]:.2f}; {r["departures"]:,.0f} veh/h got through')
            if r['departures'] > 1.1 * r['capacity']:
                fast.append(f'{lab} {_mname(r["group"])}')
            if r['X'] >= 1:
                over.append((lab, r))
    findings = '; '.join(rows) + f' (HCM base saturation flow {SAT_FLOW} veh/h/lane, {LOST_S:.0f} s lost per phase).'
    if fast:
        return _check('capacity', 'theory', 'EXPLAIN', findings + ' More vehicles got through ' + ', '.join(fast) +
                      ' than HCM capacity allows: the count is wrong, or the simulated drivers discharge faster than '
                      'real ones, and real queues would be longer.', rows=rows)
    if over:
        lab, r = max(over, key=lambda x: x[1]['X'])
        said = bool(_EXPLAINED.search(log['answer']))
        msg = (f' {lab} {_mname(r["group"])} is over capacity (X = {r["X"]:.2f}): its queue cannot clear and grows '
               'through the hour, so a verdict from one moment does not describe it.')
        if r['departures'] < 0.9 * r['capacity']:      # queued all hour, so what got through is its capacity in SUMO
            msg += (f' With a queue all hour it served {r["departures"]:,.0f} veh/h, which is its capacity in the '
                    f'simulation: {r["departures"] / r["capacity"]:.0%} of the HCM value, so the simulated drivers get '
                    'fewer cars through each green than HCM assumes.')
        return _check('capacity', 'theory', 'PASS' if said else 'EXPLAIN',
                      findings + msg + (' The answer says so.' if said else ' The answer does not say so.'), rows=rows)
    return _check('capacity', 'theory', 'PASS', findings + ' Every movement is under capacity, so its queue should '
                  'clear in each cycle.', rows=rows)


def check_queue_growth(log, segs, meas):
    """Deterministic queueing (input-output): with demand q above the service rate, the queue grows by (q - served)
    vehicles per hour, which takes (q - served) x spacing / lanes metres of road. Compare with how fast the
    measured cycle-longest queue grows. Agreement means the signal arithmetic explains the queue; disagreement
    means something else is holding vehicles (a blocked lane, lane changes, a queue backing up from downstream)."""
    if meas is None or not meas['approaches']:
        return _check('queue growth', 'theory', 'N/A', 'No approach to measure.')
    out, status = [], 'PASS'
    for lab, m in meas['approaches'].items():
        main = max(m['groups'], key=lambda g: len(m['groups'][g])).split('+')[0]
        cyc = _cycles(m['queue'], m['signal'][main])
        meas_mph = _slope([(t, b) for t, b, _ in cyc])                     # m per hour
        tab = movement_table(m)
        top = max(tab, key=lambda r: r['X'])
        surplus = max(top['demand'] - top['departures'], 0)                  # veh/h that cannot be served
        pred_mph = surplus * SPACING_M / top['lanes'] if top['X'] >= 1 else 0.0
        store = m['store_m']
        if pred_mph > 0:
            ratio = meas_mph / pred_mph
            ok = abs(ratio - 1) <= GROWTH_BAND
            txt = (f'{lab}: queueing theory predicts the {_mname(top["group"])} queue grows ({top["demand"]:,.0f} - '
                   f'{top["departures"]:,.0f} veh/h) x {SPACING_M} m / {top["lanes"]} lane{"s" * (top["lanes"] > 1)} = '
                   f'{pred_mph:,.0f} m/h; the replay\'s cycle-longest queue grows {meas_mph:,.0f} m/h '
                   f'({ratio:.0%} of the prediction)')
        else:
            ok = abs(meas_mph) <= 0.1 * store
            txt = (f'{lab}: every movement is under capacity, so theory predicts no growth; the replay\'s '
                   f'cycle-longest queue changes {meas_mph:+,.0f} m/h')
        last_t, last_b, _ = cyc[-1]
        if meas_mph > 0 and last_b < SPILL * store:
            mins = (SPILL * store - last_b) / meas_mph * 60
            t_spill = last_t + mins * 60
            txt += (f'. At that rate it reaches {SPILL:.0%} of storage {mins:.0f} min after {last_t:,.0f} s'
                    + (f', after the analysis hour ends ({END:,} s): no spillback in this hour, but only because the '
                       'peak ended' if t_spill > END else ', inside the analysis hour'))
        if not ok:
            status = 'EXPLAIN'
            txt += ('. The measured growth is not what the signal arithmetic predicts: something else is holding '
                    'vehicles (a blocked lane, lane changes, a queue backing up from downstream). Find it before '
                    'trusting the verdict')
        out.append(txt)
    return _check('queue growth', 'theory', status, '. '.join(out) + '.')


THEORY = [check_reproduce, check_whole_hour, check_capacity, check_queue_growth]


# ------------------------------------------------------------------------------------------------------
# Putting it together
# ------------------------------------------------------------------------------------------------------
def check_study(log, replay_run=True, out_dir=None):
    """Run every check on a run log. Returns {'question', 'answer', 'claim', 'checks': [...], 'gate': text or None,
    'measurements': replay data or None}."""
    log = load_log(log)
    segs = segments(log)
    checks = [f(log, segs) for f in SANITY]
    meas = None
    if replay_run and segs:
        meas = replay(log, out_dir)
        rep = check_reproduce(log, segs, meas)
        checks.append(rep)
        if rep['status'] == 'PASS':
            checks += [f(log, segs, meas) for f in THEORY[1:]]
        else:
            checks += [_check(f.__name__[6:].replace('_', ' '), 'theory', 'N/A', 'The replay does not reproduce the run.')
                       for f in THEORY[1:]]
    return {'run': log['run'], 'question': log['question'], 'answer': log['answer'],
            'claim': spill_claim(log['answer']), 'checks': checks, 'gate': _gate_text(checks), 'measurements': meas}


def _gate_text(checks):
    fails = [c for c in checks if c['kind'] == 'sanity' and c['status'] == 'FAIL']
    if not fails:
        return None
    lines = [f'{k}. {c["fix"]}' for k, c in enumerate(fails, 1)]
    return ('Harness check (not the engineer): your answer was not sent, because the evidence does not support it yet.\n'
            + '\n'.join(lines) + '\nFix this with the tools, then answer again.')


def gate(log):
    """For a harness, before an answer goes out: the sanity checks only (no SUMO run, well under a second).
    Returns None if they all pass, or the message to send back to the model. It names the missing evidence and
    never the answer: the theory and replay checks, which do know more, go to the engineer instead."""
    log = load_log(log)
    segs = segments(log)
    return _gate_text([f(log, segs) for f in SANITY])


def report(res):
    """The check report as text, for the engineer."""
    claim = {True: 'spillback', False: 'no spillback', None: 'no verdict'}[res['claim']]
    out = [f'check_study{" - run " + res["run"] if res.get("run") else ""}',
           f'Question: {res["question"]}', f'Answer:   {res["answer"]}', f'The answer says: {claim}', '']
    for kind, title in (('sanity', 'SANITY CHECKS (must pass; a failure goes back to the model)'),
                        (None, 'THEORY AND REPLAY CHECKS (must be explained; for the engineer)')):
        rows = [c for c in res['checks'] if (c['kind'] == 'sanity') == (kind == 'sanity')]
        if not rows:
            continue
        out.append(title)
        for c in rows:
            out.append(f'  {c["status"]:<8}{c["check"]:<13}{c["finding"]}')
        out.append('')
    n_fail = sum(c['status'] == 'FAIL' for c in res['checks'] if c['kind'] == 'sanity')
    n_exp = sum(c['status'] in ('EXPLAIN', 'FAIL') for c in res['checks'] if c['kind'] != 'sanity')
    if res['gate']:
        out.append(f'RESULT: BLOCKED. {n_fail} sanity check(s) failed. The harness sends this back to the model:')
        out += ['  ' + l for l in res['gate'].split('\n')]
    else:
        out.append('RESULT: the sanity checks pass; the answer can go to the engineer'
                   + (f', with {n_exp} theory or replay finding(s) to read first.' if n_exp else '.'))
    return '\n'.join(out)


if __name__ == '__main__':
    args = sys.argv[1:]
    if not args:
        raise SystemExit(__doc__)
    res = check_study(args[0], replay_run='--no-replay' not in args)
    print(report(res))
    if '--json' in args:
        path = args[args.index('--json') + 1]
        json.dump({k: v for k, v in res.items()}, open(path, 'w'), indent=1, default=str)
        print(f'\nSaved {path}')
