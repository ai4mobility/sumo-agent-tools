"""Template: one SUMO tool written the way a traffic engineer would write it, and the plain version it is measured
against. Copy this folder to contrib/<your-github-username>/ and replace the example with your own tools (at least
two). Keep the shape:

  * each tool is a function with type hints, '-> str', and a docstring: the description the model reads
  * TOOLS lists the tools the model may call; READ_ONLY names the ones that only read; SCHEMAS (optional) gives the
    allowed values and ranges of the inputs, which type hints cannot say
  * a *_plain function is the baseline: the same question answered without your knowledge. It is not in TOOLS, so
    the model never sees it; test_plain_vs_... uses it to show what your knowledge changes
  * the toolkit (sumo_agent_tools.py, imported as T) does the plumbing: the live simulation (T.start_live,
    T.advance), intersection names (T._resolve), approaches (T._approaches) and the analysis-hour warning
    (T._period_note). Your tools run in the same simulation as the toolkit's.
  * PLAIN_DESCRIPTIONS and RAW_RESULTS (at the end) are for the ablation: the same tools, with the traffic
    engineering knowledge taken out of what the model reads

The example: "What is each lane doing at this approach?" SUMO answers lane by lane with ids like
'905783594_3' and numbers its lanes from the curb, so a model that reads 'lane 0' as the left lane is wrong, and an
empty lane reports the speed limit. lane_use adds what an engineer knows. KNOWLEDGE.md lists each rule with its
source and its test.
"""
import os, sys, json, statistics
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..'))
import traci
import sumo_agent_tools as T

# Rule 1. What each SUMO connection direction means for a driver (SUMO docs, "Networks/SUMO Road Networks").
MOVE = {'s': 'through', 'l': 'left', 'L': 'left', 't': 'U-turn', 'r': 'right', 'R': 'right'}
ORDER = ['U-turn', 'left', 'through', 'right']


def _lane_movements(lane):
    """The movements a lane serves at the stop line, from its connections: e.g. ['through', 'right']."""
    have = {MOVE.get(c.getDirection(), 'through') for c in lane.getOutgoing()}
    return [m for m in ORDER if m in have]


def _n(n, word):
    return f'{n} {word}' + ('' if n == 1 else 's')


def _lane_name(moves):
    if not moves:
        return 'no movement'
    if len(moves) == 1:
        return {'through': 'through lane', 'left': 'left-turn lane', 'right': 'right-turn lane',
                'U-turn': 'U-turn lane'}[moves[0]]
    turns = [m for m in moves if m != 'U-turn']
    return 'shared ' + '-'.join(turns) + (' and U-turn' if 'U-turn' in moves else '') + ' lane'


def lane_use(intersection: str, approach: str) -> str:
    """Lane by lane at one approach's stop line, as of the last simulation step. intersection: cross streets, e.g.
    "Fowler & McKinley" (see list_intersections); approach: EB, WB, NB or SB (direction of travel). Lanes are listed
    from the median (left) to the curb (right), each named by the movements it serves at the stop line: left-turn,
    through, right-turn, or shared (for example shared through-right). SUMO's own lane index runs the other way (0 is
    the curb lane). For each lane: vehicles, stopped vehicles (below 0.1 m/s, SUMO's halting rule) and space-mean
    speed in mph, or "no vehicles (speed not measured)" on an empty lane, where SUMO's lane speed would report the
    speed limit. A lane that no connection leaves at the stop line serves no movement: it is listed but not counted
    as an approach lane. The reading covers only the edge at the stop line (its length is given), not the whole block:
    for the queue over the block use get_approach_state. One reading is a snapshot of one moment. A reading outside
    the analysis hour (900-4500 s) carries a WARM-UP or AFTER-PEAK warning. Read-only: time does not pass."""
    T._need_live()
    tid, name = T._resolve(intersection)
    app = T._approaches(tid)
    if approach not in app:
        return f'Error: {name} has approaches {sorted(app)}, not {approach}. Use one of those.'
    edge = app[approach]
    lanes = sorted(edge.getLanes(), key=lambda l: -l.getIndex())           # median first: highest SUMO index
    rows, served = [], []
    for k, lane in enumerate(lanes):
        moves = _lane_movements(lane)
        pos = ' (median side)' if k == 0 else ' (curb)' if k == len(lanes) - 1 else ''
        ids = traci.lane.getLastStepVehicleIDs(lane.getID())
        sp = [traci.vehicle.getSpeed(v) for v in ids]
        if not moves:
            rows.append(f'  {k + 1}{pos}: no movement: no connection leaves this lane at the stop line, so it is not '
                        f'counted as an approach lane (in the field, a lane that ends or a connection the network is '
                        f'missing)' + (f'; {_n(len(sp), "vehicle")} on it must change lanes' if sp else ''))
            continue
        served.append(moves)
        state = (f'{_n(len(sp), "vehicle")}, {sum(v < T.STOPPED_MPS for v in sp)} stopped, '
                 f'{statistics.mean(sp) / T.MPH:.0f} mph space-mean speed' if sp else 'no vehicles (speed not measured)')
        rows.append(f'  {k + 1}{pos}: {_lane_name(moves)}: {state}')
    kinds = {}
    for m in served:
        kinds[_lane_name(m)] = kinds.get(_lane_name(m), 0) + 1
    summary = ', '.join(_n(n, k) for k, n in kinds.items())
    t = traci.simulation.getTime()
    return (f'{name}, {approach} at {t:.0f} s, the last {edge.getLength() / T.FT:,.0f} ft before the stop line: '
            f'{len(served)} of {len(lanes)} lanes serve a movement ({summary}).{T._period_note()}\n'
            f'Lanes from the median (left) to the curb (right):\n' + '\n'.join(rows))


