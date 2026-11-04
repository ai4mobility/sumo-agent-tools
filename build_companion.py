"""Build the companion page from companion_template.html.

    python build_companion.py docs/index.html      # in the repository
    python build_companion.py                      # course folder: ../SUMO_Tools_for_Agents_Companion.html


Every number on the page comes from numbers_sumo_tools.json (experiments.py) or claims_result.json
(test_claims.py); placeholders look like {{e1.naive_mean_mph|0}}. The build fails if any placeholder is left,
or if a placeholder points at a missing number.

    python build_companion.py
"""
import os, re, json, base64, statistics, html
HERE = os.path.dirname(os.path.abspath(__file__))
import sys
sys.path.insert(0, HERE)
import sumo_agent_tools as T
import build_fowler as B

N = json.load(open(os.path.join(HERE, 'numbers_sumo_tools.json')))
CLAIMS = json.load(open(os.path.join(HERE, 'claims_result.json')))
FT, MPH = T.FT, T.MPH


def get(path):
    cur = {'D': D, **N}
    for k in path.split('.'):
        if isinstance(cur, list):
            cur = cur[int(k)]
        else:
            cur = cur[k]
    return cur


def fmt(v, spec):
    if spec is None:
        return html.escape(str(v))
    pct = spec.startswith('%')
    spec = spec.lstrip('%')
    sign = '+' if spec.startswith('+') else ''
    comma = ',' if ',' in spec else ''
    dec = int(spec.replace('+', '').replace(',', '') or 0)
    v = float(v) * (100 if pct else 1)
    s = format(v, f'{sign}{comma}.{dec}f')
    return s.replace('-', '−')


# ---------------------------------------------------------------- derived numbers
D = {}
e4 = N['e4']
mean = statistics.mean
ex, raw, chk = (mean(e4[p]['delay_s_per_veh']) for p in ('existing', 'webster_raw', 'webster'))
D.update(ex_delay=ex, raw_delay=raw, chk_delay=chk, raw_cut=100 * (ex - raw) / ex, chk_cut=100 * (ex - chk) / ex,
         ex_min=min(e4['existing']['delay_s_per_veh']), ex_max=max(e4['existing']['delay_s_per_veh']),
         chk_min=min(e4['webster']['delay_s_per_veh']), chk_max=max(e4['webster']['delay_s_per_veh']),
         raw_min=min(e4['webster_raw']['delay_s_per_veh']), raw_max=max(e4['webster_raw']['delay_s_per_veh']))
w = e4['webster_vs_existing']
D['ex_unf'] = mean(e4['existing']['cohort_unfinished'])
D.update(unpaired_pct=100 * w['unpaired_wrong_way'] / w['unpaired_pairs'], diff=w['mean'], ci_lo=w['ci95'][0],
         ci_hi=w['ci95'][1], diff_abs=-w['mean'], seeds_better=w['seeds_better'], ex_spread=D['ex_max'] - D['ex_min'])
for k in ('EB', 'WB'):
    for p in ('existing', 'webster_raw', 'webster'):
        D[f'{p}_{k}_min'] = statistics.median(e4[p][f'fowler_{k}_min'])
rows3 = {r['scale']: r for r in N['e3']['rows']}
for sc, r in rows3.items():
    tag = str(sc).replace('.', '')
    D[f'hide{tag}'] = 100 * (r['delay_s_per_veh'] - r['naive_delay_s_per_veh']) / r['delay_s_per_veh']
    D[f'naive{tag}'] = r['naive_delay_s_per_veh']
    D[f'eng{tag}'] = r['delay_s_per_veh']
    D[f'unf{tag}'] = r['cohort_unfinished']
    D[f'wait{tag}'] = r['waiting_to_enter']
    D[f'tel{tag}'] = r['teleports']
cyc = N['e5']['cycles']
D.update(raw_cyc_min=min(cyc['webster_raw'].values()), raw_cyc_max=max(cyc['webster_raw'].values()),
         chk_cyc_min=min(cyc['webster'].values()), chk_cyc_max=max(cyc['webster'].values()))
