# Postmortem Agent

Evidence-backed incident postmortems. See `docs/PRD.md` for the full MVP PRD
and `docs/adr/` for architectural decision records.

## Status

This repository is being built out one slice at a time, tracked under issue #1.

- **Slice 1 (#2): incident workspace path** — done (this branch). Incidents can
  be created, listed, and fetched through a resource-oriented API. The default
  workspace stub is bootstrapped automatically. A single-user bearer-token gate
  protects the API, with an explicit local-dev bypass.
- Later slices (#3-#13) add evidence upload, async runs, the six-stage
  pipeline, citation verification, structured postmortems, scenario fixtures,
  evaluations, and refusal behavior.

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

## Notes on this slice

- SQLAlchemy 2.x with SQLite for development; the schema uses Postgres-friendly
  column types so swapping `POSTMORTEM_DATABASE_URL` is the only change needed
  to point at Postgres.
- `IncidentService` owns incident create/list/get. Routes call the service —
  this is the boundary the future CLI (Milestone 2) will share.
- The default workspace is created on app startup (idempotent) and on every
  service-level `create` so tests against a fresh DB work without explicit
  setup.
- The single-user gate (`postmortem.auth.require_user`) requires a bearer token
  matching `POSTMORTEM_API_TOKEN`. If `POSTMORTEM_DEV_BYPASS=1`, requests pass
  without a token — never set this in a hosted/demo deploy.
