## Parent

#26

## What to build

Produce one post-challenge Advisory Hypothesis Ranking across all initial and proposed hypotheses. Ranking is ordinal and explained through support strength, counterevidence severity, explanatory coverage, Evidence Gaps, and assumption dependence. Preserve builder order for audit and visibly carry unresolved critical challenges.

Covers PRD user stories 17-25, 57-58, 74-79, and 88-89.

## Acceptance criteria

- [ ] Provisional semantic support judgments and incremental citation results are available before the ranker runs.
- [ ] Every candidate appears exactly once in the final ordinal ranking with a rationale covering the required assessment dimensions.
- [ ] The original builder order remains available in audit data and the ranker never emits probability percentages.
- [ ] A first-ranked hypothesis with an unresolved critical challenge is labeled **Leading but critically challenged** in API, Review Surface, and audit export.
- [ ] Broken or semantically unsupported evidence cannot be counted as positive ranking support.
- [ ] Tests cover reordered candidates, unchanged order, partial support, unsupported claims, critical challenges, and missing-candidate failure.

## Blocked by

- #30
