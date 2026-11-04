"""Worked example for WRITING_TOOLS.md: turning one TraCI call into a tool an AI model can use.

The question an engineer asks: "What is the signal at Fowler & McKinley showing right now, and when does it change?"
SUMO answers it with two primitive calls. This file shows both versions of the tool:

  * get_tls_state_api  - a thin wrapper whose description is TraCI's own docstring (what you get by default)
  * get_signal_state   - the same calls, written the way a traffic engineer would explain the answer

Run it to see both answers side by side and to test every claim the engineer's description makes:

    python examples/get_signal_state.py

The tool is not part of the toolkit's menu yet. WRITING_TOOLS.md, section 8, shows the four steps to add it.
"""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import traci
import sumo_agent_tools as T


# ---- Version 1: the API wrapper. Correct code; the description is TraCI's docstring, word for word. -------------
def get_tls_state_api(tls_id):
    """getRedYellowGreenState(string) -> string

    Returns the named tl's state as a tuple of light definitions from
    rugGyYoO, for red, yed-yellow, green, yellow, off, where lower case letters mean that the stream
    has to decelerate."""
    return traci.trafficlight.getRedYellowGreenState(tls_id)


# ---- Version 2: the engineer's tool. Same primitive calls; names, definitions and a result a model can read. -----
# What each SUMO signal letter means for a driver (SUMO docs, "Signal state definitions").
MEANING = {'G': 'green',
           'g': 'green, yield to conflicting traffic (permissive)',
           's': 'stop, then go if clear (right turn on red)',
           'y': 'yellow',
           'u': 'red-yellow, green is coming',
           'r': 'red',
           'o': 'signal off, flashing: yield',
           'O': 'signal off: no control'}
BEST_FIRST = 'GgsyuroO'           # if lanes of one movement differ, report the most permissive letter
MOVEMENT = {'s': 'through', 'l': 'left', 'r': 'right'}


def get_signal_state(intersection: str) -> str:
    """What the signal at one intersection shows right now, movement by movement, and how long until it changes.
    intersection: cross streets, e.g. "Fowler & McKinley" (see list_intersections). Returns, for each approach
    (EB, WB, NB or SB, the direction of travel), the indication of its through, left and right movements: green;
    green but yield to conflicting traffic (a permissive left, for example); stop, then go if clear (right turn on
    red); yellow; or red. Then the seconds until the signal changes (a countdown, not a clock time). Reads only:
    time does not pass and nothing changes. A reading outside the analysis hour (900-4500 s) carries a WARM-UP or
    AFTER-PEAK warning. Use get_signal_plan for the whole cycle; this tool shows one moment of it."""
    T._need_live()                                                  # same error text as every live tool
    tls_id, name = T._resolve(intersection)                         # cross streets -> SUMO's id (sumolib)
    state = traci.trafficlight.getRedYellowGreenState(tls_id)       # primitive 1: e.g. 'rryyrrrrrrrryyrrrrr'
    now = traci.simulation.getTime()
    countdown = traci.trafficlight.getNextSwitch(tls_id) - now      # primitive 2 is a clock time: make it a countdown
    shown = {}                                                      # approach -> movement -> letter
    for index, (approach, move) in T._links(tls_id).items():        # signal index -> (EB/WB/NB/SB, s/l/r), sumolib
        if index < len(state):
            have = shown.setdefault(approach, {}).get(move)
            if have is None or BEST_FIRST.index(state[index]) < BEST_FIRST.index(have):
                shown[approach][move] = state[index]
    lines = []
    for approach in ('NB', 'SB', 'EB', 'WB'):
        if approach in shown:
            parts = [f'{MOVEMENT[m]} {MEANING[shown[approach][m]]}' for m in ('s', 'l', 'r') if m in shown[approach]]
            lines.append(f'  {approach}: ' + '; '.join(parts))
    return (f'{name} at {now:.0f} s: the signal changes in {countdown:.0f} s.{T._period_note()}\n' + '\n'.join(lines))


# Its schema: the same helpers the toolkit uses for every intersection input.
SCHEMA = T._S(intersection=dict(T._INT))


# ---- Test every claim in the description (the toolkit's one rule) -----------------------------------------------
def check():
    T.start_live()
    early = get_signal_state('Fowler & McKinley')
    T.advance(1805)                                                 # inside the analysis hour, mid-green
    tls_id, _ = T._resolve('Fowler & McKinley')
    raw = get_tls_state_api(tls_id)
    text = get_signal_state('Fowler & McKinley')
    print('API wrapper returns:  ', repr(raw))
    print('Engineer tool returns:\n' + text + '\n')

    # every signal letter is reported under some approach and movement
    links = T._links(tls_id)
    assert all(i in links for i in range(len(raw))), 'a signal index has no movement'
    # each approach's through indication agrees with get_approach_state, the toolkit's tested tool
    for approach in T._approaches(tls_id):
        line = [l for l in text.split('\n') if l.strip().startswith(approach + ':')]
        thru = T.get_approach_state('Fowler & McKinley', approach).split('through signal ')[1].split(',')[0]
        if line and 'through ' in line[0]:
            said = line[0].split('through ')[1].split(';')[0]
            assert said.split(',')[0] == thru or (thru == 'green' and said.startswith('green')), (approach, said, thru)
    # the countdown is a countdown: from 0 up to the longest phase of the plan
    longest = max(p.duration for p in traci.trafficlight.getAllProgramLogics(tls_id)[0].phases)
    countdown = float(text.split('changes in ')[1].split(' s')[0])
    assert 0 <= countdown <= longest, (countdown, longest)
    # reading does not let time pass
    t = traci.simulation.getTime()
    get_signal_state('Fowler & McKinley')
    assert traci.simulation.getTime() == t
    # warm-up warning before 900 s, none inside the analysis hour
    assert 'WARM-UP WARNING' in early and 'WARNING' not in text, (early[:120], text[:120])
    T.stop_live()
    # no simulation: the same instructive error as every live tool
    assert T.run_tool('get_approach_state', {'intersection': 'Fowler & McKinley', 'approach': 'WB'}).startswith(
        'Error: No live simulation is running')
    print('All claims pass.')


if __name__ == '__main__':
    check()
