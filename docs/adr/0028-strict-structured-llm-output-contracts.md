# Strict Structured LLM Output Contracts

The MVP pipeline will require strict stage-specific JSON schemas for LLM outputs. Timeline extraction, RCA hypothesis generation, impact claims, remediation items, and claim support verification must parse and validate before they can become persisted pipeline state.

Invalid JSON or schema-invalid output fails the stage. Schema-valid output with missing EvidenceRefs or assumption markers on Major Claims is normalized to an assumption and counted as an Uncited Claim metric. Free-form LLM prose is not treated as pipeline truth.
