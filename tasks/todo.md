# Issue #28 — Challenge every initial RCA hypothesis

Branch: `feature/28-challenge-rca-hypotheses` (parent epic #26, blocked-by #27 done)

## Goal
Add a bounded **falsifier** Reasoning Role to the Causal Analysis Stage (stage 3).
Every initial RCA Hypothesis receives exactly one persisted **Hypothesis Challenge**
(severity `critical`/`material`/`minor`, cited **Counterclaims** or assumption marker,
**Evidence Gaps**, **Falsification Tests**). Missing or invalid challenge coverage fails
stage 3 after its existing retry, preserves prior outputs, and never looks successful.
The hypotheses resource + Review Surface expose challenge content with exact citation nav.

Covers PRD user stories 3-13, 24, 57-58, 74-79, 88-89.

## Key design decisions
- New Reasoning Role `Falsifier` behind a swappable interface (own strict schema, prompt,
  version) — mirrors `IncidentFactExtractor`. One model call per hypothesis returning one
  `HypothesisChallengeOutput`; same configured model may back all roles (honest metadata).
- `Counterclaim` is a Major Claim: cited EvidenceRefs resolved from stored lines, else
  `assumption=True` (ADR 0013). Evidence Gaps / Falsification Tests are procedural string
  lists (no citations). Counterclaim refs are a new 5th EvidenceRef owner, audited by stage 4.
- Falsifier sees ALL run artifacts (Falsification Retrieval across all artifacts, US13).
- Complete-coverage runtime gate: if any hypothesis lacks a valid challenge after the single
  retry, stage 3 fails (no degrade to builder-only, no provisional draft) — US61/62.
- Scenario seed/demo path injects a `ScenarioReplayFalsifier` + bundled `replay/falsification.json`.

## Plan (checkable)
### Backend — contracts & model
- [ ] `falsification.py`: `HypothesisChallengeOutput` strict schema, `FalsificationCounterclaim`,
      prompt builder, `Falsifier` protocol, `LLMFalsifier`, versions.
- [ ] `models.py`: `HypothesisChallenge` (1:1 hypothesis, severity check), `Counterclaim`,
      `EvidenceRef.counterclaim_id`, update owner-check constant to 5 owners.
- [ ] `db.py`: owner-check constant + counterclaim_id column add + recreate owner triggers
      (SQLite) / drop+re-add owner CHECK (PG); validation tolerant of NULL new owner.

### Backend — pipeline
- [ ] `stages.py`: stage 3 — after persisting hypotheses, challenge each via the falsifier;
      persist challenge + counterclaims (resolve refs / assumption); complete-coverage gate raises.
- [ ] `stages.py`: `_run_evidence_refs` includes counterclaim refs (stage-4 audit).
- [ ] `_clear_hypotheses` cascade covers challenges (FK ondelete cascade).

### Backend — read models / API / services
- [ ] `schemas.py`: `CounterclaimRead`, `HypothesisChallengeRead`, `HypothesisRead.challenge`.
- [ ] `services/analysis.py`: `hypothesis_read` includes challenge serialization.
- [ ] inject `falsifier` through `AnalysisService` + `PipelineStageRunner`.

### Scenarios
- [ ] `scenarios.py`: `ScenarioReplayFalsifier` + load+validate `replay/falsification.json`.
- [ ] `services/scenarios.py`: inject replay falsifier in `seed_and_run`.
- [ ] Author `replay/falsification.json` for deploy-ambiguity, dependency-failure, config-drift.

### Frontend
- [ ] `lib/api.ts`: `Counterclaim`, `HypothesisChallenge`, `Hypothesis.challenge` types.
- [ ] `incidents/[id]/page.tsx`: render challenge (severity, challenged claim, counterclaims w/
      citation nav, evidence gaps, falsification tests) in `HypothesisCard`.

### ADR + tests
- [ ] ADR 0034: bounded falsifier as a persisted stage-3 substep / new Reasoning Role.
- [ ] `_fakes.py`: `FakeFalsifier`; update existing hypothesis-producing tests to inject it.
- [ ] New tests: falsification stage (coverage, counterclaim cite/assumption, severity),
      coverage-failure (stage fails after retry, prior outputs preserved), API challenge surfacing,
      db-compat (counterclaim_id column + 5-owner constraint).
- [ ] e2e: assert challenge content on the demo Review Surface.
- [ ] full backend pytest + frontend typecheck/build.

## Review

Implemented as a vertical slice across the whole stack. All plan items done; full
backend suite green (231 passed, +10 new) and frontend typecheck clean.

**Backend**
- New `falsification.py`: strict `HypothesisChallengeOutput` / `FalsificationCounterclaim`
  contracts, `build_falsification_prompt`, `Falsifier` protocol + `LLMFalsifier` (one model
  call per hypothesis), `HypothesisToChallenge` Role Handoff, versions.
- Models: `HypothesisChallenge` (1:1 hypothesis, severity CHECK), `Counterclaim`,
  `EvidenceRef.counterclaim_id` (5th owner). Owner-check constant grown to 5 owners.
- Stage 3 (`_generate_rca`) now runs the falsifier substep after the builder: challenges every
  hypothesis, persists challenge + counterclaims (cited-or-assumption), mandatory complete-coverage
  gate. The falsifier sees ALL run artifacts (Falsification Retrieval, US13). Counterclaim refs
  audited by stage 4. `_clear_hypotheses` cascade keeps the substep idempotent across the retry.
- `db.py`: idempotent `counterclaim_id` column + index; owner triggers recreated (SQLite) /
  owner CHECK dropped+re-added (PG) for the new condition. Verified clean + idempotent against a
  copy of the real dev DB (no FK violations).
- Read models / services: `CounterclaimRead`, `HypothesisChallengeRead`, `HypothesisRead.challenge`;
  `hypothesis_read` serializes the challenge. Falsifier injected through `AnalysisService` and
  `PipelineStageRunner`.

**Scenarios**: `ScenarioReplayFalsifier` + per-hypothesis `replay/falsification.json` for the three
hypothesis scenarios; loader validates refs, strict schema, and complete title coverage; seed path
injects the replay falsifier. Demo verified end-to-end: 3 challenges, verified counterclaim citations.

**Frontend**: `Counterclaim`/`HypothesisChallenge`/`ChallengeSeverity` types; `ChallengePanel` +
`ChallengeSeverityBadge` render severity, challenged claim, cited counterclaims (navigable to exact
evidence), evidence gaps, and falsification tests in each hypothesis card.

**ADR**: 0034 (bounded falsifier as a persisted stage-3 substep / new Reasoning Role).

**Tests**: `FakeFalsifier` added; existing hypothesis-producing tests inject it (same pattern as the
incident-facts / claim-support roles). New: `test_stages_falsification.py` (coverage, cited vs
assumption counterclaim, all-artifacts retrieval, coverage-failure fails stage after retry + no draft
+ prior outputs preserved, offline-no-challenge, retry idempotency), API challenge-surfacing test,
db-compat counterclaim-owner test, scenario falsification loader tests, e2e demo challenge assertions.

**Deliberate scope boundaries (deferred to later #26 slices)**: Proposed RCA Hypotheses
(alternative expansion), Advisory Ranking, Reasoning Budgets / Targeted Repair beyond the existing
stage retry, Model Call Records, semantic claim-support for counterclaims, and Markdown rendering of
challenges. Counterclaims here satisfy "verified EvidenceRefs" via the deterministic stage-4 audit.

**Note for reviewer**: e2e is written but not executed here (needs the running web + api servers).
Backend integration was verified through the real app via TestClient (seed → hypotheses endpoint
surfaces challenges with verified citations).
