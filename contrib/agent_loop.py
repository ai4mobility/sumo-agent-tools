"""Watch the whole agent loop: a model on your own computer calls your tools through your MCP server.

    pip install torch transformers "mcp>=2"
    python contrib/agent_loop.py contrib/<you>/server.py "your question" --name q1

The first run downloads the model (Qwen3-1.7B, about 4 GB; a CPU is enough). Each run writes two files next to
your server.py: runs/<name>.md, a transcript you can read, and runs/<name>.json, the same in full. The transcript
shows every part of the loop:

  0. the harness starts your server.py and talks MCP to it: initialize, then tools/list (the raw JSON-RPC messages)
  1. the harness turns the tool list into the format the model was trained on, and the chat template writes the
     system message, the tools and the question into one text: the prompt, which is all the model ever reads
  2. the model writes text: its reasoning between <think> and </think>, then a tool call between <tool_call> and
     </tool_call>. A tool call is only text; writing it runs nothing
  3. the harness finds each call and checks it against the tool's input schema
  4. the harness sends the call to your server as an MCP tools/call request; your tool runs and the server answers
  5. the result goes back to the model as a tool message, inside <tool_response> in the next prompt
  6. repeat until the model writes no tool call: that text is the answer

Options:
    --name q1              file names in runs/ (default: run_<time>)
    --model Qwen/Qwen3-4B  a larger model, if your computer has 16 GB of memory or a GPU (default Qwen/Qwen3-1.7B)
    --no-think             no reasoning (faster; the model then writes the call directly)
    --max-steps 8          stop after this many model turns
    --seed 1               the same seed, model and computer give the same run
Commercial clients (Claude Desktop, ChatGPT) run the same loop, but they do not show you the prompt text or the raw
MCP messages; this harness hides nothing.
"""
import os, re, sys, json, time, asyncio, datetime, platform, subprocess, threading

SYSTEM = ('You are an assistant to a transportation engineer. Answer the question by calling the tools yourself: '
          'the engineer cannot call them. Keep calling tools until you can answer. Use only numbers the tools '
          'return, and say so when the tools cannot answer part of the question.')
CALL = re.compile(r'<tool_call>\s*(.*?)\s*</tool_call>', re.S)
THINK = re.compile(r'<think>(.*?)</think>', re.S)
TYPES = {'integer': int, 'number': (int, float), 'string': str, 'boolean': bool, 'object': dict, 'array': list}


# ---------------------------------------------------------------- MCP: a relay that writes down every message
def relay(log_path, cmd):
    """Sit between the harness and the server and log each line that crosses stdio: over stdio, MCP is one JSON-RPC
    message per line. Neither side knows the relay is there."""
    child = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE)
    t0, lock, log = time.time(), threading.Lock(), open(log_path, 'w', encoding='utf-8')

    def note(direction, line):
        with lock:
            try:
                msg = json.loads(line)
            except ValueError:
                msg = line.decode('utf-8', 'replace')
            log.write(json.dumps({'t_s': round(time.time() - t0, 3), 'dir': direction, 'msg': msg}) + '\n')
            log.flush()

    def harness_to_server():
        for line in sys.stdin.buffer:
            note('harness -> server', line)
            child.stdin.write(line); child.stdin.flush()
        child.stdin.close()

    threading.Thread(target=harness_to_server, daemon=True).start()
    for line in child.stdout:
        note('server -> harness', line)
        sys.stdout.buffer.write(line); sys.stdout.buffer.flush()
    child.wait()


def mcp_messages(log_path):
    return [json.loads(l) for l in open(log_path, encoding='utf-8')] if os.path.exists(log_path) else []


