# Postmortem Agent

**Turn scattered incident evidence into a postmortem you can actually trust.**

After an outage, the facts are spread across log dumps, stack traces, deploy notes, and
whatever someone typed into Slack at 2am. Writing the postmortem means reconstructing what
happened from all of that — slowly, from memory, after the context has already faded.

AI can draft that document in seconds. The problem is trust: a confident-sounding writeup
that you *can't trace back to the evidence* is worse than useful, because it hides its
mistakes inside fluent prose. Engineers won't (and shouldn't) act on it.

Postmortem Agent is built around that problem. It's **an evidence-review tool that happens
to draft the postmortem** — not a text generator. Every claim it makes is either linked to
the exact lines of evidence that back it, or it's clearly marked as an assumption. And it
never declares the root cause on its own: a human does that, deliberately.

## Why it's different

- **Every claim is cited or flagged.** Each statement about impact, timeline, or cause
  points to specific, immutable lines in your uploaded evidence. The snippet shown must
  match the source exactly. If a claim has no support, it's labeled an assumption — it can't
  hide in the narrative.
- **It argues with itself.** A first model pass tends to latch onto one tidy explanation.
  Here, after one component proposes root-cause hypotheses, a separate **falsifier** pass
  tries to knock each one down with counter-evidence and points out what's missing. You see
  the competing explanations, not just the winner.
- **It admits when it doesn't know.** If the evidence is too thin or contradictory, it says
  so instead of inventing a plausible story.
- **The human stays in charge.** The tool produces a *draft* — a "Provisional Postmortem."
  A person reviews it and finalizes the official **Root Cause Conclusion**. If new
  information later proves that conclusion wrong, you don't edit history — you append a new
  conclusion that supersedes it, keeping a clear audit trail.

## How it works

```
  Upload evidence  ──►  Run analysis  ──►  Review the draft  ──►  Finalize the conclusion
  (logs, traces,        (6 visible           (cited claims,         (a human decides the
   deploy notes)         stages)              competing causes)       root cause)
```

1. **Create an incident and add evidence.** Paste or upload logs, stack traces, and notes.
   Everything is line-numbered so it can be cited precisely. Once you start an analysis the
   evidence is locked, so citations can never drift.

2. **Start an analysis run.** It runs in the background through six visible stages you can
   watch on a status page:

   | Stage | What happens |
   |-------|--------------|
   | 1. Normalizing evidence | Parse sources, pull out timestamps, index every line |
   | 2. Extracting incident facts | Build a cited timeline and impact summary |
   | 3. Analyzing causal hypotheses | Propose root causes, then challenge each one |
   | 4. Verifying citations | Check every citation is real and supported |
   | 5. Drafting the postmortem | Compose the document from verified facts only |
   | 6. Flagging unsupported claims | Mark anything uncited as an assumption |

3. **Review the draft.** The Review Surface shows the timeline, impact, and competing
   root-cause hypotheses. Click any citation to jump to the exact evidence lines. Supporting
   *and* contradicting evidence are both shown. The whole thing is badged
   "Draft: root cause not finalized" until a human signs off.

4. **Finalize a conclusion.** A reviewer chooses the real root cause — one **failure
   mechanism** plus any **triggers** or **amplifying conditions** — drawn only from
   hypotheses the evidence actually supports. That conclusion is locked. If it's later
   disputed, a reviewer appends a **superseding conclusion** rather than rewriting the old
   one.

## How good is it, really?

The project ships with realistic example incidents (an ambiguous deploy error spike, a
dependency outage, slow configuration drift, and a deliberately under-evidenced case) and an
evaluation harness that measures the analysis against known-good answers. It specifically
checks the hard things — did it find the counter-evidence? did it weigh the alternative
explanations? did it refuse when it should have? — and compares the full "argue-with-itself"
pipeline against a naive single-pass baseline on both quality and cost.

## Tech at a glance

A FastAPI + SQLAlchemy backend (Python 3.11+) and a Next.js + TypeScript frontend. It uses
one configured LLM provider, runs fine offline with deterministic stand-ins for the demo,
and stores everything in SQLite for local dev (swap one env var for Postgres). The design
keeps the model on a short leash: strict structured outputs, deterministic citation checks
that don't depend on the model, and a bounded reasoning budget so a run's cost stays
predictable.

For the full reasoning behind every design choice, see the Product Requirements Doc in
[`docs/PRD.md`](docs/PRD.md) and the architectural decision records in
[`docs/adr/`](docs/adr/).

---

## Running it locally

### Backend

```sh
cd backend
pip install -e '.[dev]'

# Edit ../.env once with POSTMORTEM_API_TOKEN, the database URL, and LLM settings.
# The backend automatically loads .env before reading process environment.
uvicorn postmortem.app:app --reload
```

The API is then available at `http://localhost:8000` (health check at `GET /healthz`,
interactive API docs at `/docs`).

Common environment variables (all optional for local dev):

| Variable | Purpose |
|----------|---------|
| `POSTMORTEM_API_TOKEN` | Bearer token for the single-user gate |
| `POSTMORTEM_DEV_BYPASS=1` | Skip the token locally — **never** set in a hosted deploy |
| `POSTMORTEM_DATABASE_URL` | Defaults to local SQLite; point at Postgres to swap |
| `POSTMORTEM_LLM_BASE_URL` / `POSTMORTEM_LLM_API_KEY` / `POSTMORTEM_LLM_MODEL` | The LLM provider. With no API key the pipeline runs offline and still completes all six stages |
| `POSTMORTEM_PRINCIPAL_ID` / `POSTMORTEM_PRINCIPAL_DISPLAY` | Identity recorded when a human finalizes a conclusion |
| `POSTMORTEM_LOG_LEVEL=DEBUG` | Verbose local diagnostics |

Local `.env` files are git-ignored, and real environment variables always win over `.env`,
so shell overrides and hosted settings stay authoritative. Default `INFO` logging records
run lifecycle, stages, and warnings without ever logging evidence bodies, prompts, API keys,
or reviewer notes.

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
# Backend
cd backend
PYTHONPATH=. python -m pytest

# Frontend
cd frontend
npm run typecheck
npm run build    # also runs lint and type checks
```

End-to-end Playwright tests drive the real UI against a real backend:

```sh
./scripts/e2e.sh        # boots backend + frontend, runs all e2e specs, tears down
```

The script expects Playwright Chromium at `/opt/pw-browsers`; override with
`PLAYWRIGHT_BROWSERS_PATH=...` if installed elsewhere (`npx playwright install chromium`).

## Repository layout

```text
backend/    FastAPI service (Python 3.11+); scenarios/ holds the example incidents
frontend/   Next.js app (App Router, TypeScript, Tailwind)
docs/       PRD and architectural decision records
tasks/      Per-slice planning and lessons captured during the build
scripts/    End-to-end test harness
```
