# Writing SUMO tools for AI agents: a guide for traffic engineers

This guide is for you if you know traffic engineering and SUMO well but have not built anything for AI. By the end,
you will be able to take something you know, such as how to read a queue, check a timing plan or judge a calibration,
and turn it into a tool that an AI model can call and use correctly.

You do not need to know how language models work inside. You need your traffic knowledge, the Python you already use
with TraCI, and a few new ideas, all explained below. The companion page (`docs/index.html`, tab 10, "Write your own")
shows the same material with figures.

## 1. Why the AI needs you

An AI model that runs a simulation never sees SUMO, the network or your code. It sees two pieces of text:

- the tool's **description**, which tells it what the tool does, and
- the tool's **result**, the text your function sends back after it runs.

Everything the model knows about your simulation comes through those two texts.

SUMO's documentation can tell a model which function to call. It cannot tell it what the numbers mean, which
definition to use, or when a reading is worthless. That knowledge is yours. On the Fowler Ave scenario in this
repository, tools that left it out went wrong like this:

| What a traffic engineer knows | What happened when a tool left it out |
|---|---|
| Speed is undefined at zero density | Averaging lane speeds gave 32 mph; the vehicles themselves averaged 7 mph, because an empty lane reports its speed limit |
| A queue needs a definition | SUMO's helper placed a 20.7-m detector on an approach whose queue reached 2,079 ft |
| Every vehicle counts | The delay of finished trips hid 24% of the delay at today's demand |
| A warm-up is not the peak | A model read the queue at 0 s, on an empty network, and answered "not spilling back during the PM peak hour" |
| Say the verdict either way | Given a queue that filled 9% of its storage and no flag, a model answered "is spilling back" |
| One run is not evidence | Single unpaired runs pointed the wrong way 15% of the time |

The first three rows and the last are measured in `experiments.py` and shown on the companion page
(`docs/index.html`); the other two are recorded model runs in `walkthrough/`.

If you can explain a result to a new engineer on your team, you can write a tool.

## 2. How a model uses a tool, in five minutes

1. You give the model a **menu**: for each tool, a name, a description and its inputs.
2. The model reads the menu and the question, then writes a request as text, for example
   `{"name": "get_approach_state", "arguments": {"intersection": "Fowler & 30th", "approach": "WB"}}`.
   Writing it runs nothing.
3. A program called the **harness** reads the request, checks it, and calls your Python function with those inputs.
4. Your function calls SUMO through TraCI and sumolib, and turns what comes back into a short text.
5. That text goes back to the model. The model reads it and decides what to do next: call another tool, or answer.

Steps 1 to 5 repeat until the model answers. Words you will meet:

- **Model**: the AI that reads and writes text, such as Claude or Qwen. It runs no code itself.
- **Tool**: a Python function, plus its name, description and input rules.
- **Harness**: the program that runs the loop. It can be your own script (`walkthrough/qwen_harness.py`) or an
  app such as Claude Code.
- **Schema**: the rules for a tool's inputs: their names, types (text, whole number, true or false), allowed values
  and ranges.
- **Token**: a piece of text, often a short word or part of a longer one. Models read and write in tokens. Every
  description and every result is read again at every step, so long texts cost time.
- **MCP** (Model Context Protocol): the standard way apps such as Claude Code connect to tools. `mcp_server.py`
  handles it for you.

To see every step with real text, from small models run on an ordinary CPU, read `walkthrough/README.md`.

## 3. The five parts of a tool

| Part | Where it lives in this repository | Who reads it |
|---|---|---|
| Name | The function name | The model |
| Description | The function's docstring | The model, at every step |
| Inputs | The tool's entry in `SCHEMAS` | The model and the harness |
| Body | The TraCI and sumolib calls inside the function | Only Python and SUMO |
| Result | The text the function returns | The model, at every later step |

You already know how to write the body. This guide is about the other four, and about the decisions that turn
SUMO's raw values into something a model can use.

