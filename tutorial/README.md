# Tutorial: tuning the agent's reasoning depth

A self-contained demo incident built to **stress the depth** of the agent's RCA and
remediation, plus an explicit statement of the reasoning you should expect. Use it to
judge output quality and to tune the role prompts when results feel too shallow.

## Why this scenario

It is a **layered cascade** where the obvious answers are wrong:
- the deploy is a red herring (the flag shipped OFF and flipped on later),
- the traffic surge is a red herring (a bigger sale the week before was fine),
- the Elasticsearch fault is a red herring (the cluster stayed green).

The sound reading separates the **failure mechanism** (connection-pool exhaustion)
from its **trigger** (an unindexed facet query enabled by a feature flag) and its
**amplifiers** (a retry storm and flash-sale traffic). A shallow run picks one red
herring or collapses everything into a single "root cause" — exactly what we want to
detect and tune away.

## What's here

```
tutorial/
  README.md                        # this file
  EXPECTED_REASONING.md            # the depth bar + grading checklist + where to tune
  scenario/
    scenario.yaml                  # manifest incl. machine-checkable causal_evaluation
    evidence/                      # 7 evidence artifacts (the analysis input)
    replay/                        # EXPECTED OUTPUTS (golden): rca / incident_facts / falsification
    ground_truth_postmortem.md     # EXPECTED OUTPUT: the finished reference postmortem
```

- **Input** = `scenario/scenario.yaml` + `scenario/evidence/*`.
- **Expected reasoning** = `EXPECTED_REASONING.md` (prose) and the `causal_evaluation`
  block in the manifest (machine-checkable: roles, rejected alternatives, evidence
  gaps, unacceptable overclaims).
- **Expected outputs** = `scenario/replay/*.json` and `scenario/ground_truth_postmortem.md`.

## How to use it

### A. Judge a real run (live LLM)
Create an incident in the app, paste the 7 files from `scenario/evidence/` as
artifacts, run an analysis, then grade the output against the checklist in
`EXPECTED_REASONING.md`. Where it falls short, tune the prompts named there and
re-run.

### B. Run it deterministically (offline replay)
The folder is laid out exactly like the built-in scenarios in `backend/scenarios/`.
To wire it in as a seedable demo, copy the `scenario/` contents into
`backend/scenarios/search-pool-cascade/` (manifest + `evidence/` + `replay/` +
`ground_truth_postmortem.md`) — it will then appear in the scenario list and seed
with the golden `replay/` outputs, no live model required.

> The `replay/` files are both the offline seed data **and** the golden outputs you
> tune real runs toward. Keep them in sync with `ground_truth_postmortem.md`.

## The short version of "deep enough"

1. Timeline anchored to evidence lines, used as an argument.
2. Mechanism vs trigger vs amplifiers, each with citations.
3. All three red herrings rejected with counter-evidence.
4. Evidence gaps stated, not hidden.
5. Remediation per causal layer, each tied to evidence.
