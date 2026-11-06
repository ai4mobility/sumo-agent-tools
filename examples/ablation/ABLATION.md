# Ablation: what my tools and my traffic engineering knowledge change

*Run `python contrib/ablation.py contrib/<you>`: your three questions, each asked in three setups, 9 runs. It
writes every answer to `ablation/answers.md`. Read them, then fill in this page yourself, in your own words.*

The three setups:
- **A. Without your tools:** the toolkit's tools only.
- **B. Your tools, plain:** your tools find the same data, but the description is the plain one
  (`PLAIN_DESCRIPTIONS`), the result is raw (`RAW_RESULTS`), and your server instructions are left out.
- **C. Your tools as written.**

## Results

<!-- Copy the table that ablation.py printed. In each cell write right, partly or wrong, then why in a few words
(for example: "wrong: says the lanes are open"). The right answers are in ablation/tasks.json. -->

| Question | A. Without your tools | B. Your tools, plain | C. Your tools as written |
|---|---|---|---|
| pine_queue_lane | wrong: called get_approach_state and gave the approach's queue (16 vehicles), not which lane | wrong: the same; did not call lane_use | wrong: the same; did not call lane_use even with my description |
| pine_empty_speed | wrong: "2 mph", the speed of the approach's queue | wrong: "2 mph", the same | wrong: "37 mph", read from the westbound corridor |
| mckinley_warmup | partly: says it is the warm-up, but reads the corridor block by block, not the lanes | partly: the counts are right, but lanes by SUMO index with no movements, and "not good for the peak hour" because of halting vehicles, not the warm-up | right: median to curb, each lane named by movement, the lane with no movement, and the warm-up warning |

Model Qwen3-1.7B, thinking off, seed 1. The harness started the simulation and advanced it (1,800 s or 300 s)
before each run. Right answers: A 0 of 3, B 0 of 3, C 1 of 3.

## What my tools changed

<!-- A vs. C, at least 60 words, naming a question by its id. Without your tools, what did the model call and what
did it get wrong? What did your tool change? -->

Only mckinley_warmup reached lane_use in C, and there it gave the answer the question asks for, lane by lane:
"Left-turn lane (lane 1, median side): 1 vehicle, 1 stopped", then the lane with no movement and the three through
lanes. A read get_corridor_state block by block instead, so it never said what each lane does. On pine_queue_lane
and pine_empty_speed my tool changed nothing: in all three setups the model called get_approach_state (or
get_corridor_state) and answered from the whole approach. The question asks which lane, but the model took the tool
whose description talks about the queue. My description of lane_use does not say "use this for which lane holds the
queue", and it should.

## What the transportation knowledge changed

<!-- B vs. C, at least 60 words, naming a question by its id. Your tool found the same data in both. Which sentence
of your description, or which part of your result, made the difference? Quote it. If B did as well as C, why? -->

On mckinley_warmup the model called lane_use in both B and C, so it had the same data, and only the wording differed.
B got raw JSON: lanes by SUMO index (0 is the curb), connection codes, speeds in m/s, and no warning. The model listed
"Lane 0" to "Lane 5" in SUMO's order, could not say which lane turns left, and called the reading not good for the
peak hour "due to the presence of halting vehicles". C's result says "Lanes from the median (left) to the curb
(right)", names each lane by its movement, and carries "WARM-UP WARNING: 300 s is before the analysis hour". The
model repeated all three. Here the knowledge in the result made the difference, not the description: in B the model
picked the tool anyway.
