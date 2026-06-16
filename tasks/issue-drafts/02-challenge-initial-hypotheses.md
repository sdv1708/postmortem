## Parent

#26

## What to build

Add a bounded falsifier role to the Causal Analysis Stage. Every initial RCA Hypothesis receives a persisted Hypothesis Challenge containing severity, cited Counterclaims or explicit assumptions, Evidence Gaps, and Falsification Tests. Reviewers can inspect these challenges and follow Counterclaim citations in the Evidence Panel.

Covers PRD user stories 3-13, 24, 57-58, 74-79, and 88-89.

## Acceptance criteria

- [ ] Every initial RCA Hypothesis in a successful run has exactly one schema-valid Hypothesis Challenge before stage 3 succeeds.
- [ ] Counterclaims are Major Claims with verified EvidenceRefs or an explicit assumption marker; Evidence Gaps and Falsification Tests remain procedural guidance.
- [ ] Challenge severity uses `critical`, `material`, or `minor` with the causal-role meanings defined in the domain glossary.
- [ ] The hypotheses resource and Review Surface expose challenge content and exact citation navigation without exposing hidden reasoning or chat history.
- [ ] A run with missing or invalid challenge coverage fails stage 3 after its existing stage retry, preserves prior outputs, and never looks successful.
- [ ] Deterministic fake-role tests and an end-to-end Review Surface test prove the complete challenge path.

## Blocked by

- #27