e6 = N['e6']
for k in ('random', 'demand_lp', 'demand'):
    D[f'geh_{k}'] = e6[k]['geh_under_5']
D['entry_entered_zero'] = sum(1 for r in e6['entry_stations'] if r['edgedata_entered'] == 0)
D['entry_n'] = len(e6['entry_stations'])
e1 = N['e1']
D['worst_lanes_used'] = sum(1 for l in e1['worst']['lanes'] if l[1] > 0)
D['worst_lanes_empty'] = sum(1 for l in e1['worst']['lanes'] if l[1] == 0)
D['e1_share_ge30'] = 100 * e1['share_samples_naive_ge30_true_lt15']
D['e1_empty'] = 100 * e1['share_lane_samples_empty']
e2, e2b = N['e2'], N['e2b']
D['e2_det_ft'] = e2b['detector_m'] / FT
D['e2_beyond_pct'] = 100 * e2b['samples_beyond_detector'] / e2b['samples']
D['e2_below_half_pct'] = 100 * e2['share_snapshots_below_half_cycle_max']
D['snap_back_ft'] = e2b['snap_back_m'] / FT
D['e2_fill'] = 100 * e2['max_ft'] / e2['storage_ft']
e7 = N['e7']
D['id_tok_avg'] = e7['id_tokens_total'] / len(e7['id_tokens'])
D['name_tok_avg'] = e7['name_tokens_total'] / len(e7['name_tokens'])
D['dump_ratio'] = e7['corridor_dump_tokens'] / e7['corridor_tool_tokens']
D['trip_ratio'] = e7['tripinfo_tokens'] / e7['compare_tokens']
D['desc_extra'] = e7['tool_descriptions_tokens_engineer'] - e7['tool_descriptions_tokens_api']
D['claims_pass'] = sum(c['ok'] for c in CLAIMS)
D['claims_n'] = len(CLAIMS)
D['e9_empty_mph'] = N['e9']['empty_lane']['mean_speed_mps'] / MPH
D['e9_occ_pct'] = 100 * N['e9']['occupancy']['vehicle_length_share']
D['speed_limit_ft_s'] = 50 * MPH / FT
D['ite50'] = T._ite_yellow(50 * MPH)
D['ite45'] = T._ite_yellow(45 * MPH)
D['ped94'] = T.WALK_S + 94 / T.PED_FTPS
D['fowler_EB_ft'] = N['e0']['fowler_EB_mi'] * 5280

# per-signal Webster table
probs = {}
for p in N['e5']['raw_list']:
    probs.setdefault(p.split(': ')[0], []).append(p.split(': ', 1)[1])
sig_rows = []
for name in N['e0']['intersections']:
    pr = probs.get(name, [])
    xw = [p for p in pr if 'crosswalk' in p]
    worst = max(xw, key=lambda p: float(p.split(' < ')[1].split(' s')[0]) - float(p.split(' s < ')[0].split()[-1]),
                default='')
    sig_rows.append({'name': name, 'raw': cyc['webster_raw'][name], 'chk': cyc['webster'][name],
                     'existing': N['e5']['existing'][name]['cycle'], 'n': len(pr), 'n_x': len(xw), 'worst': worst})


