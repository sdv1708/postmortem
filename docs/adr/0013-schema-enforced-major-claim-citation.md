# Schema-Enforced Major Claim Citation

Every structured output object containing a Major Claim must carry EvidenceRefs or be explicitly marked as an assumption. This moves citation discipline out of best-effort prompting and into the product schema, where UI rendering, verification, and evaluation can enforce the same contract.

If an LLM emits a Major Claim with neither EvidenceRefs nor an assumption marker, the system normalizes it to `assumption=true`, logs a warning, and records it as an Uncited Claim metric in the evaluation harness. The run should not fail or retry automatically; a high uncited-claim rate is a signal to improve prompts, retrieval, or verification.
