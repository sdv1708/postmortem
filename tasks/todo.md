# Slice 10: Seed and run the canonical deploy ambiguity demo scenario (#11)

## Status check
Issue #11 is **not** implemented on `main`. There are no scenario fixtures,
no scenario loader, no seed path, and no scenario API. Slices 1–9 (#1–#10) are
merged. This plan covers #11 / Slice 10. Blocked-by #10 is merged (commit
cc14974), so #11 is unblocked.

## Objective
Add file-based Incident Scenario fixtures (ADR 0007) for the canonical
ambiguous deploy-related API error spike (ADR 0006) and wire them into the
product so a demo operator can seed synthetic evidence, run analysis, and review
a multi-hypothesis Postmortem — without real production logs and without a live
model (ADR 0011 fakes/replay). The founder-demo trust path (ADR 0032) must be
visible end to end: multiple hypotheses, exact citations, contradicting
evidence, an honestly-separated unsupported finding, and a structured Postmortem.

## Key design decisions
- **Scenario ships its own replay.** The fixture bundles `replay/rca.json` (the
  RCA model output, citing evidence by `source_name`) and `claim_support`
  overrides. A `ScenarioReplayLLMClient` + `ScenarioReplayClaimSupportVerifier`
  (product code, ADR 0009 swappable boundaries) make the demo deterministic and
  offline-capable. Experiment Metadata records the replay labels honestly
  (ADR 0025): `model_provider = scenario-replay:<id>`, the replay verifier
  version. This is the same fakes/replay sanctioned by ADR 0011 and used in tests.
- **Replay cites by `source_name`, resolved to artifact ids at seed time.** Human
  authors reference filenames, not UUIDs; the loader resolves `source_name` →
  `artifact_id` after artifacts are seeded, then the existing RCA stage validates
  line ranges and resolves snippets from the stored lines (ADR 0024). Nothing
  trusts model-supplied snippet text.
- **Fixture is self-validating (ADR 0007 reproducibility).** `load_scenario`
  fails fast if an evidence `path` is missing/empty, the ground-truth file is
  missing/empty, a replay ref names an unknown `source_name`, or a replay line
  range falls outside the cited evidence file.
- **Seed is a command endpoint (ADR 0022), reusing the service layer (ADR 0004).**
  `POST /api/scenarios/{id}/seed` creates the Incident + Artifacts as product
  data (ADR — scenario fixture vs product data) and starts an Analysis Run with
  the bundled replay; the web button and any future CLI share `ScenarioSeedService`.
- **Three hypotheses span the support spectrum**: deploy-regression (supported),
  pool-capacity (partial), upstream-dependency (assumption → unsupported Review
  Finding). Exercises supporting + contradicting + unknowns + honest uncertainty.

## Plan

### Fixtures (`backend/scenarios/deploy-ambiguity/`)
- [x] `scenario.yaml` manifest (metadata, ambiguity notes, evaluation tags,
  expected hypothesis families, evidence list, ground-truth + replay pointers,
  claim-support overrides).
- [x] `evidence/{deploy-notes.md,api-gateway.log,db-pool.log,oncall-notes.md}` —
  line-addressable synthetic evidence with consistent timestamps.
- [x] `replay/rca.json` — RCA output citing evidence by `source_name` + lines.
- [x] `ground_truth_postmortem.md` — human-authored reference (eval material).

### Backend
- [x] `scenarios.py` (new): validation error/not-found; dataclasses;
  `load_scenario`, `list_scenarios`; `ScenarioReplayLLMClient`,
  `ScenarioReplayClaimSupportVerifier`; `resolve_replay_rca`. Base dir from `__file__`.
- [x] `services/scenarios.py` (new): `ScenarioSeedService.seed_and_run`.
- [x] `schemas.py`: `ScenarioSummaryRead`, `ScenarioSeedRead`.
- [x] `api/scenarios.py` (new): `GET /api/scenarios`, `POST /{id}/seed`; router in `app.py`.
- [x] `services/__init__.py` exports; `pyproject.toml` adds `pyyaml`.

### Frontend
- [x] `lib/api.ts`: scenario types + `listScenarios`/`seedScenario`.
- [x] Incidents page: "Seed demo scenario" panel that seeds and navigates.

### Tests
- [x] `test_scenarios.py` (10): load/validate; missing evidence/ground-truth,
  unknown replay source, out-of-range cite all raise; `resolve_replay_rca` maps ids.
