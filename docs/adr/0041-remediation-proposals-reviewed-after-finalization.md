# Reviewing Remediation Proposals After Finalization

This decision turns the generated remediation that hangs off RCA Hypotheses into
human-owned **Remediation Proposals** with an explicit accept / reject / defer
lifecycle. It is the next slice of the bounded multi-pass causal-analysis work
(PRD #26, issue #35, user stories 51-53) and builds on ADR 0039 (immutable human
Root Cause Conclusion finalization), ADR 0016 (review annotations, no full inline
editing), ADR 0034 (the bounded falsifier and its Evidence Gaps), and ADR 0022
(resource APIs with explicit command endpoints). It adds no model call and no
pipeline stage — it is human-command, persisted-state, and rendering work.

## Generated remediation is a proposal, not a committed action

The system generates remediation while drafting RCA Hypotheses (stage 3); those
`action_items` are forward-looking *candidates*, not committed work (CONTEXT
"Remediation Proposal vs Committed Action"). Rather than introduce a parallel
table, this slice adds a decision overlay to the existing `action_items` row: a
`review_status` of `proposed` (the generated default), `accepted`, `rejected`, or
`deferred`, plus decision provenance (`decided_by_principal`, the optional
`decided_by_display`, `decided_at`) and an optional `decision_rationale`. The
generated `description` and its EvidenceRefs are never edited by a decision
(ADR 0016): a decision only records the human's disposition of the generated text.

A reviewer records a decision through a deliberate command,
`POST /api/incidents/{id}/analysis-runs/{run_id}/remediation/{action_item_id}/decision`.
Unlike a finalized conclusion, a remediation decision is *not* immutable: a reviewer
may move a proposal between states (e.g. `deferred` → `accepted`) as review
progresses, so `action_items` stays a mutable table and is not added to the
append-only immutability triggers.

## An accepted proposal must point at why it matters

Accepting a proposal commits follow-up work, so its purpose must be explicit
(PRD story 53): an `accepted` proposal requires a link to either a **Causal Factor**
of a finalized Root Cause Conclusion or a documented **Evidence Gap**, both drawn
from the reviewed incident. `proposed`, `rejected`, and `deferred` proposals carry
no link. This is enforced both in the service and, on fresh databases, by a
`CHECK` constraint (`accepted` ⇒ exactly one link target; otherwise none).

- A **Causal Factor** link (`causal_factor_id`) references a `causal_factors` row
  whose conclusion belongs to a run in the same incident. Linking remediation to a
  finalized Causal Factor is why "after finalization" is in the slice name: the
  reviewer has decided what caused the incident, and accepted remediation attaches
  to that decision.
- An **Evidence Gap** link references a documented gap by `(evidence_gap_challenge_id,
  evidence_gap_index)`: the index into a Hypothesis Challenge's `evidence_gaps`
  list (ADR 0034). The challenge must belong to the run and the index must be in
  range. Evidence Gaps are procedural guidance, not addressable rows, so the link
  is the stable `(challenge, index)` pair and the gap *text* is resolved at read
  time from the immutable challenge rather than snapshotted. This lets a reviewer
  accept remediation that closes a known gap even when no causal factor yet covers it.

Cross-incident links are rejected (404): a proposal cannot attach to another
incident's causal factor or evidence gap.

## Falsification stays scoped to causal reasoning

Remediation review runs entirely after the automated Analysis Run completes and is
never part of the bounded Falsification Round (CONTEXT "Causal Falsification vs
Remediation Review", PRD user story 52): the falsifier challenges causal
explanations only and never accepts, rejects, defers, or otherwise touches an
`action_items` row. Remediation quality is a separate human review after causal
factors and evidence gaps exist.

## The four states are visible everywhere remediation renders

The Review Surface and Markdown exports distinguish `proposed`, `accepted`,
`rejected`, and `deferred` (PRD #35 AC #4). In Markdown, a **clean** (shareable)
export presents only `accepted` remediation — the committed, human-owned follow-up —
each annotated with its causal-factor or evidence-gap link, and notes how many
proposals remain pending review without listing rejected ones as if they were work.
An **audit** export lists every proposal grouped by state with its link and
decision rationale, so a reviewer can see the full disposition. A dedicated
`GET …/remediation` resource backs the Review Surface panel; the proposals also stay
nested under their hypothesis in the structured Postmortem read model.

## What this slice does not yet do

No autonomous acceptance or execution of remediation (a decision only records human
disposition), no falsifier review of remediation quality, and no editing of the
generated remediation text. It establishes the Remediation Proposal lifecycle, the
decision command, the accepted-proposal link contract, and the rendering that
distinguishes the four states.
