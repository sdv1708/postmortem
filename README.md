# Postmortem Agent

Evidence-backed incident postmortems. See `docs/PRD.md` for the full MVP PRD
and `docs/adr/` for architectural decision records.

## Status

This repository is being built out one slice at a time, tracked under issue #1.

- **Slice 1 (#2): incident workspace path** — done. Incidents can be created,
  listed, and fetched through a resource-oriented API. The default workspace
  stub is bootstrapped automatically. A single-user bearer-token gate protects
  the API, with an explicit local-dev bypass.
- **Slice 2 (#3): line-addressable evidence** — done. Artifacts can be pasted or
  uploaded, viewed with stable line numbers, and deleted or replaced before a
  run uses them.
- **Slice 3 (#4): async analysis runs + locked evidence** — done (this branch).
  A command endpoint starts an Analysis Run for an Incident over selected
  current Artifacts. The run is durable, pollable async product state with
  experiment-metadata defaults; included Artifacts become immutable so their
  bodies stay the citation source of truth. Stage behavior is a placeholder
  (`PlaceholderRunExecutor`); the six-stage status page lands in #5.
- Later slices (#5-#13) add the six-stage pipeline, citation verification,
  structured postmortems, scenario fixtures, evaluations, and refusal behavior.

## Repository layout

```
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

# Single-user gate token (any string). Required unless dev bypass is set.
export POSTMORTEM_API_TOKEN=dev-token

# Or, for purely local development, opt into the explicit bypass:
# export POSTMORTEM_DEV_BYPASS=1

# SQLite by default; override with POSTMORTEM_DATABASE_URL for Postgres.
# CORS defaults to http://localhost:3000 and http://127.0.0.1:3000.
# Override with POSTMORTEM_CORS_ORIGINS for another frontend host/port.
uvicorn postmortem.app:app --reload
```

The API is then available at `http://localhost:8000`. Health check at
`GET /healthz`. OpenAPI docs at `/docs`.

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

## Notes on this slice

- SQLAlchemy 2.x with SQLite for development; the schema uses Postgres-friendly
  column types so swapping `POSTMORTEM_DATABASE_URL` is the only change needed
  to point at Postgres.
- `IncidentService`, `ArtifactService`, and `AnalysisService` own their domain
  behavior. Routes call the services — this is the boundary the future CLI
  (Milestone 2) will share. `AnalysisService.start_run` is the start-run entry
  point both the web UI and a future CLI use.
- Analysis Runs are async at the product/API level (ADR 0003): clients POST to
  start a run and then GET its status. A `RunExecutor` does the run's work; the
  MVP ships a no-op `PlaceholderRunExecutor`, and tests swap in fakes to prove
  swappability and the single-retry-free failure path.
- The default workspace is created on app startup (idempotent) and on every
  service-level `create` so tests against a fresh DB work without explicit
  setup.
- The single-user gate (`postmortem.auth.require_user`) requires a bearer token
  matching `POSTMORTEM_API_TOKEN`. If `POSTMORTEM_DEV_BYPASS=1`, requests pass
  without a token — never set this in a hosted/demo deploy.
