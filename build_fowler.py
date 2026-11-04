"""Build the Fowler Avenue scenario used by the companion "Building SUMO Tools for AI Agents".

Real network, synthetic demand (a "twin experiment": a hidden demand plays the role of the real world,
so the right answer is known).

  fowler/fowler.osm.xml      OpenStreetMap extract around USF Tampa, downloaded Nov 3 2026 from
                             api.openstreetmap.org (bbox -82.434,28.049,-82.399,28.061).
                             (c) OpenStreetMap contributors, ODbL.
  fowler/fowler.net.xml      netconvert: arterials and collectors, clipped to a box, signals guessed from OSM.
                             Signal timing is netconvert's default guess, NOT the agency's timing plan.
  fowler/candidates.rou.xml  one fastest route (sumolib) for every entry -> exit pair, weighted by the
                             modeler's prior (Fowler through trips x3)
  fowler/stations.add.xml    induction loops (E1) across every lane at 16 count stations, like field counters
  fowler/truth.rou.xml       HIDDEN demand that plays "the real world" (SYNTHETIC)
  fowler/field_counts.xml    hourly counts at the 16 stations, measured on the hidden demand (SYNTHETIC)
  fowler/demand.rou.xml      routeSampler.py rebuilds demand from field_counts.xml plus the prior
  fowler/demand_lp.rou.xml   routeSampler.py --optimize full: counts alone, no prior
  fowler/random.rou.xml      randomTrips.py demand with the same number of trips (what OSMWebWizard does)
  fowler/e2.add.xml          lane-area (E2) detectors on every signal approach lane

For a real study, replace field_counts.xml with agency counts (e.g. FDOT Florida Traffic Online).

    pip install eclipse-sumo pyproj rtree
    python build_fowler.py
"""
import os, sys, subprocess, collections
import sumo, sumolib

HERE = os.path.dirname(os.path.abspath(__file__))
F = os.path.join(HERE, 'fowler')
SUMO_HOME = os.environ.setdefault('SUMO_HOME', sumo.SUMO_HOME)
BIN, TOOLS = os.path.join(SUMO_HOME, 'bin'), os.path.join(SUMO_HOME, 'tools')
WARMUP, HOUR = 900, 3600            # 15-minute warm-up, then the analysis hour (900-4500 s)
END = WARMUP + HOUR

# 16 count stations: edge id -> what a count sheet would call it
STATIONS = {
    '1125146807#0': 'Fowler Ave EB, west of 30th St',
    '88714948#1':   'Fowler Ave WB, east of Bull Run Dr',
    '66426595#2':   'N 30th St NB, south of Fowler',
    '70945154#3':   'Bruce B Downs Blvd SB, north of Pine Dr',
    '41547256#1':   'McKinley Dr NB, south of Fowler',
    '99650283#2':   'N 46th St NB, south of Fowler',
    '59848576#1':   'Leroy Collins Blvd SB, north of Alumni Dr',
    '142214945#1':  'USF Magnolia Dr SB, north of Alumni Dr',
    '38521244':     'USF Bull Run Dr SB, north of Fowler',
    '1466353051':   'campus road EB, west of Leroy Collins Blvd',
    '905467885':    'Fowler Ave EB, 30th St to McKinley Dr',
    '905783593':    'Fowler Ave EB, McKinley Dr to Leroy Collins Blvd',
    '905731049':    'Fowler Ave EB, Leroy Collins Blvd to Bull Run Dr',
    '88714948#4':   'Fowler Ave WB, Bull Run Dr to Leroy Collins Blvd',
    '80591645':     'Fowler Ave WB, Leroy Collins Blvd to McKinley Dr',
    '77843977#0':   'Fowler Ave WB, McKinley Dr to 30th St',
}
# The hidden "real world": vehicles per hour entering at each fringe edge (SYNTHETIC)
TRUE_ENTRIES = {'1125146807#0': 1000, '88714948#1': 950, '66426595#2': 500, '70945154#3': 550,
                '41547256#1': 280, '99650283#2': 220, '59848576#1': 300, '142214945#1': 150,
                '38521244': 150, '1466353051': 50}


def run(*args):
    r = subprocess.run([str(a) for a in args], capture_output=True, text=True)
    if r.returncode:
        raise RuntimeError(' '.join(map(str, args))[:300] + '\n' + r.stderr[-2000:])
    return r.stdout + r.stderr


