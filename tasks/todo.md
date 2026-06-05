# Slice 7: Verify citations and focus exact Artifact lines from claims

## Objective

Implement GitHub issue #8 (blocked-by #7, merged → unblocked). Stage 4
(`verifying_citations`) becomes real: a deterministic **CitationIntegrityVerifier**
checks every EvidenceRef from the timeline and RCA stages for Artifact existence,
line-range existence, and exact snippet match, then stamps the outcome on
`EvidenceRef.verifier_status`. The Review Surface surfaces that status beside each
citation, and clicking a citation still focuses the Evidence Panel on the exact
immutable Artifact lines.

Note: citation-click focus + exact-line highlight (AC #4/#5) already shipped in the
Slice 6 review-fix batch (`focusEvidence` / `LineViewer`), for both timeline and
hypothesis citations. This slice adds the deterministic verifier, the verifier-status
field, its API exposure, and its UI surfacing.

## Relevant ADRs / PRD

- 0014 split citation **integrity** (deterministic: artifact/line/snippet) from claim
  **support** (semantic). This slice ships only the integrity pass.
- 0002 / 0010 working-citation contract + deterministic trust floor: a citation must
  jump to immutable artifact lines and its snippet must match exactly.
- 0024 relational EvidenceRefs reused across owners; line-addressed, not chunk-addressed.
- 0026 stage 4 may verify/annotate only — it must not introduce new factual claims.
- 0015 / CONTEXT "flagged, not deleted": a broken citation is a non-fatal warning, not
  a run failure.
- 0029 idempotent across the single retry; 0025 verifier version in experiment metadata.
- 0009 the citation verifier is a swappable boundary, proven via a fake in tests.

## Plan

### Backend
- [x] `verification.py`: `CitationIntegrityStatus` enum, `CitationTarget` dataclass,
  `CitationVerifier` Protocol, `DeterministicCitationIntegrityVerifier`,
  `CITATION_VERIFIER_VERSION`.
- [x] `models.py`: add `verifier_status` to `EvidenceRef` (default `unverified`).
- [x] `db.py`: add `verifier_status` to the idempotent `ensure_schema_compatibility`
  column upgrade for issue-6/issue-7 databases.
- [x] `services/stages.py`: route `verifying_citations` → `_verify_citations`; gather
  every run-owned EvidenceRef (`_run_evidence_refs`, all four owner types), verify,
  stamp status, emit `citation_integrity_failure` for any broken ref; verifier is an
  injectable param.
- [x] `services/analysis.py`: stamp `verifier_version` in run experiment metadata.
- [x] `schemas.py`: `CitationVerifierStatus` Literal + `verifier_status` on
  `EvidenceRefRead`.

### Frontend
- [x] `lib/api.ts`: `CitationVerifierStatus` type + `verifier_status` on `EvidenceRef`.
- [x] Incident page: `CitationStatusBadge` rendered beside every hypothesis/impact/
  action and timeline citation (verified check vs broken/unverified alert, with a
  descriptive title). Focus/highlight behavior unchanged.
- [x] Review follow-up: citation rows no longer truncate snippets; displayed snippets
  preserve whitespace so multi-line citations can visually match highlighted lines.

### Tests
- [x] `test_verification.py`: valid / missing artifact / missing line / mismatched
  snippet, short-circuit order, stable enum values.
- [x] `test_stages_citations.py`: full pipeline stamps every citation `verified` +
  `verifier_version`; tampered snippet re-verifies to `snippet_mismatch` with a
  non-fatal warning; the verifier boundary is swappable (fake verifier).
- [x] `test_api_hypotheses.py` / `test_api_analysis_runs.py`: `verifier_status` present
  and `verified` on hypothesis and timeline citations.
- [x] `test_db_compatibility.py`: issue-6 upgrade adds the `verifier_status` column.
- [x] Review follow-up: e2e now asserts the displayed citation snippet text is the same
  snippet shown on the highlighted Artifact line.
- [ ] Review follow-up verification: rerun backend/frontend/e2e commands before final
  acceptance. Not run during this targeted follow-up at user request.

## Review

Stage 4 (`verifying_citations`) is now real and end-to-end. Citation trust is visible
from the deterministic verifier all the way to a badge beside every citation.

### What landed
- **Swappable deterministic verifier** (`verification.py`).
  `DeterministicCitationIntegrityVerifier` checks artifact existence → line-range
  existence → exact snippet match, short-circuiting in that order. It works on an
  ORM-free `CitationTarget` + an `{artifact_id: body}` map, so the check is trivially
  unit-testable and the `CitationVerifier` boundary is genuinely swappable (ADR 0009 /
  0014). The snippet is rebuilt the same way the timeline/RCA stages resolve it, so a
  `verified` citation is provably the source of truth (ADR 0002).
- **`verifier_status` on EvidenceRef** (`models.py`, `db.py`). New nullable-free column
  defaulting to `unverified`; an idempotent `ALTER TABLE ADD COLUMN` upgrades issue-6/7
  databases. It is a derived, mutable status (not an ownership invariant), so unlike the
  owner/role checks it carries no DB CHECK constraint.
- **Stage 4 work** (`services/stages.py`). `_verify_citations` gathers every EvidenceRef
  owned by the run across all four owner types (`_run_evidence_refs`), stamps each
  status, and emits a deduped `citation_integrity_failure` warning for any broken ref.
  It only annotates existing claims (ADR 0026) and is naturally idempotent across the
  single retry (recomputes in place, adds no rows). A broken citation is flagged, never
  deleted, and never fails the run (ADR 0015).
- **Experiment metadata** (`services/analysis.py`): `verifier_version` is now stamped
  with the real `citation-integrity-1`, alongside the chunker version (ADR 0025).
- **API + Review Surface**: `EvidenceRefRead` carries `verifier_status`; the incident
  page renders a compact `CitationStatusBadge` (emerald check for verified, rose alert
  for broken, slate for unverified) beside every timeline and hypothesis citation, with
  a descriptive hover title. Citation rows preserve the displayed snippet text instead
  of truncating it, and click-to-focus still highlights the exact Artifact line range.

### Verification
- Backend: **127 passed** (+11). New `test_verification.py` (8) and
  `test_stages_citations.py` (3) cover all required cases — valid, missing artifact,
  missing line, mismatched snippet, swappability, and the non-fatal tampered-citation
  path. API + db-compatibility tests extended for `verifier_status`.
- Frontend: `npm run typecheck` and `npm run build` clean.
- e2e: `npx playwright test` **2 passed** in the original Slice 7 run. This targeted
  review follow-up added the missing assertion that the displayed citation snippet also
  appears on the highlighted Artifact line; rerun e2e before final acceptance.
- Follow-up tests were not run during this edit pass at user request.

### Deviations from the plan
- None of substance. `verifier_status` uses a Python-side default only (no
  `server_default`), matching the existing `role` precedent; the schema-compatibility
  test helper passes the column explicitly, as it already did for `role`.

## Deferred Backlog

- [ ] After all planned slices are complete, define and implement incident-level
  removal from the workspace dashboard. Decide explicitly between archiving analyzed
  incidents and hard-deleting the full incident aggregate. Individual evidence locked
  into an analysis run must remain protected.
- [ ] Add a dedicated prompt-quality phase after the MVP slices. Improve RCA depth
  beyond schema compliance: require evidence-backed causal chains, separate customer
  impact from inferred mechanism, produce executable validation checks, propose concrete
  remediation, identify contradicting evidence, and compare competing hypotheses.
  Evaluate changes against the synthetic incident fixtures before changing the default
  prompt version.
- [ ] Semantic `ClaimSupportVerifier` (SUPPORTED / PARTIAL / UNSUPPORTED) behind the same
  `CitationVerifier`-style boundary (ADR 0014), once an LLM judgment layer is justified.

## Application Logging Plan

Add useful pipeline visibility without logging secrets or raw incident evidence by
default. (Carried forward; not part of slice #7.)

- [ ] Add structured application logs for analysis-run queue/start/finish, stage
  attempt/success/failure, artifact/chunk counts, timeline candidate counts, RCA
  provider/model invocation, validated RCA output counts, citation-integrity outcomes,
  and hypothesis review decisions.
- [ ] Keep API keys, bearer headers, raw provider envelopes, full prompts, raw evidence
  bodies, and citation snippets out of default logs.
- [ ] Decide whether local development also needs an explicit opt-in payload logging mode
  for raw prompts and model completions. If added, default it off and document the
  data-exposure risk.
- [ ] Add focused logging regressions and run backend validation.
