"""SUMO tools for AI agents, written the way a traffic engineer would write them.

Companion: "Building SUMO Tools for AI Agents" (AI for Mobility, Module 5). It explains each design choice
and shows, with measured runs, what goes wrong when the same tools are written straight from the API docs
(api_shaped_tools.py).

Each tool is a plain Python function. Its docstring is the description the model reads, and TOOLS holds the
JSON schemas that a harness or an MCP server (mcp_server.py) hands to the model. test_claims.py checks the
claims these descriptions make against real SUMO runs (tested with SUMO 1.28.0).

Two kinds of tools:
  * live tools drive one running simulation through TraCI: start_live, advance, get_approach_state,
    get_corridor_state, get_signal_plan, set_signal_timing, take_screenshot, stop_live
  * study tools run complete headless simulations as separate SUMO processes and read the output files with
    sumolib: list_intersections, check_calibration, webster_timing, compare_plans

Scenario: the Fowler Avenue corridor at USF Tampa built by build_fowler.py (real OpenStreetMap network,
SYNTHETIC demand). Point SCENARIO at your own files to use the tools elsewhere.

    pip install eclipse-sumo pyproj rtree
    python build_fowler.py                  # once
    python sumo_agent_tools.py demo         # a short tour of the tools
    python sumo_agent_tools.py approve demand "Your Name"   # the engineer's sign-off (people only)
"""
import os, sys, json, math, re, statistics, subprocess, datetime, hashlib
import sumo, sumolib, traci

HERE = os.path.dirname(os.path.abspath(__file__))
SUMO_HOME = os.environ.setdefault('SUMO_HOME', sumo.SUMO_HOME)
BIN, SUMO_TOOLS = os.path.join(SUMO_HOME, 'bin'), os.path.join(SUMO_HOME, 'tools')
SCEN = os.path.join(HERE, 'fowler')
SCENARIO = {'net': f'{SCEN}/fowler.net.xml', 'detectors': f'{SCEN}/e2.add.xml',
            'stations': f'{SCEN}/stations.add.xml', 'field_counts': f'{SCEN}/field_counts.xml',
            'demands': {'demand': f'{SCEN}/demand.rou.xml', 'demand_lp': f'{SCEN}/demand_lp.rou.xml',
                        'random': f'{SCEN}/random.rou.xml'}}
RUNS = os.path.join(HERE, 'runs')
WARMUP, END, COOLDOWN = 900, 4500, 900     # 15-min warm-up, the analysis hour, 15 min to let it drain
APPROVAL = os.path.join(HERE, 'calibration_approved.json')

# Engineering values. They are examples: use your agency's timing standards.
MPH, FT = 0.44704, 0.3048
STOPPED_MPS = 0.1                    # SUMO counts a vehicle as halting below 0.1 m/s
QUEUE_MPS, QUEUE_GAP_M = 5 / 3.6, 10  # queue definition: SUMO's lane-area (E2) detector defaults
WALK_S, PED_FTPS = 7, 3.5            # walk interval and walking speed for pedestrian clearance (MUTCD)
MIN_GREEN_S, MIN_LEFT_S, MAX_CYCLE_S = 7, 5, 180
ITE_PRT_S, ITE_DECEL_FTPS2 = 1.0, 10.0   # yellow = t + v / (2a), level approach
GEH_OK, GEH_SHARE = 5.0, 0.85        # calibration target: GEH < 5 at 85% of count stations
FOWLER = 'E Fowler Ave'

# ------------------------------------------------------------------------------------------------------
# Network knowledge (sumolib): name things the way an engineer does
# ------------------------------------------------------------------------------------------------------
_NET = None


def _net():
    global _NET
    if _NET is None:   # withPrograms=True: readNet's default loads no signal plans at all
        _NET = sumolib.net.readNet(SCENARIO['net'], withPrograms=True)
    return _NET


def _short(name):
    for a, b in (('Boulevard', 'Blvd'), ('Avenue', 'Ave'), ('Street', 'St'), ('Drive', 'Dr'),
                 ('North ', 'N '), ('East ', 'E ')):
        name = name.replace(a, b)
    return name


def _heading(edge, at_end=True):
    """Compass heading of travel in degrees (0 = north, 90 = east) at the end or start of an edge."""
    s = edge.getShape()
    (x0, y0), (x1, y1) = (s[-2], s[-1]) if at_end else (s[0], s[1])
    return math.degrees(math.atan2(x1 - x0, y1 - y0)) % 360


