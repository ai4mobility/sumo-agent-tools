# An example run of contrib/agent_loop.py

`example_pine.md` is one question run through the whole loop with the template's server
(`contrib/_template/server.py`), which serves the toolkit's tools and the template's `lane_use`:

    python contrib/agent_loop.py contrib/_template/server.py \
      "In the Fowler Ave simulation, 1,800 s after the start, which southbound lane at Bruce B Downs & USF Pine Dr is holding the queue?" \
      --name example_pine

Qwen3-1.7B, thinking on, seed 1, on a 2-core cloud CPU with no GPU: five model turns, four tool calls, 9.8 minutes
in all. `example_pine.json` holds the same run in full.

What happens, turn by turn:

1. The model calls `lane_use` at once. No simulation is running, so the server answers with the toolkit's error,
   flagged `isError`: "No live simulation is running. You can start one yourself: call start_live (no inputs
   needed), then advance past the 900-s warm-up, then call this tool again."
2. The model reads the error in its reasoning and calls `start_live` itself, instead of asking the person to.
3. It calls `advance(1800)`: the result is the vehicle ledger at 1,800 s, inside the analysis hour.
4. It calls `lane_use` again and gets the five lanes from the median to the curb.
5. It answers.

Grade the answer yourself before you read on. "Lane 1 (median side) is holding the queue, 6 vehicles, 6 stopped" is
right, but the model never says it is the left-turn lane, and it calls lanes 2 and 3 empty through lanes: lane 2
serves no movement, and the empty through lanes are 3 and 4. Partly correct. The model also never called
`stop_live`; the simulation closed when the harness stopped the server.
