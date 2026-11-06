# Contributing

This repository is a place for SUMO tools that AI agents can trust. Students in AI for Mobility and anyone else are
welcome to add tools, scenarios and better descriptions.

## The one rule

**Every claim a tool description makes comes with a test.** A description is a promise to the model, and the model
cannot check it. If a sentence in a docstring is not tested in `test_claims.py`, it is a guess.

## Adding your tools as a contribution folder

Students in AI for Mobility (Assignment 6), and anyone who wants to add tools without changing the toolkit itself:
each contribution is one folder, `contrib/<your-github-username>/`, sent as one pull request. Follow
[`contrib/README.md`](contrib/README.md); `contrib/_template/` is a complete example. Before you open the pull
request, run `python contrib/check.py contrib/<your-github-username>`; the workflow runs it again.

## Adding a tool to the toolkit

New to AI tools? Read [`WRITING_TOOLS.md`](WRITING_TOOLS.md) first. It walks through one tool from a raw TraCI call
to a tested tool, and explains how to write descriptions and results a model can use. The steps below are the short
checklist.

1. Write the function in `sumo_agent_tools.py`. Its docstring is the description the model reads. Answer the seven
   questions:
   1. What does it return, in what units?
   2. When is the answer undefined or partial (no vehicles, a queue longer than the detector, unfinished trips)?
   3. Which definition does it use (halting, jam, back of queue; space-mean or time-mean speed)?
   4. Does it change the simulation, or let time pass (read-only, acts now, runs forward)?
   5. What will it refuse, and why (the rule and its source)?
   6. How much evidence is behind the result (one snapshot, one run, ten seeds; calibrated or not)?
   7. Who must approve before the result is used?
2. Put engineering limits in the body as checks that reject, not only as advice in the description.
3. Take names people use (cross streets, EB/WB, mph) and return a few labelled numbers with units, not raw XML.
4. Add its schema to `SCHEMAS`. If it only reads, add its name to `READ_ONLY`.
5. Add a `@claim(...)` test in `test_claims.py` for each sentence of the description, then run
   `python test_claims.py`. All claims must pass.

## Adding a scenario

Put it in its own folder next to `fowler/`, with a build script like `build_fowler.py`, and point `SCENARIO` in
`sumo_agent_tools.py` at it. Say clearly which parts are real (network, counts) and which are synthetic.

## Pull requests

- Run `python test_claims.py` before you open one (and `python contrib/check.py contrib/<you>` for a contribution
  folder); the GitHub workflow runs them again.
- A contribution folder and a change to the toolkit go in separate pull requests.
- Say in the pull request what traffic knowledge the change adds and how the tests show it.
- Do not commit simulation output (the top-level `runs/`), personal data, or data you do not have the right to
  share. The transcripts in `contrib/<you>/runs/` are part of a contribution: commit those.
