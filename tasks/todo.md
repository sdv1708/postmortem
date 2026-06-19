# Issue #33 — Finalize a supported human Root Cause Conclusion

Vertical slice across the whole stack. PRD #26 user stories 29-37, 42-43, 90.
Branch: feature/33-finalize-root-cause-conclusion (from main).

## Backend
- [ ] db.py: CAUSAL_FACTOR_ROLE_CHECK; append-only immutability triggers for
      root_cause_conclusions + causal_factors (SQLite + Postgres); wire into
      ensure_schema_compatibility.
- [ ] models.py: RootCauseConclusion (provenance + run link, immutable) and
      CausalFactor (role, hypothesis link, exactly-one-failure-mechanism index,
      unique hypothesis per conclusion).
- [ ] config.py + auth.py: single-user Principal (id + display) and
      require_principal dependency for Conclusion Provenance.
- [ ] schemas.py: CausalFactorCreate, RootCauseConclusionCreate,
      CausalFactorRead, RootCauseConclusionRead; add conclusion to PostmortemRead.
- [ ] services/conclusions.py: ConclusionService.finalize/get + read shaping
      + errors. Trust floor: accepted + supported/partial + verified citations;
      cross-run rejection; exactly one failure mechanism.
- [ ] services/analysis.py: include conclusion in get_postmortem_document.
- [ ] services/__init__.py: exports.
- [ ] api/analysis_runs.py: POST finalize (201/409/422/404) + GET conclusion.
- [ ] markdown_export.py: render finalized human conclusion section, distinct
      from advisory ranking; drop provisional banner when finalized.

## Frontend
- [ ] lib/api.ts: types + getRunConclusion / finalizeRunConclusion.
- [ ] incidents/[id]/page.tsx: RunConclusion panel.

## Docs
- [ ] ADR 0039-human-root-cause-conclusion-finalization.md.

## Tests
- [ ] test_services_conclusions.py (deep module).
- [ ] test_api_conclusions.py.
- [ ] postmortem + markdown finalized rendering.
- [ ] test_db_compatibility.py: new tables + immutability triggers.
- [ ] e2e: finalize a conclusion, separate from ranking.
- [ ] Backend regression + frontend typecheck.

## Review (done)
All backend + frontend done and green.
- Backend full suite: exit 0, 0 failures (added test_services_conclusions, test_api_conclusions, db-compat immutability tests).
- Frontend: tsc --noEmit clean.
- App builds; GET+POST /conclusion routes register; OpenAPI builds.
- e2e finalization steps added to the deploy-scenario spec (run with live servers via `npm run e2e`).

Scope notes: Partial-Support Acknowledgment, Critical-Challenge Override, Human
Assumptions, Discrepancies, Superseding, Remediation Proposals are later #26
slices (not #33). Immutability enforced via service (409 on re-finalize), no
PUT/DELETE endpoints, and SQLite/Postgres append-only triggers.