# ---------------------------------------------------------------- the map
def fowler_map():
    net = T._net()
    W, H, pad = 1200, 560, 40
    xs = [x for e in net.getEdges() for x, _ in e.getShape()]
    ys = [y for e in net.getEdges() for _, y in e.getShape()]
    x0, x1, y0, y1 = min(xs), max(xs), min(ys), max(ys)
    s = min((W - 2 * pad) / (x1 - x0), (H - 2 * pad - 30) / (y1 - y0))
    X = lambda x: pad + (x - x0) * s
    Y = lambda y: H - pad - (y - y0) * s
    out = [f'<svg viewBox="0 0 {W} {H}" role="img" aria-label="Map of the Fowler Avenue network">',
           f'<rect width="{W}" height="{H}" fill="#fbfdfc"/>']
    fow = {e.getID() for d in ('EB', 'WB') for e in T._fowler_path(d)}
    for e in sorted(net.getEdges(), key=lambda e: e.getID() in fow):
        pts = ' '.join(f'{X(x):.1f},{Y(y):.1f}' for x, y in e.getShape())
        isf = e.getID() in fow
        wdt = 1.2 + 0.9 * e.getLaneNumber() if isf else 0.8 + 0.7 * e.getLaneNumber()
        col = '#006747' if isf else '#9aa8a3'
        out.append(f'<polyline points="{pts}" fill="none" stroke="{col}" stroke-width="{wdt:.1f}" '
                   f'stroke-linecap="round" stroke-linejoin="round" opacity="{0.95 if isf else 0.8}"/>')
    # count stations
    for i, (eid, lab) in enumerate(B.STATIONS.items(), 1):
        sh = net.getEdge(eid).getShape()
        x, y = sh[len(sh) // 2]
        out.append(f'<rect x="{X(x) - 5:.1f}" y="{Y(y) - 5:.1f}" width="10" height="10" rx="2" fill="#fff" '
                   f'stroke="#0E6E9E" stroke-width="2"><title>Count station: {html.escape(lab)}</title></rect>')
    # signals with labels
    offs = {'E Fowler Ave & Bruce B Downs Blvd & N 30th St': (0, 46, 'Fowler & 30th St / BBD'),
            'Bruce B Downs Blvd & USF Pine Dr': (-14, -22, 'BBD & Pine Dr'),
            'E Fowler Ave & McKinley Dr': (-12, 44, 'Fowler & McKinley', 'end'),
            'E Fowler Ave & Leroy Collins Blvd': (12, 44, 'Fowler & Leroy Collins', 'start'),
            'Leroy Collins Blvd & USF Alumni Dr': (0, -22, 'Leroy Collins & Alumni'),
            'E Fowler Ave & USF Bull Run Dr': (0, 46, 'Fowler & Bull Run')}
    for name, tid in T._intersections().items():
        nodes = {c[0].getEdge().getToNode() for c in net.getTLS(tid).getConnections()}
        x = mean(n.getCoord()[0] for n in nodes)
        y = mean(n.getCoord()[1] for n in nodes)
        dx, dy, lab, *anc = offs[name]
        out.append(f'<circle cx="{X(x):.1f}" cy="{Y(y):.1f}" r="9" fill="#CFC493" stroke="#003E2A" stroke-width="2.5">'
                   f'<title>{html.escape(name)}</title></circle>')
        out.append(f'<text x="{X(x) + dx:.1f}" y="{Y(y) + dy:.1f}" text-anchor="{anc[0] if anc else "middle"}" font-size="15" '
                   f'font-weight="700" fill="#1c2422" stroke="#fbfdfc" stroke-width="4" paint-order="stroke">'
                   f'{html.escape(lab)}</text>')
    # street labels, north arrow, scale
    lab = [('E Fowler Ave', 2330, 655), ('Bruce B Downs Blvd', 660, 1050), ('N 30th St', 650, 240),
           ('USF campus', 1500, 1000), ('McKinley Dr', 1640, 250), ('N 46th St', 2250, 250)]
    for t, x, y in lab:
        out.append(f'<text x="{X(x):.1f}" y="{Y(y):.1f}" font-size="13" fill="#5b6b66" font-style="italic">{t}</text>')
    bar_m = 1000 * FT                               # 1,000 ft
    bx, by = W - pad - bar_m * s, H - 18
    out.append(f'<line x1="{bx:.1f}" y1="{by}" x2="{W - pad}" y2="{by}" stroke="#1c2422" stroke-width="2"/>'
               f'<text x="{(bx + W - pad) / 2:.1f}" y="{by - 6}" text-anchor="middle" font-size="12" fill="#1c2422">'
               f'1,000 ft</text>')
    out.append(f'<g transform="translate({W - pad - 10},{pad + 10})"><path d="M0,-16 L7,6 L0,1 L-7,6 Z" '
               f'fill="#1c2422"/><text x="0" y="22" text-anchor="middle" font-size="12" font-weight="700">N</text></g>')
    out.append(f'<g transform="translate({pad},{H - 22})" font-size="12.5" fill="#1c2422">'
               '<line x1="0" y1="0" x2="26" y2="0" stroke="#006747" stroke-width="5"/>'
               '<text x="32" y="4">Fowler Ave, both directions</text>'
               '<circle cx="238" cy="0" r="7" fill="#CFC493" stroke="#003E2A" stroke-width="2"/>'
               '<text x="250" y="4">signal (6)</text>'
               '<rect x="330" y="-5" width="10" height="10" rx="2" fill="#fff" stroke="#0E6E9E" stroke-width="2"/>'
               '<text x="346" y="4">count station (16)</text></g>')
    out.append('</svg>')
    return '\n'.join(out)


def b64(path):
    return base64.b64encode(open(path, 'rb').read()).decode()


# ---------------------------------------------------------------- data for the page's scripts
FILES = ['sumo_agent_tools.py', 'api_shaped_tools.py', 'mcp_server.py', 'build_fowler.py', 'test_claims.py',
         'experiments.py', 'gui_view.py', 'timing.py', 'README.md']
DATA = {
    'e1': {'series': e1['series']},
    'e2': {'series': e2['series'], 'det_m': e2b['detector_m'], 'storage_m': e2b['storage_m'],
           'snap': e2b['snap_vehicles'], 'snap_t': e2b['snap_t'], 'snap_back_m': e2b['snap_back_m']},
    'e3': N['e3']['rows'],
    'e4': {p: e4[p]['delay_s_per_veh'] for p in ('existing', 'webster_raw', 'webster')},
    'e6': {k: [[r['station'], r['simulated'], r['field'], r['geh']] for r in e6[k]['rows']]
           for k in ('random', 'demand_lp', 'demand')},
    'e7': {k: e7[k] for k in ('id_tokens_total', 'name_tokens_total', 'corridor_dump_tokens', 'corridor_tool_tokens',
                              'tripinfo_tokens', 'compare_tokens', 'corridor_calls_api')},
    'files': {f: open(os.path.join(HERE, f)).read() for f in FILES if os.path.exists(os.path.join(HERE, f))},
    'tools': T.TOOLS,
}


def table_rows_webster():
    out = []
    for r in sig_rows:
        out.append(f'<tr><td>{html.escape(r["name"])}</td><td class="num">{r["existing"]:.0f}</td>'
                   f'<td class="num">{r["raw"]:.0f}</td><td class="num">{r["n"]}</td>'
                   f'<td class="num">{r["chk"]:.0f}</td><td>{html.escape(r["worst"])}</td></tr>')
    return '\n'.join(out)


def short(t, n=150):
    return t if len(t) <= n else t[:n].rsplit(' ', 1)[0] + ' …'


def table_rows_claims():
    return '\n'.join(f'<tr><td>{"PASS" if c["ok"] else "FAIL"}</td><td>{html.escape(c["claim"])}</td>'
                     f'<td class="small">{html.escape(short(c["detail"]))}</td></tr>' for c in CLAIMS)


def table_rows_entry():
    return '\n'.join(f'<tr><td>{html.escape(r["station"])}</td><td class="num">{r["field"]:,.0f}</td>'
                     f'<td class="num">{r["loop_count"]:,}</td><td class="num">{r["edgedata_entered"]:,}</td></tr>'
                     for r in N['e6']['entry_stations'])


def table_rows_e3():
    return '\n'.join(f'<tr><td>{r["scale"]:.1f}×</td><td class="num">{r["naive_delay_s_per_veh"]:.0f}</td>'
                     f'<td class="num">{r["delay_s_per_veh"]:.0f}</td>'
                     f'<td class="num">{100 * (r["delay_s_per_veh"] - r["naive_delay_s_per_veh"]) / r["delay_s_per_veh"]:.0f}%</td>'
                     f'<td class="num">{r["cohort_unfinished"]:,}</td><td class="num">{r["waiting_to_enter"]:,}</td>'
                     f'<td class="num">{r["teleports"]:,}</td></tr>' for r in N['e3']['rows'])


def table_rows_worst():
    out = []
    for lane, n, v, lim in e1['worst']['lanes']:
        cls = ' class="hl"' if n else ''
        out.append(f'<tr{cls}><td class="mono">{html.escape(lane)}</td><td class="num">{n}</td>'
                   f'<td class="num">{v:.0f}</td><td class="num">{lim:.0f}</td></tr>')
    return '\n'.join(out)


def pre(s):
    return html.escape(s)


BLOCKS = {
    'MAP': fowler_map(),
    'IMG_30TH': b64(os.path.join(HERE, 'tmc_view_30th.png')),
    'IMG_NET': b64(os.path.join(HERE, 'tmc_view_network.png')),
    'ROWS_WEBSTER': table_rows_webster(),
    'ROWS_CLAIMS': table_rows_claims(),
    'ROWS_ENTRY': table_rows_entry(),
    'ROWS_E3': table_rows_e3(),
    'ROWS_WORST': table_rows_worst(),
    'TXT_LIST': pre(N['e0']['list_intersections']),
    'TXT_CAL_RANDOM': pre(e6['random']['text']),
    'TXT_CAL_LP': pre(e6['demand_lp']['text']),
    'TXT_CAL_DEMAND': pre(e6['demand']['text']),
    'TXT_WEBSTER': pre(N['e5']['webster_text']),
    'TXT_REJECT': pre(e7['reject_text']),
    'TXT_COMPARE': pre(e7['compare_text']),
    'TXT_ONE_SEED': pre(e7['one_seed_text']),
    'TXT_BLOCKED': pre(e7['blocked_text']),
    'TXT_CORRIDOR': pre(e7['corridor_text']),
    'DESC_ENGINEER_APPROACH': pre(next(t['description'] for t in T.TOOLS if t['name'] == 'get_approach_state')),
    'DESC_ENGINEER_ADVANCE': pre(next(t['description'] for t in T.TOOLS if t['name'] == 'advance')),
    'DESC_ENGINEER_COMPARE': pre(next(t['description'] for t in T.TOOLS if t['name'] == 'compare_plans')),
    'DESC_ENGINEER_CAL': pre(next(t['description'] for t in T.TOOLS if t['name'] == 'check_calibration')),
    'DIFF_ABS': f"{-N['e4']['webster_vs_existing']['mean']:.0f}",
    'DATA': json.dumps(DATA, separators=(',', ':')).replace('</', '<\\/'),
}

if __name__ == '__main__':
    tpl = open(os.path.join(HERE, 'companion_template.html')).read()
    for k, v in BLOCKS.items():
        tpl = tpl.replace('[[' + k + ']]', v)

    def sub(m):
        path, spec = m.group(1), m.group(2)
        return fmt(get(path), spec)
    page = re.sub(r'\{\{([A-Za-z0-9_.\-]+)(?:\|([^}]*))?\}\}', sub, tpl)
    left = re.findall(r'\{\{[^}]*\}\}|\[\[[A-Z_0-9]+\]\]', page)
    assert not left, left[:10]
    out = (os.path.abspath(sys.argv[1]) if len(sys.argv) > 1     # e.g. docs/index.html in the repository
           else os.path.join(os.path.dirname(HERE), 'SUMO_Tools_for_Agents_Companion.html'))   # the course module folder
    open(out, 'w').write(page)
    print(out, f'{len(page) / 1024:.0f} KB')
