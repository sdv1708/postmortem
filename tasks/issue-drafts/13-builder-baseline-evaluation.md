## Parent

#26

## What to build

Prove whether bounded multi-pass causal analysis improves reasoning. Extend Scenario Manifests with structured Causal Evaluation Expectations and run the multi-pass configuration beside a Builder-Only Baseline under the same model and retrieval constraints. Show deterministic quality checks, semantic scores, tokens, calls, and latency in the evaluation UI.

Covers PRD user stories 80-87.

## Acceptance criteria

- [ ] Scenario Manifests support expected causal families and roles, known counterevidence, plausible rejected alternatives, critical Evidence Gaps, refusal behavior, and unacceptable overclaims.
- [ ] Scenario validation fails fast on unknown families, invalid roles, missing evidence references, and contradictory expectations.
- [ ] Evaluation Runs execute multi-pass and Builder-Only Baseline configurations with matched scenario, model, prompt family, and retrieval constraints.
- [ ] Deterministic checks measure challenge coverage, alternative consideration, unsupported causal claims, refusal, causal-role constraints, and unacceptable overclaims without using the LLM judge for citation validity.
- [ ] Semantic judging evaluates explanatory and falsification quality, while tokens, calls, and latency are recorded for both configurations.
- [ ] The evaluation UI makes quality/cost comparisons visible and tests avoid exact natural-language matching.

## Blocked by

- #37