## 4. A worked example: from one TraCI call to a tool

The engineer's question: **"What is the signal at Fowler & McKinley showing right now, and when does it change?"**
The full code is in `examples/get_signal_state.py`. Run `python examples/get_signal_state.py` to see both versions
below answer the same moment, and to test every claim the second one makes.

### Version 1: the API wrapper

This is what you get if you wrap TraCI as it is, or ask a coding assistant to "make TraCI into tools". The
description is TraCI's own docstring, word for word.

```python
def get_tls_state_api(tls_id):
    """getRedYellowGreenState(string) -> string

    Returns the named tl's state as a tuple of light definitions from
    rugGyYoO, for red, yed-yellow, green, yellow, off, where lower case letters mean that the stream
    has to decelerate."""
    return traci.trafficlight.getRedYellowGreenState(tls_id)
```

At 1,805 s it returns `'rGGGGGGrrrrrrGGG'`. Nothing in the code is wrong, but think about what the model has to
know to use it:

- It needs SUMO's internal id for the signal, `joinedS_6067633741_cluster_365779835_511131072_511131148_97802393`,
  not "Fowler & McKinley".
- To read the answer, it must know which of the 16 letters belongs to which movement. That is written only in the
  network file.
- The description calls the string a "tuple" and has a typo ("yed-yellow").
- Nothing says when the signal will change.

### Version 2: the engineer's tool

Same TraCI calls. Seven decisions make the difference.

**Decision 1. Start from the engineer's question, not from the API function.** One question needs several primitive
calls: `traci.trafficlight.getRedYellowGreenState`, `traci.trafficlight.getNextSwitch`,
`traci.simulation.getTime`, and the network's connections from sumolib. The model should not have to know that.

**Decision 2. Take inputs the way people name things.** The tool takes cross streets. A toolkit helper (`_resolve`)
finds the SUMO id with sumolib, so the model never sees one. If a name matches no signal, or more than one, the error
lists the signals by name.

