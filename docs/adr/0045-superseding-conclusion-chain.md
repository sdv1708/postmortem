# Superseding a Disputed Conclusion

This decision adds the append-only path that lets a **Disputed Conclusion** be
followed by a new immutable **Superseding Conclusion**, so an incident can regain
an authoritative Root Cause Conclusion without ever editing history. It is the next
slice of the bounded multi-pass causal-analysis work (PRD #26, issue #39, user
stories 47-50) and builds on ADR 0039 (immutable human Root Cause Conclusion
finalization), ADR 0040 (Conclusion Discrepancy / derived disputed state), ADR 0035
(provisional postmortem until human finalization), ADR 0022 (resource APIs with
explicit command endpoints), and ADR 0017 (single-user gate). Like ADR 0040 it adds
no model call and no pipeline stage — it is human-command, persisted-state, and
rendering work.

## A dispute is resolved by appending a successor, never by editing the predecessor

A finalized Root Cause Conclusion is immutable (ADR 0039), and disagreement is
recorded by appending a Conclusion Discrepancy that makes it a Disputed Conclusion
(ADR 0040). A reviewer resolves that dispute not by editing the predecessor but by
finalizing a **new** immutable Root Cause Conclusion that links back to the disputed
predecessor and the open discrepancy it answers (CONTEXT "Superseding Conclusion vs
Revision"). The successor is an ordinary `root_cause_conclusions` row carrying two
new nullable links: `supersedes_id` (the predecessor conclusion) and
`superseded_discrepancy_id` (the discrepancy on the predecessor it resolves). Both
are null for an original conclusion. The predecessor row is never touched.

## The chain is linear and authority lives at its undisputed tail

Conclusions for an incident form a linear chain: original → s1 → s2 → … Each link is
a single `supersedes_id` pointer, and a predecessor may be superseded at most once
(a unique index on `supersedes_id` makes the chain a chain, not a tree — this is the
"chain integrity" invariant). A conclusion is **authoritative** when it is the tail
of its chain (nothing supersedes it) *and* it is not itself disputed (no open
discrepancy). Because superseding is only permitted against a disputed predecessor, a
superseded conclusion is always also disputed, so the two ways a conclusion can lose
authority — being disputed, or being superseded — never present a stale conclusion as
current fact (CONTEXT "Disputed Conclusion", "Superseding Conclusion vs Revision").

## Reinterpretation reuses the run; new evidence requires a new run

A Superseding Conclusion is finalized against an Analysis Run — the run whose
hypotheses its Causal Factors are drawn from — exactly like an original conclusion,
and it clears the same evidence trust floor (accepted hypotheses, verified citations,
supported/partial support, partial-support and critical-challenge qualifications).
Two cases follow from where the run comes from (CONTEXT "New Evidence vs
Reinterpretation", PRD stories 49-50):

- **Reinterpretation of unchanged Evidence** reuses the predecessor's own run. The
  successor's `run_id` equals the predecessor's `run_id`; its factors come from that
  same run's hypotheses. This is why the per-run single-conclusion invariant from
  ADR 0039 is relaxed to a *partial* unique index — `run_id` is unique only **where
  `supersedes_id IS NULL`**, so a run keeps at most one original conclusion while
  still allowing a same-run superseding conclusion.

- **New Evidence requires a new Analysis Run.** Evidence is immutable and a run locks
  its artifacts (ADR 0018), so new evidence can only enter through a new run. The
  successor is finalized against that new run, and its factors are validated against
  that run's hypotheses (the existing cross-run rejection). A reviewer therefore
  cannot pull new evidence into the old run's conclusion; they must run analysis over
  it first. To keep each run's conclusion story unambiguous, a cross-run successor is
  only allowed against a run that does not already carry its own conclusion.

## Authority moves to the successor; the predecessor stays for audit

Finalizing a successor moves authoritative presentation to it. The per-run Review
Surface and **clean** exports present only the latest undisputed conclusion: a run
whose representative conclusion has been superseded is rendered as `superseded` (a new
derived `conclusion_status`, alongside `provisional`/`finalized`/`disputed`), with a
pointer to the successor's run rather than the stale causal account. The
representative conclusion for a run is the latest one finalized against it, so a
same-run reinterpretation surfaces the successor while the predecessor remains in the
chain. **Audit** exports and the conclusion read model expose the complete chain —
every predecessor with its discrepancies and provenance — so no historical human
judgment is lost (PRD story 48, CONTEXT "Superseding Conclusion vs Revision").

## What this slice does not do

No editing or deletion of any conclusion (still immutable, ADR 0039); no branching
chains; no automatic re-analysis when superseding; no resolution of a dispute by any
means other than appending a successor. New Evidence still flows only through the
normal new-Analysis-Run path, never by mutating a locked run.
