# 0044 — Compare multi-pass causal analysis against a Builder-Only Baseline

- Status: Accepted
- Date: 2026-06-25
- Supersedes/amends: extends 0010 (deterministic check floor + LLM judge), 0007
  (file-based scenario fixtures), 0025 (experiment metadata), 0034/0036/0037 (the
  causal-analysis substeps), 0043 (bounded causal analysis)

## Context

The product now runs bounded multi-pass causal analysis (ADR 0034/0036/0037/0043):
a builder generates RCA Hypotheses, a falsifier challenges every one and may
propose bounded alternatives, and an advisory ranker orders them. The PRD's
problem statement is that a *single* model pass can be analytically shallow —
overlooking counterevidence, collapsing several causal factors into one apparent
winner, or presenting ranking as stronger than the evidence warrants. The
multi-pass flow is the answer to that, but until now nothing *measured* whether it
actually improves reasoning, or whether the improvement is bought with unbounded
cost.

The existing evaluation harness (ADR 0010) ran each file-based scenario once
through the deterministic check floor and the LLM judge. It had no notion of a
comparison configuration, no causal-specific checks, no structured expectations
about *what* the causal analysis should conclude, and recorded no cost metrics.

## Decision

Extend the evaluation harness to run every scenario under two configurations and
compare them on quality and cost, framework-neutrally and offline.

1. **Causal Evaluation Expectations on the Scenario Manifest.** A new optional
   `causal_evaluation` block records the expected causal factor families and roles,
   known counterevidence (cited to real evidence lines), plausible rejected
   alternatives, critical Evidence Gaps, whether the scenario should refuse, and
   the unacceptable overclaims a confident-but-shallow run must not make. The
   loader fails fast on the contract violations the PRD calls out: unknown families
   (an expected factor — or a plausible rejected alternative — not in
   `expected_hypothesis_families`), invalid causal roles, missing evidence
   references (a counterevidence citation to a nonexistent file or out-of-range
   line), and contradictory expectations (a refusal scenario that also expects
   factors, more than one Failure Mechanism, a non-refusal scenario with none, or a
   family listed as both expected and a plausible rejected alternative). Rejected
   alternatives are constrained to declared families so the alternative-consideration
   check is satisfiable by a real run. The expectations enable deterministic checks
   without depending on exact generated wording.

2. **Builder-Only Baseline configuration.** A `falsification_enabled` flag threads
   through `AnalysisService` and the stage runner; when false the Causal Analysis
   Stage generates and ranks hypotheses but skips the Falsification Round entirely.
   This is **only** for the evaluation harness — a normal product run that *fails*
   falsification must fail the stage (ADR 0043), never degrade to builder-only
   output. The harness runs each scenario in both modes under matched scenario,
   model, prompt family, and retrieval constraints (the same replay seeds both).

3. **Causal deterministic checks.** Seven checks join the floor: challenge
   coverage (every hypothesis challenged), counterevidence coverage (every declared
   known counterevidence item is surfaced by a Counterclaim, matched by evidence
   line-range overlap, not wording), alternative consideration (each declared
   plausible rejected alternative family is represented by a generated hypothesis
   the ranking did not place first), unsupported causal claims (the advisory leader
   must not rest on unsupported evidence), causal refusal (driven by the structured
   `expected_refusal`), causal-role constraints (a non-refusal run must produce a
   finalizable Failure Mechanism candidate), and unacceptable overclaims. They read
   the run's persisted outputs and the scenario's expectations — never the judge —
   so citation validity stays mechanical (ADR 0010). A scenario with no
   expectations declared degrades the expectation-driven checks to trivial passes.

   Challenge coverage and counterevidence coverage are both Builder-Only
   discriminators: the baseline raises no Counterclaims, so it can neither challenge
   a hypothesis nor surface the known counterevidence. Counterevidence and the
   declared alternatives are therefore *exercised against the run*, not merely
   recorded — a multi-pass run that misses the known counterevidence or never weighs
   the declared alternative fails, so the evaluation cannot falsely prove the PRD's
   core claim. The prose critical Evidence Gaps are routed to the semantic judge
   rather than a deterministic check, because matching free-form gap text
   deterministically would mean exact-wording matching, which the PRD's testing
   decisions explicitly avoid.

4. **Semantic judge depth + cost metrics.** The judge rubric gains two dimensions —
   explanatory coverage and falsification quality — and the judge is told each
   hypothesis's challenge status so it can score a baseline's falsification quality
   low. Each Evaluation Run records its `analysis_mode` and three cost signals
   beside the quality results: persisted Model Call Records, summed model token
   usage, and total Run Stage latency. The dashboard shows the two configurations
   side by side.

## Consequences

- The Builder-Only Baseline is measurably weaker, not assumed so: it fails
  `causal_challenge_coverage` while the multi-pass run passes, at strictly fewer
  model calls and no greater latency, so the comparison demonstrates value under a
  recorded cost budget (PRD stories 80, 87) rather than merely producing more text.
- Causal expectations are self-validating fixture data: a malformed `causal_evaluation`
  block fails the loader before it can reach the harness, like the existing replay
  validation (ADR 0007).
- The judge rubric is now six dimensions. Older recorded runs predate the two new
  ones; `judge_scores` is free-form JSON so they coexist, and the deterministic
  floor — never the judge — remains the citation-validity authority (ADR 0010).
- `evaluation_runs` gains `analysis_mode` and the three cost columns, added through
  the existing idempotent SQLite/PostgreSQL compatibility shim with `multi_pass`
  and `0` defaults so existing rows upgrade cleanly.
- Token cost reads `0` on the offline scenario replay (the replay reports no
  usage), which is honest: the plumbing populates with a real model. Model-call and
  latency signals still differ between the two configurations on the replay path.
