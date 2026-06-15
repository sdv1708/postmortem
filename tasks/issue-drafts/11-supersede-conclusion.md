## Parent

#26

## What to build

Allow a disputed Root Cause Conclusion to be followed by a new immutable Superseding Conclusion. Preserve predecessor and discrepancy links, move authoritative presentation to the undisputed successor, and require a new Analysis Run when the successor relies on newly added Evidence.

Covers PRD user stories 47-50.

## Acceptance criteria

- [ ] A Superseding Conclusion is created as a new immutable record linked to the disputed predecessor and an open Conclusion Discrepancy.
- [ ] The Review Surface and clean exports present only the latest undisputed conclusion as authoritative while audit views show the complete chain.
- [ ] Reinterpretation of unchanged Evidence may reuse the original Analysis Run.
- [ ] A successor that references Evidence outside the predecessor run requires a new Analysis Run containing that Evidence.
- [ ] Tests cover authority transfer, chain integrity, invalid predecessor states, same-run reinterpretation, and new-run enforcement.

## Blocked by

- #34
