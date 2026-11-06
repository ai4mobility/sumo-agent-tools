"""Test check_study.py: every check must catch its known-bad case and pass a good run.

    python test_check_study.py      # about 3 minutes: three SUMO replays; prints PASS/FAIL, exit code 1 if any fail

A checker that has never failed anything has not been tested. Each check here gets a log it must fail (a good log
with one thing changed, or a recorded model run) and a log it must pass (walkthrough/reference_run.json, the study
done the careful way by walkthrough/reference_run.py).
"""
import copy, json, os, sys
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, 'walkthrough'))
import check_study as C
import sumo_agent_tools as T

RESULTS = []
W = os.path.join(HERE, 'walkthrough')
REF_PATH = os.path.join(W, 'reference_run.json')
if not os.path.exists(REF_PATH):
    import reference_run
    reference_run.main(REF_PATH)
REF = json.load(open(REF_PATH))
RUN = {r: os.path.join(W, f'qwen_run_{r}.json') for r in 'CFG'}
_REPLAYS = {}


def claim(text):
    def wrap(f):
        try:
            detail = f()
            RESULTS.append((True, text, detail or ''))
        except AssertionError as e:
            RESULTS.append((False, text, str(e)))
        except Exception as e:
            RESULTS.append((False, text, f'{type(e).__name__}: {e}'))
        finally:
            if T._LIVE.get('on'):
                T.stop_live()
        return f
    return wrap


def sanity(log):
    """{check name: result} for the sanity checks only."""
    return {c['check']: c for c in C.check_study(log, replay_run=False)['checks']}


def edit(log, i, old, new):
    """A copy of the log with one call's result changed."""
    d = copy.deepcopy(log)
    assert old in d['calls'][i]['result'], (old, d['calls'][i]['result'][:120])
    d['calls'][i]['result'] = d['calls'][i]['result'].replace(old, new)
    return d


def replayed(key, log):
    if key not in _REPLAYS:
        _REPLAYS[key] = C.check_study(log)
    return _REPLAYS[key]


READS = [i for i, c in enumerate(REF['calls']) if c['name'] == 'get_approach_state']
ADVS = [i for i, c in enumerate(REF['calls']) if c['name'] == 'advance']


# ---------------------------------------------------------------- sanity checks: from the log alone
@claim('period: readings at 0 s (run C) and 8,100 s (run G) fail; four readings inside the hour pass')
def _():
    c, g, ref = sanity(RUN['C'])['period'], sanity(RUN['G'])['period'], sanity(REF)['period']
    assert c['status'] == 'FAIL' and 'Advance to a time' in c['fix'], c
    assert g['status'] == 'FAIL' and 'Time cannot go back' in g['fix'], g
    assert ref['status'] == 'PASS', ref
    return 'C: advance; G: start again; reference: pass'


@claim('repeats: fewer than 3 readings inside the hour, 5+ min apart, fail')
def _():
    d = copy.deepcopy(REF)
    d['calls'] = [c for i, c in enumerate(d['calls']) if i not in READS[2:]]
    two = sanity(d)['repeats']
    assert two['status'] == 'FAIL' and 'read 2 times' in two['finding'], two['finding']
    assert sanity(REF)['repeats']['status'] == 'PASS'
    return two['finding'][:90]


@claim('ledger: one changed vehicle count breaks the ledger and fails')
def _():
    a = ADVS[1]
    n = REF['calls'][a]['result'].split(' entered')[0].split(': ')[-1]
    bad = sanity(edit(REF, a, f'{n} entered', f'{int(n) + 10} entered'))['ledger']
    assert bad['status'] == 'FAIL', bad
    assert sanity(REF)['ledger']['status'] == 'PASS'
    return bad['finding'][:110]


