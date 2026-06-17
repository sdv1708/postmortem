# Bounded Alternative-Expansion Round in the Falsification Round

This decision extends the bounded falsifier (ADR 0034) with a single, bounded **alternative-expansion** pass: while challenging the initial RCA Hypotheses, the falsifier may introduce at most two **Proposed RCA Hypotheses**, each of which then travels the normal citation, semantic-support, challenge, and review path exactly once. It is the next slice of the bounded multi-pass causal-analysis work (PRD #26, issue #30, user stories 14-16, 24, 57-58, 65, 75) and preserves the six visible status-page stages — expansion is a persisted substep of stage 3 ("Analyzing causal hypotheses"), not a seventh stage.

## One round, two passes, no recursion

The Falsification Round runs inside stage 3 after the builder persists the initial hypotheses:

1. **Challenge pass.** Every initial RCA Hypothesis receives exactly one persisted Hypothesis Challenge (ADR 0034). While challenging an initial hypothesis the falsifier may surface a missed alternative the builder overlooked, returned in the challenge's optional `proposed_hypotheses` using the *same* shape as an RCA hypothesis (`RcaHypothesis`). Proposals are collected across the challenge pass in order.

2. **Expansion pass.** The collected proposals (at most two) are persisted as hypotheses with `origin='proposed'`, ranked after the initial ones, with citations resolved from the stored artifact lines over the full immutable run-artifact set (ADR 0024) — an uncited proposed statement is normalized to an assumption like any other Major Claim (ADR 0013). Each proposed hypothesis is then challenged **once** with proposals disabled.

The round never recurses (PRD user story 16): a proposed hypothesis's own challenge may not introduce further alternatives. A proposed alternative is therefore not trusted output — it earns its place by passing the identical verification and review path as an initial hypothesis (CONTEXT "Proposed RCA Hypothesis vs Trusted Output").

## `origin` records provenance, never trust level

Hypotheses gain an `origin` column (`initial` | `proposed`, default `initial`; existing databases upgrade through the established idempotent compatibility path). `origin` only records *how* a hypothesis entered the analysis. A proposed alternative receives the same citation integrity audit (stage 4), semantic support judgment (stage 6), and human review controls as an initial hypothesis, and the Review Surface labels it "proposed alternative" so a reviewer can see the falsifier's contribution without treating it — or any hypothesis — as a Root Cause Conclusion (PRD user stories 14-15). Ranking still uses `rank`; the expansion does not reorder the builder's hypotheses.

## The expansion is bounded by a Runtime Reasoning Gate

The cap is two proposed alternatives total across the round (`MAX_PROPOSED_HYPOTHESES`). Exceeding it, or a second-round challenge that tries to propose again, is a deterministic gate failure: the stage raises rather than silently truncating, so the bound stays auditable. With the targeted-repair machinery not yet built, the bounded repair/failure contract available at this point is the existing single stage retry (ADR 0029): a gate failure fails stage 3 after one retry, preserves the builder's already-persisted output for inspection, and produces no Provisional Postmortem (ADR 0034/0035). The same bound is enforced ahead of time in scenario fixtures: the loader rejects a replay that declares more than two proposed alternatives or a proposed alternative that recursively proposes again, so a fixture cannot ship an out-of-contract demo.

## The canonical demo exercises the round deterministically

The deploy-ambiguity replay's falsifier now surfaces one missed alternative — a cache-node eviction shifting read load onto the primary database — from a challenge of the first builder hypothesis, and bundles that proposed hypothesis's own second-round challenge. The `ScenarioReplayFalsifier` serves both, keyed by title, so the founder-demo trust path shows a falsifier-proposed alternative flowing all the way to a fully reviewable, citation-verified hypothesis offline and without a live model.

## What this slice does not yet do

It does not add the Advisory Hypothesis Ranking that would order initial and proposed hypotheses by plausibility, the full Reasoning Budget / Targeted Repair machinery, or Model Call Records. Those are later slices of PRD #26. The expansion here is limited to one round and two proposals, and proposed alternatives are challenged once but not yet re-ranked.
