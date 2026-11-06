# SUMO tools for AI agents

SUMO tools that an AI agent can call, written the way a traffic engineer would write them, with tests for every
claim their descriptions make. Built for **AI for Mobility** (CGN 6933, University of South Florida), and open for
anyone who wants to give an AI agent a traffic simulator.

**Read first:** the companion page, [`docs/index.html`](docs/index.html) (download it and open it in a browser). It
shows each tool twice, once with the description copied from SUMO's API docs and once written by a traffic engineer,
and measures the difference on a real network.

**Want to write your own tool?** Start with [`WRITING_TOOLS.md`](WRITING_TOOLS.md), a guide for traffic engineers
who know SUMO but are new to AI. It builds one tool step by step, from a raw TraCI call to a tested tool a model can
use ([`examples/get_signal_state.py`](examples/get_signal_state.py)).
Then add yours as a folder, `contrib/<your-github-username>/`, sent as a pull request: see
[`contrib/README.md`](contrib/README.md). Students in AI for Mobility: this is Assignment 6.
`contrib/agent_loop.py` runs a model on your computer and saves the whole tool-calling loop, MCP messages included.

**Checking a whole study?** [`CHECKS.md`](CHECKS.md) explains `check_study.py`. It reads the log of a run and checks it
twice: sanity checks on the log (a gate sends failures back to the model before the answer goes out), and theory
checks (HCM capacity, queueing) on its own replay of the run in SUMO, reported to the engineer.

## Why traffic knowledge belongs in the tool

The model never reads your code. It reads a tool's name, its description, its inputs and the text that comes back.
SUMO's documentation can tell an AI which function to call. It cannot tell it that a speed means nothing on an empty
road, what counts as a queue, that vehicles waiting outside the network still count, or that one run is not
evidence. Measured on the Fowler Avenue scenario in this repository:

| What a traffic engineer knows | What happened when a tool left it out |
|---|---|
| Speed is undefined at zero density | Averaging lane speeds gave 32 mph; the vehicles themselves averaged 7 mph (empty lanes report their speed limit) |
| A queue needs a definition | SUMO's helper placed a 20.7-m detector on an approach whose queue reached 2,079 ft |
| Every vehicle counts | The delay of finished trips hid 24% of the delay at today's demand and 50% at 1.6 times the demand |
| Timing rules are rules | Webster's plan as SUMO's script writes it cut delay by 82% while breaking 44 timing minimums, 19 at crosswalks |
| One run is not evidence | After the check the gain was 5% (10 paired seeds); single unpaired runs pointed the wrong way 15% of the time |
| Calibrate before you compare | Three demands built from the same counts passed GEH < 5 at 6, 13 and 15 of 16 stations |
| Name things the way engineers do | One corridor call: 217 tokens; the lane-by-lane survey it replaces: 156 calls and 2,576 tokens |

## Quick start

```
pip install -r requirements.txt
python test_claims.py                      # about a minute; every claim should pass
python sumo_agent_tools.py demo            # a short tour of the tools
```

Connect the tools to Claude (no API key needed):

- **Claude Code:** `claude mcp add sumo -- python /full/path/to/mcp_server.py`
- **Claude Desktop:** Settings > Developer > Edit Config, then add
  `{"mcpServers": {"sumo": {"command": "python", "args": ["/full/path/to/mcp_server.py"]}}}`

Then ask, for example: *"Is Fowler Ave WB at 30th St spilling back during the PM peak? Use the SUMO tools."* or
*"Find a better timing plan for the corridor."* and watch what the tools refuse.

`compare_plans` will not run until an engineer approves the calibration. Approving is a command for people, not a
tool the model can call: `python sumo_agent_tools.py approve demand "Your Name"`.

## The scenario

Fowler Avenue along the USF Tampa campus, from west of N 30th St to east of USF Bull Run Dr: 124 road segments,
372 lanes, 6 signals.

- **Real network:** an OpenStreetMap extract (downloaded Nov 3, 2026), converted with netconvert the way
  OSMWebWizard does it. Signal timing is netconvert's guess, not the agency's plan.
- **Synthetic demand:** a hidden "true" demand plays the real world (`fowler/truth.rou.xml`), and 16 count
  stations measure it (`fowler/field_counts.xml`). Because the truth is known, every step can be graded. For a real
  study, replace the field counts with agency counts.
