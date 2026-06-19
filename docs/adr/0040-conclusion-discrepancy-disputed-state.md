# Flagging an Immutable Conclusion as Disputed

This decision adds the append-only path for recording disagreement with a finalized
**Root Cause Conclusion** without ever editing it. It is the next slice of the bounded
multi-pass causal-analysis work (PRD #26, issue #34, user stories 44-46) and builds on
ADR 0039 (immutable human Root Cause Conclusion finalization), ADR 0035 (provisional
postmortem until human finalization), ADR 0022 (resource APIs with explicit command
endpoints), and ADR 0017 (single-user gate). It adds no model call and no pipeline
stage — it is human-command, persisted-state, and rendering work.

## A finalized conclusion is never edited; disagreement is appended

A finalized Root Cause Conclusion is immutable (ADR 0039): it is never edited, replaced
in place, or deleted. When a reviewer later disagrees with it, that disagreement is
recorded by appending a **Conclusion Discrepancy** — a new `conclusion_discrepancies`
row carrying the human-authored `explanation` plus provenance (`raised_by_principal`,
the optional `raised_by_display`, and `created_at`) — through a deliberate command,
`POST /api/incidents/{id}/analysis-runs/{run_id}/conclusion/discrepancies`. The linked
conclusion row is never touched (CONTEXT "Root Cause Conclusion vs Conclusion
Discrepancy"). A discrepancy requires a finalized conclusion to dispute; a request for
a run with no conclusion, or for a run that does not belong to the incident in the
path, is rejected (404) so the endpoint cannot leak or invent state.

## The disputed state is derived, not stored on the immutable row

A conclusion is a **Disputed Conclusion** when it carries at least one open Conclusion
Discrepancy. That state is *derived* from the existence of a discrepancy
(`conclusion_read` sets `disputed`, and `postmortem_read` reports
`conclusion_status = "disputed"`), so nothing mutates the immutable conclusion to mark
it disputed. This also means the Postmortem's stored `conclusion_status` lifecycle
column (`provisional` → `finalized`) is left untouched by a dispute; the read model
overrides it to `disputed` while a discrepancy is open. Deriving the state keeps the
immutability story clean and leaves the future Superseding-Conclusion slice (PRD
stories 47-50) free to resolve a dispute by linking a successor rather than editing
history.

## A disputed conclusion is preserved for audit but not authoritative

Raising a discrepancy returns the incident to unresolved Postmortem Review (CONTEXT
"Disputed Conclusion vs Unresolved Review"): the Review Surface marks the conclusion
disputed prominently, shows the recorded discrepancies, and stops presenting the
conclusion as the authoritative answer, while still offering an append-only "flag a
discrepancy" control (a reviewer may record more than one concern). Markdown rendering
splits by mode (ADR 0015): a **clean** export withholds the disputed causal account so
it cannot read as current fact, surfacing only the disputed banner; an **audit** export
preserves the full conclusion and its recorded discrepancies for the historical record.

## The dispute command is retry-safe for identical submissions

Because a discrepancy is append-only and the database blocks `UPDATE`/`DELETE`, a
duplicate row is permanent and would overstate how many independent concerns were
raised against a conclusion. A lost-response retry that re-POSTs the identical
explanation is therefore treated as the same dispute: the service matches on the
exact (trimmed) explanation text for the conclusion and returns the existing
discrepancy instead of appending a new one (an idempotent create). A genuinely
different explanation still appends, preserving the append-only audit trail for
distinct concerns.

This deliberately stops short of a client-supplied idempotency key with its own
unique constraint: that abstraction is disproportionate for the MVP single-user gate
(ADR 0017) and inconsistent with the other non-idempotent command endpoints (finalize,
hypothesis review, reviewer notes). The guard covers the realistic single-user
sequential-retry case; it is not a cross-request lock, and two truly concurrent
submissions of the same text could still both insert — an acceptable residual for a
single-user MVP, revisited only if multi-user review (out of scope here) arrives.

## Discrepancies are themselves append-only

Like the conclusion they dispute, Conclusion Discrepancies are append-only: there is no
service or API edit/delete path, and the database blocks `UPDATE`/`DELETE` where
supported by adding `conclusion_discrepancies` to the existing append-only immutability
triggers (SQLite `ABORT` triggers, PostgreSQL row triggers; `_ensure_append_only_immutability`).
Since both the conclusion and its discrepancies are delete-blocked, neither can be
cascade-deleted — consistent with the immutability already accepted in ADR 0039.

## What this slice does not yet do

No Superseding Conclusions, no resolution of a discrepancy, and no Remediation Proposal
lifecycle. It establishes the append-only Conclusion Discrepancy entity, the command
that disputes a conclusion, the derived disputed state, and the rendering that withholds
a disputed conclusion from authoritative presentation while preserving it for audit.
Resolving a dispute by finalizing a Superseding Conclusion linked to the discrepancy
arrives with its dedicated slice (PRD stories 47-50).
