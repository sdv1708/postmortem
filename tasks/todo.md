# Issue #27 — Extract run-level incident facts

Branch: `feature/27-run-level-incident-facts` (parent epic #26)

## Goal
Make incident facts (Impact Claims) a complete **run-level** product path, produced in
the renamed stage 2 **"Extracting incident facts"**, shown **once** across API / Review
Surface / Markdown exports regardless of hypothesis count. Rename stage 3 to
**"Analyzing causal hypotheses"**. Keep six visible stages and DB-persisted handoffs.

Covers PRD user stories 1–2 and 54–56.

## Key design decision
Impact Claims move from `Hypothesis` ownership to `AnalysisRun` ownership, and impact
**generation** moves out of the stage-3 RCA model output into stage 2 via a dedicated,
strict structured LLM contract (`IncidentFactsOutput`) behind a swappable
`IncidentFactExtractor` boundary. Offline path returns `{}` so both strict schemas
validate empty. This realizes PRD US1 "incident facts separated from causal interpretation."

## Plan (checkable)

### Backend — contracts & model
- [ ] Rename stage identifiers in `pipeline.py`: `extracting_timeline_candidates` →
      `extracting_incident_facts`, `generating_rca_hypotheses` → `analyzing_causal_hypotheses`.
- [ ] `models.py`: `ImpactClaim` — drop `hypothesis_id`, add `run_id` (FK run, NOT NULL);
      add `AnalysisRun.impact_claims` relationship; remove `Hypothesis.impact_claims`.
- [ ] New `incident_facts.py`: `IncidentFactsOutput` strict schema + `build_incident_facts_prompt`
      + `IncidentFactExtractor` protocol + `LLMIncidentFactExtractor` default + version.
- [ ] `rca.py`: remove `RcaImpactClaim` + `impact_claims` from `RcaHypothesis`/prompt.
- [ ] `llm.py`: `OfflineLLMClient` returns `{}`; give `RcaGenerationOutput.hypotheses` a default.

### Backend — pipeline stages
- [ ] `stages.py`: stage 2 (`_extract_incident_facts`) — keep deterministic timeline +
      add run-level impact-claim generation via extractor; clear run impact on retry.
- [ ] `stages.py`: stage 3 (`_generate_rca`) — stop creating impact claims.
- [ ] `stages.py`: `_run_evidence_refs` — join impact refs by `ImpactClaim.run_id`.
- [ ] `stages.py`: `_flag_unsupported_claims` — classify run-level impact claims.

### Backend — read models / API / export
- [ ] `schemas.py`: rename `RunStage` literals; remove `impact_claims` from `HypothesisRead`;
      add `impact_claims` to `PostmortemRead`.
- [ ] `services/analysis.py`: read-model + `get_postmortem_document` run-level impact;
      add `list_impact`.
- [ ] `api/analysis_runs.py`: add `GET /{run_id}/impact` endpoint.
- [ ] `markdown_export.py`: render impact once from run-level claims.

### Backend — DB compatibility
- [ ] `db.py`: migrate existing `impact_claims` to run-level without losing data
      (SQLite rebuild; Postgres add/backfill/not-null/drop). Keep EvidenceRef owner check.

### Scenarios / replay
- [ ] Add per-scenario `incident_facts.json` replay; strip impact from `rca.json`.
- [ ] `scenarios.py` loader + replay wiring for incident facts.

### Frontend
- [ ] `lib/api.ts`: rename `RunStage` + labels; move `impact_claims` to `Postmortem`.
- [ ] `incidents/[id]/page.tsx`: render run-level Impact section once; drop per-hypothesis impact.

### ADR + tests
- [ ] ADR 0033 superseding affected parts of 0026 (impact → stage 2 / run-level; stage labels).
- [ ] Update existing backend tests; add integration tests for 0/1/multiple hypotheses and
      impact independence from hypothesis review decisions.
- [ ] Run full backend pytest + frontend typecheck/build.

## Review

Implemented as a vertical slice across the stack. All plan items done.

**Backend**
- `ImpactClaim` re-owned from `Hypothesis` to `AnalysisRun` (`run_id` FK); `AnalysisRun.impact_claims`
  relationship added; `Hypothesis.impact_claims` removed.
- New `incident_facts.py`: strict `IncidentFactsOutput` contract, `build_incident_facts_prompt`,
  `IncidentFactExtractor` protocol + `LLMIncidentFactExtractor` default.
- Stage 2 renamed `extracting_incident_facts` (timeline + run-level impact via the extractor);
  stage 3 renamed `analyzing_causal_hypotheses` (RCA no longer emits impact). Flagging + citation
  walks updated to run-level impact.
- Read models / API: `PostmortemRead.impact_claims`, `HypothesisRead.impact_claims` removed,
  new `GET /analysis-runs/{id}/impact`, `AnalysisService.list_impact_claims`.
- Markdown export renders impact once from run-level claims.
- `db.py`: idempotent SQLite-rebuild / Postgres alter migration backfilling `run_id` from the
  former hypothesis; EvidenceRef owner constraint untouched.
- Offline client returns `{}`; both strict contracts default their collections to empty.

**Scenarios**: per-scenario `incident_facts.json` replays added, impact stripped from `rca.json`,
loader + `ScenarioReplayIncidentFactExtractor` wired through `seed_and_run`.

**Frontend**: stage labels + `RunStage` renamed; `impact_claims` moved to `Postmortem`; new
`RunImpact` panel renders impact once between timeline and hypotheses; per-hypothesis impact removed.

**ADR**: 0033 added; 0026 annotated as partially superseded.

**Tests**: full backend suite green (219 passed). Added `FakeIncidentFactExtractor`, a db-compat
migration test, and run-level impact assertions incl. independence from hypothesis review decisions
(0/1/multiple hypotheses covered across stage + API tests). Frontend `next build` (typecheck) clean;
e2e stage-label expectations updated. Canonical demo verified end-to-end: 3 hypotheses + 2 run-level
impact claims, renamed stages.

**Note for reviewer**: design decision — impact *generation* moved into stage 2 (a dedicated
Reasoning Role), realizing PRD US1 "facts separated from causal interpretation," not just re-owning
the row. This is the intended direction for epic #26.

### Adversarial-review follow-ups (both fixed)
- **Legacy run-stage rows would fail the renamed API schema**: added a `run_stage_events.stage`
  data migration (`extracting_timeline_candidates` → `extracting_incident_facts`,
  `generating_rca_hypotheses` → `analyzing_causal_hypotheses`) + a compat test that also validates
  the migrated values through `RunStageEventRead`.
- **SQLite impact rebuild dangled EvidenceRef FKs**: the rename-the-referenced-table approach made
  `evidence_refs.impact_claim_id` point at the dropped legacy table. Switched to a
  create-new / drop-old / rename-new rebuild on an AUTOCOMMIT connection with `foreign_keys` off;
  added a test asserting the citation FK resolves to `impact_claims` and `PRAGMA foreign_key_check`
  is clean for `evidence_refs`. Backend suite now 221 passed.