def download_osm():
    """Fetch the OpenStreetMap extract if it is missing. Newer map data can change the network and the numbers."""
    import urllib.request
    url = 'https://api.openstreetmap.org/api/0.6/map?bbox=-82.434,28.049,-82.399,28.061'
    req = urllib.request.Request(url, headers={'User-Agent': 'AI4Mobility-course/1.0'})
    os.makedirs(F, exist_ok=True)
    open(f'{F}/fowler.osm.xml', 'wb').write(urllib.request.urlopen(req, timeout=120).read())


def build_network():
    if not os.path.exists(f'{F}/fowler.osm.xml'):
        download_osm()
    return run(os.path.join(BIN, 'netconvert'), '--osm-files', f'{F}/fowler.osm.xml',
               '--type-files', f'{SUMO_HOME}/data/typemap/osmNetconvert.typ.xml',
               '--keep-edges.by-type', 'highway.primary,highway.primary_link,highway.secondary,'
               'highway.secondary_link,highway.tertiary,highway.tertiary_link,highway.unclassified',
               '--keep-edges.in-geo-boundary', '-82.4320,28.0500,-82.4025,28.0600',
               '--geometry.remove', '--roundabouts.guess', '--ramps.guess', '--junctions.join',
               '--tls.guess-signals', '--tls.discard-simple', '--tls.join', '--tls.default-type', 'static',
               '--remove-edges.isolated', '--keep-edges.components', '1', '--no-turnarounds.except-deadend',
               '--output.street-names', '--output.original-names', '--no-warnings',
               '-o', f'{F}/fowler.net.xml')


def entries_exits(net):
    """Fringe edges: nothing flows in (entries) or nothing flows on (exits), U-turns ignored."""
    ent = [e for e in net.getEdges()
           if not [i for i in e.getFromNode().getIncoming() if i.getFromNode() != e.getToNode()]]
    ext = [e for e in net.getEdges()
           if not [o for o in e.getToNode().getOutgoing() if o.getToNode() != e.getFromNode()]]
    return ent, ext


FOWLER = 'East Fowler Avenue'


def hidden_weight(a, b):
    """Hidden-world trip pattern (only the truth uses it): most Fowler traffic stays on Fowler."""
    fa, fb = a.getName() == FOWLER, b.getName() == FOWLER
    return 10 if (fa and fb) else 2 if (fa or fb) else 1


def engineer_prior(a, b):
    """The modeler's rule of thumb, not the hidden weights: on an arterial, through trips are more
    likely than trips that turn on and off it. Fowler-to-Fowler routes count three times."""
    return 3 if (a.getName() == FOWLER and b.getName() == FOWLER) else 1


def write_candidates(net, weight, path):
    ent, ext = entries_exits(net)
    n = 0
    with open(path, 'w') as f:
        f.write('<routes>\n')
        for a in ent:
            for b in ext:
                if a.getName() and a.getName() == b.getName() and a.getFromNode().getCoord() == b.getToNode().getCoord():
                    continue                                    # straight back out where it came in
                path, cost = net.getFastestPath(a, b)
                if path:
                    f.write(f'  <route id="r{n}" edges="{" ".join(e.getID() for e in path)}" '
                            f'probability="{weight(a, b)}"/>\n')
                    n += 1
        f.write('</routes>\n')
    return n


def write_edge_counts(counts, path):
    """edgeData count file for routeSampler: warm-up at 25% of the hourly count, then the hour."""
    with open(path, 'w') as f:
        f.write('<data>\n')
        for b, e, k in ((0, WARMUP, 0.25), (WARMUP, END, 1.0)):
            f.write(f'  <interval id="{"warmup" if b == 0 else "pm_peak"}" begin="{b}" end="{e}">\n')
            for eid, v in counts.items():
                f.write(f'    <edge id="{eid}" entered="{round(v * k)}"/>  <!-- {STATIONS.get(eid, "")} -->\n')
            f.write('  </interval>\n')
        f.write('</data>\n')
    return path


def write_loops(net):
    """An induction loop across every lane at mid-edge: a simulated counter that works like a field counter."""
    with open(f'{F}/stations.add.xml', 'w') as f:
        f.write('<additional>\n')
        for eid in STATIONS:
            e = net.getEdge(eid)
            for lane in e.getLanes():
                f.write(f'  <inductionLoop id="cnt_{eid}_{lane.getIndex()}" lane="{lane.getID()}" '
                        f'pos="{lane.getLength() / 2:.1f}" period="{WARMUP}" file="loops_out.xml"/>\n')
        f.write('</additional>\n')


