## Parent

#26

## What to build

Make causal reasoning diagnosable without duplicating Sensitive Evidence. Persist role-specific Retrieval Traces and Model Call Records, then expose a restricted run-diagnostics view showing component versions, ordered retrieved Chunk references, token usage, hashes, and structured outcomes.

Covers PRD user stories 57, 69-73, and 75-79.

## Acceptance criteria

- [ ] Builder, falsifier, support verifier, and ranker calls persist role/substep identity, prompt and schema versions, model identity, usage, hashes, and validated structured output.
- [ ] Retrieval Traces persist query, strategy version, and ordered Chunk references including retrieved-but-uncited results.
- [ ] Product records do not duplicate Artifact text, complete prompts, raw responses, or hidden chain-of-thought.
- [ ] An authenticated diagnostics resource and UI expose provenance for a run without changing the normal Review Surface workflow.
- [ ] Tests distinguish retrieval omission from model omission and verify Sensitive Evidence is not copied into provenance tables.

## Blocked by

- #31
