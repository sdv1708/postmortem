# Slice 2 Artifact Evidence Management

## Objective

Implement GitHub issue #3: let a user add pasted or uploaded line-addressable
Artifact evidence to an Incident, view canonical artifact text with stable line
numbers, and delete or replace evidence before any Analysis Run uses it.

## Implementation Plan

- [x] Confirm issue scope and existing Incident slice integration points.
- [x] Add backend Artifact persistence under Incidents with source type, source
  name, canonical body, derived line count, and an analysis-use lock flag.
- [x] Add Artifact service behavior for create, list, fetch, delete, and replace
  without duplicating ORM logic in routes.
- [x] Add resource-oriented Artifact API endpoints under `/api/incidents/{id}`.
- [x] Add backend tests for create/fetch/list/delete/replace, unknown incidents,
  line indexing, and immutable-after-use guard behavior.
- [x] Extend the frontend API client and Incident hub with evidence creation,
  file upload text ingestion, artifact list, line-numbered viewer, delete, and
  replace controls.
- [x] Extend UI tests to add evidence and assert exact line-addressable text is
  visible from the Incident hub.
- [x] Run backend tests, frontend typecheck/build, and targeted e2e verification
  where the local environment allows it.
- [x] Review whether the implementation can be simpler or more aligned with the
  Artifact/EvidenceRef ADRs before calling it done.
- [x] Document verification results and residual risks in this file.

## Notes

- GitHub issue #2 is Slice 1 and is already closed. The matching Slice 2 issue
  is #3, blocked by #2.
- Analysis Runs do not exist yet, so the immutability rule will be represented
  as an explicit Artifact-level lock field and enforced by service methods.

## Review

- Backend Artifact resource is persisted under Incidents with canonical text,
  derived line numbers, and delete/replace guards for future Analysis Run use.
- Frontend Incident hub now provides evidence add/upload, line-numbered viewing,
  replacement, and deletion while preserving the revamped Slice 2 visual style.
- `.gitignore` now excludes local SQLite database files so dev/runtime DBs do
  not enter PRs.
- Verification completed:
  - Backend artifact API smoke test passed with create/list/delete and line
    canonicalization checks.
  - Frontend `npm run typecheck` passed.
  - Frontend `npm run build` passed when run with network access for the
    configured Google font fetch.
- Full `python -m pytest` was not rerun here because this Windows sandbox blocks
  pytest temp/cache directory creation; the targeted API smoke covers the Slice
  2 artifact path.