# ---------------------------------------------------------------- the model
class Model:
    def __init__(self, model_id, think, seed):
        import torch
        from transformers import AutoTokenizer, AutoModelForCausalLM
        self.torch, self.think, self.seed = torch, think, seed
        self.device = 'cuda' if torch.cuda.is_available() else 'mps' if torch.backends.mps.is_available() else 'cpu'
        self.tok = AutoTokenizer.from_pretrained(model_id)
        # bfloat16 on a CPU (half the memory of float32); float16 on a GPU without bfloat16 and on Apple silicon
        half = torch.bfloat16 if self.device == 'cpu' or (self.device == 'cuda' and torch.cuda.is_bf16_supported()) \
            else torch.float16
        self.lm = AutoModelForCausalLM.from_pretrained(model_id, dtype=half).to(self.device).eval()

    def prompt(self, messages, tools):
        """Step 1: the chat template writes the messages and the tool list into one text."""
        return self.tok.apply_chat_template(messages, tools=tools, add_generation_prompt=True, tokenize=False,
                                            enable_thinking=self.think)

    def write(self, text, max_new):
        """Step 2: the model writes, one token at a time (printed as it goes)."""
        from transformers import TextStreamer
        torch = self.torch
        ids = self.tok(text, return_tensors='pt', add_special_tokens=False)['input_ids'].to(self.device)
        torch.manual_seed(self.seed)
        # Qwen3's recommended sampling settings (greedy decoding makes its reasoning repeat itself)
        kw = dict(do_sample=True, temperature=0.6, top_p=0.95, top_k=20) if self.think else \
             dict(do_sample=True, temperature=0.7, top_p=0.8, top_k=20)
        t0 = time.time()
        with torch.no_grad():
            out = self.lm.generate(ids, max_new_tokens=max_new, pad_token_id=self.tok.eos_token_id,
                                   streamer=TextStreamer(self.tok, skip_prompt=True, skip_special_tokens=False), **kw)
        new = out[0, ids.shape[1]:]
        reply = self.tok.decode(new, skip_special_tokens=False)
        reply = reply.split('<|im_end|>')[0]                       # the model's end-of-turn mark
        return reply, int(ids.shape[1]), int(new.shape[0]), round(time.time() - t0, 1)


# ---------------------------------------------------------------- step 3: check a call against the schema
def check_call(raw, schemas):
    try:
        call = json.loads(raw)
    except json.JSONDecodeError as e:
        return None, None, f'Error: the tool call is not valid JSON ({e.msg}). Write it as {{"name": ..., "arguments": {{...}}}}.'
    name, args = call.get('name'), call.get('arguments', {})
    if isinstance(args, str):
        try:
            args = json.loads(args)
        except json.JSONDecodeError:
            return name, args, 'Error: the arguments are not valid JSON.'
    if name not in schemas:
        return name, args, f'Error: there is no tool named {name}. Tools: {", ".join(schemas)}.'
    s = schemas[name] or {}
    props = s.get('properties', {})
    for key in s.get('required', []):
        if key not in args:
            return name, args, f'Error: {name} needs "{key}".'
    for key, value in (args or {}).items():
        spec = props.get(key)
        if spec is None:
            return name, args, f'Error: {name} has no input "{key}". Inputs: {", ".join(props) or "none"}.'
        types = [spec.get('type')] + [a.get('type') for a in spec.get('anyOf', [])]
        if value is None and 'null' in types:
            continue
        want = tuple(t for k in types if k in TYPES for t in (TYPES[k] if isinstance(TYPES[k], tuple) else (TYPES[k],)))
        if want and (not isinstance(value, want) or (isinstance(value, bool) and bool not in want)):
            return name, args, f'Error: "{key}" must be {" or ".join(k for k in types if k)}, not {json.dumps(value)}.'
        if 'enum' in spec and value not in spec['enum']:
            return name, args, f'Error: "{key}" must be one of {spec["enum"]}, not {json.dumps(value)}.'
    return name, args, None


# ---------------------------------------------------------------- the loop
def data_note():
    if os.environ.get('WZDX_SNAPSHOT'):
        return 'WZDx snapshot ' + os.path.relpath(os.environ['WZDX_SNAPSHOT'])
    if os.path.exists(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'sumo_agent_tools.py')):
        return 'SUMO Fowler Ave scenario (the demand and seed are in the start_live call)'
    return 'live feeds, read during the run'


