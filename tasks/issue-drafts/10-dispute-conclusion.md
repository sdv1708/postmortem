## Parent

#26

## What to build

Let a reviewer append a Conclusion Discrepancy to an immutable Root Cause Conclusion. An open discrepancy makes the conclusion disputed, returns Postmortem Review to unresolved, and prevents clean UI/export presentation from treating the conclusion as authoritative while retaining full audit history.

Covers PRD user stories 44-46.

## Acceptance criteria

- [ ] An authenticated command creates an append-only Conclusion Discrepancy with author, timestamp, and explanation.
- [ ] Creating a discrepancy does not update or delete the linked Root Cause Conclusion.
- [ ] The incident Review Surface prominently marks the conclusion disputed and returns review to an unresolved state.
- [ ] Clean exports do not present a disputed conclusion as current fact; audit exports preserve the conclusion and discrepancy.
- [ ] Tests cover immutable history, duplicate/open discrepancy behavior, cross-incident rejection, UI state, and export behavior.

## Blocked by

- #33
