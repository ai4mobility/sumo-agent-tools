"""The ablation: two comparisons, on your own questions.

    python contrib/ablation.py contrib/<you>              # 3 questions x 3 setups = 9 runs, thinking off, seed 1
    python contrib/ablation.py contrib/<you> --think      # with reasoning (about 4 times slower)

The same model answers the same questions in three setups:

    A  without   the toolkit's tools only: yours are not served
    B  plain     your tools find the same data, but nothing the model reads carries your transportation knowledge:
                 the description is PLAIN_DESCRIPTIONS[tool], the result is RAW_RESULTS[tool] (the same data, raw),
                 and your server instructions are left out
    C  full      your tools as you wrote them

    A vs C: what do your tools change?
    B vs C: what does the transportation knowledge in your descriptions and results change?

Your server.py switches between the setups by the ABLATION environment variable, which this script sets for each
run. The questions and their right answers are in contrib/<you>/ablation/tasks.json, written by you before you run.
A question may have a "setup": tool calls the harness makes before the model's first turn, the same in every setup
(for SUMO: start the simulation and advance it to the time the question is about), so the runs test your tools
rather than the model's handling of the simulation.
Each run is saved in ablation/runs/<setup>__<question id>.json; a finished run is not run again, so you can stop
and go on later. All the answers are written to ablation/answers.md. Read them, then grade each one in the table in
ABLATION.md: right, partly or wrong, and why.
Options: --seed N (default 1), --model <id> (default Qwen/Qwen3-1.7B), --only <id,id> (some questions only).
"""
import os, sys, json, time, asyncio, tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)
import agent_loop as AL

SETUPS = [('without', 'A. Without your tools'), ('plain', 'B. Your tools, plain'), ('full', 'C. Your tools as written')]


def tasks_of(folder):
    return json.load(open(os.path.join(folder, 'ablation', 'tasks.json'), encoding='utf-8'))


def compact(rec, mine):
    """What the ablation keeps of a run: the descriptions of your tools the model saw, its calls, and its answer.
    (agent_loop.py's own transcripts hold the full prompt; here it would only repeat itself.)"""
    calls = [{'name': c.get('name'), 'arguments': c.get('arguments'), 'check': c.get('check'),
              'result': (c.get('result') or '')[:1500]} for s in rec['steps'] for c in s.get('calls', [])]
    return {'harness': 'ablation.py', 'model': rec['model'], 'thinking': rec['thinking'], 'seed': rec['seed'],
            'server': rec['server'], 'date': rec['date'], 'data': rec['data'], 'device': rec.get('device'),
            'setup': [{'name': c['name'], 'arguments': c['arguments'], 'result': c['result'][:600]}
                      for c in rec.get('setup', [])],
            'descriptions_of_your_tools': {t['function']['name']: t['function']['description']
                                           for t in rec['tools_for_model'] if t['function']['name'] in mine},
            'tools_served': [t['function']['name'] for t in rec['tools_for_model']],
            'instructions': rec.get('instructions'), 'calls': calls, 'answer': rec.get('answer'),
            'note': rec.get('note'), 'turns': len(rec['steps']),
            'model_s': round(sum(s['model_s'] for s in rec['steps']), 1)}


def setup_of(T, q):
    return q.get('setup', T.get('setup')) or []


def table(T):
    L = ['| Question | ' + ' | '.join(label for _, label in SETUPS) + ' |', '|---|---|---|---|']
    return '\n'.join(L + [f"| {q['id']} | ? | ? | ? |" for q in T['questions']])


def answers_md(T, runs, meta):
    L = ['# The answers: %d questions x 3 setups' % len(T['questions']), '',
         f"Written by contrib/ablation.py. Model {meta['model']}, thinking {'on' if meta['think'] else 'off'}, seed "
         f"{meta['seed']}, on {meta['device']}. Data: {meta['data']}.", '',
         'Read each answer against the right answer, then grade it in the table in ABLATION.md: right, partly or '
         'wrong, and why in a few words. The table to copy:', '', table(T), '']
    for q in T['questions']:
        L += [f"## {q['id']}", '', f"**Question:** {q['question']}", '',
              f"**Right answer (tasks.json):** {q.get('answer', '')}", '']
        if setup_of(T, q):
            L += ['Before the model\'s first turn, the harness called: ' + ', '.join(
                f"`{n}({', '.join(f'{k}={v!r}' for k, v in a.items())})`" for n, a in setup_of(T, q)) + '.', '']
        for cond, label in SETUPS:
            r = runs[(cond, q['id'])]
            calls = [f"`{c['name']}({', '.join(f'{k}={v!r}' for k, v in (c.get('arguments') or {}).items())})`"
                     + ('' if c.get('check') == 'ok' else ' (refused by the harness: ' + str(c.get('check')) + ')')
                     for c in r['calls']]
            L += [f'### {label}', '',
                  f"Tools called: {', '.join(calls) or 'none'}. {r['turns']} turns, {r['model_s']:.0f} s. "
                  f"Run: `ablation/runs/{cond}__{q['id']}.json`", '']
            ans = (r.get('answer') or '').strip()
            L += ['> ' + line if line.strip() else '>' for line in ans.split('\n')] if ans else \
                 [f"(no answer: {r.get('note') or 'the run ended without one'})"]
            L.append('')
    return '\n'.join(L)


