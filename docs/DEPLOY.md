# Deploying to Render (with Neon Postgres)

Two services — a FastAPI backend (persistent server, runs the background analysis)
and a Next.js frontend (Node server, runs the token-hiding BFF proxy) — plus an
external Neon Postgres database. The [`render.yaml`](../render.yaml) blueprint at
the repo root defines both services.

## Why this shape
- **Backend needs a persistent server**, not serverless: an analysis run executes
  as an in-process background task *after* the HTTP response returns. Serverless
  (e.g. Vercel functions) would freeze the process and the run would never finish.
- **Frontend must be a Node server** (`next start`), not a static export: the BFF
  proxy at `/bff/[...path]` runs server-side to attach the secret bearer token.
- The browser never receives the token; both services share one generated
  `POSTMORTEM_API_TOKEN` via a Render env group.

## Steps

1. **Push `render.yaml` to your default branch** (it must be on the branch Render
   reads — usually `main`).

2. **Render → New → Blueprint**, connect this repo. Render reads `render.yaml` and
   proposes `postmortem-backend` and `postmortem-frontend`. Apply.

3. **Set the secrets** (marked `sync: false`, not in git):
   - `postmortem-backend` → `POSTMORTEM_DATABASE_URL` = your Neon connection
     string. A raw `postgresql://…` works; the app rewrites it to the psycopg3
     driver automatically. Keep Neon's `?sslmode=require`.
   - `postmortem-backend` → `POSTMORTEM_LLM_API_KEY` = your provider key.
   - Let the backend deploy first; confirm `GET /healthz` on its URL returns
     `{"status":"ok"}`.

4. **Wire the frontend to the backend:**
   - `postmortem-frontend` → `POSTMORTEM_API_ORIGIN` = the backend's URL
     (e.g. `https://postmortem-backend.onrender.com`).
   - If Render assigned the frontend a different name, update the backend's
     `POSTMORTEM_CORS_ORIGINS` to the real frontend URL (not strictly required —
     the browser only talks to the frontend origin — but keep it accurate).
   - Redeploy the frontend so it picks up `POSTMORTEM_API_ORIGIN`.

5. **Verify live** (see the checklist below).

## Post-deploy verification

- `curl https://<backend>/healthz` → `{"status":"ok"}`.
- `curl https://<backend>/api/incidents` (no auth) → **401** (gate enforced;
  `POSTMORTEM_DEV_BYPASS` is `false`).
- Open `https://<frontend>/incidents` → loads and lists incidents (the browser
  called `/bff/api/incidents`; the proxy added the token server-side).
- **Confirm the token is not exposed:** open browser devtools → Network on the
  frontend; requests go to `…/bff/…` with **no `Authorization` header** from the
  browser. View-source / bundle search for the token finds nothing.
- Trigger one real analysis run end-to-end to confirm the live LLM path.

## Notes & caveats

- **Free plan** web services sleep after ~15 min idle; the first request wakes
  them with a cold start (tens of seconds). Fine for a demo.
- **Neon autosuspend:** handled — the engine uses `pool_pre_ping` + a 5-minute
  `pool_recycle`, so a request after idle reconnects instead of erroring.
- **Cost-abuse (accepted risk):** live LLM + no login gate means anyone can use
  the public site and spend your budget *through* the proxy. The proxy's per-IP
  rate limit (30 mutations/min) is a per-instance speed bump, not access control.
  If abuse appears, add a login gate or a provider-side spend cap.
- **Schema:** the app runs `create_all` + compatibility triggers on startup, so a
  fresh Neon database is provisioned automatically on first boot (validated
  against real Neon).
