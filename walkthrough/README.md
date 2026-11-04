# Walkthrough: how a model calls a SUMO tool

The recorded runs behind the handout *How a Model Calls a SUMO Tool, Step by Step* (AI for Mobility, Module 5).
They follow one question, "Is Fowler Ave westbound at 30th St spilling back during the PM peak hour?", through the
tool-calling loop: the prompt, the model's tool call, the harness's checks, the tool running SUMO through TraCI, the
result going back, and the answer.

| File | What it is |
|---|---|
| `qwen_harness.py` | A complete harness in about 260 lines: it renders the prompt with Qwen's chat template, lets the model write, finds and checks each `<tool_call>`, runs the tool with `run_tool` (counting every TraCI call), sends the result back, and repeats. |
| `qwen_run_A.json` ... `qwen_run_G.json` | The seven recorded runs: every prompt's size, every reply word for word, each check, each result, the TraCI calls per tool, and the times. The first and last prompts are saved in full. |
| `qwen3_run_gui_log.txt` | A Qwen3-1.7B run recorded before `start_live` learned to refuse `gui=True` on a computer without a screen. |
| `mcp_trace.py`, `mcp_trace.json`, `mcp_trace.jsonl` | Every MCP message between a test client and `../mcp_server.py` (no model involved). |
| `raw_vs_result.py`, `raw_vs_result.json` | Everything TraCI returned for the reading in round 8 of run G, next to the sentence `get_approach_state` built from it. |
| `summarize_runs.py`, `walkthrough_numbers.json` | One line per step for every run, and the numbers the handout quotes. |

```
pip install torch transformers            # a CPU is enough: 3.5-4 GB of memory in bfloat16
python walkthrough/qwen_harness.py        # run G; downloads Qwen3-1.7B the first time (about 4 GB)
python walkthrough/qwen_harness.py A      # any of A-G
python walkthrough/mcp_trace.py
python walkthrough/raw_vs_result.py
python walkthrough/summarize_runs.py
```

## The runs

Each run fixed what went wrong in the one before. `qwen_harness.py` puts back the tool texts an earlier run saw, so
every run can be made again with today's code.

| Run | Model | What happened | Fix for the next run |
|---|---|---|---|
| A | Qwen2.5-1.5B-Instruct | Got "No live simulation. Call start_live first." and asked the engineer to start SUMO | The error says the model can start it itself |
| B | Qwen2.5-1.5B-Instruct | Said it would start SUMO itself, then gave the engineer a list of steps | The prompt says the engineer cannot call the tools |
| C | Qwen2.5-1.5B-Instruct | Read the queue at 0 s on an empty network and answered "not spilling back" | Readings before 900 s carry a WARM-UP WARNING |
| D | Qwen2.5-1.5B-Instruct | Understood the warning, then asked the engineer whether to go on | The engineer answers once (run E) |
| E | Qwen2.5-1.5B-Instruct | After the engineer's "Yes, go ahead", asked `advance(4500)` to reach "the point where the analysis hour begins" (it begins at 900 s); the harness refused anything over 3,600 s; then the model wrote the next call as prose | A different model |
| log | Qwen3-1.7B | Asked for sumo-gui on a server; after TraCI's "Could not connect" it asked again, eight times in all | `start_live` says to use `gui=false` |
| F | Qwen3-1.7B | Read the queue at 8,100 s, after the peak, and answered "is spilling back" for 9% of the storage | The verdict is stated either way; AFTER-PEAK WARNING |
| G | Qwen3-1.7B | Same calls; answered "no spillback" and mentioned the warning | Open: read during the analysis hour |

Recorded on November 4, 2026, on a 2-core Intel Xeon cloud CPU with no GPU: SUMO 1.28.0, PyTorch 2.15.0 (CPU),
transformers 5.22.1, greedy decoding. Times will differ on your machine. Replies should repeat with the same versions;
other versions or hardware can change a reply, and with it the rest of the run.

## What the MCP trace found

The first traces showed three problems in `mcp_server.py`, all fixed: the MCP library replaced a tool's error text
with "Error executing tool <name>"; it published schemas built from Python type hints alone (no ranges, no allowed
values); and refusals such as "Rejected: seconds must be 1-3600." came back with `isError: false`. The server now
passes errors on as `ToolError`, publishes the toolkit's own schemas, and flags results that start with "Rejected",
"Blocked" or "Error". The library still does not enforce the schema's ranges: the tools check their own inputs.
