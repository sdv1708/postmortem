# End-to-End Testing Scenario

Use this to manually test the Postmortem Agent from local configuration through
the browser Review Surface.

## Preconditions

1. Edit the repo-root `.env` with local backend settings:

   ```env
   POSTMORTEM_API_TOKEN=your-local-token
   POSTMORTEM_DEV_BYPASS=0
   POSTMORTEM_DATABASE_URL=sqlite:///./postmortem.db
   POSTMORTEM_CORS_ORIGINS=http://localhost:3000,http://127.0.0.1:3000
   POSTMORTEM_LLM_API_KEY=
   ```

2. Edit `frontend/.env.local` so the frontend can call the backend:

   ```env
   NEXT_PUBLIC_POSTMORTEM_API_BASE=http://localhost:8000
   NEXT_PUBLIC_POSTMORTEM_API_TOKEN=your-local-token
   ```

3. Start the backend:

   ```sh
   cd backend
   .\.venv\Scripts\python.exe -m uvicorn postmortem.app:app --reload
   ```

4. Start the frontend:

   ```sh
   cd frontend
   npm run dev
   ```

5. Open `http://localhost:3000/incidents`.

## Scenario A: Evidence-Backed Postmortem

Goal: prove the happy path generates a structured postmortem with citations,
hypotheses, review actions, and exports.

1. On the Incidents page, find **Deploy ambiguity after API error spike**.
2. Click **Seed demo scenario**.
3. Wait for the incident page to open and the run status to become `succeeded`.
4. Confirm the Evidence section contains multiple artifacts, including logs and
   deployment notes.
5. Open the completed analysis run.
6. Confirm the six stage rows are visible and succeeded.
7. Confirm the Timeline section shows timestamped events with clickable
   citations.
8. Confirm RCA hypotheses are shown with:
   - supporting evidence,
   - contradicting evidence where available,
   - unknowns,
   - validation steps,
   - support status badges.
9. Click a citation and confirm the Evidence panel focuses the cited artifact
   lines.
10. Add a Reviewer Note to a hypothesis.
11. Refresh the page and confirm the note persists.
12. Click **Accept** on the leading hypothesis and confirm the review status
   changes without changing the claim text.
13. Export **Clean** Markdown.
14. Confirm the clean export omits unsupported Review Findings.
15. Export **Audit** Markdown.
16. Confirm the audit export includes unsupported assumptions clearly labeled.

Expected result: the app presents a useful, evidence-backed postmortem without
inventing unsupported claims.

## Scenario B: Insufficient Evidence Refusal

Goal: prove sparse evidence produces a refusal instead of a confident root cause.

1. Return to `http://localhost:3000/incidents`.
2. Find **Insufficient evidence for confident postmortem**.
3. Click **Seed demo scenario**.
4. Wait for the incident page to open and the run status to become `succeeded`.
5. Open the completed analysis run.
6. Confirm the Postmortem panel shows:
   - `insufficient evidence`,
   - **Insufficient evidence - no confident root cause asserted**,
   - **What's missing**,
   - **Suggested next evidence**.
7. Confirm no confident RCA hypotheses section is presented.
8. Confirm the sparse source artifact is still visible in the Evidence section.
9. Export **Clean** Markdown.
10. Confirm the export includes:
    - `Evidence sufficiency: insufficient`,
    - the refusal notice,
    - what's missing,
    - suggested next evidence,
    - no confident root-cause hypothesis.

Expected result: the app refuses to write a confident postmortem and tells the
reviewer what evidence to collect next.

## Scenario C: Evaluation Dashboard

Goal: prove the scenario suite records deterministic checks and refusal behavior.

1. Open `http://localhost:3000/evaluations`.
2. Click **Run evaluation suite**.
3. Confirm rows appear for:
   - `deploy-ambiguity`,
   - `dependency-failure`,
   - `config-drift`,
   - `insufficient-evidence`.
4. Confirm normal scenarios pass citation integrity and required output checks.
5. Confirm `insufficient-evidence` passes the refusal check and records an
   `insufficient_evidence` warning.
6. Confirm judge scores are absent when no LLM API key is configured, while
   deterministic checks still run.

Expected result: evaluation distinguishes normal evidence-backed scenarios from
the refusal scenario without relying on an LLM judge.

## Quick API Smoke Checks

With the backend running:

```sh
curl http://localhost:8000/healthz
```

```sh
curl -H "Authorization: Bearer your-local-token" http://localhost:8000/api/scenarios
```

Expected result: `/healthz` returns healthy status and `/api/scenarios` lists the
scenario fixtures.

## Pass Criteria

The manual end-to-end test passes when:

- normal scenarios produce cited hypotheses and structured postmortems,
- unsupported claims remain auditable instead of authoritative,
- Reviewer Notes persist without editing generated claims,
- insufficient evidence produces a refusal banner and refusal export,
- evaluation runs record deterministic pass/fail checks for all scenarios.
