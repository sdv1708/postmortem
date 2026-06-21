# Qualifying Partial and Critically Challenged Conclusions

This decision lets a human Root Cause Conclusion carry uncertainty *without hiding it*.
It is the next slice of the bounded multi-pass causal-analysis work (PRD #26, issue #36,
user stories 38-41) and builds on ADR 0039 (immutable human Root Cause Conclusion
finalization), ADR 0014 (semantic claim support), ADR 0034 (bounded falsifier / Challenge
Severity), and ADR 0015 (clean vs audit Markdown). It adds no model call and no pipeline
stage — it is human-command, persisted-state, and rendering work that tightens the
finalization trust floor ADR 0039 deliberately left for a later slice.

## A partially supported factor must be acknowledged, not silently included

ADR 0039 permits a Causal Factor whose hypothesis carries `partial` claim support, but it
did not yet require the reviewer to say *why*. This slice closes that gap: a factor whose
hypothesis is `partial` cannot be finalized without a **Partial-Support Acknowledgment**
(`causal_factors.partial_support_acknowledgment`) describing what is supported and what
remains uncertain (CONTEXT "Supported vs Partially Supported Causal Factor", PRD stories
38-39). The service enforces presence (a blank-only string is rejected) and the
acknowledgment is rendered wherever the factor appears, so the uncertainty travels with
the conclusion into the Review Surface and both export modes. A fully supported factor
needs none; any stray text it carries is dropped so the conclusion never shows misleading
qualification.

## A critically challenged Failure Mechanism requires an explicit override

Challenge Severity `critical` means the hypothesis cannot serve as the Failure Mechanism
if the challenge is valid (ADR 0034, CONTEXT "Challenge Severity"). A reviewer may still
conclude it is the mechanism, but only through a deliberate **Critical-Challenge Override**
(`causal_factors.critical_challenge_override`) that addresses the unresolved critical
challenge (PRD stories 40-41). The override is required *only* for the `failure_mechanism`
role: `critical` blocks that role specifically, so a critically challenged hypothesis may
still be a Trigger or Amplifying Condition without one. Finalization never erases the
challenge: the finalized factor carries the *full* persisted Hypothesis Challenge (the
challenged claim, cited Counterclaims, Evidence Gaps, and Falsification Tests via the
existing `challenge_read` shaper), not merely a severity label, and the override is always
rendered with non-definitive wording ("included with override (not definitive)"). Carrying
the whole challenge is deliberate — the override must be auditable against the specific
concern it claims to address, which a bare severity badge cannot support (PRD story 41). A
hypothesis has at most one Hypothesis Challenge (ADR 0034), so "every unresolved critical
challenge" reduces to that single challenge.

## Unevidenced beliefs are Human Assumptions, never Causal Factors

A reviewer belief that lacks sufficient verified evidence cannot be presented as an
established Causal Factor (CONTEXT "Causal Factor vs Human Assumption", PRD story 38).
Rather than weaken the factor trust floor, such beliefs are recorded as **Human
Assumptions** — a new `human_assumptions` table linked to the conclusion, holding the
reviewer's `statement` with no EvidenceRefs. They are part of the finalization payload,
stored separately from `causal_factors`, and always rendered under an explicit
"Human assumptions (not evidence-backed)" label in the Review Surface and exports. They
therefore can never render as a factor, and the evidence-backed factor requirements
(accepted hypothesis, verified citations, supported/partial support) are untouched.

## Persisted with the immutable conclusion

The two qualification columns live on `causal_factors`; Human Assumptions are their own
table. All three are finalized once, with the conclusion, and are append-only thereafter:
`human_assumptions` joins `root_cause_conclusions` and `causal_factors` in the
append-only immutability triggers (`_ensure_append_only_immutability`; SQLite `ABORT`
triggers, PostgreSQL row triggers). The new nullable columns are added to existing
development databases through the idempotent `ensure_schema_compatibility` column upgrade,
needing no backfill — an existing factor simply carries neither qualification.

## Rendering preserves the qualifications everywhere

The read models carry the acknowledgment, the override, the factor's full Hypothesis
Challenge, and the human assumptions, so a single shaping path feeds the API, the Review
Surface, and Markdown. Clean and audit exports both preserve partial-support
acknowledgments, the actual critical challenge content, override rationale, and the
labeled human assumptions, because these qualify a
human conclusion the reviewer chose to record — withholding them would hide uncertainty
rather than surface it (the existing disputed-conclusion withholding in ADR 0040 is
unchanged and still applies to the conclusion as a whole).

## What this slice does not do

It does not change how hypotheses are generated, challenged, or ranked, and it does not
relax the ADR 0039 factor trust floor — it adds to it. It introduces no new causal roles,
no probability or confidence scoring on the qualifications, and no Superseding-Conclusion
or Remediation behavior (those remain ADR 0040 / 0041 and later slices).
