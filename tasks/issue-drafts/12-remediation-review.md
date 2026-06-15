## Parent

#26

## What to build

Turn generated actions into human-owned Remediation Proposals. After causal review, reviewers can accept, reject, or defer each proposal and link accepted work to a finalized Causal Factor or documented Evidence Gap. Falsification remains scoped to causal reasoning.

Covers PRD user stories 51-53.

## Acceptance criteria

- [ ] Generated action items are presented and persisted as Remediation Proposals rather than committed actions.
- [ ] An authenticated command supports accept, reject, and defer decisions without editing the generated proposal.
- [ ] Accepted proposals require a link to a Causal Factor or Evidence Gap from the reviewed incident.
- [ ] Review Surface and exports distinguish proposed, accepted, rejected, and deferred remediation.
- [ ] Tests cover decision transitions, invalid cross-incident links, unchanged generated text, and absence of remediation review from the Falsification Round.

## Blocked by

- #33
