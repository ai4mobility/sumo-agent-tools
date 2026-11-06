# Agent run

*Ask three questions through `contrib/agent_loop.py`, which runs a model on your computer, connects it to your
`server.py` over MCP and saves the whole loop to `runs/<name>.md` (instructions at the top of that file). Read each
transcript, then fill in this page. Replace every TODO, and commit the transcripts (the `.md` and the `.json`) with
it. Do not paste keys or personal information.*

    python contrib/agent_loop.py contrib/<you>/server.py "your question" --name q1

## Setup

- Model: TODO (as the transcript's first table shows it, for example Qwen/Qwen3-1.7B, thinking on, seed 1)
- Date: TODO
- Data: TODO (what the tools read: live feeds or the saved snapshot; or the scenario, demand and seed)
- Computer: TODO (CPU or GPU, memory, and how long one question took)

## Questions

### Question 1: one of your tools answers it

**Question:** TODO (in the words the person in "Who it is for" would use)

**Transcript:** [runs/q1.md](runs/q1.md)

**Tool calls:** TODO (each call the model made, with its inputs, in order)

**What the loop shows:** TODO (point to the places in the transcript: where your tool's description enters the
prompt; the sentence of the reasoning where the model chooses your tool and its inputs; the `<tool_call>` text;
the `tools/call` request and response; and what the model reads back in `<tool_response>`)

**Answer:** TODO (the model's final answer, word for word)

**My grade:** TODO (correct, partly correct or wrong, and why: check it against the tool results and what you know)

### Question 2: it needs two or more tools together

**Question:** TODO (one of the tools must be yours)

**Transcript:** [runs/q2.md](runs/q2.md)

**Tool calls:** TODO

**What the loop shows:** TODO (how the result of one call shaped the model's next call)

**Answer:** TODO

**My grade:** TODO

### Question 3: the data cannot fully answer it

**Question:** TODO (a question whose honest answer includes "the data does not say")

**Transcript:** [runs/q3.md](runs/q3.md)

**Tool calls:** TODO

**What the loop shows:** TODO (did your result text tell the model what it could not know, and did the model pass
that on, or fill the gap?)

**Answer:** TODO

**My grade:** TODO

## One fix I made

TODO: what went wrong, or could have gone better, in one of these runs; what you changed (the description, the
result text, an error message, a check in the code, or the server's instructions); and what the same question gave
after the change. Link both transcripts:

**Before:** [runs/q2.md](runs/q2.md) **After:** [runs/q2_after_fix.md](runs/q2_after_fix.md)

## Optional: the same question in Claude

If you connect Claude Desktop or Claude Code to your `server.py` (instructions at the top of that file), ask one of
the questions there too. Which parts of the loop can you see in Claude, and which can you not?