- [x] `test_services_scenarios.py`: seed creates incident + 4 artifacts; run
  succeeds; 3 ranked hypotheses; supporting + contradicting + unknowns; partial +
  unsupported/assumption finding; Postmortem drafted; offline & deterministic.
- [x] `test_api_scenarios.py`: list (auth-gated) + seed populate the Review Surface.
- [x] Backend pytest **175 passed**; frontend typecheck + build clean; Playwright
  **3 passed** (incl. new seed-and-review founder-demo path).

## Review

Slice 10 (#11) is implemented: the canonical ambiguous deploy scenario is a
file-based fixture that seeds into product data and runs the full pipeline on a
bundled replay, so a demo operator reaches a populated, multi-hypothesis Review
Surface with zero live-model dependency.

### What landed
- **File-based fixture (ADR 0006 / 0007)** under `backend/scenarios/deploy-ambiguity/`:
  `scenario.yaml`, four `evidence/` files, `replay/rca.json`, and a human-authored
  `ground_truth_postmortem.md` (evaluation material, not product output).
- **Self-validating loader** (`scenarios.py`): fails fast on a missing/empty
  evidence file, missing/empty ground-truth, an unknown replay `source_name`, or
  an out-of-range replay line cite. Replay cites evidence by `source_name`,
  resolved to seeded artifact ids at seed time; the RCA stage still resolves
  snippets from stored lines (ADR 0024).
- **Deterministic, offline replay (ADR 0011)**: `ScenarioReplayLLMClient` +
  `ScenarioReplayClaimSupportVerifier` (swappable boundaries, ADR 0009). Run
  metadata records the replay honestly (`model_provider=scenario-replay:<id>`,
  `verifier_version` includes `scenario-replay-claim-support-1`, ADR 0025).
- **Seed command (ADR 0022 / 0004)**: `ScenarioSeedService.seed_and_run` +
  `GET /api/scenarios`, `POST /api/scenarios/{id}/seed`. Frontend "Seed demo
  scenario" panel seeds and routes to the Review Surface.
- **Founder-demo trust path (ADR 0032)**: three hypotheses — deploy-regression
  (supported), pool-capacity (partial via override), upstream-dependency
  (assumption → unsupported Review Finding) — with supporting + contradicting
  evidence, unknowns, verified citations, and a drafted structured Postmortem.

### Verification
- Backend: `pytest` **175 passed** (+14). Frontend: `npm run typecheck` + `npm run
  build` clean. e2e: `npx playwright test` **3 passed** (new test seeds the
  scenario and asserts the rendered hypotheses, verified citations, and the
  separated Review Findings); `_e2e.db` removed and servers torn down.
- `git diff --check` clean (line-ending warnings only).

### Notable fix
- The repo's Python `.gitignore` `*.log` rule silently ignored the `.log`
  evidence fixtures (the lessons.md polyglot-gitignore pitfall, new form). Added a
  scoped negation `!backend/scenarios/**/*.log` and verified with `git check-ignore`
  so the demo seeds from a clean checkout. Captured in `lessons.md`.

### Deviations from the plan
- None of substance. Claim-support uses a scenario replay verifier (default
  SUPPORTED + declared overrides) rather than routing claim-support prompts
  through the replay LLM client, keeping the two swappable boundaries cleanly
  separated and matching how prior slices inject a fake verifier.

## Review Follow-up

- [x] Remove the untracked local `key` credential file and add a root ignore rule
  so it cannot be accidentally staged.
- [x] Validate scenario replay RCA JSON against the strict `RcaGenerationOutput`
  schema during fixture loading, before product rows are created.
- [x] Add regressions for schema-invalid replay fixtures and no half-seeded
  Incident/Artifact/AnalysisRun rows.

Verification:
- `backend\.venv\Scripts\python.exe -m pytest -p no:cacheprovider tests/test_scenarios.py tests/test_services_scenarios.py tests/test_api_scenarios.py` -> 16 passed.
- `backend\.venv\Scripts\python.exe -m pytest -p no:cacheprovider` -> 177 passed, 1 warning.
- `npm run typecheck` -> passed.
- `npm run build` -> passed after allowing Next.js to fetch Google Fonts.
- `git diff --check` -> no whitespace errors; Git reported line-ending warnings only.
