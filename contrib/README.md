# Contributing your tools

Each contribution is one folder, `contrib/<your-github-username>/`, sent as one pull request. It holds tools an AI
agent can call, written the way a transportation engineer would write them, with the tests that hold them, an MCP
server that serves them, and the record of a model using them. Students in AI for Mobility (CGN 6933, USF) send
theirs for Assignment 5.1; anyone else is welcome too.

| File | What it holds |
|---|---|
| `DESIGN.md` | **in your own words:** (1) the task you ask the agent to do; (2) the tools you designed for it, and why each is useful; (3) how each description helps the model pick the right tool; (4) how each result helps the model read it correctly |
| `tools.py` | at least two new tools (functions with type hints, `-> str` and a description), `TOOLS`, `READ_ONLY`, a `*_plain` baseline, and `PLAIN_DESCRIPTIONS` and `RAW_RESULTS` for the ablation |
| `test_tools.py` | a test for every rule in `KNOWLEDGE.md`, and `test_plain_vs_<tool>` |
| `KNOWLEDGE.md` | the knowledge card: each rule with its source and its test, plain vs. yours, what the data cannot tell, AI use |
| `server.py` | the MCP server: the toolkit's tools and yours, with read-only tools marked |
| `AGENT_RUN.md` and `runs/` | three questions run through `agent_loop.py`, their transcripts, your grade of each answer, and one fix |
| `ablation/tasks.json`, `ABLATION.md` | the ablation: three questions with their right answers; your grade of each answer `ablation.py` collected (the agent without your tools, with your tools but plain descriptions and raw results, and with your tools as written); and, **in your own words**, the two comparisons |

`_template/` is a complete example of every file except `AGENT_RUN.md` and `ABLATION.md`, which you fill in from your own runs. It has one tool (`lane_use`); yours
needs at least two. Keep its shape, not its content: the checker refuses the template's tool and test names.

## Steps

1. **Fork and clone.** On GitHub, press Fork on https://github.com/ai4mobility/sumo-agent-tools. Then, in a terminal:
   ```
   git clone https://github.com/<your-github-username>/sumo-agent-tools.git
   cd sumo-agent-tools
   pip install -r requirements.txt
   python test_claims.py                  # about a minute; every claim should pass
   ```
2. **Copy the template** to a folder named after your GitHub username, in lowercase:
   ```
   cp -r contrib/_template contrib/<your-github-username>
   ```
3. **Write down the task and the tools first,** before any code: sections 1 and 2 of `DESIGN.md`, in your own
   words. Then write the rules in `KNOWLEDGE.md`: each rule is something a transportation engineer knows, with a
   source you can cite (a manual, a standard, a paper, the data itself, or field practice you can describe).
4. **Write the plain version, then yours,** in `tools.py`. [`WRITING_TOOLS.md`](../WRITING_TOOLS.md) explains the
   description, the result, errors, and the plain version. AI may write the code, but the words the model reads,
   the descriptions and the result text, are your design. Explain them in sections 3 and 4 of `DESIGN.md`.
5. **Test every rule** in `test_tools.py`, on one live simulation (demand `demand`, seed 1; the template's `at()` starts it), so everyone gets the same answers:
   ```
   python contrib/<you>/test_tools.py
   ```
6. **Serve them over MCP** with `server.py`: your tools next to the toolkit's, with the right annotations and
   instructions.
7. **Watch a model use them.** `agent_loop.py` runs Qwen3 on your computer (no key; a CPU is enough; the first run
   downloads about 4 GB) and saves the whole loop:
   ```
   pip install torch transformers
   python contrib/agent_loop.py contrib/<you>/server.py "your question" --name q1
   ```
   Run three questions, read the transcripts in `contrib/<you>/runs/`, make one fix, and fill in `AGENT_RUN.md`.
   Then update sections 3 and 4 of `DESIGN.md` with what the transcripts showed. Section 3 quotes each tool's
   description, and section 4 quotes a result your tools returned in these runs, word for word.
8. **Run the ablation: two comparisons.** With and without your tools: does the agent do the task better? With and
   without the transportation knowledge in your descriptions and results: does that knowledge matter? First write
   three questions in `ablation/tasks.json`, each with its right answer and where you checked it, before you run
   anything. In `tools.py`, write `PLAIN_DESCRIPTIONS` (each description as any programmer would write it) and
   `RAW_RESULTS` (each tool's same data, returned raw); the template shows both. Then:
   ```
   python contrib/ablation.py contrib/<you>
   ```
   It asks each question in three setups: A without your tools; B your tools, with the plain description and the
   raw result; C your tools as written. That is 9 runs, and it writes every answer to `ablation/answers.md`. Grade
   each answer in the table in `ABLATION.md` (right, partly or wrong, and why), then write the two comparisons:
   A vs. C and B vs. C. Give each question a `setup` in `tasks.json`: the calls that start the simulation and
   advance it to the time you ask about. The harness makes them before the model's first turn, so the runs test
   your tools, not how a small model handles the simulation (the template shows how). On a 2-core computer with no
   GPU, the template's 9 runs (`examples/ablation/`) took 13 minutes. It can be stopped and resumed.
9. **Check, then open the pull request:**
   ```
   python contrib/check.py contrib/<you>
   git checkout -b <you>-tools
   git add contrib/<you>
   git commit -m "Add <your tools> (<one line on the knowledge they add>)"
   git push -u origin <you>-tools
   ```
   GitHub then offers "Compare & pull request". Open it against `main` of ai4mobility/sumo-agent-tools, and fill in the form.
   The workflow runs `check.py` again. A first-time contributor's workflow waits until a maintainer approves it.
10. **Answer the review.** Push more commits to the same branch; the pull request updates itself.

## Rules for a pull request

- One folder, `contrib/<your-github-username>/`, and nothing outside it. A fix to the toolkit is welcome as a
  separate pull request.
- No file over 1 MB, no data you do not have the right to share, and no keys, tokens or passwords.
- Every rule in the knowledge card has a test, and every test passes. A description is a promise to the model, and
  the model cannot check it.
- `DESIGN.md`, and your grades and comparisons in `ABLATION.md`, are your own writing, not an AI's: they are where your
  transportation knowledge and your thinking show.
  AI may help with everything else. Say in `KNOWLEDGE.md` which AI tools you used and for what; the rules, the
  sources and the expected answers in the tests must be ones you checked yourself.
