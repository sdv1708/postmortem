# 0043 — Bound the Causal Analysis Stage with budgets, gates, and one Targeted Repair

- Status: Accepted
- Date: 2026-06-21
- Supersedes/amends: extends 0028 (strict structured output), 0029 (stage-level
  failure with single retry), 0034/0036/0037 (the causal-analysis substeps),
  0025 (experiment metadata)

## Context

The Causal Analysis Stage (stage 3, `analyzing_causal_hypotheses`) drives several
Reasoning Roles in sequence — the builder, the falsifier (challenging every
hypothesis and running one bounded expansion round), the semantic support
verifier, and the advisory ranker. Until now the only recovery from a bad role
output was the generic stage-level single retry (ADR 0029), which re-runs the
*entire* stage — every already-succeeded role included — and the gates that
caught mechanically invalid output raised a bare `ValueError`, so a failed run
recorded only an opaque error string.

That is too blunt for a multi-role stage. Re-running a successful builder and
falsifier just to retry a ranker wastes tokens and is not the bounded,
predictable recovery the PRD requires (PRD #26 user stories 59-68). A run also
had no recorded bound on retrieval breadth, model input/output size, or call
counts, and a failure carried no machine-readable code or failed-substep, so the
API and UI could not explain *why* stage 3 failed without leaking the raw error.

## Decision

Introduce three deterministic controls for the Causal Analysis Stage, in a new
framework-neutral `postmortem/reasoning.py` module, and wire them into the
existing stage runner without adding an orchestration framework.

1. **Reasoning Budget.** A recorded `ReasoningBudget` of per-role and stage
   limits: initial/proposed/final hypothesis caps, max retrieval chunks per
   retrieval, max input/output tokens per role, max calls per role, and a max
   total calls for the stage. One Targeted Repair per role is *reserved on top of*
   the normal per-role call ceiling, so a normal call can never consume the
   recovery allowance and vice versa. The budget is stamped into the run's
   Experiment Metadata (ADR 0025) so a run documents the bounds it ran under, and
   a `BudgetLedger` enforces it during the stage, failing with
   `budget_exhausted` when any dimension is exceeded. Token usage is observed at
   the single boundary every role's model call funnels through (the recording
   client drain in `_record_model_call`), so input/output token budgets apply to
   the builder, falsifier, support verification, and ranking alike — including a
   repair attempt's tokens — not only the role that reads usage inline. A zero
   token budget means "unmetered" so offline/fake-role runs are never failed for a
   signal they do not produce.

2. **Runtime Reasoning Gates.** The deterministic contract checks already present
   in the stage are centralized as `ReasoningGateError`s carrying a controlled
   gate code and the validation messages: `schema_invalid`,
   `challenge_coverage_incomplete`, `ranking_coverage_incomplete`,
   `uncited_counterclaim`, `duplicate_hypothesis`,
   `missing_dimensional_rationale`, `limit_exceeded`, and
   `citation_integrity_failure`. Gate messages are contract text (counts, ids,
   line ranges) — never Artifact text.

3. **Targeted Repair.** Each repairable role invocation (builder generation, each
   falsifier challenge, the advisory ranking) runs through `targeted_repair`:
   produce → gate. On a gate failure it charges the *reserved* repair call and
   re-invokes **only that role once**, feeding the deterministic validation
   errors back into the role. The repair is *informed*, not a blind replay: the
   gate errors are threaded through the role interfaces (`Falsifier.challenge`,
   `AdvisoryRanker.rank`) and appended to the model prompt by the shared
   `append_repair_feedback`, so a real LLM-backed role corrects the specific
   violation. A deterministic role (the default ranker) accepts the feedback and
   ignores it, since its output is a pure function of its inputs. A still-invalid
   repair fails the stage with a controlled `repair_exhausted` code naming the
   failed substep. Successful roles are never re-run. Structural limits that one
   re-invocation could not plausibly fix (an over-cap expansion round, a forbidden
   second expansion) fail immediately with `limit_exceeded`.

A controlled `CausalAnalysisError(code, substep, …)` is the terminal failure. The
stage runner treats it as **terminal** — it does **not** apply the generic
whole-stage retry, because the bounded per-role repair already ran and the
controlled failure is deterministic. The run records `failure_code` and
`failed_substep`; prior successful substep outputs are preserved for inspection,
and **no Provisional Postmortem is produced** (stage 4 never runs). The stage
never degrades to a successful builder-only run.

## Consequences

- A failed causal run now carries a machine-readable `failure_code`
  (`repair_exhausted`, `budget_exhausted`, `limit_exceeded`) and a
  `failed_substep`, surfaced through `AnalysisRunRead` and the Review Surface so
  the failure is explainable without exposing Sensitive Evidence (PRD story 68).
- Recovery is cheaper and bounded: only the failed role is re-invoked, not the
  whole stage. The generic single retry (ADR 0029) still governs the other five
  stages and any non-controlled exception.
- The recorded Reasoning Budget and its per-run consumption snapshot (on the
  stage event `usage`) make run cost comparable across experiments (ADR 0025) and
  visible on the status page (ADR 0021).
- Gate codes and the targeted-repair seam are the same for fakes and real models,
  so the orchestrator is tested as a deep module with deterministic fake roles:
  successful repair, failed repair, budget exhaustion, preserved outputs, and the
  absence of a degraded builder-only success.
