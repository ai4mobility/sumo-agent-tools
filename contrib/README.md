# Contributing your tools

Each contribution is one folder, `contrib/<your-github-username>/`, sent as one pull request. It holds tools an AI
agent can call, written the way a transportation engineer would write them, with the tests that hold them, an MCP
server that serves them, and the record of a model using them. Students in AI for Mobility (CGN 6933, USF) send
theirs for Assignment 6; anyone else is welcome too.

| File | What it holds |
|---|---|
| `tools.py` | at least two new tools (functions with type hints, `-> str` and a description), `TOOLS`, `READ_ONLY`, and a `*_plain` baseline |
| `test_tools.py` | a test for every rule in `KNOWLEDGE.md`, and `test_plain_vs_<tool>` |
| `KNOWLEDGE.md` | the knowledge card: who the tools are for, each rule with its source and its test, plain vs. yours, what the data cannot tell, AI use |
| `server.py` | the MCP server: the toolkit's tools and yours, with read-only tools marked |
| `AGENT_RUN.md` and `runs/` | three questions run through `agent_loop.py`, their transcripts, your grade of each answer, and one fix |

`_template/` is a complete example of every file except `AGENT_RUN.md`. It has one tool (`lane_use`); yours
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
3. **Write the knowledge card first.** Decide who the tools are for and write the rules in `KNOWLEDGE.md` before
   the code: each rule is something a transportation engineer knows, with a source you can cite (a manual, a
   standard, a paper, the data itself, or field practice you can describe).
4. **Write the plain version, then yours,** in `tools.py`. [`WRITING_TOOLS.md`](../WRITING_TOOLS.md) explains the
   description, the result, errors, and the plain version.
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
8. **Check, then open the pull request:**
   ```
   python contrib/check.py contrib/<you>
   git checkout -b <you>-tools
   git add contrib/<you>
   git commit -m "Add <your tools> (<one line on the knowledge they add>)"
   git push -u origin <you>-tools
   ```
   GitHub then offers "Compare & pull request". Open it against `main` of ai4mobility/sumo-agent-tools, and fill in the form.
   The workflow runs `check.py` again. A first-time contributor's workflow waits until a maintainer approves it.
9. **Answer the review.** Push more commits to the same branch; the pull request updates itself.

## Rules for a pull request

- One folder, `contrib/<your-github-username>/`, and nothing outside it. A fix to the toolkit is welcome as a
  separate pull request.
- No file over 1 MB, no data you do not have the right to share, and no keys, tokens or passwords.
- Every rule in the knowledge card has a test, and every test passes. A description is a promise to the model, and
  the model cannot check it.
- Say in `KNOWLEDGE.md` which AI tools you used and for what. Using them is fine; the rules, the sources and the
  expected answers in the tests must be ones you checked yourself.
