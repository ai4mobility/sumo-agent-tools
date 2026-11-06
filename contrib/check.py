"""Check a contribution folder before you open a pull request. The GitHub workflow runs the same checks.

    python contrib/check.py contrib/your-github-username       # your folder
    python contrib/check.py --all                              # every folder in contrib/

A folder passes when:
  1. it is named after your GitHub username and has the six files: DESIGN.md, KNOWLEDGE.md, tools.py,
     test_tools.py, server.py, AGENT_RUN.md
  2. tools.py lists at least two new tools in TOOLS, each with type hints, '-> str', and a description of at least
     40 words that says whether the tool only reads ('Read-only.') or what it changes; READ_ONLY agrees; and a
     *_plain function (not in TOOLS) is the baseline for at least one of them
  3. KNOWLEDGE.md names your tools and has at least four rules in its Rules table, each with a source and a test
     in test_tools.py, and the other sections filled in
  4. every test in test_tools.py passes, and one of them (test_plain_vs_...) compares the plain version with yours
  5. server.py serves your tools (and, if you like, the toolkit's) over MCP, with read-only tools marked
     read-only (skipped if the mcp package is not installed; the workflow installs it)
  6. AGENT_RUN.md reads three transcripts made by contrib/agent_loop.py (runs/q1.md ...): question 1 calls one of
     your tools, question 2 calls two or more tools; each has your grade; and one fix, with transcripts before and
     after
  7. nothing in the folder looks like a key or a password, and no file is larger than 1 MB
  8. DESIGN.md, in your own words, answers its four questions: (1) the task, with at least two questions as the
     person would ask them; (2) the tools and why each is useful; (3) how each description helps the model pick the
     tool, quoting each tool's description; (4) how the results help the model read them, quoting a result one of
     your tools returned in your transcripts

The workflow also checks that a pull request changes one folder, contrib/<the author's username>/, and nothing else:
    python contrib/check.py --changed <base commit> --author <github-username>
"""
import os, re, sys, ast, json, asyncio, importlib, importlib.util, inspect, traceback, subprocess

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
FILES = ['DESIGN.md', 'KNOWLEDGE.md', 'tools.py', 'test_tools.py', 'server.py', 'AGENT_RUN.md']
DESIGN = [('The task', 80), ('The tools', 100), ('The descriptions', 100), ('The results', 100)]
BASES = {'sumo_agent_tools.py': 'sumo_agent_tools', 'wzdx_tools.py': 'wzdx_tools'}
PLACEHOLDER = re.compile(r'\bTODO\b|<your|<replace', re.I)
SECRET = re.compile(r'sk-ant-[A-Za-z0-9_-]{10,}|sk-[A-Za-z0-9]{32,}|ghp_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{20,}'
                    r'|AKIA[0-9A-Z]{16}|(api[_-]?key|app[_-]?key|password|secret|token)\s*[=:]\s*[\'"]?[A-Za-z0-9_\-]{16,}',
                    re.I)
SAYS_READ_ONLY = re.compile(r'\bread-only\b|\breads only\b', re.I)
SAYS_CHANGES = re.compile(r'\bchanges?\b|\bruns? the simulation forward\b|\blets? time pass\b|\bwrites?\b|\bcloses?\b'
                          r'|\bstarts?\b|\bsets?\b', re.I)


def public_functions(path):
    if not os.path.exists(path):
        return set()
    tree = ast.parse(open(path, encoding='utf-8').read())
    return {n.name for n in tree.body if isinstance(n, ast.FunctionDef) and not n.name.startswith('_')}


TEMPLATE_TOOLS = public_functions(os.path.join(HERE, '_template', 'tools.py'))
TEMPLATE_TESTS = {n for n in public_functions(os.path.join(HERE, '_template', 'test_tools.py')) if n.startswith('test_')}


