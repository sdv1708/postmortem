# Task: Resolve ADR conformance review findings

- [x] Add Reviewer Notes as separate review annotations with backend schema, model, service command, API endpoint, client type/method, and focused tests.
- [x] Add an insufficient-evidence/refusal scenario fixture and cover it in scenario/evaluation tests.
- [x] Add the documented `RetrievalStrategy` boundary and route RCA generation through it with metadata backed by an exercised implementation.
- [x] Refresh README implementation status so it matches the current six-stage pipeline, verification, scenarios, and evaluations.
- [x] Run focused backend/frontend verification and record results.

## Review

Resolved the ADR conformance review findings:

- Reviewer Notes are now first-class run-scoped review annotations with optional
  hypothesis attachment. They have a database model, Pydantic schemas, service
  command, `POST /api/incidents/{incident_id}/analysis-runs/{run_id}/review-notes`,
  frontend client method, Review Surface UI, and service/API tests proving notes
  do not rewrite generated claims.
- Added `backend/scenarios/insufficient-evidence/` with sparse evidence and an
  empty RCA replay. Evaluation checks now treat `insufficient-evidence` tagged
  scenarios as refusal cases, so zero citations/timeline/hypotheses can pass only
  there while normal scenarios still require the deterministic floor.
- Added `backend/postmortem/retrieval.py` with a `RetrievalStrategy` Protocol and
  deterministic chunk-backed default. RCA generation now retrieves candidates
  through that boundary, run metadata records the real retrieval version, and a
  test injects an alternate strategy.
- Refreshed `README.md` status from stale Slice 3 placeholder text to the current
  MVP implementation state.

Verification:

- `backend\.venv\Scripts\python.exe -m pytest -p no:cacheprovider tests/test_services_hypotheses.py tests/test_api_hypotheses.py tests/test_scenarios.py tests/test_evaluation_runner.py tests/test_api_evaluations.py tests/test_stages_rca.py tests/test_db_compatibility.py` -> 57 passed.
- `npm run typecheck` -> passed.
- `backend\.venv\Scripts\python.exe -m pytest -p no:cacheprovider` -> 205 passed, 1 existing deprecation warning from `HTTP_422_UNPROCESSABLE_ENTITY`.
- `git diff --check` -> no whitespace errors; Git reported CRLF conversion warnings only.
