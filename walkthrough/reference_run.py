"""A reference run: the study done the way a careful engineer would do it, with no model in the loop.

It answers the walkthrough's question ("Is Fowler Ave westbound at 30th St spilling back during the PM peak hour?")
with the same tools the models used: start the simulation, advance past the warm-up, and read the approach four
times inside the analysis hour, 15 minutes apart. The answer is written from the readings by a fixed rule.
check_study.py should pass every sanity check on this log; walkthrough/qwen_run_F.json and qwen_run_G.json fail.

    python walkthrough/reference_run.py          # writes walkthrough/reference_run.json (about 15 s)
    python check_study.py walkthrough/reference_run.json
"""
import json, os, re, sys
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
import sumo_agent_tools as T

QUESTION = 'Is Fowler Ave westbound at 30th St spilling back during the PM peak hour?'
PLAN = [('start_live', {'gui': False}), ('advance', {'seconds': 1500})] + \
       [c for k in range(4) for c in ([('get_approach_state', {'intersection': 'Fowler & 30th', 'approach': 'WB'})] +
                                      ([('advance', {'seconds': 900})] if k < 3 else []))]


def main(out=os.path.join(HERE, 'reference_run.json')):
    calls = []
    try:
        for name, args in PLAN:
            calls.append({'name': name, 'arguments': args, 'result': T.run_tool(name, args)})
    finally:
        T.stop_live()
    shares = [int(m.group(1)) for c in calls if (m := re.search(r'queue fills (\d+)%', c['result']))]
    times = [c['result'].split(' at ')[1].split(' s:')[0] for c in calls if c['name'] == 'get_approach_state']
    answer = (f'{"Spillback" if max(shares) > 85 else "No spillback"} on Fowler Ave WB at 30th St in the PM peak hour: '
              f'in {len(shares)} readings inside the hour ({", ".join(times)} s) the queue filled at most '
              f'{max(shares)}% of the storage (the flag is 85%).')
    json.dump({'run': 'reference', 'question': QUESTION, 'answer': answer, 'calls': calls}, open(out, 'w'), indent=1)
    print(answer)
    print(f'Saved {out}')


if __name__ == '__main__':
    main()
