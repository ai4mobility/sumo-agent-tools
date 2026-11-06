# An example ablation

A real run of `contrib/ablation.py` on a copy of the template (`contrib/_template/`, with its one tool, `lane_use`),
made as `contrib/sumo-check/`. The copy is not in `contrib/`; its code is the template's.

    python contrib/ablation.py contrib/sumo-check        # 3 questions x 3 setups = 9 runs

Qwen3-1.7B, thinking off, seed 1, on a 2-core cloud CPU with no GPU: 13 minutes in all. Each question has a
`setup` in `tasks.json`: the harness starts the simulation and advances it before the model's first turn.

| Setup | Right answers (graded by hand) |
|---|---|
| A. Without lane_use (the toolkit only) | 0 of 3, and 1 partly |
| B. lane_use with a plain description and a raw result | 0 of 3, and 1 partly |
| C. lane_use as written | 1 of 3 |

The files, as they were in the copy (its `ablation/runs/` is `runs/` here):
- `tasks.json`: the three questions, their right answers and their setup, written before the run
- `answers.md`: every answer, with the tools each run called (written by `ablation.py`)
- `ABLATION.md`: the grades and the two comparisons, written as a student would
- `runs/`: one file per run: the descriptions the model saw, its calls with their results, and its answer

Two things are worth noticing. On the two Pine questions the model never called `lane_use`, even with its full
description: it took `get_approach_state` every time, so the description has work to do. And on `mckinley_warmup`
the model called `lane_use` in both B and C, so the same data came back in two forms. With the raw result it listed
the lanes in SUMO's order and missed the warm-up; with the written result it gave the lanes from the median, by
movement, with the warning. That difference is the knowledge in the result.

An earlier run without `setup` took 33 minutes, and the model spent most of its turns starting and advancing the
simulation: of the six runs that had `lane_use` (B and C), four never reached it.
