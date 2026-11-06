# Checking a whole study: `check_study.py`

The tools in `sumo_agent_tools.py` check one result at a time, as they write it: a warm-up warning, a verdict
either way, a rejected timing plan. Some checks need all the results of a study at once. Did the agent read during
the peak at all? Do the vehicle counts add up across calls? Does the answer agree with its own readings? Does the
evidence agree with traffic flow theory? No single tool sees all of that. The harness does, because it keeps the
log of every call. `check_study.py` reads that log.

| | Sanity checks | Theory and replay checks |
|---|---|---|
| Reads | the log only | the log, plus its own replay of the run in SUMO |
| Time | under a second | about a minute (one SUMO run) |
| A failure means | the evidence is missing or wrong | a question for the engineer |
| Goes to | the model, through the gate, before the answer goes out | the engineer, in the report |
| Status | PASS / FAIL / N/A | PASS / EXPLAIN / FAIL / N/A |

The gate sends back what evidence is missing, never what the answer should be. The theory and replay checks know
more (they measured every second of the hour), so they go to the engineer instead.

## The checks

| Check | What it tests | The knowledge behind it |
|---|---|---|
| `period` | at least one reading is inside the analysis hour (900–4500 s) | warm-up and after-peak traffic say nothing about the peak |
| `repeats` | each approach read at least 3 times inside the hour, 5+ min apart | a queue at a signal rises and falls every cycle |
| `ledger` | the advance ledgers chain and add up (start = last end; change = entered − left) | conservation of vehicles |
| `teleports` | no teleports, and no more than 20 vehicles stuck at the network edge | a teleport means a 300-s jam; stuck vehicles mean less demand got in |
| `physics` | each reading is possible: queue within the block, density below jam (215 veh/mi/lane), speed under 1.25 × the limit, the queued vehicles fit the queue length, the printed share matches | jam spacing 7.5 m; the E2 queue rule (5 km/h, 10 m) |
| `answer` | the answer's yes/no agrees with its own readings (flag at 85% of storage) | the toolkit's spillback definition |
| `compare` | a claim that one plan is better rests on `compare_plans`, not one live run | one run of each plan pointed the wrong way 15 times in 100 here |
| `replay` | the checker's rerun (same demand, seed and signal changes) reproduces every ledger and reading in the log | SUMO is deterministic: if the rerun differs, the log is not what it says |
| `whole hour` | the answer's verdict holds for the longest queue of every cycle of the hour, measured every second | the snapshot problem, solved by measuring everything |
| `capacity` | per lane group: demand, HCM capacity c = 1,900 × lanes × g/C (4 s lost per phase), X = demand / c; no group serves more than 1.1 c | HCM; X > 1 means the queue cannot clear |
| `queue growth` | with X > 1, the cycle-longest queue grows at (demand − served) × 7.5 m / lanes per hour, within 30%; otherwise it should not grow | deterministic queueing (input–output) |

The theory checks measure with the checker's own loop detectors at the stop line and each vehicle's route, not
with the tools' readings.

## Run it

```
python check_study.py walkthrough/qwen_run_G.json              # the full report (about a minute)
python check_study.py walkthrough/qwen_run_G.json --no-replay  # sanity checks only
python check_study.py walkthrough/qwen_run_G.json --json out.json
python walkthrough/reference_run.py                            # the study done the careful way, no model
python test_check_study.py                                     # every check against its known-bad case
```

A log is the walkthrough format (`walkthrough/qwen_run_*.json`) or
`{"question": ..., "answer": ..., "calls": [{"name": ..., "arguments": ..., "result": ...}]}`, which any harness
(an MCP client included) can write.

## In a harness

```python
import check_study
feedback = check_study.gate({'question': q, 'answer': reply, 'calls': calls_so_far})
if feedback:                       # a sanity check failed
    messages.append({'role': 'user', 'content': feedback})   # back to the model, instead of the answer
```

`walkthrough/qwen_harness.py H` is run G with this gate (see `walkthrough/README.md`).

## What it finds on the recorded runs

| Run | Sanity checks | Theory and replay checks |
|---|---|---|
| G (Qwen3-1.7B, "no spillback") | FAIL `period`, `repeats`: one reading, at 8,100 s | the verdict is right for the hour (worst cycle 70%), by luck; the left turn is over capacity and the answer does not say so |
| F (Qwen3-1.7B, "spilling back") | also FAIL `answer`: "spilling back" from a 9% reading | the hour says no spillback: the answer is wrong |
| C (Qwen2.5-1.5B, a reading at 0 s) | FAIL `period`, `repeats` | (no advance, nothing to replay past 0 s) |
| reference (no model) | all pass | the left turn is over capacity, which the answer does not say |

What the theory checks found on Fowler Ave WB at 30th St (demand "demand", seed 1): the through movement uses 13% of
its capacity (X = 0.13), but the left turn gets 6 s of green per 90-s cycle: demand 185 veh/h, HCM capacity 148,
X = 1.25. Its queue grows all hour, single file in the left lane: queueing theory predicts 638 m/h, the replay
measures 556 m/h (87%). It reaches 70% of the storage at 4,489 s and would reach 85% about 15 minutes later. So "no
spillback in the peak hour" is true for this run, but only because the peak ended. With a queue all hour, the left
turn served 100 veh/h in SUMO, 68% of HCM's 148: the simulated drivers get fewer cars through a short green than HCM
assumes.

## Writing your own check

1. Decide first whether it must pass (the evidence is wrong or missing) or must be explained (theory disagrees,
   and the disagreement may be the finding).
2. Give it a case it must fail before you trust it to pass anything: change one number in a good log, or use a
   recorded run that went wrong. `test_check_study.py` does this for every check.
3. Do not tune a threshold until a run passes. Set it from the knowledge (HCM, MUTCD, your agency's standards)
   and write down where it came from.
4. A message to the model names the missing evidence and what to do, never the answer.
5. Keep every check run in the log, not only the last one: an agent can rerun until it passes.

## Limits

- `spill_claim` reads the answer's verdict with a simple rule (the last sentence that mentions spillback; a
  negation before the word means no). The engineer reads answers better than it does.
- The capacity check uses the HCM base saturation flow with no adjustments (lane width, heavy vehicles, turning
  radius) and treats every green as protected.
- The replay needs the same SUMO version (1.28.0) and the same scenario files; it replays the last simulation in
  the log, and measures the approaches read with `get_approach_state`.
- The checks are written for the walkthrough's kind of question (queues and spillback on an approach); a corridor
  travel-time or plan-comparison study needs checks of its own.
