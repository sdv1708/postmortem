## Parent

#26

## What to build

Bound the Causal Analysis Stage with configurable retrieval, input, output, call, and total-stage budgets. Reserve capacity for one Targeted Repair of mechanically invalid role output. Surface explicit failure codes and diagnostics when repair or budget is exhausted.

Covers PRD user stories 59-68.

## Acceptance criteria

- [ ] Role and stage budgets are recorded in Experiment Metadata and enforced across builder, falsifier, proposed alternatives, support verification, and ranking.
- [ ] Runtime Reasoning Gates detect schema failure, incomplete challenge/ranking coverage, uncited Counterclaims, duplicate hypotheses, missing dimensional rationale, limit violations, and citation failure.
- [ ] Only the failed role is repaired once with deterministic validation errors; successful role outputs are not rerun.
- [ ] Exhausted repair or budget fails stage 3 with a controlled error code, preserves inspectable prior outputs, and produces no Provisional Postmortem.
- [ ] Failed-run API and UI diagnostics explain the failed substep without exposing raw Sensitive Evidence.
- [ ] Tests cover successful repair, failed repair, budget exhaustion, preserved outputs, and absence of degraded builder-only success.

## Blocked by

- #32