@claim('teleports: a teleport, or vehicles stuck at the network edge, fails')
def _():
    a = ADVS[-1]
    tel = sanity(edit(REF, a, 'Teleports: 0.', 'Teleports: 3.'))['teleports']
    wait = sanity(edit(REF, a, 'Waiting to enter: 0.', 'Waiting to enter: 45.'))['teleports']
    assert tel['status'] == 'FAIL' and 'teleported 3' in tel['finding'], tel
    assert wait['status'] == 'FAIL' and '45 vehicles' in wait['finding'], wait
    assert sanity(REF)['teleports']['status'] == 'PASS'
    return 'teleport -> FAIL; 45 waiting -> FAIL'


@claim('physics: a queue longer than its block, 90 mph on a 45-mph street, or a wrong share fails')
def _():
    r = READS[-1]
    txt = REF['calls'][r]['result']
    back = txt.split('back of queue ')[1].split(' ft')[0]
    mph = txt.split(' mph space-mean')[0].split('; ')[-1]
    share = txt.split('queue fills ')[1].split('%')[0]
    cases = {'queue': edit(REF, r, f'back of queue {back} ft', 'back of queue 3,100 ft'),
             'speed': edit(REF, r, f'; {mph} mph space-mean', '; 90 mph space-mean'),
             'share': edit(REF, r, f'queue fills {share}%', 'queue fills 20%')}
    for k, d in cases.items():
        res = sanity(d)['physics']
        assert res['status'] == 'FAIL', (k, res['finding'])
    assert sanity(REF)['physics']['status'] == 'PASS', sanity(REF)['physics']
    return 'all three caught'


@claim('answer: an answer against its own readings (run F) or with no verdict fails')
def _():
    f = sanity(RUN['F'])['answer']
    assert f['status'] == 'FAIL' and '9%' in f['finding'], f
    d = copy.deepcopy(REF)
    d['answer'] = 'The queue on Fowler Ave WB is long during the peak.'
    none = sanity(d)['answer']
    assert none['status'] == 'FAIL' and none['data']['claim'] is None, none
    assert sanity(REF)['answer']['status'] == 'PASS' and sanity(RUN['G'])['answer']['status'] == 'PASS'
    return f['finding'][:100]


@claim('spill_claim reads the verdict, including negations and the threshold sentence of run G')
def _():
    cases = {'Fowler WB is spilling back.': True, 'There is no spillback.': False,
             'WB is not spilling back during the peak.': False, "It isn't spilling back.": False,
             'The queue is below the 85% threshold for spillback. Therefore, there is no spillback.': False,
             'The queue is long.': None, json.load(open(RUN['G']))['answer']: False,
             json.load(open(RUN['F']))['answer']: True}
    for text, want in cases.items():
        got = C.spill_claim(text)
        assert got == want, (text[:60], got, want)
    return f'{len(cases)} sentences'


@claim('compare: a timing comparison from one live run fails; the same with compare_plans passes')
def _():
    d = copy.deepcopy(REF)
    d['calls'].insert(ADVS[1], {'name': 'set_signal_timing',
                                'arguments': {'intersection': 'Fowler & 30th', 'durations': {'4': 12}},
                                'result': 'E Fowler Ave & Bruce B Downs Blvd & N 30th St: new plan, cycle 96 s, durations [..].'})
    d['answer'] = REF['answer'] + ' The new plan is better: it has less delay.'
    bad = sanity(d)['compare']
    assert bad['status'] == 'FAIL', bad
    d['calls'].append({'name': 'compare_plans', 'arguments': {'alternative': 'webster'},
                       'result': 'webster vs existing, 10 seeds, demand "demand":\n  delay ...'})
    assert sanity(d)['compare']['status'] == 'PASS'
    assert sanity(REF)['compare']['status'] == 'N/A'
    return 'one live run -> FAIL; compare_plans -> PASS'


@claim('gate: sends the sanity failures back to the model, never the replay findings; passes the reference run')
def _():
    g = C.gate(RUN['G'])
    assert g and '8,100 s' in g and 'start_live' in g and 'at least 3 times' in g, g
    for leak in ('70%', 'over capacity', '2,079'):
        assert leak not in g, leak
    assert C.gate(REF) is None
    return g.split('\n')[1][:100]