- Each run is a 15-minute warm-up, the PM peak hour (900-4,500 s), and 15 minutes for the network to drain.

## Files

| File | What it does |
|---|---|
| `sumo_agent_tools.py` | The engineer-shaped toolkit: 12 tools (8 live through TraCI, 4 study tools that run whole simulations), their descriptions (docstrings), JSON schemas (`TOOLS`) and `run_tool`, the harness side. |
| `api_shaped_tools.py` | The comparison case: thin wrappers whose descriptions are TraCI's and sumolib's own docstrings. |
| `mcp_server.py` | Serves the toolkit over MCP (stdio) for Claude Code or Claude Desktop. |
| `build_fowler.py` | Builds `fowler/`: the network, count stations, the hidden demand, the field counts and three rebuilt demands (`demand`, `demand_lp`, `random`). Downloads the OSM extract if it is missing. |
| `test_claims.py` | Tests every claim the descriptions make, and six traps in the API docstrings, against SUMO. |
| `check_study.py`, `CHECKS.md` | Checks a whole study from its log before the answer goes out: sanity checks for the model (`gate`), theory and replay checks for the engineer. |
| `test_check_study.py` | Gives every check in `check_study.py` a case it must fail and a run it must pass (about 3 minutes). |
| `experiments.py` | Produces `numbers_sumo_tools.json`, every number on the companion page (about 15 minutes). |
| `gui_view.py`, `timing.py` | The sumo-gui screenshots (the TMC view) and run times with and without the window. |
| `build_companion.py`, `companion_template.html` | Build the companion page from the numbers; the build fails if a number is missing. |
| `numbers_sumo_tools.json`, `claims_result.json` | The measured numbers and the claim results the page is built from. |
| `docs/index.html` | The companion page. |
| `WRITING_TOOLS.md` | How to turn traffic knowledge into a tool: descriptions, results, SUMO traps, tests, and how to watch a model use it. |
| `examples/get_signal_state.py` | The guide's worked example: one TraCI call as an API wrapper and as an engineer's tool, with a test for each claim. |
| `walkthrough/` | How a model calls these tools, step by step: a small Qwen harness, eight recorded runs on a laptop-size model (the last one with a gate before the answer), a reference run with no model, and every MCP message between a client and `mcp_server.py` ([walkthrough/README.md](walkthrough/README.md)). |

Rebuild everything:

```
python build_fowler.py
python test_claims.py
python experiments.py                      # sumo-gui needs a screen, or xvfb-run on a server
python experiments.py e2b
python build_companion.py docs/index.html
```

## Things to know

- Tested with SUMO 1.28.0. Other versions can change the numbers; the claim tests will tell you.
- The timing rules (7-s through green, 5-s left turn, a 7-s walk plus crossing width at 3.5 ft/s, ITE yellow with
  t = 1 s and a = 10 ft/s², cycle at most 180 s) are examples. Use your agency's standards.
- The network has no sidewalks, so a crosswalk is assumed on every leg that netconvert's own plan stops at some point.
- Over MCP, stdout carries the protocol. `mcp_server.py` sends tool printing to stderr, and `start_live` sends
  SUMO's console text to the null device. The server also publishes the toolkit's own schemas, passes each tool's
  error text on to the model, and flags refusals ("Rejected", "Blocked", "Error") with `isError`; the MCP library
  would otherwise do none of these (`walkthrough/mcp_trace.py` shows the messages). Keep it that way if you add tools.
- `runs/` holds every simulation's output and is not tracked; delete it freely.

## Contributing

New tools, new scenarios and better descriptions are welcome. Read [CONTRIBUTING.md](CONTRIBUTING.md): the one rule
is that every claim a description makes comes with a test.

## Licenses and credit

- Code: MIT ([LICENSE](LICENSE)).
- `fowler/` is derived from OpenStreetMap data, © OpenStreetMap contributors, and is available under the Open
  Database License ([DATA_LICENSE.md](DATA_LICENSE.md)).
- SUMO is developed by the German Aerospace Center (DLR) and others under the Eclipse Public License 2.0; this
  repository uses it as a dependency and does not include it.
- Course: AI for Mobility (CGN 6933), University of South Florida, Hao Zhou. The agents unit follows the flow of
  CMU 11-768 *AI Agents* (Daniel Fried and Graham Neubig), rebuilt for transportation.