def lane_use_plain(intersection: str, approach: str) -> str:
    """The baseline: what TraCI's lane getters return, lane by lane, as SUMO names them."""
    tid, _ = T._resolve(intersection)
    edge = T._approaches(tid)[approach]
    return '\n'.join(f'{l.getID()}: halting {traci.lane.getLastStepHaltingNumber(l.getID())}, '
                     f'mean speed {traci.lane.getLastStepMeanSpeed(l.getID()):.2f} m/s' for l in edge.getLanes())


TOOLS = [lane_use]
READ_ONLY = {'lane_use'}
SCHEMAS = {'lane_use': T._S(intersection=dict(T._INT), approach=dict(T._APP))}

# For the ablation's plain setup (contrib/ablation.py): your tools with the traffic engineering knowledge taken out
# of what the model reads. The reading stays the same; only the words change. The input schema (SCHEMAS) stays too.
#   PLAIN_DESCRIPTIONS: each tool's description as any programmer would write it from the function signature alone
#     (what it returns, its inputs, read-only), without what only a traffic engineer would add.
#   RAW_RESULTS: for each tool, a function with the same inputs that returns the same data raw (here, SUMO's lanes
#     and numbers in JSON), without the wording you designed (DESIGN.md, section 4).
PLAIN_DESCRIPTIONS = {
    'lane_use': 'Lane data at an intersection approach: for each lane, vehicles, halting vehicles and mean speed. '
                'intersection: intersection name. approach: approach direction. Read-only.',
}


def lane_use_raw(intersection: str, approach: str) -> str:
    """The same reading as lane_use, returned raw: SUMO's lanes and numbers, in JSON."""
    T._need_live()
    tid, _ = T._resolve(intersection)
    app = T._approaches(tid)
    if approach not in app:
        return f'Error: approach {approach} not in {sorted(app)}'
    edge = app[approach]
    lanes = []
    for lane in edge.getLanes():
        sp = [traci.vehicle.getSpeed(v) for v in traci.lane.getLastStepVehicleIDs(lane.getID())]
        lanes.append({'lane_id': lane.getID(), 'index': lane.getIndex(),
                      'connections': sorted(c.getDirection() for c in lane.getOutgoing()),
                      'vehicles': len(sp), 'halting': sum(v < T.STOPPED_MPS for v in sp),
                      'mean_speed_mps': round(statistics.mean(sp), 2) if sp else None})
    return json.dumps({'tls': tid, 'approach': approach, 'edge': edge.getID(), 'edge_length_m': round(edge.getLength(), 1),
                       'time_s': traci.simulation.getTime(), 'lanes': lanes})


RAW_RESULTS = {'lane_use': lane_use_raw}

if __name__ == '__main__':
    print(T.start_live()); print(T.advance(1800))
    print(lane_use('Bruce B Downs & Pine', 'SB')); print(lane_use_plain('Bruce B Downs & Pine', 'SB'))
    print(lane_use_raw('Bruce B Downs & Pine', 'SB'))
    T.stop_live()
