# Slice 1 — Incident workspace path (Issue #2 under PRD #1)

## Why this scope

Issue #1 is the umbrella PRD; the work decomposes into slices #2-#13.
Slice 1 (#2) is the only unblocked slice and establishes the vertical
shape for every later slice. Doing it well is more useful than half-doing
all twelve.

## Acceptance criteria (from #2)

- [x] Default Workspace stub exists; incidents persist under it.
- [x] Resource-oriented API endpoints support creating and fetching incidents.
- [x] Service layer owns incident creation/fetch (callable from routes and a future CLI).
- [x] Tests prove an incident can be created through the API.
- [x] UI workflow hub: list, create, overview routes.
- [x] Hosted/demo access protected by MVP single-user gate with explicit local-dev bypass.

## Plan

### Backend
- [x] Project skeleton: `backend/pyproject.toml`, `backend/postmortem/` package, pytest config
- [x] DB layer: SQLAlchemy engine/session, SQLite for dev/test (Postgres-compatible columns)
- [x] Models: `Workspace`, `Incident` with `workspace_id` FK to default workspace stub
- [x] Default workspace bootstrapped on app startup (idempotent)
- [x] Pydantic schemas for incident create/read
- [x] Service layer: `IncidentService.create`, `IncidentService.get`, `IncidentService.list`
- [x] Single-user gate dependency: `Authorization: Bearer <token>` from `POSTMORTEM_API_TOKEN` env;
      explicit `POSTMORTEM_DEV_BYPASS=1` opt-out for local dev
- [x] Resource API:
  - `POST /api/incidents`
  - `GET  /api/incidents`
  - `GET  /api/incidents/{id}`
- [x] Tests:
  - service: create + get + list against real SQLite session
  - API: create + list + get with auth, plus 401 without auth, plus dev-bypass

### Frontend (minimal)
- [x] Next.js + TypeScript + Tailwind
- [x] `/incidents` list page (TanStack Query fetch)
- [x] `/incidents/new` create form
- [x] `/incidents/[id]` overview page (workflow hub stub with sections for evidence, runs, postmortem)

### Polish
- [x] README with run instructions for backend + frontend
- [x] Commit on `claude/implement-issue-1-FGyX0`
- [x] Push

## Out of scope for this slice (deferred to later issues)
- Artifacts / evidence upload (#3)
- Analysis runs / run executor (#4-#5)
- Pipeline stages (#6-#10)
- Scenario fixtures / evaluation (#11-#13)
- Real LLM client (no LLM calls in this slice)

## Review notes

- Backend: 12 tests pass (`pytest`), covering service CRUD, idempotent default
  workspace, API auth (valid token, missing token, wrong token), dev bypass,
  404 on unknown id, and 422 on invalid severity.
- Frontend: `tsc --noEmit` clean; `next build` succeeds for all routes
  (`/`, `/incidents`, `/incidents/new`, `/incidents/[id]`).
- Schema is Postgres-compatible despite SQLite default; switching is just an
  env var.
- Service layer is the only path between routes and the ORM, so the future
  CLI (Milestone 2) can share it without duplication.