async def run_all(folder, seed, think, model_id, only):
    T = tasks_of(folder)
    for k, v in (T.get('env') or {}).items():
        os.environ[k] = os.path.join(ROOT, v) if os.path.exists(os.path.join(ROOT, v)) else v
    sys.path.insert(0, folder)
    import importlib.util
    spec = importlib.util.spec_from_file_location('ablation_tools', os.path.join(folder, 'tools.py'))
    M = importlib.util.module_from_spec(spec); spec.loader.exec_module(M)
    mine = [t.__name__ for t in M.TOOLS]
    server = os.path.join(folder, 'server.py')
    out = os.path.join(folder, 'ablation', 'runs')
    os.makedirs(out, exist_ok=True)
    qs = [q for q in T['questions'] if not only or q['id'] in only]
    model, runs = None, {}
    todo = [(c, q) for q in qs for c, _ in SETUPS]
    for i, (cond, q) in enumerate(todo, 1):
        path = os.path.join(out, f"{cond}__{q['id']}.json")
        old = json.load(open(path, encoding='utf-8')) if os.path.exists(path) else None
        if old and (old.get('question'), old.get('model'), old.get('thinking'), old.get('seed'),
                    [[c['name'], c['arguments']] for c in old.get('setup', [])]) == \
                (q['question'], model_id, think, seed, [[n, a] for n, a in setup_of(T, q)]):
            runs[(cond, q['id'])] = old
            continue
        if model is None:
            print(f'Loading {model_id} ...', file=sys.stderr)
            model = AL.Model(model_id, think, seed)
        os.environ['ABLATION'] = cond
        log = os.path.join(tempfile.mkdtemp(), 'mcp.jsonl')
        print(f'[{i}/{len(todo)}] {cond:8s} {q["id"]} ...', file=sys.stderr, end=' ', flush=True)
        t0 = time.time()
        rec = await AL.loop(server, q['question'], {'model': model_id, 'think': think, 'seed': seed,
                                                    'max_steps': int(T.get('max_steps', 8)),
                                                    'max_new': 2048 if think else 512, 'setup': setup_of(T, q),
                                                    'stream': False}, log, model=model)
        r = compact(rec, mine)
        r.update(setup=cond, question_id=q['id'], question=q['question'])
        json.dump(r, open(path, 'w', encoding='utf-8'), indent=1, ensure_ascii=False)
        runs[(cond, q['id'])] = r
        called = [c['name'] for c in r['calls'] if c['check'] == 'ok']
        print(f"{time.time() - t0:.0f} s; called: {', '.join(called) or 'nothing'}", file=sys.stderr)
    if only:
        print('Some questions only (--only): answers.md is written after a run of every question.', file=sys.stderr)
        return
    any_run = next(iter(runs.values()))
    meta = {'model': model_id, 'think': think, 'seed': seed, 'device': any_run.get('device') or '?',
            'data': any_run.get('data') or '?'}
    open(os.path.join(folder, 'ablation', 'answers.md'), 'w', encoding='utf-8').write(answers_md(T, runs, meta))
    print(f"\nSaved {os.path.relpath(os.path.join(folder, 'ablation', 'answers.md'), ROOT)}. Read it, then grade each "
          f"answer in ABLATION.md:\n\n{table(T)}", file=sys.stderr)


def main():
    a = sys.argv[1:]
    if not a or a[0].startswith('-'):
        print(__doc__); sys.exit(2)
    folder = os.path.abspath(a[0])
    seed = int(a[a.index('--seed') + 1]) if '--seed' in a else 1
    model_id = a[a.index('--model') + 1] if '--model' in a else 'Qwen/Qwen3-1.7B'
    only = a[a.index('--only') + 1].split(',') if '--only' in a else None
    asyncio.run(run_all(folder, seed, '--think' in a, model_id, only))


if __name__ == '__main__':
    main()
