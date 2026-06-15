## Parent

#26

## What to build

Add the complete human finalization path for an evidence-governed Root Cause Conclusion. A reviewer first retains credible RCA Hypotheses, then finalizes exactly one supported Failure Mechanism with optional repeatable Triggers and Amplifying Conditions. Persist provenance and render the immutable conclusion in the Review Surface and exports.

Covers PRD user stories 29-37, 42-43, and 90.

## Acceptance criteria

- [ ] Hypothesis acceptance remains a separate decision and never creates a Root Cause Conclusion implicitly.
- [ ] A finalization command requires exactly one Failure Mechanism and permits zero or more Triggers and Amplifying Conditions from accepted hypotheses.
- [ ] Every Causal Factor has verified citations and `supported` or `partial` claim support; unsupported hypotheses cannot be finalized as factors.
- [ ] Conclusion Provenance records the authenticated principal, display name when available, finalization time, and source Analysis Run.
- [ ] Finalized conclusions are immutable through service and API behavior and protected by database constraints where supported.
- [ ] Review Surface and clean/audit exports clearly separate the human Root Cause Conclusion from the Advisory Hypothesis Ranking.
- [ ] Integration and browser tests prove finalization, cardinality validation, cross-run ownership rejection, and immutability.

## Blocked by

- #31
- #29