async def loop(server, question, opts, log_path):
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client
    params = StdioServerParameters(command=sys.executable,
                                   args=[os.path.abspath(__file__), '--relay', log_path, '--', sys.executable, server],
                                   env=dict(os.environ))
    rec = {'harness': 'agent_loop.py', 'question': question, 'server': os.path.relpath(server),
           'model': opts['model'], 'thinking': opts['think'], 'seed': opts['seed'],
           'date': datetime.datetime.now().astimezone().isoformat(timespec='seconds'),
           'data': data_note(),
           'python': platform.python_version(), 'platform': platform.platform(), 'steps': []}
    async with stdio_client(params) as (r, w):
        async with ClientSession(r, w) as s:
            init = await s.initialize()                                        # 0. MCP handshake
            listed = (await s.list_tools()).tools                              # 0. tools/list
            schema = lambda t: getattr(t, 'input_schema', None) or getattr(t, 'inputSchema', None) or {}
            tools = [{'type': 'function', 'function': {'name': t.name, 'description': t.description or '',
                                                       'parameters': schema(t)}} for t in listed]   # 1. model format
            schemas = {t.name: schema(t) for t in listed}
            system = SYSTEM + ('\n\n' + init.instructions if getattr(init, 'instructions', None) else '')
            rec.update(server_name=init.server_info.name if hasattr(init, 'server_info') else init.serverInfo.name,
                       instructions=getattr(init, 'instructions', None), tools_for_model=tools, system=system)
            print(f'Loading {opts["model"]} ...', file=sys.stderr)
            t0 = time.time()
            model = Model(opts['model'], opts['think'], opts['seed'])
            rec['load_s'], rec['device'] = round(time.time() - t0, 1), model.device
            messages = [{'role': 'system', 'content': system}, {'role': 'user', 'content': question}]
            last_prompt = ''
            for step in range(1, opts['max_steps'] + 1):
                prompt = model.prompt(messages, tools)                         # 1. the prompt
                k = len(os.path.commonprefix([last_prompt, prompt]))
                k = max(prompt.rfind('<|im_start|>', 0, k + 1), 0) if step > 1 else 0   # from the turn that changed
                st = {'step': step, 'prompt_full' if step == 1 else 'prompt_new': prompt if step == 1 else prompt[k:]}
                last_prompt = prompt
                print(f'\n===== step {step}: the model writes =====', file=sys.stderr)
                reply, n_in, n_out, secs = await asyncio.to_thread(model.write, prompt, opts['max_new'])   # 2.
                think = '\n'.join(m.strip() for m in THINK.findall(reply))
                content = THINK.sub('', reply).replace('<think>', '').strip()
                st.update(prompt_tokens=n_in, reply_tokens=n_out, model_s=secs, reply=reply, thinking=think)
                calls = CALL.findall(content)
                text = CALL.sub('', content).strip()
                if '<think>' in reply and '</think>' not in reply:             # cut off in the middle of thinking
                    st['note'] = (f'the model used all {opts["max_new"]} new tokens while still thinking, so it wrote '
                                  f'no call and no answer (raise --max-new-tokens, or use --no-think)')
                    rec['steps'].append(st); rec['note'] = st['note']
                    break
                if not calls:                                                  # 6. no call: the answer
                    st['note'] = 'no tool call: this text is the answer, so the loop stops'
                    rec['steps'].append(st); rec['answer'] = text
                    break
                done = []
                for raw in calls:
                    name, args, error = check_call(raw, schemas)               # 3. check
                    item = {'raw': raw, 'name': name, 'arguments': args, 'check': error or 'ok'}
                    if error:
                        item['result'] = error
                    else:
                        n_before = len(mcp_messages(log_path))
                        t1 = time.time()
                        res = await s.call_tool(name, args)                    # 4. MCP tools/call
                        item['tool_s'] = round(time.time() - t1, 2)
                        item['is_error'] = bool(getattr(res, 'is_error', None) or getattr(res, 'isError', None))
                        item['result'] = '\n'.join(getattr(c, 'text', str(c)) for c in res.content)
                        await asyncio.sleep(0.05)
                        item['mcp'] = [m for m in mcp_messages(log_path)[n_before:]
                                       if isinstance(m['msg'], dict) and m['msg'].get('method') != 'notifications/message']
                    done.append(item)
                    print(f'\n----- harness: {name}({json.dumps(args)}) -> {item["check"]}; '
                          f'{len(item["result"])} characters back', file=sys.stderr)
                st['calls'] = done
                rec['steps'].append(st)
                messages.append({'role': 'assistant', 'content': text, 'reasoning_content': think,
                                 'tool_calls': [{'type': 'function', 'function': {'name': c['name'] or '?',
                                                                                  'arguments': c['arguments'] or {}}}
                                                for c in done]})
                for c in done:                                                 # 5. the result goes back
                    messages.append({'role': 'tool', 'name': c['name'] or '?', 'content': c['result']})
            else:
                rec['note'] = f'stopped after {opts["max_steps"]} steps without an answer'
    rec['messages'] = messages
    rec['mcp_all'] = mcp_messages(log_path)
    rec['total_s'] = round(time.time() - t0 + rec['load_s'], 1)
    return rec


# ---------------------------------------------------------------- the transcript
FENCE = '~~~~'


def block(text, lang=''):
    return f'{FENCE}{lang}\n{text}\n{FENCE}\n'


def jl(m):
    return json.dumps(m, indent=1, ensure_ascii=False)


