# Slice 3: Start an asynchronous analysis run and lock used evidence

## Objective

Implement GitHub issue #4 (blocked-by #3, which is closed → unblocked): add the
first Analysis Run command path. A user starts analysis from an Incident with
selected current Artifacts, the run is created as durable, pollable async
product state, and the included Artifacts become immutable. Stage behavior is a
placeholder (real six-stage pipeline lands in #5).

## Relevant ADRs

- 0003 async run API model (status polling, internal synchronous worker is fine)
- 0004 shared service layer for UI + future CLI
- 0009 swappability demonstrated with fakes (RunExecutor)
- 0018 artifacts immutable once included in a run
- 0022 resource APIs + explicit command endpoints (start run is a command)
- 0024 explicit structured tables (analysis_runs, run_artifacts)
- 0025 experiment metadata defaults persisted on the run
- 0029 stage-level failure (run marked failed, prior state preserved)

## Implementation Plan

- [x] Confirm #4 is unblocked and study existing slices + ADRs.
- [x] Add `AnalysisRun` and `RunArtifact` models with status, experiment
  metadata defaults, and included-artifact references.
- [x] Add `AnalysisRun` schemas (create + read with artifact_ids + metadata).
- [x] Add `RunExecutor` interface + `PlaceholderRunExecutor`, and an
  `AnalysisService` that starts/fetches/lists runs and locks artifacts.
- [x] Wire run lifecycle: queued → running → succeeded; failed executor marks
  the run failed but keeps artifacts locked and prior state intact.
- [x] Add resource-oriented + command analysis-run API endpoints under
  `/api/incidents/{id}/analysis-runs`.
- [x] Fix root `.gitignore` so `frontend/src/lib/` is not swallowed by the
  Python `lib/` rule, and commit the missing `api.ts` client.
- [x] Extend the frontend API client with analysis-run methods/types.
- [x] Replace the Incident page "Analysis runs" placeholder with a real
  start-run control + run status list that reloads locked evidence.
- [x] Add backend tests: start run, immutability (409 delete/replace), body is
  unchanged source of truth, status fetch/list, no-artifact + 404 cases,
  service-layer start (CLI path), fake-executor lifecycle + failure.
- [x] Extend e2e spec to start a run and see status + locked evidence.
- [x] Run backend pytest + frontend typecheck/build; document results here.

## Notes

- `frontend/src/lib/api.ts` was authored in slice 2 but never committed because
  the root Python `.gitignore` `lib/` rule matches `frontend/src/lib/`. The
  frontend currently cannot build. Fixing this is in-scope for getting #4's UI
  acceptance criteria to actually work.
- TanStack Query polling is explicitly a #5 concern (and not installed); #4 uses
  the existing plain-fetch pattern: start the run, then fetch status afterward.

## Review

- Backend: `AnalysisRun` + `RunArtifact` tables persist run status, experiment
  metadata defaults (ADR 0025), and immutable Artifact references. `AnalysisService`
  (ADR 0004) starts/fetches/lists runs; starting locks the included Artifacts
  (`included_in_analysis_run=True`) before execution so the existing
  ArtifactService guards (ADR 0018) reject delete/replace with 409.
- `RunExecutor` is a kept interface (ADR 0009) with a no-op
  `PlaceholderRunExecutor`. The service drives queued → running → terminal; an
  executor exception marks the run `failed` with its message while keeping the
  artifact lock and run-artifact references intact (ADR 0029). Real six-stage
  behavior + Run Stage Events are deferred to #5.
- API: command + resource endpoints under
  `/api/incidents/{id}/analysis-runs` (POST start, GET list, GET one), behind
  the single-user gate. Status polling, not streaming (ADR 0003/0005).
- Frontend: reconstructed `src/lib/api.ts` (see note below) with analysis-run
  methods, and replaced the Incident page placeholder with a real start-run
  control + run status list. Starting a run reloads evidence so the lock badge
  appears and delete/replace disable.
- Fixed a real bug: the root Python `.gitignore` `lib/` rule was hiding
  `frontend/src/lib/`, so `api.ts` had never been committed and the frontend
  could not build from a clean checkout. Added a scoped negation and committed
  the client.

### Verification

- Backend: `PYTHONPATH=. python -m pytest` → 39 passed (was 30; +9 analysis +
  service/API coverage for immutability, source-of-truth body, lifecycle,
  failure, 404/422 cases).
- Frontend: `npm run typecheck` and `npm run build` both pass.
- E2E: `./scripts/e2e.sh` → 2 passed, including starting a run, seeing
  `succeeded`, and confirming the included artifact is locked.
- Note: several pre-existing e2e assertions had latent strict-mode ambiguities
  that only surfaced once the frontend could build again; tightened them to
  exact/role-scoped locators.

## Lessons captured

- A platform-default Python `.gitignore` (`lib/`) silently swallowed
  `frontend/src/lib/`. Captured in `tasks/lessons.md` so future polyglot repos
  scope language-specific ignore rules.
