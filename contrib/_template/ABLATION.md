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
| pine_queue_lane | ? | ? | ? |
| pine_empty_speed | ? | ? | ? |
| mckinley_warmup | ? | ? | ? |

## What my tools changed

<!-- A vs. C, at least 60 words, naming a question by its id. Without your tools, what did the model call and what
did it get wrong? What did your tool change? -->

TODO

## What the transportation knowledge changed

<!-- B vs. C, at least 60 words, naming a question by its id. Your tool found the same data in both. Which sentence
of your description, or which part of your result, made the difference? Quote it. If B did as well as C, why? -->

TODO