def _bound(h):
    return ['NB', 'EB', 'SB', 'WB'][int(((h + 45) % 360) // 90)]


def _intersections():
    """Signal name -> traffic-light id. Names come from the cross streets, as on a timing sheet."""
    out = {}
    for tls in _net().getTrafficLights():
        streets = []
        for c in tls.getConnections():
            n = _short(c[0].getEdge().getName())
            if n and n not in streets:
                streets.append(n)
        streets.sort(key=lambda s: (s != FOWLER, s))
        out[' & '.join(streets)] = tls.getID()
    return out


def _resolve(intersection):
    names = _intersections()
    for k, v in names.items():
        if intersection == v:
            return v, k
    skip = {'and', 'at', 'e', 'n', 'ave', 'st', 'blvd', 'dr', 'usf', 'the'}
    want = [w for w in re.split(r'[^a-z0-9]+', intersection.lower()) if w and w not in skip]
    hits = [k for k in names if want and all(w in k.lower() for w in want)]
    if len(hits) != 1:
        raise ValueError(f'"{intersection}" matches {len(hits)} signals. The signals are: ' + '; '.join(names))
    return names[hits[0]], hits[0]


def _tls_edges(tls_id):
    tls = _net().getTLS(tls_id)
    inc, out = [], []
    for c in tls.getConnections():
        a, b = c[0].getEdge(), c[1].getEdge()
        if a not in inc:
            inc.append(a)
        if b not in out:
            out.append(b)
    return inc, out


def _approaches(tls_id):
    """{'EB': edge, ...}: the stop-line edge of each approach. A short edge between two halves of a joined
    intersection (it is both entering and leaving the same signal) is not an approach."""
    inc, out = _tls_edges(tls_id)
    app = {}
    for e in inc:
        if e in out:
            continue
        b = _bound(_heading(e))
        if b not in app or e.getLaneNumber() > app[b].getLaneNumber():
            app[b] = e
    return app


def _upstream_chain(edge, max_m=1500):
    """The approach block: this edge and the edges behind it on the same street, back to the previous
    signal (or the network edge). Returns [(edge, distance from stop line to the edge's downstream end)]."""
    chain, dist, e = [(edge, 0.0)], edge.getLength(), edge
    while dist < max_m:
        fn = e.getFromNode()
        if fn.getType() == 'traffic_light':
            break
        prev = [p for p in fn.getIncoming() if p.getName() == e.getName() and p.getFromNode() != e.getToNode()]
        if not prev:
            break
        e = max(prev, key=lambda p: p.getLaneNumber())
        chain.append((e, dist))
        dist += e.getLength()
    return chain, dist


def _leg_width_ft(tls_id):
    """Curb-to-curb width of each approach leg in feet: lanes entering plus lanes leaving on that leg."""
    inc, out = _tls_edges(tls_id)
    app = _approaches(tls_id)
    width = {}
    for b, e in app.items():
        h = _heading(e)
        back = [o for o in out if abs(((_heading(o, at_end=False) - h + 180) % 360) - 180) > 135]
        w = sum(l.getWidth() for l in e.getLanes()) + sum(l.getWidth() for o in back[:1] for l in o.getLanes())
        width[b] = w / FT
    return width


def _links(tls_id):
    """link index -> (approach direction, movement 's'/'l'/'r'), from the network's connections."""
    out = {}
    for c in _net().getTLS(tls_id).getConnections():
        a, b, idx = c[0].getEdge(), c[1].getEdge(), c[2]
        cs = a.getConnections(b)
        d = {'s': 's', 'l': 'l', 'L': 'l', 't': 'l', 'r': 'r', 'R': 'r'}.get(cs[0].getDirection() if cs else 's', 's')
        out[idx] = (_bound(_heading(a)), d)
    return out


def _phase_moves(tls_id, state):
    """What a phase lets go, e.g. {'EB': {'s': 'G', 'l': 'g'}} (G protected, g permissive/yield)."""
    moves = {}
    for idx, (b, d) in _links(tls_id).items():
        if idx < len(state) and state[idx] in 'Gg':
            mv = moves.setdefault(b, {})
            if mv.get(d) != 'G':
                mv[d] = state[idx]
    return moves


def _runs(durations, flags):
    """Durations of the continuous runs of phases where flag is True, wrapping around the cycle."""
    n = len(flags)
    if all(flags):
        return [sum(durations)]
    start = next(i for i in range(n) if not flags[i])
    runs, cur = [], 0.0
    for k in range(1, n + 1):
        i = (start + k) % n
        if flags[i]:
            cur += durations[i]
        elif cur:
            runs.append(cur)
            cur = 0.0
    if cur:
        runs.append(cur)
    return runs


def _checks(tls_id, phases):
    """Every timing rule for one signal. phases: [(duration, state)]. Returns [(rule, have, need, ok)].
      * each through movement: every green interval at least 7 s; each left turn: at least 5 s
      * each crosswalk: pedestrians cross a leg while that leg's through and left traffic is stopped and some
        other approach is green; the longest such interval must fit walk + clearance at 3.5 ft/s"""
    d = [p[0] for p in phases]
    moves = [_phase_moves(tls_id, p[1]) for p in phases]
    out = []
    for b in sorted({b for m in moves for b in m}):
        for mv, need in (('s', MIN_GREEN_S), ('l', MIN_LEFT_S)):
            flags = [mv in m.get(b, {}) for m in moves]
            if any(flags):
                have = min(_runs(d, flags))
                out.append((f'{b} {"through" if mv == "s" else "left"} green', have, need, have >= need))
    for b, w in _leg_width_ft(tls_id).items():
        if b not in _crosswalk_legs(tls_id):
            continue
        need = math.ceil(WALK_S + w / PED_FTPS)
        flags = _ped_flags(phases, moves, b)
        runs = _runs(d, flags) if any(flags) else [0.0]
        out.append((f'crosswalk across the {b} leg ({w:.0f} ft)', max(runs), need, max(runs) >= need))
    return out


def _ped_flags(phases, moves, b):
    """Phases in which pedestrians can cross leg b: no yellow, something green, and b's through and left stopped."""
    return [('y' not in p[1]) and bool(m) and not ({'s', 'l'} & set(m.get(b, {}))) for p, m in zip(phases, moves)]


_XWALK = {}


def _crosswalk_legs(tls_id):
    """Legs with a crosswalk: those the network's own plan stops at some point (the network has no sidewalks, so
    we assume a crosswalk wherever the original plan leaves time for one)."""
    if tls_id not in _XWALK:
        prog = list(_net().getTLS(tls_id).getPrograms().values())[0]
        phases = [(p.duration, p.state) for p in prog.getPhases()]
        moves = [_phase_moves(tls_id, p[1]) for p in phases]
        _XWALK[tls_id] = {b for b in _leg_width_ft(tls_id) if any(_ped_flags(phases, moves, b))}
    return _XWALK[tls_id]


def _change_need(tls_id, state, prev_state):
    """ITE yellow for the movements that turn yellow in this phase (fastest of their approaches)."""
    app = _approaches(tls_id)
    bs = {b for idx, (b, _) in _links(tls_id).items() if idx < len(state) and state[idx] == 'y'}
    v = [app[b].getSpeed() for b in bs if b in app]
    return _ite_yellow(max(v)) if v else 0.0


def _ite_yellow(speed_mps):
    v = speed_mps / FT
    return ITE_PRT_S + v / (2 * ITE_DECEL_FTPS2)


def _describe_moves(moves):
    name = {'s': 'through', 'l': 'left', 'r': 'right'}
    parts = []
    for b in ('NB', 'SB', 'EB', 'WB'):
        if b in moves:
            parts.append(b + ' ' + '+'.join(name[x] + ('' if moves[b][x] == 'G' else ' (yield)')
                                             for x in ('s', 'l', 'r') if x in moves[b]))
    return ', '.join(parts) or 'nothing'


def list_intersections() -> str:
    """List every signalized intersection in the network, named by its cross streets, with each approach's
    direction of travel (EB/WB/NB/SB), lanes at the stop line, speed limit in mph, and storage length in feet
    (stop line back to the previous signal or the network edge). Use these names in the other tools; you
    never need SUMO's internal ids. Reads the network file only; no simulation runs."""
    lines = []
    for name, tid in _intersections().items():
        parts = []
        for b, e in sorted(_approaches(tid).items()):
            _, store = _upstream_chain(e)
            parts.append(f'{b} {e.getLaneNumber()} ln {e.getSpeed() / MPH:.0f} mph {store / FT:,.0f} ft')
        lines.append(f'{name}: ' + '; '.join(parts))
    return f'{len(lines)} signals.\n' + '\n'.join(lines)


# ------------------------------------------------------------------------------------------------------
# Live tools (TraCI): one running simulation, with or without the GUI
# ------------------------------------------------------------------------------------------------------
_LIVE = {'on': False}


def start_live(gui: bool = False, demand: str = 'demand', seed: int = 1) -> str:
    """Start one live SUMO simulation of the Fowler Ave scenario that the other live tools then read and change.
    gui=True opens SUMO's graphical window (sumo-gui) so people can watch, for example in a TMC; gui=False runs
    headless, which is faster and is what you want for long or repeated runs. The clock starts at 0 s; the first
    900 s are warm-up and the analysis hour is 900-4500 s. Starting a new one closes any running simulation."""
    if demand not in SCENARIO['demands']:
        return f'Error: demand must be one of {list(SCENARIO["demands"])}.'
    stop_live()
    binary = os.path.join(BIN, 'sumo-gui' if gui else 'sumo')
    cmd = [binary, '-n', SCENARIO['net'], '-r', SCENARIO['demands'][demand], '-a', SCENARIO['detectors'],
           '--seed', str(seed), '--no-step-log', '--no-warnings', '--time-to-teleport', '300']
    if gui:
        cmd += ['--start', '--quit-on-end', '--delay', '20']
    traci.start(cmd, stdout=subprocess.DEVNULL)      # keep SUMO's console text off stdout (MCP uses stdout)
    _LIVE.update(on=True, gui=gui, demand=demand, seed=seed, teleports=0,
                 probe={d: {'in': {}, 'done': []} for d in ('EB', 'WB')})
    return (f'Started {"sumo-gui" if gui else "sumo (headless)"} with demand "{demand}", seed {seed}. '
            f'Time 0 s. Warm-up until 900 s; analysis hour 900-4500 s.')


def stop_live() -> str:
    """Close the live simulation, if one is running."""
    if _LIVE.get('on'):
        traci.close()
        _LIVE['on'] = False
        return 'Closed the live simulation.'
    return 'No live simulation was running.'


def _need_live():
    if not _LIVE.get('on'):
        raise RuntimeError('No live simulation. Call start_live first.')


CORRIDOR_ENDS = {'EB': ('1125146807#0', '77843971#0'), 'WB': ('88714948#1', '1344053686')}


def _probe_step():
    """Like two Bluetooth readers per direction: note when each vehicle passes the first and the last Fowler edge."""
    t = traci.simulation.getTime()
    for d, (a, b) in CORRIDOR_ENDS.items():
        p = _LIVE['probe'][d]
        for v in traci.edge.getLastStepVehicleIDs(a):
            p['in'].setdefault(v, t)
        for v in traci.edge.getLastStepVehicleIDs(b):
            if v in p['in']:
                p['done'].append((t, t - p['in'].pop(v)))


def advance(seconds: int) -> str:
    """Run the live simulation FORWARD by this many seconds (1-3600), relative to now; a change you made (a new signal
    timing) acts only while time passes. Returns the vehicle ledger for the interval: vehicles that entered and
    left, the change in vehicles in the network (always entered minus left), how many are waiting to enter at the
    network edge, and teleports. SUMO teleports a vehicle stuck for 300 s by moving it ahead: any teleport means
    the network jammed somewhere and travel times are no longer physical."""
    _need_live()
    if not 1 <= seconds <= 3600:
        return 'Rejected: seconds must be 1-3600.'
    t0, n0 = traci.simulation.getTime(), traci.vehicle.getIDCount()
    dep = arr = tel = 0
    for _ in range(int(seconds)):
        traci.simulationStep()          # one 1-s step; simulationStep(t) would run to the ABSOLUTE time t
        dep += traci.simulation.getDepartedNumber()
        arr += traci.simulation.getArrivedNumber()
        tel += traci.simulation.getStartingTeleportNumber()
        _probe_step()
    _LIVE['teleports'] += tel
    t, n = traci.simulation.getTime(), traci.vehicle.getIDCount()
    waiting = len(traci.simulation.getPendingVehicles())
    phase = 'warm-up' if t <= WARMUP else 'analysis hour' if t <= END else 'after the analysis hour'
    msg = (f'Time {t:.0f} s ({phase}). In the last {t - t0:.0f} s: {dep} entered, {arr} left; network '
           f'{n0} -> {n} vehicles ({n - n0:+d} = {dep} - {arr}). Waiting to enter: {waiting}. Teleports: {tel}.')
    if tel:
        msg += f' WARNING: {tel} teleport(s): something jammed for 300 s; treat delays from this run as unreliable.'
    if waiting > 20:
        msg += f' WARNING: {waiting} vehicles cannot enter: demand at the network edge exceeds what it can take.'
    return msg


def _queue_back(vehicles, speed_mps=QUEUE_MPS, gap_m=QUEUE_GAP_M):
    """Back of queue (m from the stop line) and vehicles in it. `vehicles`: (distance of the front bumper from the
    stop line, length, speed). A vehicle is queued if slower than speed_mps and linked to the stop line through
    queued vehicles at most gap_m apart (bumper to bumper), in any lane."""
    slow = sorted((d, L) for d, L, v in vehicles if v < speed_mps)
    back, n = 0.0, 0
    for d, L in slow:
        if d - back > gap_m:
            break
        back, n = max(back, d + L), n + 1
    return back, n


def _approach_vehicles(edge):
    chain, store = _upstream_chain(edge)
    out = []
    for e, off in chain:
        for lane in e.getLanes():
            for v in traci.lane.getLastStepVehicleIDs(lane.getID()):
                d = off + lane.getLength() - traci.vehicle.getLanePosition(v)
                out.append((d, traci.vehicle.getLength(v), traci.vehicle.getSpeed(v)))
    lane_m = sum(l.getLength() for e, _ in chain for l in e.getLanes())
    return out, store, lane_m


def get_approach_state(intersection: str, approach: str) -> str:
    """Traffic on one approach to a signal, over the whole block (stop line back to the previous signal), as of the
    last simulation step. intersection: cross streets, e.g. "Fowler & McKinley"; approach: EB, WB, NB or SB
    (direction of travel). Returns: vehicles on the block; stopped vehicles (below 0.1 m/s); back of queue in feet
    and vehicles in it, where a vehicle is queued if slower than 5 km/h (3.1 mph) and within 10 m of the queue
    ahead in any lane (SUMO's lane-area detector rule); storage length, with a SPILLBACK flag when the queue fills
    85% of it; space-mean speed in mph, the average of the vehicles' speeds, or "no vehicles" when the block is
    empty (speed is undefined at zero density; SUMO's lane speed would report the speed limit); density in
    veh/mi/lane; and the through signal indication. A queue at a signal rises and falls every cycle: one reading
    is a snapshot, so read it at the end of red or several times. Read-only."""
    _need_live()
    tid, name = _resolve(intersection)
    app = _approaches(tid)
    if approach not in app:
        return f'Error: {name} has approaches {sorted(app)}, not {approach}.'
    edge = app[approach]
    veh, store, lane_m = _approach_vehicles(edge)
    back, nq = _queue_back(veh)
    stopped = sum(v < STOPPED_MPS for _, _, v in veh)
    speed = (f'{statistics.mean(v for _, _, v in veh) / MPH:.0f} mph space-mean speed' if veh
             else 'no vehicles (speed not measured)')
    density = len(veh) / (lane_m / 1609.344)
    st = traci.trafficlight.getRedYellowGreenState(tid)
    thru = [st[i] for i, (b, d) in _links(tid).items() if b == approach and d == 's' and i < len(st)]
    sig = ('green' if any(c in 'Gg' for c in thru) else 'yellow' if any(c == 'y' for c in thru) else
           'red' if thru else 'no through movement')
    nxt = traci.trafficlight.getNextSwitch(tid) - traci.simulation.getTime()
    spill = ' SPILLBACK: the queue fills over 85% of the storage.' if back > 0.85 * store else ''
    return (f'{name}, {approach} at {traci.simulation.getTime():.0f} s: {len(veh)} vehicles on {store / FT:,.0f} ft '
            f'of storage, {stopped} stopped; back of queue {back / FT:,.0f} ft ({nq} vehicles); {speed}; '
            f'{density:.0f} veh/mi/lane; through signal {sig}, next change in {nxt:.0f} s.{spill}')


def _fowler_path(direction):
    n = _net()
    a, b = CORRIDOR_ENDS[direction]
    return n.getShortestPath(n.getEdge(a), n.getEdge(b))[0]


def _segments(direction):
    """Fowler split at its signals: [(label, [edges])]."""
    names = {v: k for k, v in _intersections().items()}
    stop = {}
    for t in _net().getTrafficLights():
        for b, e in _approaches(t.getID()).items():
            stop[e.getID()] = names[t.getID()].replace(FOWLER + ' & ', '')
    segs, cur, start = [], [], 'west end' if direction == 'EB' else 'east end'
    for e in _fowler_path(direction):
        cur.append(e)
        if e.getID() in stop:
            segs.append((f'{start} -> {stop[e.getID()]}', cur))
            cur, start = [], stop[e.getID()]
    segs.append((f'{start} -> {"east end" if direction == "EB" else "west end"}', cur))
    return [s for s in segs if s[1]]


def get_corridor_state(direction: str) -> str:
    """Fowler Ave in one direction (EB or WB) as of the last step, one line per segment between signals: length,
    vehicles, stopped vehicles and space-mean speed in mph ("empty" when no vehicle is on it). Travel time is
    MEASURED, not computed from spot speeds: the median of the vehicles that drove the whole corridor and finished
    in the last 10 minutes (like Bluetooth or probe data), with how many trips that is, next to the free-flow time.
    One call replaces a lane-by-lane survey of the corridor. Read-only."""
    _need_live()
    if direction not in ('EB', 'WB'):
        return 'Error: direction must be EB or WB.'
    now, rows, total_m, ff = traci.simulation.getTime(), [], 0.0, 0.0
    for label, edges in _segments(direction):
        L = sum(e.getLength() for e in edges)
        sp = [traci.vehicle.getSpeed(v) for e in edges for v in traci.edge.getLastStepVehicleIDs(e.getID())]
        txt = (f'{len(sp)} veh, {sum(x < STOPPED_MPS for x in sp)} stopped, {statistics.mean(sp) / MPH:.0f} mph'
               if sp else 'empty')
        rows.append(f'  {label}: {L / FT:,.0f} ft, {txt}')
        total_m += L
        ff += sum(e.getLength() / e.getSpeed() for e in edges)
    recent = [tt for t, tt in _LIVE['probe'][direction]['done'] if t > now - 600]
    meas = (f'measured travel time {statistics.median(recent) / 60:.1f} min (median of {len(recent)} trips in the '
            f'last 10 min)' if recent else 'no corridor trips finished in the last 10 min')
    return (f'Fowler Ave {direction} at {now:.0f} s, {total_m / 1609.344:.2f} mi: {meas}; free-flow '
            f'{ff / 60:.1f} min.\n' + '\n'.join(rows))


def _plan_report(tid, phases):
    lines, d = [], [p[0] for p in phases]
    for i, (dur, state) in enumerate(phases):
        mv = _phase_moves(tid, state)
        if 'y' in state:
            need = _change_need(tid, state, phases[i - 1][1])
            flag = f'  SHORTER THAN ITE {need:.1f} s' if dur < need - 0.05 else ''
            lines.append(f'  phase {i}: {dur:.0f} s change (yellow){flag}; still green: {_describe_moves(mv)}')
        elif mv:
            lines.append(f'  phase {i}: {dur:.0f} s, green: {_describe_moves(mv)}')
        else:
            lines.append(f'  phase {i}: {dur:.0f} s all red')
    bad = [c for c in _checks(tid, phases) if not c[3]]
    rules = '\n'.join(f'  FAILS: {r}: {h:.0f} s, needs {n} s' for r, h, n, _ in bad) or '  all timing minimums met'
    return f'cycle {sum(d):.0f} s\n' + '\n'.join(lines) + '\n' + rules


def get_signal_plan(intersection: str) -> str:
    """The timing plan running now at one signal: each phase's number, duration in seconds and what is green
    ("(yield)" = permissive), then every timing minimum it fails: each through movement's green at least 7 s and each
    left turn's at least 5 s; each crosswalk needs walk (7 s) + crossing width / 3.5 ft/s while that leg's traffic
    is stopped; each yellow at least the ITE change interval for the approach speed (1 s + v / 2a, a = 10 ft/s^2).
    Live simulation only. Read-only."""
    _need_live()
    tid, name = _resolve(intersection)
    logic = traci.trafficlight.getAllProgramLogics(tid)[0]
    return f'{name}, ' + _plan_report(tid, [(p.duration, p.state) for p in logic.phases])


def set_signal_timing(intersection: str, durations: dict[str, float]) -> str:
    """Change phase durations at one signal in the live simulation. durations: {phase number: seconds}; phases you
    leave out keep their durations (see get_signal_plan for the numbers). The whole new plan is checked first and
    REJECTED, with nothing changed, if any timing minimum fails (through green 7 s, left 5 s, walk + pedestrian
    clearance, ITE yellow) or the cycle exceeds 180 s. The new plan starts at once; call advance to see its effect."""
    _need_live()
    tid, name = _resolve(intersection)
    logic = traci.trafficlight.getAllProgramLogics(tid)[0]
    try:
        durations = {int(k): float(v) for k, v in durations.items()}
    except (TypeError, ValueError):
        return 'Error: durations must map phase numbers to seconds, e.g. {"0": 40, "4": 30}.'
    if any(not 0 <= i < len(logic.phases) for i in durations):
        return f'Error: phase numbers run 0-{len(logic.phases) - 1}.'
    phases = [(durations.get(i, p.duration), p.state) for i, p in enumerate(logic.phases)]
    problems = [f'{r}: {h:.0f} s, needs {n} s' for r, h, n, ok in _checks(tid, phases) if not ok]
    problems += [f'phase {i} yellow {d:.1f} s is shorter than ITE {_change_need(tid, s, phases[i - 1][1]):.1f} s'
                 for i, (d, s) in enumerate(phases) if 'y' in s and d < _change_need(tid, s, phases[i - 1][1]) - 0.05]
    cyc = sum(d for d, _ in phases)
    if cyc > MAX_CYCLE_S:
        problems.append(f'cycle {cyc:.0f} s is over {MAX_CYCLE_S} s')
    if problems:
        return 'Rejected, nothing changed: ' + '; '.join(problems) + '.'
    for i, (d, _) in enumerate(phases):
        logic.phases[i].duration = logic.phases[i].minDur = logic.phases[i].maxDur = d
    traci.trafficlight.setProgramLogic(tid, logic)
    return f'{name}: new plan, cycle {cyc:.0f} s, durations {[d for d, _ in phases]}.'


def take_screenshot(path: str = 'tmc_view.png') -> str:
    """Save a picture of the sumo-gui window (only when start_live was called with gui=True). The file is written
    at the end of the next simulation step, so call advance afterwards."""
    _need_live()
    if not _LIVE.get('gui'):
        return 'Error: no GUI. Start with start_live(gui=True) to take screenshots.'
    traci.gui.screenshot('View #0', os.path.abspath(path))
    return f'Screenshot will be saved to {path} after the next step.'


# ------------------------------------------------------------------------------------------------------
# Study tools: whole runs, several seeds, read with sumolib
# ------------------------------------------------------------------------------------------------------
def _sumo(*args):
    r = subprocess.run([os.path.join(BIN, 'sumo')] + [str(a) for a in args], capture_output=True, text=True)
    if r.returncode:
        raise RuntimeError(r.stderr[-1500:])


def _plan_file(plan):
    if plan == 'existing':
        return None
    p = os.path.join(RUNS, f'{plan}.add.xml')
    if not os.path.exists(p):
        raise ValueError(f'No plan "{plan}". Make one with webster_timing first.')
    return p


def _run(plan='existing', seed=1, demand='demand', scale=1.0, stations=False):
    """One headless run. Returns the engineer's measures and the naive one, for the analysis-hour cohort."""
    tag = f'{demand}_{plan}_s{seed}_x{scale:g}'
    out = os.path.join(RUNS, tag)
    os.makedirs(out, exist_ok=True)
    adds = [p for p in (_plan_file(plan),) if p]
    if stations:
        st = open(SCENARIO['stations']).read().replace('file="loops_out.xml"', f'file="{out}/loops_out.xml"')
        open(f'{out}/stations.add.xml', 'w').write(st)
        adds.append(f'{out}/stations.add.xml')
    _sumo('-n', SCENARIO['net'], '-r', SCENARIO['demands'][demand], *(['-a', ','.join(adds)] if adds else []),
          '--end', END + COOLDOWN, '--seed', seed, '--scale', scale, '--no-step-log', '--no-warnings',
          '--tripinfo-output', f'{out}/tripinfo.xml', '--tripinfo-output.write-unfinished',
          '--statistic-output', f'{out}/stats.xml')
    st = sumolib.xml.parse(f'{out}/stats.xml', 'statistics').__next__()
    veh, tel, trip = st.vehicles[0], st.teleports[0], st.vehicleTripStatistics[0]
    waiting, wait_delay = int(veh.waiting), float(trip.departDelayWaiting)
    cohort, finished_all = [], []
    corridor = {'EB': [], 'WB': []}
    ends = {'EB': ('1125146807#0', '77843971#0'), 'WB': ('88714948#1', '1344053686')}
    for t in sumolib.xml.parse_fast(f'{out}/tripinfo.xml', 'tripinfo',
                                    ['id', 'depart', 'departLane', 'departDelay', 'arrival', 'arrivalLane',
                                     'duration', 'timeLoss']):
        arrived = float(t.arrival) >= 0
        if arrived:
            finished_all.append(float(t.timeLoss))
        sched = float(t.depart) - float(t.departDelay)
        if WARMUP <= sched < END:
            cohort.append((float(t.timeLoss) + float(t.departDelay), arrived))
            for d, (a, b) in ends.items():
                if t.departLane.rsplit('_', 1)[0] == a:
                    corridor[d].append(float(t.duration) if arrived and t.arrivalLane.rsplit('_', 1)[0] == b
                                       else None if not arrived else 'other')
    n = len(cohort) + waiting
    res = {
        'plan': plan, 'seed': seed, 'demand': demand, 'scale': scale,
        'loaded': int(veh.loaded), 'inserted': int(veh.inserted), 'waiting_to_enter': waiting,
        'teleports': int(tel.total),
        'cohort': n, 'cohort_unfinished': sum(not a for _, a in cohort) + waiting,
        'delay_s_per_veh': (sum(d for d, _ in cohort) + waiting * wait_delay) / max(n, 1),
        'naive_delay_s_per_veh': statistics.mean(finished_all) if finished_all else float('nan'),
        'naive_vehicles': len(finished_all),
    }
    for d, v in corridor.items():
        done = [x for x in v if isinstance(x, float)]
        res[f'fowler_{d}_min'] = statistics.median(done) / 60 if done else None
        res[f'fowler_{d}_trips'] = len(done)
        res[f'fowler_{d}_unfinished'] = sum(x is None for x in v)
    if stations:
        res['station_counts'] = _station_counts(f'{out}/loops_out.xml')
    return res


def _station_counts(loop_file):
    tot = {}
    for iv in sumolib.xml.parse(loop_file, 'interval'):
        if float(iv.begin) >= WARMUP and float(iv.end) <= END:
            eid = iv.id[4:].rsplit('_', 1)[0]
            tot[eid] = tot.get(eid, 0) + int(iv.nVehContrib)
    return {k: v * 3600 / (END - WARMUP) for k, v in tot.items()}


def _field_counts():
    field, labels = {}, {}
    for iv in sumolib.xml.parse(SCENARIO['field_counts'], 'interval'):
        if iv.id == 'pm_peak':
            for e in iv.edge:
                field[e.id] = float(e.entered)
    try:
        sys.path.insert(0, HERE)
        from build_fowler import STATIONS
        labels = STATIONS
    except ImportError:
        pass
    return field, labels


def _geh(m, c):
    return math.sqrt(2 * (m - c) ** 2 / (m + c)) if m + c else 0.0


def check_calibration(demand: str = 'demand', seeds: int = 3) -> str:
    """Compare simulated and field counts at the 16 count stations for the analysis hour (900-4500 s). The
    simulated counts come from induction loops across every lane at mid-block, which count the way a field counter
    does, averaged over several runs (seeds, 1-10). Returns GEH = sqrt(2(M-C)^2/(M+C)) per station (M simulated, C field,
    veh/h), the worst stations, and PASS if GEH < 5 at 85% of stations or more. A pass is not an approval: an
    engineer must review the result and sign it off before compare_plans will run. demand: "demand" (counts with
    the through-trip prior), "demand_lp" (counts alone) or "random" (random trips)."""
    if demand not in SCENARIO['demands']:
        return f'Error: demand must be one of {list(SCENARIO["demands"])}.'
    if not 1 <= seeds <= 10:
        return 'Rejected: seeds must be 1-10.'
    field, labels = _field_counts()
    runs = [_run('existing', s, demand, stations=True)['station_counts'] for s in range(1, seeds + 1)]
    rows = []
    for eid, c in field.items():
        m = statistics.mean(r.get(eid, 0.0) for r in runs)
        rows.append((_geh(m, c), labels.get(eid, eid), m, c))
    ok = sum(g < GEH_OK for g, *_ in rows)
    passed = ok >= GEH_SHARE * len(rows)
    rows.sort(reverse=True)
    worst = '\n'.join(f'  {lab}: simulated {m:,.0f}, field {c:,.0f} veh/h, GEH {g:.1f}' for g, lab, m, c in rows[:4])
    result = {'demand': demand, 'seeds': seeds, 'stations': len(rows), 'geh_under_5': ok, 'passed': passed,
              'rows': [dict(station=lab, simulated=round(m), field=round(c), geh=round(g, 2)) for g, lab, m, c in rows]}
    os.makedirs(RUNS, exist_ok=True)
    json.dump(result, open(os.path.join(RUNS, f'calibration_{demand}.json'), 'w'), indent=1)
    return (f'Calibration of "{demand}" ({seeds} seeds): GEH < 5 at {ok} of {len(rows)} stations '
            f'({ok / len(rows):.0%}); target 85%: {"PASS" if passed else "FAIL"}.\nWorst stations:\n{worst}\n'
            + ('An engineer must review and approve this calibration before compare_plans will run.' if passed else
               'Do not compare plans on this demand. Fix the demand (counts, routes, the trip prior) and check again.'))


def approve_calibration(demand, engineer):
    """For PEOPLE, not for the model: record an engineer's sign-off of a passing calibration. Not in TOOLS."""
    p = os.path.join(RUNS, f'calibration_{demand}.json')
    res = json.load(open(p))
    if not res['passed']:
        raise SystemExit('This calibration did not pass; it cannot be approved.')
    rec = {'demand': demand, 'engineer': engineer, 'time': datetime.datetime.now().isoformat(timespec='seconds'),
           'result_sha1': hashlib.sha1(open(p, 'rb').read()).hexdigest()}
    json.dump(rec, open(APPROVAL, 'w'), indent=1)
    return rec


def _write_plan(path, logics):
    with open(path, 'w') as f:
        f.write('<additional>\n')
        for tid, phases in logics.items():
            f.write(f'  <tlLogic id="{tid}" type="static" programID="study" offset="0">\n')
            for d, s in phases:
                f.write(f'    <phase duration="{d:g}" state="{s}"/>\n')
            f.write('  </tlLogic>\n')
        f.write('</additional>\n')


def _fix_plan(tid, phases):
    """Raise durations until every minimum is met: the engineer's pass over a computed plan."""
    phases = [list(p) for p in phases]
    for i, (d, st) in enumerate(phases):
        if 'y' in st:
            phases[i][0] = max(d, math.ceil(_change_need(tid, st, phases[i - 1][1]) * 2) / 2)
    raised = []
    for _ in range(50):
        bad = [c for c in _checks(tid, [tuple(p) for p in phases]) if not c[3]]
        if not bad:
            break
        rule, have, need, _ = bad[0]
        moves = [_phase_moves(tid, p[1]) for p in phases]
        if rule.startswith('crosswalk'):
            b = rule.split(' the ')[1].split(' ')[0]
            cand = [i for i, (p, m) in enumerate(zip(phases, moves))
                    if 'y' not in p[1] and m and not ({'s', 'l'} & set(m.get(b, {})))]
        else:
            b, mv = rule.split(' ')[0], 's' if 'through' in rule else 'l'
            cand = [i for i, (p, m) in enumerate(zip(phases, moves)) if 'y' not in p[1] and mv in m.get(b, {})]
        i = max(cand, key=lambda k: phases[k][0])
        phases[i][0] += need - have
        raised.append(f'{rule}: {have:.0f} -> {need} s')
    return [tuple(p) for p in phases], raised


def webster_timing(demand: str = 'demand') -> str:
    """Signal timing for every intersection from Webster's method (SUMO's tlsCycleAdaptation.py, flows of the
    analysis hour), then checked the way an engineer would: each yellow raised to the ITE change interval for its
    approach speed, and greens lengthened until every through movement has 7 s, every left 5 s and every crosswalk
    its walk + clearance, which lengthens the cycle. Saves two plans for compare_plans: "webster_raw" (the script
    as it comes: 4 s yellows, greens as short as 4 s) and "webster" (checked). Webster assumes each signal is
    isolated and undersaturated, hourly flows are steady and a lane saturates at 1,800 veh/h (2 s headway); it does
    not coordinate signals. Returns each signal's cycle before and after the check, and what was raised."""
    os.makedirs(RUNS, exist_ok=True)
    raw = os.path.join(RUNS, 'webster_raw.add.xml')
    subprocess.run([sys.executable, os.path.join(SUMO_TOOLS, 'tlsCycleAdaptation.py'), '-n', SCENARIO['net'],
                    '-r', SCENARIO['demands'][demand], '-o', raw, '-b', str(WARMUP)], check=True, capture_output=True)
    names = {v: k for k, v in _intersections().items()}
    safe, lines, raised_all = {}, [], 0
    for tl in sumolib.xml.parse(raw, 'tlLogic'):
        phases = [(float(p.duration), p.state) for p in tl.phase]
        fixed, raised = _fix_plan(tl.id, phases)
        safe[tl.id] = fixed
        raised_all += len(raised)
        lines.append(f'  {names[tl.id]}: cycle {sum(d for d, _ in phases):.0f} s raw -> '
                     f'{sum(d for d, _ in fixed):.0f} s checked' + (f'; raised {"; ".join(raised)}' if raised else ''))
    _write_plan(os.path.join(RUNS, 'webster.add.xml'), safe)
    return (f'Saved plans "webster_raw" and "webster" (checked; {raised_all} minimums raised, yellows set to ITE).\n'
            + '\n'.join(lines))


def _plan_problems(plan):
    p = _plan_file(plan)
    if p is None:
        return []
    names = {v: k for k, v in _intersections().items()}
    probs = []
    for tl in sumolib.xml.parse(p, 'tlLogic'):
        phases = [(float(x.duration), x.state) for x in tl.phase]
        probs += [f'{names[tl.id]}: {r} {h:.0f} s < {n} s' for r, h, n, ok in _checks(tl.id, phases) if not ok]
        probs += [f'{names[tl.id]}: yellow {d:.1f} s < ITE {_change_need(tl.id, s, phases[i - 1][1]):.1f} s'
                  for i, (d, s) in enumerate(phases) if 'y' in s and d < _change_need(tl.id, s, phases[i - 1][1]) - 0.05]
    return probs


_T975 = {2: 12.71, 3: 4.30, 4: 3.18, 5: 2.78, 6: 2.57, 7: 2.45, 8: 2.36, 9: 2.31, 10: 2.26, 11: 2.23, 12: 2.20,
         13: 2.18, 14: 2.16, 15: 2.14, 16: 2.13, 17: 2.12, 18: 2.11, 19: 2.10, 20: 2.09}


def compare_plans(alternative: str, seeds: int = 10, demand: str = 'demand') -> str:
    """Compare a timing plan with the existing timing on the same demand and the same random seeds (each seed runs
    both plans), for the vehicles due to start in the analysis hour. Delay counts every second lost, including
    waiting to enter the network and vehicles still travelling when the run ends, so gridlock cannot make a plan
    look good. Returns mean delay (s/veh) for both, the paired difference with a 95% confidence interval, how many
    seeds disagree with the average, median Fowler Ave EB/WB travel times, and teleports. alternative: "webster" or
    "webster_raw" (make them with webster_timing). seeds: 2-20. Runs only on a demand whose calibration an
    engineer approved, and rejects plans that break a minimum green or pedestrian clearance."""
    if not 2 <= seeds <= 20:
        return 'Rejected: seeds must be 2-20 (one run is an anecdote, not evidence).'
    appr = json.load(open(APPROVAL)) if os.path.exists(APPROVAL) else None
    if not appr or appr['demand'] != demand:
        return (f'Blocked: no engineer has approved the calibration of "{demand}". Run check_calibration and ask '
                'the engineer to review it.')
    probs = _plan_problems(alternative)
    if probs:
        return f'Rejected: "{alternative}" breaks {len(probs)} timing minimum(s), e.g. ' + '; '.join(probs[:3]) + '.'
    base = [_run('existing', s, demand) for s in range(1, seeds + 1)]
    alt = [_run(alternative, s, demand) for s in range(1, seeds + 1)]
    diff = [a['delay_s_per_veh'] - b['delay_s_per_veh'] for a, b in zip(alt, base)]
    m, sd = statistics.mean(diff), statistics.stdev(diff)
    hw = _T975.get(seeds, 2.0) * sd / math.sqrt(seeds)
    disagree = sum((d > 0) != (m > 0) for d in diff)

    def med(rs, k):
        v = [r[k] for r in rs if r[k] is not None]
        return statistics.median(v) if v else float('nan')
    verdict = ('better' if m + hw < 0 else 'worse' if m - hw > 0 else 'not distinguishable from existing')
    return (f'{alternative} vs existing, {seeds} seeds, demand "{demand}":\n'
            f'  delay {statistics.mean(r["delay_s_per_veh"] for r in alt):.1f} vs '
            f'{statistics.mean(r["delay_s_per_veh"] for r in base):.1f} s/veh; difference {m:+.1f} s/veh, '
            f'95% CI {m - hw:+.1f} to {m + hw:+.1f}: {verdict}. {disagree} of {seeds} single seeds point the other way.\n'
            f'  Fowler EB {med(alt, "fowler_EB_min"):.1f} vs {med(base, "fowler_EB_min"):.1f} min; '
            f'WB {med(alt, "fowler_WB_min"):.1f} vs {med(base, "fowler_WB_min"):.1f} min (median trip).\n'
            f'  Teleports per run {statistics.mean(r["teleports"] for r in alt):.1f} vs '
            f'{statistics.mean(r["teleports"] for r in base):.1f}; unfinished trips per run '
            f'{statistics.mean(r["cohort_unfinished"] for r in alt):.0f} vs {statistics.mean(r["cohort_unfinished"] for r in base):.0f}.')


# ------------------------------------------------------------------------------------------------------
# What the model sees: names, descriptions (the docstrings) and input schemas
# ------------------------------------------------------------------------------------------------------
_S = lambda **p: {'type': 'object', 'properties': p, 'required': [k for k, v in p.items() if not v.pop('_opt', False)]}
_INT = {'type': 'string', 'description': 'Cross streets, e.g. "Fowler & McKinley" (see list_intersections)'}
_APP = {'type': 'string', 'enum': ['EB', 'WB', 'NB', 'SB'], 'description': 'Direction of travel'}
_DEM = {'type': 'string', 'enum': ['demand', 'demand_lp', 'random'], '_opt': True}
SCHEMAS = {
    'list_intersections': _S(),
    'start_live': _S(gui={'type': 'boolean', '_opt': True}, demand=dict(_DEM),
                     seed={'type': 'integer', 'minimum': 1, '_opt': True}),
    'advance': _S(seconds={'type': 'integer', 'minimum': 1, 'maximum': 3600, 'description': 'Seconds to run forward'}),
    'get_approach_state': _S(intersection=dict(_INT), approach=dict(_APP)),
    'get_corridor_state': _S(direction={'type': 'string', 'enum': ['EB', 'WB']}),
    'get_signal_plan': _S(intersection=dict(_INT)),
    'set_signal_timing': _S(intersection=dict(_INT), durations={'type': 'object', 'description':
                            'Phase number -> seconds, e.g. {"0": 40, "4": 30}',
                            'additionalProperties': {'type': 'number'}}),
    'take_screenshot': _S(path={'type': 'string', '_opt': True}),
    'stop_live': _S(),
    'check_calibration': _S(demand=dict(_DEM), seeds={'type': 'integer', 'minimum': 1, 'maximum': 10, '_opt': True}),
    'webster_timing': _S(demand=dict(_DEM)),
    'compare_plans': _S(alternative={'type': 'string', 'enum': ['webster', 'webster_raw']},
                        seeds={'type': 'integer', 'minimum': 2, 'maximum': 20, '_opt': True}, demand=dict(_DEM)),
}
FUNCS = {n: globals()[n] for n in SCHEMAS}
TOOLS = [{'name': n, 'description': ' '.join(FUNCS[n].__doc__.split()), 'input_schema': s} for n, s in SCHEMAS.items()]
READ_ONLY = {'list_intersections', 'get_approach_state', 'get_corridor_state', 'get_signal_plan', 'check_calibration'}


def run_tool(name, arguments):
    """The harness side: run one tool call and always return text, errors included."""
    if name not in FUNCS:
        return f'Error: there is no tool named {name}. Tools: {", ".join(FUNCS)}.'
    try:
        return str(FUNCS[name](**(arguments or {})))
    except Exception as e:
        return f'Error: {e}'


if __name__ == '__main__':
    if len(sys.argv) >= 4 and sys.argv[1] == 'approve':
        print(approve_calibration(sys.argv[2], ' '.join(sys.argv[3:])))
    elif len(sys.argv) >= 2 and sys.argv[1] == 'demo':
        print(list_intersections())
        print(start_live())
        print(advance(1200))
        print(get_corridor_state('WB'))
        print(get_approach_state('Fowler & McKinley', 'WB'))
        print(get_signal_plan('Fowler & McKinley'))
        print(stop_live())
    else:
        print(json.dumps(TOOLS, indent=1)[:3000])
