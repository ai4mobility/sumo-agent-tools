"""What TraCI hands back, next to what the tool returns, for the reading in run G (round 8).

Run G read Fowler Ave WB at 30th St at 8,100 s. This script repeats that run's simulation steps (start_live with
seed 1, then advance 900, 3600 and 3600 s), collects the raw TraCI values behind the reading, and calls
get_approach_state on the same state. It writes raw_vs_result.json.

    python walkthrough/raw_vs_result.py
"""
import json, os, sys
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
import traci
import sumo_agent_tools as T

INTERSECTION, APPROACH = 'E Fowler Ave & Bruce B Downs Blvd', 'WB'      # as the model wrote them in run G

T.start_live()
for seconds in (900, 3600, 3600):
    T.advance(seconds)
tid, name = T._resolve(INTERSECTION)
chain, storage_m = T._upstream_chain(T._approaches(tid)[APPROACH])
raw = {'simulation.getTime()': traci.simulation.getTime(), 'lanes': []}
for edge, _ in chain:
    for lane in edge.getLanes():
        ids = traci.lane.getLastStepVehicleIDs(lane.getID())
        raw['lanes'].append({
            'lane': lane.getID(),
            'lane.getLastStepVehicleIDs()': list(ids),
            'lane.getLastStepMeanSpeed()': traci.lane.getLastStepMeanSpeed(lane.getID()),   # not used by the tool
            'lane.getMaxSpeed()': traci.lane.getMaxSpeed(lane.getID()),
            'vehicles': [{'id': v, 'vehicle.getLanePosition()': traci.vehicle.getLanePosition(v),
                          'vehicle.getLength()': traci.vehicle.getLength(v),
                          'vehicle.getSpeed()': traci.vehicle.getSpeed(v)} for v in ids]})
raw['trafficlight.getRedYellowGreenState()'] = traci.trafficlight.getRedYellowGreenState(tid)
raw['trafficlight.getNextSwitch()'] = traci.trafficlight.getNextSwitch(tid)
result = T.get_approach_state(INTERSECTION, APPROACH)
T.stop_live()

lanes = raw['lanes']
summary = {'lanes': len(lanes), 'empty_lanes': sum(not l['lane.getLastStepVehicleIDs()'] for l in lanes),
           'vehicles': sum(len(l['vehicles']) for l in lanes),
           'empty_lanes_reporting_their_speed_limit': sum(not l['lane.getLastStepVehicleIDs()'] and
                                                          l['lane.getLastStepMeanSpeed()'] == l['lane.getMaxSpeed()']
                                                          for l in lanes),
           'storage_m_from_network_file': storage_m}
run_g = json.load(open(os.path.join(HERE, 'qwen_run_G.json')))
round8 = [c['result'] for s in run_g['steps'] if s['step'] == 8 for c in s['calls']][0]
out = {'intersection': name, 'approach': APPROACH, 'raw_traci': raw, 'summary': summary, 'tool_result': result,
       'same_as_run_G_round_8': result == round8}
json.dump(out, open(os.path.join(HERE, 'raw_vs_result.json'), 'w'), indent=1)
print(json.dumps(summary, indent=1))
print('time', raw['simulation.getTime()'], 'signal', raw['trafficlight.getRedYellowGreenState()'],
      'next switch', raw['trafficlight.getNextSwitch()'])
for l in lanes:
    if l['vehicles']:
        print(l['lane'], [(round(v['vehicle.getLanePosition()'], 1), v['vehicle.getLength()'], v['vehicle.getSpeed()'])
                          for v in l['vehicles']])
print('empty-lane mean speeds:', sorted({round(l['lane.getLastStepMeanSpeed()'], 2) for l in lanes if not l['vehicles']}))
print(result)
print('same as run G round 8:', out['same_as_run_G_round_8'])
