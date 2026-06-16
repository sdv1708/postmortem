## Parent

#26

## What to build

Make incident facts a complete run-level product path. Rename the second visible Run Stage to **Extracting incident facts**, produce cited Timeline Events and run-level Impact Claims there, and show impact once in the Review Surface and Markdown exports regardless of how many RCA Hypotheses exist.

Record the pipeline decision in an ADR that supersedes the affected parts of ADR 0026 while preserving the six-stage ceiling and persisted handoffs.

Covers PRD user stories 1-2 and 54-56.

## Acceptance criteria

- [ ] A completed Analysis Run persists Impact Claims against the run rather than an RCA Hypothesis, with verified EvidenceRefs or an assumption marker.
- [ ] The run API, Review Surface, clean export, and audit export show each Impact Claim once even when the run contains multiple hypotheses.
- [ ] The status UI and API use **Extracting incident facts** for stage 2 and **Analyzing causal hypotheses** for stage 3 while retaining six visible stages.
- [ ] Existing databases are upgraded without losing impact data or weakening EvidenceRef ownership constraints.
- [ ] Integration tests cover zero, one, and multiple hypotheses and prove impact output is independent of hypothesis review decisions.

## Blocked by

None - can start immediately
