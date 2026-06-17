# Advisory Hypothesis Ranking

This decision adds the final substep of the bounded Causal Analysis Stage (stage 3): one post-challenge **Advisory Hypothesis Ranking** that orders every initial and proposed RCA Hypothesis by relative plausibility, explained across five assessment dimensions. It is the next slice of the bounded multi-pass causal-analysis work (PRD #26, issue #31, user stories 17-25, 57-58, 74-79, 88-89) and builds directly on the bounded falsifier (ADR 0034) and alternative-expansion round (ADR 0036). It preserves the six visible status-page stages — ranking is a persisted substep of "Analyzing causal hypotheses", not a seventh stage.

## The ranker is a fourth Reasoning Role

Builder, falsifier, support verifier, and now ranker are separate Reasoning Roles behind their own swappable interfaces (PRD user story 74). The ranker consumes a persisted, structured Role Handoff — each candidate's title, origin, builder order, provisional support status, count of *verified* supporting citations, challenge severity, counterclaim count, open evidence-gap count, and assumption flag — never another role's hidden chain-of-thought (PRD user story 75).

The MVP default is the **`DeterministicAdvisoryRanker`**: it orders candidates by an explainable, evidence-derived plausibility score and emits a per-dimension rationale, making no model call. Like the deterministic citation verifier and postmortem composer, it is a deterministic implementation behind a swappable boundary — the canonical demo and evaluations rank offline and reproducibly, and an LLM-backed ranker can replace it later without touching the stage. Because the offline builder produces no hypotheses, the ranker is never invoked on the offline path; the replay and live paths both rank the persisted candidates.

## Three deterministic steps so ranking never rests on broken evidence

After the falsification round persists every challenged hypothesis, the ranking substep runs:

1. **Incremental Citation Check.** The stage-3 citations (hypotheses, their remediation, and counterclaims) are verified in place with the same deterministic integrity verifier the Final Citation Audit uses, so a broken reference is known before it could be counted as support (CONTEXT "Incremental Citation Check vs Final Citation Audit"). Stage 4 still rechecks the whole run at the visible trust checkpoint.
2. **Support Judgment.** Each hypothesis's semantic support is judged from its *verified* supporting citations only, so a valid citation that does not actually support its claim cannot inflate plausibility (PRD user story 23).

This single support judgment is **canonical** for the hypothesis. The stage-6 complete unsupported-claim audit reuses it — surfacing the Warning Code from the persisted status — rather than re-invoking the support verifier. Because ranking happens in stage 3 and an audit stage must not reorder, re-judging in stage 6 with the LLM-backed (non-deterministic) verifier could return a different verdict and leave a hypothesis displayed as `unsupported` while carrying an advisory rank and rationale computed when it was `supported` — exactly the inconsistency issue #31 AC #5 forbids. Judging once removes that failure mode by construction and avoids a second model call per hypothesis. Run-level Impact Claims are not ranked, so they are judged for the first time at the stage-6 audit. "Provisional" here means the judgment is made mid-stage-3 before the run completes; the final audit confirms and surfaces it rather than overriding it (CONTEXT "Provisional Support Judgment vs Final Unsupported-Claim Audit").
3. **Advisory ranking.** The ranker orders every candidate exactly once. A broken or semantically unsupported citation contributes zero positive support to the score, and an UNSUPPORTED hypothesis contributes negative weight, so it can never outrank a genuinely supported one (issue #31 AC #5).

## Builder order is retained; the advisory ranking is separate

`Hypothesis.rank` keeps the original builder/generation order for audit (PRD user story 20). The advisory ranking is persisted separately as `advisory_rank` (1-based ordinal position, null until the substep runs) and `ranking_rationale` (the five dimensions — support strength, counterevidence severity, explanatory coverage, evidence gaps, assumption dependence — plus a one-line summary). Both columns are nullable and upgrade existing databases through the established idempotent compatibility path. Plausibility is **ordinal and evidence-explained, never a probability or percentage** (PRD user story 18): the output contract has no numeric likelihood field anywhere.

The Review Surface, API, and Markdown export present hypotheses in advisory order while still showing the builder order as audit context.

## Leading but critically challenged

A critically challenged hypothesis may remain first in the ranking — critical severity reduces plausibility but does not force last place. Wherever the advisory leader (`advisory_rank == 1`) carries a critical challenge, it is labeled **"Leading but critically challenged"** in the API, the Review Surface, and the audit export (PRD user stories 21-22), so a top rank is never read as confidence. The label is *derived* at read time from the persisted advisory rank and challenge severity rather than stored, so it cannot drift from the facts it summarizes.

## The Runtime Reasoning Gate enforces complete coverage

A deterministic gate validates the ranker's output against the persisted candidate set: every hypothesis must appear exactly once, with no missing, duplicated, or unknown candidate (PRD user story 60). The required five-dimension rationale is enforced by the strict output schema (every dimension is a non-empty string), so a schema-valid ranking always shows its work. A gate failure fails stage 3 through the bounded repair/failure contract available at this point — the existing single stage retry (ADR 0029) — preserving the builder's and falsifier's persisted output for inspection and producing no Provisional Postmortem. Targeted Repair and full Reasoning Budgets remain a later slice.

## Evaluation

A new deterministic check, `advisory_ranking_coverage`, asserts that a run's hypotheses hold distinct advisory ranks forming `1..N` (a refusal scenario with no hypotheses passes trivially). The check-suite version is bumped to `eval-checks-2`. Semantic ranking quality (whether the chosen order is *good*) remains an evaluation concern, not a runtime success condition (CONTEXT "Runtime Reasoning Gate vs Semantic Evaluation").

## What this slice does not yet do

It does not add the full Reasoning Budget / Targeted Repair machinery, Model Call Records, or the human Root Cause Conclusion finalization that consumes the ranking. Those are later slices of PRD #26. The advisory ranking remains a review aid — only a human creates a Root Cause Conclusion (CONTEXT "Advisory Hypothesis Ranking vs Root Cause Conclusion").
