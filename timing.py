"""With and without the GUI: wall-clock time for 1,800 simulated seconds of the Fowler scenario, driven step by
step through the same API (one small read per step), in sumo, libsumo (SUMO inside the Python process) and sumo-gui.

    python timing.py                  # sumo-gui needs a screen, or: xvfb-run -a python timing.py
"""
import os, sys, time, json, subprocess
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import sumo_agent_tools as T

CODE = '''
import os, sys, time, json
mode = sys.argv[1]
if mode == "libsumo":
    import libsumo as tr
else:
    import traci as tr
cmd = json.loads(sys.argv[2])
tr.start(cmd) if mode == "libsumo" else tr.start(cmd, stdout=open(os.devnull, "w"))
t0 = time.time()
for _ in range(1800):
    tr.simulationStep()
    tr.lane.getLastStepVehicleNumber("905687312#0_0")
print(json.dumps({"secs": time.time() - t0}))
tr.close()
'''
res = {}
for mode in ('sumo', 'libsumo', 'sumo-gui'):
    cmd = [os.path.join(T.BIN, 'sumo-gui' if mode == 'sumo-gui' else 'sumo'), '-n', T.SCENARIO['net'],
           '-r', T.SCENARIO['demands']['demand'], '--seed', '1', '--no-step-log', '--no-warnings']
    if mode == 'sumo-gui':
        cmd += ['--start', '--quit-on-end']
    run = [sys.executable, '-c', CODE, mode, json.dumps(cmd)]
    if mode == 'sumo-gui' and not os.environ.get('DISPLAY'):
        run = ['xvfb-run', '-a', '-s', '-screen 0 1600x900x24'] + run
    r = subprocess.run(run, capture_output=True, text=True)
    try:
        res[mode] = round(json.loads(r.stdout.strip().splitlines()[-1])['secs'], 2)
    except Exception:
        res[mode] = None
        res[mode + '_error'] = (r.stderr or r.stdout)[-500:]
    print(mode, res[mode], flush=True)
json.dump(res, open(os.path.join(HERE, 'runs', 'timing.json'), 'w'), indent=1)
