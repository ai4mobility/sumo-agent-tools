"""Watch a model call SUMO tools, one step at a time (Qwen2.5-1.5B-Instruct and Qwen3-1.7B on a CPU).

The handout "How a Model Calls a SUMO Tool, Step by Step" walks through this file. Each loop turn does the same six
things, and all of them are saved to qwen_run_<run>.json:

  1. the harness writes the prompt: the chat template turns the messages and the tool menu into one text
  2. the model writes text; a tool call is just text between <tool_call> and </tool_call>
  3. the harness finds the call and checks it against the menu
  4. the harness runs the tool, and the tool drives SUMO through TraCI (every TraCI call is counted)
  5. the result goes back to the model as a "tool" message, which the template wraps in <tool_response>
  6. repeat until the model writes no tool call: that text is its answer

    pip install torch transformers          # a CPU is enough: 3.5-4 GB of memory in bfloat16
    python walkthrough/qwen_harness.py      # run G, the last one; downloads Qwen3-1.7B the first time (about 4 GB)
    python walkthrough/qwen_harness.py A    # runs A-F: the earlier runs, each fixed in the next (see RUNS)
"""
import collections, json, os, re, sys, time
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
import torch, traci
from transformers import AutoTokenizer, AutoModelForCausalLM
import sumo_agent_tools as T

MENU = ['list_intersections', 'start_live', 'advance', 'get_approach_state', 'stop_live']
SYSTEM_FIRST = ('You are an assistant to a traffic engineer. Answer questions from the SUMO simulation of the Fowler '
                'Ave corridor by calling the tools. Do not guess numbers.')
SYSTEM = ('You are an assistant to a traffic engineer. Answer questions from the SUMO simulation of the Fowler Ave '
          'corridor by calling the tools yourself: the engineer cannot call them. Keep calling tools until you can '
          'answer. Do not guess numbers.')
Q25, Q3 = 'Qwen/Qwen2.5-1.5B-Instruct', 'Qwen/Qwen3-1.7B'
# The recorded runs of the handout, in the order they were made; each run fixes what went wrong in the one before.
#   error:   'first' = the tool's first error text; 'next' = an error that says what to do next
#   period:  a reading outside the analysis hour gets 'none' = no warning, 'warmup' = a warm-up warning only,
#            'both' = a warm-up or an after-peak warning
#   verdict: 'flag' = a SPILLBACK flag only when it is set; 'both' = the verdict either way, with the share
# Between E and F, Qwen3-1.7B asked for sumo-gui on this screenless server and got TraCI's own "Could not connect";
# start_live now says to use gui=false. That run used the code before the fix: see qwen3_run_gui_log.txt.
ENGINEER = 'Yes, go ahead: run it into the peak hour and check the queue again.'
RUNS = {'A': dict(model=Q25, system=SYSTEM_FIRST, error='first', period='none', verdict='flag', gui='none'),
        'B': dict(model=Q25, system=SYSTEM_FIRST, error='next', period='none', verdict='flag', gui='none'),
        'C': dict(model=Q25, system=SYSTEM, error='next', period='none', verdict='flag', gui='none'),
        'D': dict(model=Q25, system=SYSTEM, error='next', period='warmup', verdict='flag', gui='none'),
        'E': dict(model=Q25, system=SYSTEM, error='next', period='warmup', verdict='flag', gui='none',
                  replies=[ENGINEER]),
        'F': dict(model=Q3, system=SYSTEM, error='next', period='warmup', verdict='flag', gui='guard'),
        'G': dict(model=Q3, system=SYSTEM, error='next', period='both', verdict='both', gui='guard')}
QUESTION = 'Is Fowler Ave westbound at 30th St spilling back during the PM peak hour?'
MAX_STEPS = 10

# ---- Step 1 (setup): the same tools, in the format Qwen's chat template expects -----------------------------
# sumo_agent_tools.TOOLS uses Claude's field names (name, description, input_schema). Qwen, like most open models,
# takes the OpenAI-style wrapper: {"type": "function", "function": {name, description, parameters}}.
CLAUDE_STYLE = {t['name']: t for t in T.TOOLS}
# Each fix also changed a description, so an earlier run gets the descriptions it had (sumo_agent_tools has today's).
NOW = {'period': 'A reading outside the analysis hour (900-4500 s) carries a WARM-UP or AFTER-PEAK warning: it says '
                  'nothing about the peak. ',
       'verdict': 'storage length, and a verdict: SPILLBACK when the queue fills over 85% of it, otherwise "No '
                   'spillback", with the share either way;',
       'gui': ' (and the only choice on a computer without a screen, such as a server)'}
EARLIER = {('period', 'none'): '',
           ('period', 'warmup'): 'A reading before 900 s carries a WARM-UP warning: the network is still filling and '
                                 'says nothing about the analysis hour. ',
           ('verdict', 'flag'): 'storage length, with a SPILLBACK flag when the queue fills 85% of it;',
           ('gui', 'none'): ''}


