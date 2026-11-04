"""Print every recorded run as one table row per step, and save the numbers the handout quotes.

    python walkthrough/summarize_runs.py      # reads qwen_run_*.json and mcp_trace.json, writes walkthrough_numbers.json
"""
import glob, json, os
HERE = os.path.dirname(os.path.abspath(__file__))


def short(text, n=110):
    text = ' '.join(str(text).split())
    return text if len(text) <= n else text[:n - 3] + '...'


numbers = {}
for path in sorted(glob.glob(os.path.join(HERE, 'qwen_run_*.json'))):
    run = json.load(open(path))
    key = os.path.basename(path)[len('qwen_run_'):-len('.json')]
    print(f"\n=== run {key}: {run['model']}, setup {run['setup']}")
    rows = []
    for s in run['steps']:
        calls = s.get('calls', [])
        did = '; '.join(f"{c['name']}({json.dumps(c['arguments'])}) [{c['check']}]" for c in calls) or s.get('note', '')
        res = '; '.join(short(c['result'], 90) for c in calls)
        print(f"{s['step']:>2} in {s['prompt_tokens']:>5} out {s['reply_tokens']:>4} model {s['model_s']:>5} s | {did}")
        if res:
            print(f"   -> {res}")
        if s.get('engineer'):
            print(f"   engineer: {s['engineer']}")
        rows.append({'step': s['step'], 'prompt_tokens': s['prompt_tokens'], 'reply_tokens': s['reply_tokens'],
                     'model_s': s['model_s'],
                     'calls': [{'name': c['name'], 'arguments': c['arguments'], 'check': c['check'],
                                'tool_s': c['tool_s'], 'traci_total': c['traci_total'],
                                'traci_calls': c['traci_calls']} for c in calls],
                     'engineer': s.get('engineer')})
    model_s = round(sum(s['model_s'] for s in run['steps']), 1)
    tool_s = round(sum(c['tool_s'] for s in run['steps'] for c in s.get('calls', [])), 2)
    print(f"   answer: {short(run.get('answer', run.get('note', '')), 300)}")
    print(f"   model {model_s} s, tools {tool_s} s, load {run['load_s']} s, total {run['total_s']} s")
    numbers[key] = {'model': run['model'], 'setup': run['setup'], 'steps': rows, 'answer': run.get('answer'),
                    'model_s': model_s, 'tool_s': tool_s, 'load_s': run['load_s'], 'total_s': run['total_s']}

mcp = os.path.join(HERE, 'mcp_trace.json')
if os.path.exists(mcp):
    trace = json.load(open(mcp))
    print('\n=== MCP trace')
    for m in trace['messages']:
        msg = m['msg']
        what = msg.get('method') or ('result' if 'result' in msg else 'error' if 'error' in msg else '?')
        print(f"{m['t_s']:7.3f} s  {m['dir']}: id={msg.get('id')} {what} {short(json.dumps(msg), 120)}")
    numbers['mcp'] = {'messages': len(trace['messages']), 'total_s': trace['total_s']}

json.dump(numbers, open(os.path.join(HERE, 'walkthrough_numbers.json'), 'w'), indent=1)