# ---------------------------------------------------------------- theory and replay checks: SUMO runs
@claim('replay: reproduces recorded run G exactly; a log with the wrong seed fails, which turns the theory checks off')
def _():
    good = {c['check']: c for c in replayed('G', RUN['G'])['checks']}
    assert good['replay']['status'] == 'PASS', good['replay']
    d = json.load(open(RUN['G']))
    for s in d['steps']:
        for c in s.get('calls', []):
            if c['name'] == 'start_live' and c['result'].startswith('Started'):
                c['arguments']['seed'] = 2
    bad = {c['check']: c for c in C.check_study(d)['checks']}
    assert bad['replay']['status'] == 'FAIL', bad['replay']
    assert all(bad[k]['status'] == 'N/A' for k in ('whole hour', 'capacity', 'queue growth')), bad
    return bad['replay']['finding'][:120]


@claim('theory on the reference run: the WB left turn is over capacity, and its queue grows as queueing theory says')
def _():
    res = replayed('REF', REF)
    ch = {c['check']: c for c in res['checks']}
    assert ch['replay']['status'] == 'PASS', ch['replay']
    rows = C.movement_table(res['measurements']['approaches']['E Fowler Ave & Bruce B Downs Blvd & N 30th St WB'])
    left = next(r for r in rows if r['group'] == 'l')
    thru = next(r for r in rows if r['group'] == 's')
    assert left['X'] > 1 and thru['X'] < 0.5, (left['X'], thru['X'])
    assert ch['capacity']['status'] == 'EXPLAIN' and 'does not say so' in ch['capacity']['finding'], ch['capacity']
    assert ch['queue growth']['status'] == 'PASS', ch['queue growth']
    assert ch['whole hour']['status'] == 'PASS', ch['whole hour']
    return f'left X = {left["X"]:.2f}, through X = {thru["X"]:.2f}'


@claim('theory checks catch what they should: an answer that says so, impossible counts, unexplained growth, a wrong verdict')
def _():
    res = replayed('REF', REF)
    log = C.load_log(REF)
    segs = C.segments(log)
    meas = res['measurements']
    lab = 'E Fowler Ave & Bruce B Downs Blvd & N 30th St WB'
    said = dict(log, answer=log['answer'] + ' The left-turn queue grows through the hour: it is over capacity.')
    assert C.check_capacity(said, segs, meas)['status'] == 'PASS'
    fast = copy.deepcopy(meas)
    for lane in fast['approaches'][lab]['departures']:
        fast['approaches'][lab]['departures'][lane] *= 10
    out = C.check_capacity(log, segs, fast)
    assert out['status'] == 'EXPLAIN' and 'More vehicles got through' in out['finding'], out['finding'][-200:]
    grow = copy.deepcopy(meas)
    q = grow['approaches'][lab]['queue']
    grow['approaches'][lab]['queue'] = [(t, b * (1 + (t - C.WARMUP) / 1800), n) for t, b, n in q]
    out = C.check_queue_growth(log, segs, grow)
    assert out['status'] == 'EXPLAIN' and 'not what the signal arithmetic predicts' in out['finding'], out['finding']
    wrong = dict(log, answer='Fowler Ave WB at 30th St is spilling back in the PM peak hour.')
    assert C.check_whole_hour(wrong, segs, meas)['status'] == 'FAIL'
    return 'said -> PASS; x10 counts, faster growth, wrong verdict -> caught'


if __name__ == '__main__':
    bad = 0
    for ok, text, detail in RESULTS:
        bad += not ok
        print(('PASS ' if ok else 'FAIL ') + text + (f'\n       {detail}' if detail else ''))
    print(f'\n{len(RESULTS) - bad} of {len(RESULTS)} checks of the checker pass')
    sys.exit(1 if bad else 0)