def menu_for(cfg):
    desc = {n: CLAUDE_STYLE[n]['description'] for n in MENU}
    for key, tool in (('period', 'get_approach_state'), ('verdict', 'get_approach_state'), ('gui', 'start_live')):
        if (key, cfg[key]) in EARLIER:
            assert NOW[key] in desc[tool], key
            desc[tool] = desc[tool].replace(NOW[key], EARLIER[key, cfg[key]])
    return [{'type': 'function', 'function': {'name': n, 'description': desc[n],
                                              'parameters': CLAUDE_STYLE[n]['input_schema']}} for n in MENU]

# ---- Step 3: the harness's checks, before anything touches SUMO ----------------------------------------------
CALL = re.compile(r'<tool_call>\s*(.*?)\s*</tool_call>', re.S)
TYPES = {'integer': int, 'number': (int, float), 'string': str, 'boolean': bool, 'object': dict}


def check_call(raw):
    """Return (name, arguments, None) for a good call, or (name, arguments, error text) for a bad one."""
    try:
        call = json.loads(raw)
    except json.JSONDecodeError as e:
        return None, None, f'Error: the tool call is not valid JSON ({e.msg}).'
    name, args = call.get('name'), call.get('arguments', {})
    if isinstance(args, str):                       # some models send the arguments as a JSON string
        try:
            args = json.loads(args)
        except json.JSONDecodeError:
            return name, args, 'Error: the arguments are not valid JSON.'
    if name not in MENU:
        return name, args, f'Error: there is no tool named {name}. Tools: {", ".join(MENU)}.'
    schema = CLAUDE_STYLE[name]['input_schema']
    for key in schema.get('required', []):
        if key not in args:
            return name, args, f'Error: {name} needs "{key}".'
    for key, value in args.items():
        spec = schema['properties'].get(key)
        if spec is None:
            return name, args, f'Error: {name} has no input "{key}". Inputs: {", ".join(schema["properties"]) or "none"}.'
        want = TYPES.get(spec.get('type'))
        if want and (not isinstance(value, want) or (spec.get('type') in ('integer', 'number') and isinstance(value, bool))):
            return name, args, f'Error: "{key}" must be a {spec["type"]}, not {json.dumps(value)}.'
        if 'enum' in spec and value not in spec['enum']:
            return name, args, f'Error: "{key}" must be one of {spec["enum"]}, not {json.dumps(value)}.'
        if 'minimum' in spec and value < spec['minimum']:
            return name, args, f'Error: "{key}" must be at least {spec["minimum"]}, not {value}.'
        if 'maximum' in spec and value > spec['maximum']:
            return name, args, f'Error: "{key}" must be at most {spec["maximum"]}, not {value}.'
    return name, args, None


# ---- Step 4: count what each tool asks of SUMO (every TraCI function the tool code calls) --------------------
TRACI = collections.Counter()
SUMO_CMD = []
_depth = [0]


def _counted(label, f):
    def wrapper(*a, **k):
        if _depth[0] == 0:
            TRACI[label] += 1                       # count only the calls the tool code makes itself
        _depth[0] += 1
        try:
            return f(*a, **k)
        finally:
            _depth[0] -= 1
    return wrapper


traci.simulationStep = _counted('simulationStep', traci.simulationStep)
for domain in ('simulation', 'vehicle', 'lane', 'edge', 'trafficlight'):
    d = getattr(traci, domain)
    for m in dir(d):
        if m.startswith(('get', 'set')) and callable(getattr(d, m)):
            setattr(d, m, _counted(f'{domain}.{m}', getattr(d, m)))
_start = traci.start


def _start_logged(cmd, **kw):
    SUMO_CMD[:] = [os.path.basename(c) if os.sep in c else c for c in cmd]
    return _start(cmd, **kw)


traci.start = _start_logged


def run_and_count(name, args):
    TRACI.clear()
    t0 = time.time()
    text = T.run_tool(name, args)                   # the same run_tool the MCP server and every harness use
    return text, round(time.time() - t0, 2), dict(TRACI)


# ---- Step 2: the model writes text -------------------------------------------------------------------------
class Qwen:
    def __init__(self, model_id, tools):
        self.tools = tools
        self.tok = AutoTokenizer.from_pretrained(model_id)
        self.lm = AutoModelForCausalLM.from_pretrained(model_id, dtype=torch.bfloat16).eval()

    def prompt(self, messages):                      # Step 1: messages + tools -> one text
        return self.tok.apply_chat_template(messages, tools=self.tools, add_generation_prompt=True, tokenize=False,
                                            enable_thinking=False)   # Qwen3 only; Qwen2.5's template ignores it

    def write(self, text, max_new=256):
        ids = self.tok(text, return_tensors='pt', add_special_tokens=False)['input_ids']
        t0 = time.time()
        with torch.no_grad():                       # greedy: the same prompt gives the same reply every time
            out = self.lm.generate(ids, max_new_tokens=max_new, do_sample=False, top_p=None, top_k=None,
                                   temperature=None, pad_token_id=self.tok.eos_token_id)
        new = out[0, ids.shape[1]:]
        return (self.tok.decode(new, skip_special_tokens=True), int(ids.shape[1]), int(new.shape[0]),
                round(time.time() - t0, 1))


