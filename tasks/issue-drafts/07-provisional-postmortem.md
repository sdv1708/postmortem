## Parent

#26

## What to build

Make every automated postmortem explicitly provisional until a human creates a Root Cause Conclusion. The Review Surface and all Markdown exports must state **Draft: Root cause not finalized**, and generated narrative must describe hypotheses and uncertainty without declaring that a root cause was established.

Covers PRD user stories 26-28.

## Acceptance criteria

- [ ] Successful automated runs produce a Provisional Postmortem state distinct from a finalized human conclusion.
- [ ] The Review Surface, clean export, and audit export display **Draft: Root cause not finalized**.
- [ ] Deterministic composition does not introduce a Root Cause Conclusion or convert the top-ranked hypothesis into authoritative wording.
- [ ] Insufficient-evidence refusal remains compatible with provisional labeling.
- [ ] API, renderer, and browser tests prove provisional status remains visible through review and export.

## Blocked by

- #27
