# Human Root Cause Conclusion Finalization

This decision adds the human-in-the-loop path from generated, ranked RCA Hypotheses to a finalized **Root Cause Conclusion**. It is the next slice of the bounded multi-pass causal-analysis work (PRD #26, issue #33, user stories 29-37, 42-43, 90) and builds on ADR 0035 (provisional postmortem until human finalization), ADR 0037 (advisory hypothesis ranking), ADR 0016 (review annotations, no inline editing), and ADR 0024 (relational EvidenceRefs). It adds no model call and no pipeline stage — it is human-command, persisted-state, and rendering work.

## The system never declares a root cause; only a human finalizes one

The Analysis Run completes and produces a Provisional Postmortem (ADR 0035). Accepting a hypothesis retains it as credible (ADR 0016); it does not create a conclusion. A separate, deliberate human command — `POST /api/incidents/{id}/analysis-runs/{run_id}/conclusion` — finalizes a Root Cause Conclusion. This keeps the Advisory Hypothesis Ranking a review aid, never causal authority (CONTEXT "Advisory Hypothesis Ranking vs Root Cause Conclusion").

## A conclusion is one Failure Mechanism plus optional repeatable roles

A `root_cause_conclusions` row holds the reviewer's structured causal `summary` and Conclusion Provenance. Its `causal_factors` are accepted hypotheses assigned a causal role: exactly one `failure_mechanism` plus zero or more `trigger` and `amplifying_condition` factors, so a multi-factor incident is represented honestly rather than collapsed onto one winner (CONTEXT "Failure Mechanism vs Trigger vs Amplifying Condition"). The at-most-one-Failure-Mechanism invariant is enforced by a partial unique index where supported (SQLite and PostgreSQL); the service enforces the at-least-one half and rejects assigning one hypothesis two roles.

## Finalization cannot bypass the evidence trust floor

Every Causal Factor must reference a hypothesis from **this run** (cross-run references are rejected as not-found) that is `accepted`, carries `supported` or `partial` semantic claim support (ADR 0014), and has at least one **verified** supporting citation (ADR 0013). An unsupported hypothesis, or one whose citations did not pass the deterministic Citation Integrity check, cannot be finalized as a factor. This preserves generated provenance (the conclusion links back to the hypotheses and their exact EvidenceRefs) and keeps human finalization from manufacturing unevidenced fact.

This slice deliberately does **not** yet implement the Partial-Support Acknowledgment, Critical-Challenge Override, or Human Assumption refinements (PRD stories 38-41) — those are later slices. A partially supported factor is permitted per the acceptance criteria; the acknowledgment text and override flow arrive with their dedicated slice.

## Conclusion Provenance and immutability

The authenticated `finalized_by_principal`, the `finalized_by_display` name when configured, the `finalized_at` time, and the source `run_id` are recorded (PRD story 42). The MVP single-user gate (ADR 0017) supplies the principal through a new `require_principal` dependency; no roles or approval chains are introduced.

A finalized conclusion is immutable (PRD story 43): the service and API expose no update or delete path, a second finalization for the same run is a `409 Conflict`, and the database blocks `UPDATE`/`DELETE` on `root_cause_conclusions` and `causal_factors` where supported (SQLite `ABORT` triggers, PostgreSQL row triggers). Later disagreement will be recorded through append-only Conclusion Discrepancies and Superseding Conclusions (PRD stories 44-50) — never by editing an existing row — so blocking in-place mutation now does not constrain those future slices.

## Rendered distinctly from the advisory ranking

When a conclusion exists, the Postmortem read model carries it, the Review Surface renders a "Root Cause Conclusion" panel separate from the advisory hypotheses, and the provisional banner drops (the postmortem's `conclusion_status` flips to `finalized`). Clean and audit Markdown exports render a "Root Cause Conclusion" section with the failure mechanism, triggers, amplifying conditions, and provenance, explicitly noting it is the human's decision and that the hypotheses below are the advisory candidates it was drawn from.

## What this slice does not yet do

No Conclusion Discrepancies, Superseding Conclusions, Remediation Proposal lifecycle, Partial-Support Acknowledgment, Critical-Challenge Override, or Human Assumptions. It establishes the finalization command, the immutable Root Cause Conclusion entity with Causal Factors and provenance, and the rendering that separates the human conclusion from the advisory ranking.