def use_earlier_texts(cfg):
    """Put back the tool texts an earlier run saw, so every recorded run can be made again with this code."""
    period, verdict = T._period_note, T._verdict
    if cfg['error'] == 'first':
        def need_live():
            if not T._LIVE.get('on'):
                raise RuntimeError('No live simulation. Call start_live first.')
        T._need_live = need_live
    if cfg['period'] == 'none':
        T._period_note = lambda: ''
    elif cfg['period'] == 'warmup':
        T._period_note = lambda: period() if traci.simulation.getTime() < T.WARMUP else ''
    if cfg['verdict'] == 'flag':
        T._verdict = lambda share: ' SPILLBACK: the queue fills over 85% of the storage.' if share > 0.85 else ''


def main(run='G'):
    cfg = RUNS[run]
    use_earlier_texts(cfg)
    model_id = os.environ.get('QWEN_MODEL') or cfg['model']        # QWEN_MODEL tries another model on run `run`
    tag = '' if model_id == cfg['model'] else '_' + model_id.split('/')[-1]
    out_path = os.path.join(HERE, f'qwen_run_{run}{tag}.json')
    replies = list(cfg.get('replies', []))
    t_start = time.time()
    model = Qwen(model_id, menu_for(cfg))
    load_s = round(time.time() - t_start, 1)
    messages = [{'role': 'system', 'content': cfg['system']}, {'role': 'user', 'content': QUESTION}]
    log = {'run': run, 'setup': cfg, 'model': model_id, 'menu': MENU, 'question': QUESTION, 'load_s': load_s,
           'torch': torch.__version__, 'qwen_tools': model.tools, 'steps': []}
    try:
        for step in range(1, MAX_STEPS + 1):
            prompt = model.prompt(messages)                                   # 1. the prompt
            if step == 1:
                log['first_prompt'] = prompt
            reply, n_in, n_out, model_s = model.write(prompt)                 # 2. the model writes
            rec = {'step': step, 'prompt_tokens': n_in, 'reply_tokens': n_out, 'model_s': model_s, 'reply': reply}
            print(f'\n--- step {step}: {n_in} tokens in, {n_out} out, {model_s} s\n{reply}')
            calls = CALL.findall(reply)                                       # 3. find the calls
            if not calls:
                messages.append({'role': 'assistant', 'content': reply})
                if replies:                                                   # the engineer types the next message
                    rec['note'] = 'no tool call: the turn ends and the engineer replies'
                    rec['engineer'] = replies.pop(0)
                    log['steps'].append(rec)
                    messages.append({'role': 'user', 'content': rec['engineer']})
                    print(f'  engineer: {rec["engineer"]}')
                    continue
                rec['note'] = 'no tool call: this text is the answer, so the loop stops'
                log['steps'].append(rec)
                log['answer'] = reply
                break
            parsed, results = [], []
            for raw in calls:
                name, args, error = check_call(raw)                           # 3. check each call
                if error:
                    text, tool_s, traci_calls = error, 0.0, {}
                else:
                    text, tool_s, traci_calls = run_and_count(name, args)      # 4. run it in SUMO
                parsed.append({'name': name, 'arguments': args})
                results.append({'name': name, 'arguments': args, 'check': error or 'ok', 'result': text,
                                'tool_s': tool_s, 'traci_calls': traci_calls,
                                'traci_total': sum(traci_calls.values())})
                if name == 'start_live' and not error:
                    results[-1]['sumo_command'] = SUMO_CMD + ['--remote-port', '<free port>']
                print(f'  {name}({json.dumps(args)}) -> {text}')
            rec['calls'] = results
            log['steps'].append(rec)
            before = reply.split('<tool_call>')[0].strip()
            messages.append({'role': 'assistant', 'content': before,        # the call, kept as structured data
                             'tool_calls': [{'type': 'function', 'function': c} for c in parsed]})
            for r in results:                                                 # 5. the result goes back as text
                messages.append({'role': 'tool', 'name': r['name'], 'content': r['result']})
        else:
            log['note'] = f'stopped after {MAX_STEPS} steps without an answer'
    finally:
        log['cleanup'] = T.stop_live()                                        # the harness owns the SUMO process
    log['last_prompt'] = model.tok.apply_chat_template(messages, tools=model.tools, tokenize=False,
                                                       enable_thinking=False)   # the whole conversation as text
    log['total_s'] = round(time.time() - t_start, 1)
    log['messages'] = messages
    with open(out_path, 'w') as f:
        json.dump(log, f, indent=1)
    print(f'\nSaved {out_path} ({log["total_s"]} s in all).')


if __name__ == '__main__':
    main(*sys.argv[1:2])                            # python walkthrough/qwen_harness.py [A-G], default G
