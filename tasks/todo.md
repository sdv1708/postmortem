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

- [ ] Add `RunStageEvent` model: run_id, stage, status, sequence, started_at,
  completed_at, duration_ms, usage (tokens/model, nullable), warning_codes,
  attempt. Add relationship from `AnalysisRun`.
- [ ] Add schema types: `RunStage`/`StageStatus` literals, `RunStageEventRead`,
  and embed `stage_events` in `AnalysisRunRead`.
- [ ] Define the six-stage contract in one place (`pipeline.py`) so executor,
  schema, and tests share the ordered stage names.
- [ ] Implement `StagedRunExecutor` (default) that runs the six stages in order,
  persisting each event before the next; one retry per failing stage; on final
  failure mark the stage + run failed and stop, leaving prior events intact.
  Keep `PlaceholderRunExecutor` for tests / trivial swap demos.
- [ ] Have the executor own stage-event persistence via a small callback/sink
  injected by `AnalysisService` so the session boundary stays in the service
  (ADR 0004). Service still owns run-level status transitions.
- [ ] Wire `AnalysisService` to use `StagedRunExecutor` by default and to expose
  stage events on reads; keep failure semantics (run failed, lock preserved).
- [ ] Frontend: add TanStack Query + provider in layout; build a Run Status
  panel that polls the run while non-terminal and renders all six stages with
  per-stage status, duration, and warning codes.
- [ ] Backend tests: stage ordering, an event persisted per stage before the
  next, one-retry-then-success, one-retry-then-fail (run failed + later stages
  never created + earlier events preserved), warning codes surface, API shows
  stage_events and polling-visible transitions.
- [ ] Frontend: typecheck + build; extend e2e to assert the six stages render
  and the run reaches succeeded via polling.
- [ ] Self-review for elegance/standards; run all tests; document results.

## Notes

- "Async" stays product/API-level (ADR 0003): the executor runs synchronously
  within start_run, but each stage is persisted as it completes so a poller
  observes progress. To make polling-visible transitions testable without
  real latency, the executor accepts an injectable per-stage hook; tests use it
  to assert intermediate persisted state.
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

- The MVP executor runs synchronously inside `start_run` (ADR 0003: async is
  product/API-level), so a poller's first read already sees terminal state; the
  polling machinery is built for the real async future and is exercised by the
  list-level refetch today. Intermediate per-stage states are asserted at the
  service layer via an injected stage hook rather than over HTTP.
- Schema is created with `create_all` (no migrations yet); the new table is
  created fine on existing dev DBs, but column additions in later slices will
  need a migration story. Out of scope for this slice.
