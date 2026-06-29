# Incident Deletion

## Plan
- [x] Add a backend incident delete command that returns 204 for draft incidents and a clear conflict once analysis history exists.
- [x] Add API/client coverage so the frontend can call `DELETE /api/incidents/{id}` safely.
- [x] Add frontend delete controls for created incidents, with loading and failure states.
- [x] Verify with focused backend tests and frontend type checking.

## Review
- Added `DELETE /api/incidents/{id}`. Draft incidents delete with 204; analyzed incidents without finalized human conclusions now delete with their run outputs and evidence. Incidents with finalized human conclusions still return 409 because those conclusion rows are append-only.
- Added frontend delete actions on the incident list and incident detail page. The detail-page action covers the create redirect path immediately after POST.
- Added backend API tests for successful delete, missing incident, and analysis-run conflict.
- Added a Playwright create/delete scenario.
- Verification run:
  - `pytest test_delete_created_incident` passed.
  - `pytest test_delete_unknown_incident_returns_404` passed.
  - `pytest test_delete_incident_with_analysis_run` passed.
  - Focused delete group (`created`, `unknown`, `with analysis run`) passed.
  - `npm run typecheck` passed.
  - Local server smoke test passed: create incident, add evidence, start analysis to `succeeded`, delete incident returned 204.
  - Full `test_api_incidents.py` run timed out in this Windows environment after pytest temp/stdout handling; the new tests were verified individually.
  - `npm run lint` did not run because the existing `next lint` script resolves `lint` as an invalid project directory.
