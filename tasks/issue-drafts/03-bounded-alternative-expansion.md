## Parent

#26

## What to build

Allow the falsifier to introduce at most two Proposed RCA Hypotheses in one bounded expansion round. Each proposed alternative must enter the normal hypothesis, citation, semantic-support, challenge, API, and Review Surface path exactly once before causal analysis continues.

Covers PRD user stories 14-16, 24, 57-58, 65, and 75.

## Acceptance criteria

- [ ] A Falsification Round may add zero, one, or two Proposed RCA Hypotheses and cannot recursively propose further alternatives.
- [ ] Proposed alternatives are persisted as identifiable hypotheses and receive the same citation integrity, support, challenge, and review treatment as initial hypotheses.
- [ ] The Review Surface distinguishes proposed alternatives from initial hypotheses without treating either as a Root Cause Conclusion.
- [ ] More than two alternatives or a second expansion attempt fails the Runtime Reasoning Gate and follows the bounded repair/failure contract available at this point.
- [ ] Scenario replay and integration tests demonstrate one missed alternative flowing from falsifier output to a fully reviewable hypothesis.

## Blocked by

- #28
