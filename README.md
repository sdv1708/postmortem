# Postmortem Agent

Evidence-backed incident postmortems. See `docs/PRD.md` for the full MVP PRD
and `docs/adr/` for architectural decision records.

## Status

This repository is being built out one slice at a time, tracked under issue #1.
Milestone 1 is now implemented through the evidence-backed Review Surface: the
app can ingest evidence, run the six-stage analysis pipeline, verify citations,
compose structured postmortems, replay scenario fixtures, and record evaluations.

- **Slice 1 (#2): incident workspace path** - done. Incidents can be created,
  listed, and fetched through a resource-oriented API. The default workspace
  stub is bootstrapped automatically. A single-user bearer-token gate protects
  the API, with an explicit local-dev bypass.
- **Slice 2 (#3): line-addressable evidence** - done. Artifacts can be pasted or
  uploaded, viewed with stable line numbers, and deleted or replaced before a
  run uses them.
- **Slice 3 (#4): async analysis runs + locked evidence** - done. A command
  endpoint starts an Analysis Run for an Incident over selected current
  Artifacts. The run is durable, pollable async product state with experiment
  metadata; included Artifacts become immutable so their bodies stay the
  citation source of truth.
- **Slices 5-13: MVP analysis and review surface** - done. Runs progress through
  persisted stages for evidence normalization, timeline extraction, RCA
  hypotheses, citation verification, postmortem drafting, and unsupported-claim
  flagging. The Review Surface shows citations, support status, accept/reject
  decisions, Reviewer Notes, clean/audit Markdown export, and stage telemetry.
- **Scenario and evaluation harness** - done. File-based scenarios cover deploy
  ambiguity, dependency failure, configuration drift, and insufficient-evidence
  refusal behavior. Evaluation Runs execute scenarios independently of product
  Incident data and record deterministic checks, warning counts, judge scores
  when configured, and experiment metadata.

## Repository layout

```text
backend/    FastAPI service (Python 3.11)
frontend/   Next.js app (App Router, TypeScript, Tailwind)
docs/       PRD and ADRs
tasks/      Per-slice planning and lessons captured during work
```

## Running it locally

### Backend

```sh
cd backend
pip install -e '.[dev]'

# Edit ../.env once with POSTMORTEM_API_TOKEN, database URL, and LLM settings.
# The backend automatically loads .env before reading process environment.
uvicorn postmortem.app:app --reload
```

The API is then available at `http://localhost:8000`. Health check at
`GET /healthz`. OpenAPI docs at `/docs`.

Local `.env` files are intentionally ignored by git. Real process environment
variables still take precedence over `.env`, so one-off shell overrides and
hosted deployment settings remain authoritative.

### Frontend

```sh
cd frontend
cp .env.local.example .env.local   # set NEXT_PUBLIC_POSTMORTEM_API_TOKEN to match the backend
npm install
npm run dev
```

The UI runs at `http://localhost:3000`.

## Running the tests

```sh
cd backend
PYTHONPATH=. python -m pytest
```

```sh
cd frontend
npm run typecheck
npm run build    # also runs lint and type checks during build
```

### End-to-end UI tests

A Playwright suite drives the actual UI in headless Chromium against a real
backend.

```sh
./scripts/e2e.sh        # boots backend + frontend, runs all e2e specs, tears down
```

The script expects Playwright Chromium at `/opt/pw-browsers`. Override with
`PLAYWRIGHT_BROWSERS_PATH=...` if you've installed it elsewhere
(`npx playwright install chromium`).

## Implementation notes

- SQLAlchemy 2.x with SQLite for development; the schema uses Postgres-friendly
  column types so swapping `POSTMORTEM_DATABASE_URL` is the only change needed
  to point at Postgres.
- `IncidentService`, `ArtifactService`, and `AnalysisService` own their domain
  behavior. Routes call the services - this is the boundary the future CLI
  (Milestone 2) will share. `AnalysisService.start_run` is the start-run entry
  point both the web UI and a future CLI use.
- Analysis Runs are async at the product/API level (ADR 0003): clients POST to
  start a run and then GET its status. A `RunExecutor` advances the six persisted
  stages with one retry per failed stage and records stage events, usage, errors,
  and warning codes.
- Swappable MVP boundaries are exercised in code and tests: `LLMClient`,
  `RetrievalStrategy`, `CitationVerifier`, `ClaimSupportVerifier`,
  `PostmortemComposer`, and the evaluation judge.
- The default workspace is created on app startup (idempotent) and on every
  service-level `create` so tests against a fresh DB work without explicit
  setup.
- The single-user gate (`postmortem.auth.require_user`) requires a bearer token
  matching `POSTMORTEM_API_TOKEN`. If `POSTMORTEM_DEV_BYPASS=1`, requests pass
  without a token - never set this in a hosted/demo deploy.
