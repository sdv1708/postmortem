# Slice 5: Normalize evidence into source-aware chunks and timeline candidates

## Objective

Implement GitHub issue #6 (blocked-by #5, merged → unblocked). Turn the raw
Artifacts in a run into auditable normalized evidence and initial Timeline
Events. A user runs analysis on timestamped evidence and sees sorted timeline
candidates that preserve original timestamp text and cite exact Artifact lines.

No LLM in this slice (that is #7). All work here is deterministic and runs
inside the existing `StagedRunExecutor` stage_runner hook.

## Relevant ADRs / PRD

- 0027 source-type-aware line-window chunking, 15% overlap; chunks are
  retrieval aids, EvidenceRefs point to artifact line ranges not chunk ids.
- 0019 normalize timestamps to UTC, preserve original text, label inferred /
  uncertain timestamps.
- 0024 explicit structured tables (timeline_events, evidence_refs); EvidenceRefs
  relational, not JSON-only.
- 0026 each stage persists output to the DB before the next stage starts.
- 0025 Experiment Metadata records the Chunking Strategy version used.
- 0009 ChunkingStrategy is a kept interface; demonstrate via fakes/tests.
- PRD chunking rules: logs = timestamp-aware windows; stack traces stay together;
  human notes preserve paragraph/heading boundaries; deploy notes = small
  release-entry chunks. EvidenceRef = artifact_id, source_name, line_start,
  line_end, snippet, confidence_score.

## Plan

- [x] `chunking.py`: `ChunkingStrategy` Protocol + `SourceAwareLineWindowChunker`
  (version `source-aware-1`), line-numbered chunks, 15% overlap, source-aware
  rules.
- [x] `timestamps.py`: deterministic parse -> normalized UTC + original text +
  inferred/uncertainty flag.
- [x] Models: `TimelineEvent` and relational `EvidenceRef`.
- [x] Schemas: `TimelineEventRead` + `EvidenceRefRead`.
- [x] `services/stages.py`: real `normalizing_evidence` + `extracting_timeline_candidates`;
  dispatched stage_runner wired into the default executor; stages 3-6 no-op.
- [x] Persist chunking strategy version into Experiment Metadata.
- [x] API `GET .../analysis-runs/{run_id}/timeline` + `AnalysisService.list_timeline`.
- [x] Frontend `listRunTimeline` + timeline candidates under a succeeded run.
- [x] Tests across chunking, timestamps, timeline extraction, API, e2e.
- [x] Backend pytest + frontend typecheck/build + e2e; self-review; document.

## Notes

- Stage work plugs into the existing executor via `stage_runner(stage, attempt,
  run)`. `PipelineStageRunner` holds the session it was constructed with;
  `AnalysisService` builds it in `__init__` from the same session it operates
  on, and the HTTP background path builds a fresh service per session — so the
  runner always writes through the run's own session (ADR 0004).
- EvidenceRefs are reusable across later slices (hypotheses cite them too), so
  the table is generic (nullable timeline_event_id FK now).

## Review

- Backend: `chunking.py` (`SourceAwareLineWindowChunker`, kept-interface
  `ChunkingStrategy`, version `source-aware-1`) does source-aware line-window
  chunking with 15% overlap (ADR 0027): timestamp-windowed logs, stack traces
  kept whole, notes/deploys split on blank-line blocks. `timestamps.py` parses
  absolute/offset/time-only/relative anchors into normalized UTC + preserved
  original text + inferred flag (ADR 0019). `services/stages.py` runs the two
  real stages through the existing executor, persisting before the next stage
  (ADR 0026); timeline events cite exact Artifact lines via relational
  `EvidenceRef` (ADR 0024). The run records the Chunking Strategy version (ADR
  0025). New timeline endpoint + `AnalysisService.list_timeline`.
- Frontend: timeline candidates render under a succeeded run with normalized
  time, original text, an "inferred" badge for uncertain timestamps, and the
  cited `source:line` + snippet.

### Verification

- Backend: `python -m pytest` -> 81 passed (was 52; +29 across chunking,
  timestamps, timeline extraction/ordering/idempotency, and API). Re-ran 6x to
  confirm no flakiness.
- Frontend: `npm run typecheck` + `npm run build` pass.
- E2E: `./scripts/e2e.sh` -> 2 passed, including timeline candidates citing
  exact lines and the inferred-timestamp badge.

### Self-review (code-review skill, high effort) — fixes applied

- **Timeline retry was not idempotent**: a stage that wrote events then failed
  and retried produced duplicate events with colliding sequences ([1,1,2,2]).
  `_extract_timeline` now clears prior events first; reproduced and regression-
  tested ([1,2]).
- **Timestamp with fractional seconds + tz offset** was mis-normalized as UTC,
  silently dropping the offset (2h off). Offset pattern now tolerates the
  fractional part; regression-tested (14:28:31+02:00 -> 12:28:31Z).
- **Bracketed time-only** (`[14:40]`) dropped its brackets from original text,
  so the description-strip left `14:40] ...`. Pattern now captures the full
  token; regression-tested.
- **Naive/aware datetime flakiness**: SQLite drops tzinfo, so reloaded events
  compared unequal/uncomparable to freshly-parsed aware ones. Now stored naive
  UTC (backend-uniform) and re-tagged UTC at the API read boundary.
- **Deterministic ordering**: `_run_artifacts` tiebreaks on `Artifact.id` so
  equal `created_at` no longer yields non-deterministic order.
- Cleanup: simplified stage dispatch (if/elif vs unbound-method table); cached
  the immutable run-artifact set so both stages share one query.

### Known/accepted limitations

- Chunks are validated/counted but not persisted: per ADR 0027 chunks are
  retrieval aids, not citation targets, and nothing consumes them until the
  retrieval/RCA slices. The normalize stage proves chunkability and emits
  `chunk_count_anomaly`; persisting chunks is deferred to when retrieval needs
  them.
- The frontend fetches timeline per succeeded run card (fine for the few runs
  per incident in the MVP); a batched endpoint can come later if needed.
