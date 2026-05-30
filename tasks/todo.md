# Slice 4: Six-stage run status page with persisted stage events

## Objective

Implement GitHub issue #5 (blocked-by #4, merged → unblocked). Make the
demo-worthy waiting experience real: an Analysis Run progresses through the six
named Run Stages, persists a Run Stage Event per stage *before* moving to the
next (ADR 0026), retries a failing stage at most once then fails the run while
preserving prior stage outputs (ADR 0029), and the UI polls run status/events
with TanStack Query (ADR 0001) — no SSE, no token streaming (ADR 0005).

## Relevant ADRs

- 0026 six-stage DB-persisted pipeline contract (persist each stage before next)
- 0021 run-centric observability: stage, status, timestamps, duration, usage,
  Warning Codes; heavy debug context stays in logs, not the event table
- 0029 stage-level failure with a single retry; prior outputs preserved
- 0005 demo-worthy status page without token streaming
- 0001 web UI first; TanStack Query for polling
- 0003 async run API model is status polling
- 0009 RunExecutor is a kept interface; swap fakes in tests

## The six stages (exact order, ADR 0026)

1. normalizing evidence
2. extracting timeline candidates
3. generating RCA hypotheses
4. verifying citations
5. drafting postmortem
6. flagging unsupported claims

## Implementation Plan

- [x] Add `RunStageEvent` model: run_id, stage, status, sequence, started_at,
  completed_at, duration_ms, usage (tokens/model, nullable), warning_codes,
  attempt. Add relationship from `AnalysisRun`.
- [x] Add schema types: `RunStage`/`StageStatus` literals, `RunStageEventRead`,
  and embed `stage_events` in `AnalysisRunRead`.
- [x] Define the six-stage contract in one place (`pipeline.py`) so executor,
  schema, and tests share the ordered stage names.
- [x] Implement `StagedRunExecutor` (default) that runs the six stages in order,
  persisting each event before the next; one retry per failing stage; on final
  failure mark the stage + run failed and stop, leaving prior events intact.
  Keep `PlaceholderRunExecutor` for tests / trivial swap demos.
- [x] Have the executor own stage-event persistence via a small callback/sink
  injected by `AnalysisService` so the session boundary stays in the service
  (ADR 0004). Service still owns run-level status transitions.
- [x] Wire `AnalysisService` to use `StagedRunExecutor` by default and to expose
  stage events on reads; keep failure semantics (run failed, lock preserved).
- [x] Frontend: add TanStack Query + provider in layout; build a Run Status
  panel that polls the run while non-terminal and renders all six stages with
  per-stage status, duration, and warning codes.
- [x] Backend tests: stage ordering, an event persisted per stage before the
  next, one-retry-then-success, one-retry-then-fail (run failed + later stages
  never created + earlier events preserved), warning codes surface, API shows
  stage_events and polling-visible transitions.
- [x] Frontend: typecheck + build; extend e2e to assert the six stages render
  and the run reaches succeeded via polling.
- [x] Self-review for elegance/standards; run all tests; document results.

## Follow-up Fix Plan: externally visible polling state

- [x] Review code-review finding: stage events were flushed inside the POST
  transaction, so external HTTP pollers could not observe them before the POST
  completed.
- [x] Add an API regression test proving POST returns a queued run before the
  background executor records stage events.
- [x] Keep service-level inline execution as the default for existing callers,
  but allow API callers to create and lock a run without executing it inline.
- [x] Commit queued run + locked Artifact state in the POST route, then execute
  the run in a background task with a fresh DB session.
- [x] Update comments/notes so they do not imply `flush()` makes cross-request
  polling visible.
- [x] Run backend and frontend regression checks; document results.

## Notes

- Service callers still default to inline execution for simple tests and future
  CLI-style flows, but the HTTP command endpoint commits the queued run and
  locked Artifact state before scheduling execution in a background session.
  This keeps polling product-level (ADR 0003) while making queued/running/stage
  transitions visible across requests.
- Usage fields (tokens/model) are nullable now — no LLM is wired until #7, so
  they stay null but the column/contract exists per ADR 0021.

## Review

- Backend: `pipeline.py` holds the single ordered six-stage contract (ADR
  0026). `RunStageEvent` persists stage/status/sequence/attempt/timestamps/
  duration_ms/usage/warning_codes (ADR 0021). `StagedRunExecutor` runs the six
  stages in order; each attempt is recorded as an event before the next stage,
  with one retry per stage then fail-and-stop (ADR 0029). `StageRecorder` owns
  event persistence; `AnalysisService` keeps the session boundary (ADR 0004)
  and marks the run failed on executor error while preserving prior events and
  the Artifact lock. Stage work is a no-op until the LLM arrives in #7.
- Frontend: TanStack Query provider (ADR 0001) drives a Run Status panel that
  polls the run list while any run is non-terminal and renders all six stages
  with per-stage status, duration, retried badge, and warning codes. No
  streaming (ADR 0005).

### Verification

- Backend: `python -m pytest` → 50 passed (was 39; +11 for stage ordering,
  persist-before-next, one-retry-then-succeed, retry-then-fail with
  preservation, warning codes, recorder sequencing, non-dict runner guard, and
  API stage_events visibility).
- Frontend: `npm run typecheck` + `npm run build` pass.
- E2E: `./scripts/e2e.sh` → 2 passed, including rendering all six stages and the
  run reaching succeeded via the polling UI.

### Follow-up fix verification

- Added regression coverage for the HTTP execution boundary: the POST response
  now returns a queued run with no stage events before the captured background
  executor runs, a separate session can observe committed running/stage
  transitions during execution, and a subsequent poll sees succeeded with all
  six stage events.
- Backend targeted regression:
  `python -m pytest backend/tests/test_api_analysis_runs.py backend/tests/test_run_executor.py backend/tests/test_services_analysis.py -q -p no:cacheprovider`
  -> 32 passed.
- Backend full suite:
  `python -m pytest backend/tests -q -p no:cacheprovider` -> 52 passed.
- Frontend: `npm run typecheck` -> passed.
- Frontend: `npm run build` -> passed after allowing the expected Google Fonts
  network fetch.
- E2E: manual Windows equivalent of `scripts/e2e.sh` -> passed. The shell script
  itself still has CRLF line endings and fails under Bash in this workspace
  before starting the app.

### Self-review (code-review skill, high effort) — fixes applied

- Restored a "Refresh status" control: the query only polls while a run is
  non-terminal, so without it a terminal/externally-started run list could go
  stale with no manual recovery.
- Hardened `eventsByStage` to keep the highest-`sequence` event per stage rather
  than relying on array delivery order, so a retried stage can't display its
  failed first attempt.
- Stage timing now shows the recorded `duration_ms` for failed (not just
  succeeded) terminal events, so observability isn't lost on failure.
- Simplified the start-run mutation to a single authoritative refetch (dropped a
  fragile optimistic prepend that wouldn't reconcile on refetch failure).
- Removed dead `RUN_STAGE_LABELS` (no backend consumer; labels live in the UI).
- Added `_normalize_outcome` so a future stage runner returning a non-dict is
  recorded as a stage failure instead of escaping as an uncaught exception.

### Known/accepted limitations

- The current stage bodies are no-op placeholders until LLM/pipeline work lands,
  so runs may still complete too quickly for a human to see every intermediate
  state. The HTTP execution boundary is now separate from the POST transaction,
  and the API regression test holds the scheduler to prove queued state is
  externally visible before execution.
- Schema is created with `create_all` (no migrations yet); the new table is
  created fine on existing dev DBs, but column additions in later slices will
  need a migration story. Out of scope for this slice.