def transcript(rec):
    out = [f"# Agent loop: {rec['question']}\n",
           '| | |\n|---|---|',
           f"| Model | {rec['model']} ({'thinking on' if rec['thinking'] else 'thinking off'}), seed {rec['seed']}, on {rec['device']} |",
           f"| Server | `{rec['server']}` ({rec['server_name']}) |",
           f"| Data | {rec['data']} |",
           f"| Date | {rec['date']} |",
           f"| Harness | `contrib/agent_loop.py`, Python {rec['python']}, {rec['platform']} |\n"]
    mcp = rec['mcp_all']
    first_call = next((i for i, m in enumerate(mcp) if isinstance(m['msg'], dict) and m['msg'].get('method') == 'tools/call'), len(mcp))
    out.append('## 0. The harness starts the server and talks MCP to it\n')
    out.append('Every line below crossed stdin/stdout between the harness and `server.py`, word for word '
               '(JSON-RPC 2.0, one message per line). `tools/list` is how the harness learns the tools.\n')
    for m in mcp[:first_call]:
        if isinstance(m['msg'], dict) and m['msg'].get('method', '').startswith('notifications/message'):
            continue
        out.append(f"**{m['dir']}** at {m['t_s']} s\n" + block(jl(m['msg']), 'json'))
    out.append('## 1. The tool list, in the format the model was trained on\n')
    out.append('The harness rewrites each MCP tool as an OpenAI-style function (name, description, parameters). '
               "The chat template then writes this list into the system message, inside `<tools>`.\n")
    out.append(block(jl(rec['tools_for_model']), 'json'))
    for st in rec['steps']:
        out.append(f"## Step {st['step']}\n")
        if 'prompt_full' in st:
            out.append(f"### The prompt: everything the model reads ({st['prompt_tokens']:,} tokens)\n")
            out.append(block(st['prompt_full']))
        else:
            out.append(f"### The prompt: what was added since the last step (now {st['prompt_tokens']:,} tokens in all)\n")
            out.append('The model\'s own last turn is now part of the prompt, and each tool result follows it inside '
                       '`<tool_response>` (Qwen\'s template puts tool results in a user turn).\n')
            out.append(block(st['prompt_new']))
        out.append(f"### What the model writes ({st['reply_tokens']:,} tokens, {st['model_s']} s)\n")
        out.append(block(st['reply']))
        if 'calls' not in st:
            out.append(f"### The harness\n\n{st['note']}.\n")
            continue
        out.append('### The harness\n')
        for c in st['calls']:
            out.append(f"Found a tool call: `{c['name']}` with arguments `{json.dumps(c['arguments'], ensure_ascii=False)}`. "
                       f"Check against the input schema: **{c['check']}**." +
                       (' Not sent to the server; the error goes back to the model.\n' if c['check'] != 'ok' else '\n'))
            for m in c.get('mcp', []):
                out.append(f"**MCP, {m['dir']}** at {m['t_s']} s\n" + block(jl(m['msg']), 'json'))
            if c['check'] == 'ok':
                out.append(f"The tool ran in {c['tool_s']} s" + (' and the server flagged the result as an error' if c.get('is_error') else '') +
                           '. Its text goes back to the model as a tool message (inside `<tool_response>` in the next prompt).\n')
    out.append('## The answer\n')
    out.append(block(rec.get('answer', '(no answer: ' + rec.get('note', '') + ')')))
    n_calls = sum(len(s.get('calls', [])) for s in rec['steps'])
    out.append(f"{len(rec['steps'])} model turns, {n_calls} tool calls, "
               f"{sum(s['reply_tokens'] for s in rec['steps']):,} tokens written, {rec['total_s']} s in all "
               f"(model load {rec['load_s']} s).\n")
    return '\n'.join(out)


def main():
    a = sys.argv[1:]
    if a[:1] == ['--relay']:
        return relay(a[1], a[3:])
    if len(a) < 2 or a[0].startswith('-'):
        print(__doc__); sys.exit(2)
    server, question = a[0], a[1]
    opt = lambda k, d: a[a.index(k) + 1] if k in a else d
    opts = {'model': opt('--model', 'Qwen/Qwen3-1.7B'), 'think': '--no-think' not in a,
            'max_steps': int(opt('--max-steps', 8)), 'seed': int(opt('--seed', 1)),
            'max_new': int(opt('--max-new-tokens', 2048 if '--no-think' not in a else 512))}
    runs = os.path.join(os.path.dirname(os.path.abspath(server)), 'runs')
    os.makedirs(runs, exist_ok=True)
    name = opt('--name', 'run_' + datetime.datetime.now().strftime('%Y%m%d_%H%M'))
    log_path = os.path.join(runs, name + '.mcp.jsonl')
    if os.path.exists(log_path):
        os.remove(log_path)
    rec = asyncio.run(loop(server, question, opts, log_path))
    json.dump(rec, open(os.path.join(runs, name + '.json'), 'w', encoding='utf-8'), indent=1, ensure_ascii=False)
    open(os.path.join(runs, name + '.md'), 'w', encoding='utf-8').write(transcript(rec))
    os.remove(log_path)
    print(f"\nAnswer:\n{rec.get('answer', rec.get('note'))}\n\nSaved {os.path.join(runs, name)}.md and .json", file=sys.stderr)


if __name__ == '__main__':
    main()