def read_station_counts(loop_file, begin=WARMUP, end=END):
    """Sum loop counts over all lanes of each station, analysis hour only -> veh/h."""
    tot = collections.Counter()
    for iv in sumolib.xml.parse(loop_file, 'interval'):
        if float(iv.begin) >= begin and float(iv.end) <= end:
            eid = iv.id[4:].rsplit('_', 1)[0]
            tot[eid] += int(iv.nVehContrib)
    hours = (end - begin) / 3600
    return {eid: tot[eid] / hours for eid in STATIONS}


def route_sampler(counts_file, out, weighted, seed=42, candidates=None):
    args = [sys.executable, os.path.join(TOOLS, 'routeSampler.py'), '-r', candidates or f'{F}/candidates.rou.xml',
            '--edgedata-files', counts_file, '-o', out, '--seed', seed,
            '--attributes', 'departLane="best" departSpeed="max"']
    return run(*(args + (['--weighted'] if weighted else ['--optimize', 'full'])))


def stations_for(outdir):
    """A copy of the count stations that writes into outdir (SUMO resolves output paths next to the file)."""
    os.makedirs(outdir, exist_ok=True)
    path = os.path.join(outdir, 'stations.add.xml')
    open(path, 'w').write(open(f'{F}/stations.add.xml').read().replace(
        'file="loops_out.xml"', f'file="{os.path.abspath(outdir)}/loops_out.xml"'))
    return path


def simulate_counts(routes, seed, outdir):
    run(os.path.join(BIN, 'sumo'), '-n', f'{F}/fowler.net.xml', '-r', routes, '-a', stations_for(outdir),
        '--end', END, '--seed', seed, '--no-step-log', '--no-warnings')
    return read_station_counts(f'{outdir}/loops_out.xml')


def write_detectors():
    out = run(sys.executable, os.path.join(TOOLS, 'output', 'generateTLSE2Detectors.py'),
              '-n', f'{F}/fowler.net.xml', '-l', '150', '-d', '1', '-f', '60', '-o', f'{F}/e2.add.xml', '-r', 'NUL')
    s = open(f'{F}/e2.add.xml').read().replace('file="e2_output.xml"', 'file="NUL"')
    open(f'{F}/e2.add.xml', 'w').write(s)
    return out


if __name__ == '__main__':
    os.makedirs(os.path.join(HERE, 'runs'), exist_ok=True)
    build_network()
    net = sumolib.net.readNet(f'{F}/fowler.net.xml')
    print('candidate routes:', write_candidates(net, hidden_weight, f'{F}/truth_candidates.rou.xml'),
          write_candidates(net, engineer_prior, f'{F}/candidates.rou.xml'))
    write_loops(net)
    write_detectors()
    # 1. the hidden real world
    write_edge_counts(TRUE_ENTRIES, f'{F}/truth_entries.xml')
    route_sampler(f'{F}/truth_entries.xml', f'{F}/truth.rou.xml', weighted=True, seed=7,
                  candidates=f'{F}/truth_candidates.rou.xml')
    field = simulate_counts(f'{F}/truth.rou.xml', 0, os.path.join(HERE, 'runs', 'truth'))
    field = {k: int(5 * round(v / 5)) for k, v in field.items()}        # count sheets round to 5 veh
    write_edge_counts(field, f'{F}/field_counts.xml')
    print('field counts (synthetic):', field)
    # 2. what a modeler does with the counts: (a) counts plus the through-trip prior, (b) counts alone (LP fit)
    print(route_sampler(f'{F}/field_counts.xml', f'{F}/demand.rou.xml', weighted=True)[-200:])
    print(route_sampler(f'{F}/field_counts.xml', f'{F}/demand_lp.rou.xml', weighted=False)[-200:])
    # 3. what OSMWebWizard-style random demand looks like, same number of trips
    n_trips = sum(1 for l in open(f'{F}/demand.rou.xml') if '<vehicle ' in l)
    run(sys.executable, os.path.join(TOOLS, 'randomTrips.py'), '-n', f'{F}/fowler.net.xml', '-r', f'{F}/random.rou.xml',
        '-o', os.path.join(HERE, 'runs', 'random.trips.xml'), '-e', END, '-p', f'{END / n_trips:.4f}', '--fringe-factor', '10',
        '--seed', 42, '--validate')
    print('trips:', n_trips, 'random:', sum(1 for l in open(f'{F}/random.rou.xml') if '<vehicle ' in l))