**Decision 3. Translate codes and units.** Each letter becomes a movement (EB through, WB left, and so on) using the
network's connections. Each letter becomes words a driver would understand, following [SUMO's table of signal
states](https://sumo.dlr.de/docs/Simulation/Traffic_Lights.html#signal_state_definitions): `G` green, `g` green but yield to conflicting traffic, `s` stop then go if clear (right turn on red),
`y` yellow, `r` red. And `getNextSwitch` returns a clock time, so the tool subtracts the current time to give a
countdown.

**Decision 4. Write the result for a reader who cannot see SUMO.** At the same 1,805 s:

```text
E Fowler Ave & McKinley Dr at 1805 s: the signal changes in 30 s.
  NB: through red; left red; right red
  EB: through green
  WB: through green; left red
```

Outside the analysis hour (900 to 4,500 s), the first line also carries a WARM-UP or AFTER-PEAK warning, written by
the toolkit's `_period_note`.

**Decision 5. Write the description.** It says what the tool does, what the input means with an example, what each
word in the result means, the units, that it only reads, its caveats, and which tool to use instead for the whole
cycle:

```python
def get_signal_state(intersection: str) -> str:
    """What the signal at one intersection shows right now, movement by movement, and how long until it changes.
    intersection: cross streets, e.g. "Fowler & McKinley" (see list_intersections). Returns, for each approach
    (EB, WB, NB or SB, the direction of travel), the indication of its through, left and right movements: green;
    green but yield to conflicting traffic (a permissive left, for example); stop, then go if clear (right turn on
    red); yellow; or red. Then the seconds until the signal changes (a countdown, not a clock time). Reads only:
    time does not pass and nothing changes. A reading outside the analysis hour (900-4500 s) carries a WARM-UP or
    AFTER-PEAK warning. Use get_signal_plan for the whole cycle; this tool shows one moment of it."""
```

**Decision 6. Write the input rules.** One input, written with the toolkit's helpers:

```python
SCHEMA = _S(intersection=dict(_INT))
# {"type": "object",
#  "properties": {"intersection": {"type": "string",
#                                  "description": "Cross streets, e.g. \"Fowler & McKinley\" (see list_intersections)"}},
#  "required": ["intersection"]}
```

**Decision 7. Test every claim.** Each sentence of the description is a promise the model cannot check, so each one
gets a check in `check()`: every signal letter is reported under some movement; each approach's through indication
agrees with `get_approach_state`, an already-tested tool; the countdown lies between 0 and the longest phase; reading
lets no time pass; and a reading at 0 s carries the warm-up warning.

## 5. Writing the description

Answer these questions, in this order. Leave out any that do not apply.

1. **What it does, and when to use it.** Use the words an engineer would use. Name the tool to use instead when
   there is a better one.
2. **Each input.** What it means, its units, its allowed values, and an example (`"Fowler & McKinley"`, `EB`).
3. **What it returns, and in which units.**
4. **Every definition that has more than one version.** A queue (which speed and gap thresholds), delay (which
   vehicles count), speed (space-mean or time-mean), the peak (which hours). A model will pick one if you do not.
5. **When the answer is undefined or partial.** No vehicles on the block, warm-up, unfinished trips, teleports.
6. **What it changes.** Does it only read? Does it change the simulation? Does it let time pass?
7. **What it refuses, and why.** The rule and where it comes from (MUTCD, ITE, your agency).
8. **How much evidence is behind the answer.** One snapshot, one run, ten seeds; calibrated or not.

Three habits help:

- **Write only what you test.** A sentence that is not checked in `test_claims.py` is a guess, and the model will
  treat it as a fact.
- **Spend words on knowledge, not on politeness.** `get_approach_state`'s description is the longest in the toolkit,
  about 200 words, because it carries the queue rule, the spillback flag and the warnings. `list_intersections`
  needs about 65.
- **Use the names engineers use.** Cross streets, EB/WB/NB/SB, mph, ft, veh/mi/lane. Never make the model handle
  SUMO's internal ids.

`CONTRIBUTING.md` lists the same questions as a short checklist for pull requests.

## 6. Writing the result

SUMO hands back Python values. You can read bare values because the context is in your head: you wrote the call, you
know the units, and you know what time it is in the simulation. The model has only the text that comes back.

For example, behind one reading of Fowler Ave WB at 30th St, TraCI returned a time of `8100.0`, 23 lanes of vehicle
lists (21 of them empty), positions in meters from the start of each lane, speeds of `0.0`, the signal string
`'rryyrrrrrrrryyrrrrr'`, and a "mean speed" of 20.12 or 22.35 m/s on every empty lane, which is simply the speed limit.
`walkthrough/raw_vs_result.py` records all of it, next to the sentence the tool built from it.

Before you share a tool, read its result as if you could not see SUMO:

1. **Would a colleague know what each number measures, and in what units?** Write "back of queue 274 ft", not `83.5`.
2. **Does it state the verdict even when nothing is wrong?** Write "No spillback: the queue fills 9% of the
   storage", not silence. A model reads a missing flag as easily as a present one.
3. **Does it say when the reading cannot answer the question?** Warm-up, after the peak, an empty block, a teleport,
   one snapshot of a queue that rises and falls every cycle.
4. **If something failed, does it say what to do next, and who can do it?** See errors below.
5. **Is it short enough to be read again at every step?** Summarize; do not dump. One corridor call in this toolkit
   returns 217 tokens; the lane-by-lane survey it replaces would take 156 calls and 2,576 tokens.

What goes in the description, and what in the result? **Rules that never change** (the queue definition, the 85%
flag, input units) belong in the description. **Anything that depends on the state of the simulation** (the clock,
an empty block, a teleport, a failure) can only go in the result, because only the result knows the state.

The result does not have to be prose. JSON with clear field names works too, for example
`{"back_of_queue_ft": 274, "storage_ft": 2973, "verdict": "no spillback", "period": "after peak"}`. What matters is
that the result explains itself. This toolkit returns short sentences because they read like a briefing.

### Errors are results too

Return an error as text, starting with `Error:`, `Rejected:` or `Blocked:` (the MCP server marks these as errors for
the app). Say three things: what went wrong, who can fix it, and what to do next.

| Before | What the model did | After |
|---|---|---|
| `No live simulation. Call start_live first.` | Asked the engineer to start SUMO | `No live simulation is running. You can start one yourself: call start_live (no inputs needed), then advance past the 900-s warm-up, then call this tool again.` |
| TraCI's own `Could not connect in 1 tries` | Asked for the same window eight times | `sumo-gui needs a screen to open its window, and this computer has none. Call start_live again with gui=false...` |

### What a result should not do

Suggest how to get good evidence, not engineering decisions. "Advance to a time between 900 and 4,500 s" is fine.
"Retime this signal" is the engineer's call.

## 7. Building on SUMO's primitives, safely

**Pick the right primitive.**

- **TraCI** for one running simulation: vehicles, lanes, detectors and signals as they are now, and changes such as
  a new timing plan.
- **sumolib** for the network: names, lengths, lanes, connections, signal programs. No simulation needs to run.
- **SUMO's output files** (tripinfo, detectors, statistics) for whole-run results. The toolkit's study tools run
  complete simulations as separate processes and read these files.

**Know the traps.** These are tested in `test_claims.py`, so you can see each one happen:

- An empty lane's "mean speed" is its speed limit.
- Lane occupancy comes back as a fraction (0 to 1), although the docstring says %.
- `simulationStep(t)` runs to the absolute time t, and a time in the past does nothing.
- `setPhaseDuration` changes the current phase once; the next cycle is back to the plan.
- `sumolib.net.readNet` reads no signal plans unless you pass `withPrograms=True`.
- `--end` is ignored when TraCI drives SUMO.

Two more from traffic practice: vehicles waiting to enter at the network edge are not in the network yet, and a
teleport means something jammed for 300 s.

**Put the rules in the body, not only in the description.** `set_signal_timing` rejects any plan that breaks a
pedestrian or minimum-green rule and changes nothing. A rule written only as advice can be ignored; a check cannot.

**Keep decisions that belong to people out of the menu.** Approving a calibration is a command that only people run
(`python sumo_agent_tools.py approve ...`); it is not a tool, so no model can claim it.

**One run is not evidence.** A tool that compares plans should run several seeds and pair them, as `compare_plans`
does.

**Never print to standard output inside a tool.** Over MCP, standard output carries the protocol, and a stray
`print()` breaks it. Return text instead.

## 8. Add your tool to the toolkit

1. **Put the function in `sumo_agent_tools.py`.** Its docstring is the description. Use the helpers the other tools
   use: `_need_live()` for live tools, `_resolve()` for intersection names, `_period_note()` for the analysis-hour
   warning.
2. **Add its input rules to `SCHEMAS`**, for example `'get_signal_state': _S(intersection=dict(_INT)),`.
3. **If it only reads, add its name to `READ_ONLY`.** The MCP server then marks it read-only, so an app can let it
   run without asking each time.
4. **Add a test for each claim to `test_claims.py`:**

   ```python
   @claim('get_signal_state reports every movement and a countdown, and lets no time pass')
   def _():
       T.start_live()
       T.advance(1805)
       t = traci.simulation.getTime()
       txt = T.get_signal_state('Fowler & McKinley')
       assert 'changes in' in txt and traci.simulation.getTime() == t, txt
       return txt[:100]
   ```

5. **Run `python test_claims.py`.** Every claim must pass.
6. **Try it, three ways:**
   - By hand: `python -c "import sumo_agent_tools as T; T.start_live(); T.advance(1805); print(T.get_signal_state('Fowler & McKinley'))"`
   - With a small model on your own computer: add the tool's name to `MENU` and write your question in `QUESTION`
     at the top of `walkthrough/qwen_harness.py`, then run `python walkthrough/qwen_harness.py`. It needs
     `pip install torch transformers`, about 4 GB of memory, and no GPU. Read the saved JSON to see every step.
   - With Claude Code or Claude Desktop: nothing to add. `mcp_server.py` serves every tool in `TOOLS`. See
     `README.md` to connect it.
7. **Open a pull request** and say what traffic knowledge your tool adds and how the tests show it
   (`CONTRIBUTING.md`). To add tools as your own folder instead of changing `sumo_agent_tools.py` (Assignment 5.1),
   follow `contrib/README.md`: the same steps, with `contrib/agent_loop.py` to record the whole loop.

## 9. Watch a model use your tool, and fix what you see

Run a model on a real question and read what it did. Each failure points to a place to fix:

| What you see | Where to fix it |
|---|---|
| The model never calls your tool | The description: say what the tool is for and when to use it |
| It calls with the wrong inputs (ids, wrong units, a clock time for a duration) | The input descriptions and ranges, and an error that says what to send |
| It calls tools in the wrong order, such as reading before starting SUMO | An error that says what to do first |
| It asks the person to do something it could do itself | An error that says "you can do it yourself"; a prompt that says who calls the tools |
| It repeats the same failing call | An error that says something it can act on |
| It concludes something the numbers do not support | The result: the verdict either way, and warnings when the reading cannot answer the question |
| It answers from weak evidence, such as one snapshot or the wrong hour | The result: say how much evidence it is; or write a tool that measures over the period |

Fix the tool first: a better tool helps every model and every harness. The walkthrough shows eight recorded runs,
each with the fix that followed (`walkthrough/README.md`).

## 10. Ideas for your first tool

The traffic knowledge is the hard part of each of these. The Python is the easy part.

- **Worst queue during the analysis hour.** Read the back of queue at the end of every red and report the worst one,
  with its time. One reading is a snapshot; this tool would measure the peak.
- **Level of service for an approach.** Control delay over the analysis hour, the HCM level, and how many vehicles
  and seeds stand behind it.
- **Travel-time reliability on the corridor.** The median and 95th-percentile travel time from vehicles that drove
  the whole corridor, with how many trips that is.
- **An incident.** Close a lane for a period, then report the change in queue and travel time against the same seeds
  without the closure.
- **Detector health.** Compare a detector's counts with the field counts at its station, and say whether it can be
  trusted.
- **A run id from `start_live`.** The MCP specification advises tools to hand back an id when state lasts between
  calls, and later calls to pass it back.

## 11. Measure what your work is worth: the ablation

A tool is a claim that the agent does the task better with it. Writing your knowledge into the description and the
result is a second claim: that the words the model reads matter, not only the code. `contrib/ablation.py` tests each
claim with one comparison, on your own three questions:

- **With and without your tools** (A vs. C): the toolkit alone, then your tools as written.
- **With and without the knowledge in what the model reads** (B vs. C): your tools find the same data both times,
  but in B the description is plain (`PLAIN_DESCRIPTIONS`), the result is raw (`RAW_RESULTS`), and your server
  instructions are left out.

In the worked example (`examples/ablation/`, the template's `lane_use`), the tool helped on one question of three,
and that one shows the knowledge in the result at work: with the raw result the model listed the lanes in SUMO's
order and missed the warm-up; with the written result it gave the lanes from the median, by movement, with the
warning. On the other two questions the model took `get_approach_state` even with the full description.

Give each question a `setup` in `ablation/tasks.json` that starts the simulation and advances it to the time the
question is about. Without it, a small model spends its turns starting and advancing the simulation, and the runs
say little about your tools.

Write the questions and their right answers before you look at any run, and check each right answer against the
data. When a result goes against you, it is still a result: read the answers to find out why.

Questions and ideas are welcome as issues on this repository.