def base_toolkit():
    """(tool names, read-only names) of the toolkit at the repository root."""
    for f, mod in BASES.items():
        if os.path.exists(os.path.join(ROOT, f)):
            sys.path.insert(0, ROOT)
            B = importlib.import_module(mod)
            names = {t['name'] if isinstance(t, dict) else t.__name__ for t in B.TOOLS}
            return names, set(getattr(B, 'READ_ONLY', names))
    return set(), set()


def load(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    sys.path.insert(0, os.path.dirname(path)); sys.path.insert(0, ROOT)
    spec.loader.exec_module(mod)
    return mod


def md_section(text, title):
    """The body of '## <title>' (or '## 2. <title>'), without HTML comments."""
    text = re.sub(r'<!--.*?-->', '', text, flags=re.S)
    m = re.search(r'^##\s+(?:\d+\.\s*)?' + re.escape(title) + r'[^\n]*\n(.*?)(?=^##\s|\Z)', text, re.M | re.S)
    return m.group(1).strip() if m else None


QUOTE = re.compile(r'"([^"]{0,600})"|\u201c([^\u201d]{0,600})\u201d|`([^`]{0,600})`')     # pairs in order
norm = lambda t: re.sub(r'\s+', ' ', t).strip().lower()


def quotes(text):
    """Quoted phrases of four words or more; an ellipsis splits a quote into parts that must each be found."""
    out = []
    for m in QUOTE.finditer(text or ''):
        q = next((g for g in m.groups() if g is not None), '')
        parts = [norm(p).strip(' .,;:') for p in re.split(r'\.\.\.|\u2026', q)]
        parts = [p for p in parts if p]
        if parts and len(' '.join(parts).split()) >= 4:
            out.append(parts)
    return out


def found(parts, text):
    t = norm(text)
    return all(p in t for p in parts)


def check_folder(folder):
    res = []                                        # (True/False/None, label, detail)
    def ok(cond, label, detail=''):
        res.append((bool(cond), label, detail)); return bool(cond)
    name = os.path.basename(os.path.normpath(folder))
    if not ok(os.path.isdir(folder), 'the folder exists', folder):
        return res
    ok(re.fullmatch(r'[a-z0-9][a-z0-9-]*', name), 'the folder is named after your GitHub username, in lowercase', name)
    missing = [f for f in FILES if not os.path.exists(os.path.join(folder, f))]
    if not ok(not missing, 'the six files are there', 'missing: ' + ', '.join(missing) if missing else ''):
        return res
    # 7. hygiene
    big, leaks = [], []
    for dp, dirs, fs in os.walk(folder):
        dirs[:] = [d for d in dirs if d != '__pycache__']
        for f in fs:
            p = os.path.join(dp, f)
            if os.path.getsize(p) > 1_000_000: big.append(f)
            if f.endswith(('.py', '.md', '.json', '.txt', '.yml', '.yaml', '.toml', '.cfg', '.env', '.ini')):
                if SECRET.search(open(p, encoding='utf-8', errors='ignore').read()): leaks.append(f)
    ok(not big, 'no file larger than 1 MB (use the data in the repository; do not commit data)', ', '.join(big))
    ok(not leaks, 'nothing that looks like a key, token or password', ', '.join(leaks))
    # 2. tools
    try:
        M = load(os.path.join(folder, 'tools.py'), f'contrib_{name.replace("-", "_")}_tools')
    except Exception:
        ok(False, 'tools.py imports', traceback.format_exc(limit=3)[-900:]); return res
    base, base_ro = base_toolkit()
    tools = list(getattr(M, 'TOOLS', []))
    ro = set(getattr(M, 'READ_ONLY', set()))
    names = [getattr(t, '__name__', '?') for t in tools]
    ok(len(tools) >= 2 and all(callable(t) for t in tools), 'TOOLS lists at least two tools', ', '.join(names))
    clash = set(names) & (base | TEMPLATE_TOOLS)
    ok(not clash, "the tools are new (not the toolkit's or the template's)", ', '.join(sorted(clash)))
    ok(ro <= set(names), 'READ_ONLY names only tools in TOOLS', ', '.join(sorted(ro - set(names))))
    plain = sorted(n for n, f in inspect.getmembers(M, inspect.isfunction)
                   if n.endswith('_plain') and f.__module__ == M.__name__)
    ok(plain and not any(n.endswith('_plain') for n in names),
       'a *_plain function is the baseline, and it is not in TOOLS (the model never sees it)', ', '.join(plain))
    for t in tools:
        n = t.__name__; sig = inspect.signature(t); doc = inspect.getdoc(t) or ''
        unann = [p for p, v in sig.parameters.items() if v.annotation is inspect._empty]
        ok(not unann and sig.return_annotation in (str, 'str'), f'{n}: every input has a type and it returns str',
           ('no type: ' + ', '.join(unann)) if unann else ('returns ' + str(sig.return_annotation)))
        words = len(doc.split())
        ok(words >= 40, f'{n}: description of at least 40 words', f'{words} words')
        if n in ro:
            ok(SAYS_READ_ONLY.search(doc) and not re.search(r'not read-only', doc, re.I),
               f'{n}: in READ_ONLY, and its description says "Read-only."')
        else:
            ok(SAYS_CHANGES.search(doc) and not SAYS_READ_ONLY.search(doc),
               f'{n}: not in READ_ONLY, and its description says what it changes (and not "read-only")')
    # 3. knowledge card
    K = open(os.path.join(folder, 'KNOWLEDGE.md'), encoding='utf-8').read()
    unnamed = [n for n in names if n not in K]
    ok(not unnamed and "template's example tool" not in K, 'KNOWLEDGE.md is about your tools (it names each one)',
       ', '.join(unnamed))
    rules_md = md_section(K, 'Rules') or ''
    rows = [r for r in re.findall(r'^\|(.+)\|\s*$', rules_md, re.M)
            if not re.match(r'\s*[-:| ]+\s*$', r) and not re.match(r'\s*#\s*\|', r)]
    test_src = open(os.path.join(folder, 'test_tools.py'), encoding='utf-8').read()
    tests_defined = set(re.findall(r'^def (test_\w+)\(', test_src, re.M))
    named = [re.findall(r'test_\w+', r) for r in rows]
    ok(len(rows) >= 4, 'KNOWLEDGE.md: at least four rules in the Rules table', f'{len(rows)} rules')
    bad = [i + 1 for i, nm in enumerate(named) if not nm or not set(nm) <= tests_defined]
    ok(rows and not bad, 'KNOWLEDGE.md: every rule names a test that exists in test_tools.py',
       ('rules without a matching test: ' + ', '.join(map(str, bad))) if bad else '')
    reused = sorted({t for nm in named for t in nm} & TEMPLATE_TESTS)
    ok(not reused, "KNOWLEDGE.md: the rules' tests are yours, not the template's", ', '.join(reused))
    cells = [[c.strip() for c in r.split('|')] for r in rows]
    nosrc = [i + 1 for i, c in enumerate(cells) if len(c) < 5 or len(c[2]) < 3]
    ok(rows and not nosrc, 'KNOWLEDGE.md: every rule has a source', ('rules without one: ' + ', '.join(map(str, nosrc))) if nosrc else '')
    ok(not PLACEHOLDER.search(rules_md), 'KNOWLEDGE.md: no TODO left in the Rules table')
    for sec in ('Plain vs. yours', 'What the data cannot tell', 'AI use'):
        body = md_section(K, sec)
        ok(body and len(body.split()) >= 12 and not PLACEHOLDER.search(body), f'KNOWLEDGE.md: "{sec}" filled in')
    # 4. tests
    ok(any(t.startswith('test_plain_vs') for t in tests_defined), 'a test_plain_vs_... test compares the plain version with yours')
    proc = subprocess.run([sys.executable, os.path.join(HERE, 'check.py'), '--run-tests', folder],
                          capture_output=True, text=True, timeout=1800, cwd=ROOT)
    try:
        out = json.loads(proc.stdout.strip().splitlines()[-1])
    except Exception:
        out = {'passed': [], 'failed': [['(the tests did not run)', (proc.stdout + proc.stderr)[-800:]]]}
    ok(not out['failed'] and len(out['passed']) >= max(4, len(rows)),
       f'every test passes ({len(out["passed"])} passed, {len(out["failed"])} failed; at least 4, one per rule)',
       '; '.join(f'{n}: {e}' for n, e in out['failed'])[:1200])
    # 5. MCP server
    try:
        import mcp  # noqa: F401
        have_mcp = True
    except ImportError:
        have_mcp = False
    if have_mcp:
        try:
            listed = asyncio.run(list_server_tools(os.path.join(folder, 'server.py')))
            missing_t = set(names) - set(listed); extra = set(listed) - set(names) - base
            ok(not missing_t and not extra, "server.py serves your tools over MCP (and only the toolkit's besides)",
               '; '.join(x for x in (('not served: ' + ', '.join(sorted(missing_t))) if missing_t else '',
                                     ('unknown: ' + ', '.join(sorted(extra))) if extra else '') if x))
            want = {n: (n in ro) if n in names else (n in base_ro) for n in listed}
            wrong = sorted(n for n, r in listed.items() if r != want[n])
            ok(not wrong, 'server.py marks read-only tools read-only, and only those', ', '.join(wrong))
        except Exception as e:
            ok(False, 'server.py starts and lists its tools', f'{type(e).__name__}: {e}'[:800])
    else:
        res.append((None, 'server.py over MCP: skipped, the mcp package is not installed (pip install "mcp>=2")', ''))
    # 6. agent run: three transcripts made by agent_loop.py, read and graded in AGENT_RUN.md
    A = open(os.path.join(folder, 'AGENT_RUN.md'), encoding='utf-8').read()
    setup = md_section(A, 'Setup') or ''
    ok(all(re.search(r'\b' + k + r'\s*:\s*\S', setup) for k in ('Model', 'Date', 'Data', 'Computer'))
       and not PLACEHOLDER.search(setup), 'AGENT_RUN.md: Setup gives the model, date, data and computer')
    link = re.compile(r'\]\((runs/[^)\s]+\.md)\)')
    qs = [q.split('\n## ')[0] for q in re.split(r'^###\s+Question\s+\d', A, flags=re.M)[1:]]
    fields = ('Question', 'Transcript', 'Tool calls', 'What the loop shows', 'Answer', 'My grade')
    good = [q for q in qs if all(re.search(r'\*\*' + k, q, re.I) for k in fields) and link.search(q)
            and not PLACEHOLDER.search(q)]
    ok(len(good) >= 3, 'AGENT_RUN.md: three questions, each with its transcript, the tool calls, what the loop shows, '
       'the answer and your grade', f'{len(good)} complete')
    recs, bad_links = [], []
    for q in good[:3]:
        md = link.search(q).group(1)
        try:
            rec = json.load(open(os.path.join(folder, md[:-3] + '.json'), encoding='utf-8'))
            assert rec.get('harness') == 'agent_loop.py' and os.path.exists(os.path.join(folder, md))
            assert rec.get('server', '').replace('\\', '/').endswith(f'contrib/{name}/server.py'), 'another server'
            recs.append(rec)
        except Exception:
            bad_links.append(md)
    ok(len(recs) >= 3, 'AGENT_RUN.md: each question links a transcript that contrib/agent_loop.py made with your '
       'server.py (runs/<name>.md and runs/<name>.json, committed)', ', '.join(bad_links))
    called = lambda r: [c['name'] for s in r.get('steps', []) for c in s.get('calls', []) if c.get('check') == 'ok']
    methods = lambda r: {m['msg'].get('method') for m in r.get('mcp_all', []) if isinstance(m.get('msg'), dict)}
    if len(recs) >= 3:
        ok(all({'tools/list', 'tools/call'} <= methods(r) and r.get('answer') for r in recs[:3]),
           'transcripts: each holds the MCP messages (tools/list, tools/call) and ends with an answer')
        ok(any(r.get('thinking') for r in recs[:3]), 'transcripts: at least one ran with thinking on (no --no-think), '
           'so its reasoning is visible')
        ok(set(called(recs[0])) & set(names), 'transcript 1: the model called one of your tools',
           'called: ' + (', '.join(called(recs[0])) or 'nothing'))
        ok(len(set(called(recs[1]))) >= 2 and set(called(recs[1])) & set(names),
           'transcript 2: the model called two or more different tools, one of them yours',
           'called: ' + (', '.join(called(recs[1])) or 'nothing'))
    fix = md_section(A, 'One fix I made') or ''
    fl = sorted(set(link.findall(fix)))
    ok(len(fix.split()) >= 40 and not PLACEHOLDER.search(fix) and len(fl) >= 2
       and all(os.path.exists(os.path.join(folder, l)) for l in fl),
       'AGENT_RUN.md: "One fix I made" filled in, linking the transcripts before and after', ', '.join(fl))
    # 8. DESIGN.md: the four questions, in your own words, tied to your real descriptions and results
    Ds = open(os.path.join(folder, 'DESIGN.md'), encoding='utf-8').read()
    ok("template's example tool" not in Ds, "DESIGN.md is yours, not the template's")
    body = {t: md_section(Ds, t) or '' for t, _ in DESIGN}
    for i, (t, n_min) in enumerate(DESIGN, 1):
        words = len(body[t].split())
        ok(words >= n_min and not PLACEHOLDER.search(body[t]),
           f'DESIGN.md, section {i} "{t}": answered (at least {n_min} words)', f'{words} words')
    ok(body['The task'].count('?') >= 2, 'DESIGN.md, section 1: at least two questions as the person would ask them')
    for i, t in ((2, 'The tools'), (3, 'The descriptions'), (4, 'The results')):
        missing_n = [n for n in names if n not in body[t]]
        ok(not missing_n, f'DESIGN.md, section {i}: names each of your tools', ', '.join(missing_n))
    q3 = quotes(body['The descriptions'])
    unquoted = [t.__name__ for t in tools if not any(found(q, inspect.getdoc(t) or '') for q in q3)]
    ok(not unquoted, "DESIGN.md, section 3: quotes each tool's description (a phrase of 4+ words, in quotes, "
       'word for word)', ('no quote from: ' + ', '.join(unquoted)) if unquoted else '')
    results = []
    for f in sorted(os.listdir(os.path.join(folder, 'runs'))) if os.path.isdir(os.path.join(folder, 'runs')) else []:
        if f.endswith('.json'):
            try:
                r = json.load(open(os.path.join(folder, 'runs', f), encoding='utf-8'))
            except Exception:
                continue
            if r.get('harness') == 'agent_loop.py':
                results += [c.get('result') or '' for s in r.get('steps', []) for c in s.get('calls', [])
                            if c.get('name') in names]
    ok(any(found(q, res) for q in quotes(body['The results']) for res in results),
       'DESIGN.md, section 4: quotes a result one of your tools returned in your transcripts (4+ words, in quotes, '
       'word for word)', '' if results else 'no result from your tools in runs/*.json yet')
    return res


async def list_server_tools(server_path):
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client
    p = StdioServerParameters(command=sys.executable, args=[server_path], env=dict(os.environ), cwd=ROOT)
    async with stdio_client(p) as (r, w):
        async with ClientSession(r, w) as s:
            await asyncio.wait_for(s.initialize(), 120)
            tools = (await s.list_tools()).tools
    ro = lambda a: bool(a) and bool(getattr(a, 'read_only_hint', None) or getattr(a, 'readOnlyHint', None))
    return {t.name: ro(t.annotations) for t in tools}


def run_tests(folder):
    """Run every test_ function in the folder's test_tools.py, in file order; print one JSON line with the results.
    A module-level teardown() runs once at the end, if there is one (for example, to close a live simulation)."""
    name = os.path.basename(os.path.normpath(folder)).replace('-', '_')
    passed, failed = [], []
    try:
        mod = load(os.path.join(folder, 'test_tools.py'), f'contrib_{name}_tests')
    except Exception as e:
        print(json.dumps({'passed': [], 'failed': [['import test_tools.py', f'{type(e).__name__}: {e}']]})); return
    tests = [(n, f) for n, f in inspect.getmembers(mod, inspect.isfunction)
             if n.startswith('test_') and f.__module__ == mod.__name__]
    for n, f in sorted(tests, key=lambda x: x[1].__code__.co_firstlineno):
        try:
            f(); passed.append(n)
        except AssertionError as e:
            failed.append([n, f'AssertionError: {str(e)[:400]}'])
        except Exception as e:
            failed.append([n, f'{type(e).__name__}: {str(e)[:400]}'])
    if callable(getattr(mod, 'teardown', None)):
        try: mod.teardown()
        except Exception: pass
    sys.stdout.flush()
    print(json.dumps({'passed': passed, 'failed': failed}))


def changed(base, author=None):
    """Folders a pull request changes, and the problems with its shape. Run from the repository root."""
    files = subprocess.run(['git', 'diff', '--name-only', base, 'HEAD'], capture_output=True, text=True, cwd=ROOT,
                           check=True).stdout.split()
    mine = lambda p: p.startswith('contrib/') and p.count('/') >= 2 and not p.split('/')[1].startswith(('_', '.'))
    folders = sorted({p.split('/')[1] for p in files if mine(p)})
    problems = []
    if folders:
        outside = [p for p in files if not mine(p)]
        if len(folders) > 1:
            problems.append('a pull request adds one contribution folder; this one changes ' + ', '.join(folders))
        if outside:
            problems.append('a contribution changes only files in its own folder; this pull request also changes '
                            + ', '.join(outside[:8]) + '. Put changes to the toolkit in a separate pull request.')
        if author and any(f != author.lower() for f in folders):
            problems.append(f'the folder must be named after the author of the pull request: contrib/{author.lower()}/')
    return [os.path.join(HERE, f) for f in folders], problems


def main():
    args = sys.argv[1:]
    if args[:1] == ['--run-tests']:
        return run_tests(args[1])
    problems = []
    if args == ['--all']:
        folders = sorted(os.path.join(HERE, d) for d in os.listdir(HERE)
                         if os.path.isdir(os.path.join(HERE, d)) and not d.startswith(('_', '.')))
    elif args[:1] == ['--changed']:
        author = args[args.index('--author') + 1] if '--author' in args else None
        folders, problems = changed(args[1], author)
        if not folders:
            print('This pull request adds no contribution folder: nothing to check here.'); return
    elif args:
        folders = args
    else:
        print(__doc__); sys.exit(2)
    if not folders:
        print('No contribution folders yet.'); return
    failed_any = bool(problems)
    for p in problems:
        print('FAIL  ' + p)
    for folder in folders:
        res = check_folder(folder)
        n_bad = sum(1 for r in res if r[0] is False)
        failed_any |= n_bad > 0
        print(f'\n{os.path.relpath(folder, ROOT)}: ' + ('ALL CHECKS PASS' if not n_bad else f'{n_bad} check(s) to fix'))
        for good, label, detail in res:
            mark = 'PASS' if good else ('SKIP' if good is None else 'FAIL')
            print(f'  {mark}  {label}' + (f'  [{detail}]' if detail and good is not True else ''))
    sys.exit(1 if failed_any else 0)


if __name__ == '__main__':
    main()
