from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..chunking import ChunkingStrategy, SourceAwareLineWindowChunker
from ..models import AnalysisRun, Artifact, EvidenceRef, RunArtifact, TimelineEvent
from ..timestamps import parse_timestamp


def _as_naive_utc(value: datetime | None) -> datetime | None:
    """Convert an aware datetime to naive UTC; pass through None/naive.

    Timeline timestamps are normalized to UTC (ADR 0019). Storing them naive
    keeps reads uniform across SQLite (which drops tzinfo) and Postgres, so
    chronological sorting never compares an aware value against a naive one.
    """
    if value is None or value.tzinfo is None:
        return value
    return value.astimezone(timezone.utc).replace(tzinfo=None)


class PipelineStageRunner:
    """Deterministic stage work for an Analysis Run (slice #5).

    This is the `stage_runner` the StagedRunExecutor invokes per stage. It holds
    the session so a stage can persist its structured output before the next
    stage starts (ADR 0026); the AnalysisService still owns the transaction
    boundary (ADR 0004). No LLM is involved yet — stages 1 and 2 do real
    deterministic work, and the remaining stages stay as no-ops until later
    slices wire them up.

    A stage returns an outcome dict ({"warning_codes": [...]}); the executor
    records it on the Run Stage Event and treats a raised exception as a stage
    failure (ADR 0029).
    """

    def __init__(self, session: Session, chunker: ChunkingStrategy | None = None) -> None:
        self._session = session
        self._chunker = chunker or SourceAwareLineWindowChunker()
        self._artifacts_cache: dict[str, list[Artifact]] = {}

    def __call__(self, stage: str, attempt: int, run: AnalysisRun) -> dict | None:
        if stage == "normalizing_evidence":
            return self._normalize_evidence(run)
        if stage == "extracting_timeline_candidates":
            return self._extract_timeline(run)
        # Stages 3-6 (RCA, verification, drafting, flagging) stay no-ops until
        # later slices wire them up.
        return None

    def _normalize_evidence(self, run: AnalysisRun) -> dict | None:
        """Chunk every included Artifact into source-aware line windows.

        Chunks are retrieval aids, not citation targets (ADR 0027), so they are
        not persisted; the stage's product is the validated chunk set and a
        Warning Code when an Artifact yields no chunks.
        """
        artifacts = self._run_artifacts(run)
        warning_codes: list[str] = []
        total_chunks = 0
        for artifact in artifacts:
            chunks = self._chunker.chunk(artifact.source_type, artifact.source_name, artifact.body)
            total_chunks += len(chunks)
            if not chunks:
                warning_codes.append("chunk_count_anomaly")
        if total_chunks == 0:
            warning_codes.append("chunk_count_anomaly")
        return {"warning_codes": _dedupe(warning_codes)}

    def _extract_timeline(self, run: AnalysisRun) -> dict | None:
        """Build Timeline Events with EvidenceRefs from timestamped lines.

        Each line carrying a recognizable time anchor becomes a candidate event
        citing its exact Artifact line (ADR 0024). Normalized timestamps sort
        first chronologically; inferred/uncertain timestamps follow in source
        order and are flagged (ADR 0019).

        Idempotent across the single stage retry (ADR 0029): any events left by
        a failed prior attempt are cleared first, so a retry never duplicates
        timeline events or collides on sequence numbers.
        """
        self._clear_timeline(run)
        artifacts = self._run_artifacts(run)
        candidates: list[_Candidate] = []
        for artifact in artifacts:
            for offset, line in enumerate(artifact.body.split("\n")):
                parsed = parse_timestamp(line)
                if parsed is None:
                    continue
                line_number = offset + 1
                candidates.append(
                    _Candidate(
                        artifact=artifact,
                        line_number=line_number,
                        line_text=line,
                        original_ts_text=parsed.original_text,
                        normalized_ts=parsed.normalized,
                        uncertain=parsed.inferred,
                    )
                )

        ordered = _order_candidates(candidates)
        for sequence, candidate in enumerate(ordered, start=1):
            event = TimelineEvent(
                run_id=run.id,
                sequence=sequence,
                # Store naive UTC so the value round-trips identically on SQLite
                # and Postgres; comparisons/sorting in later slices never mix
                # naive and aware datetimes. UTC tz is re-attached on API read.
                normalized_ts=_as_naive_utc(candidate.normalized_ts),
                original_ts_text=candidate.original_ts_text,
                uncertain=candidate.uncertain,
                description=candidate.description,
            )
            event.evidence_refs.append(
                EvidenceRef(
                    artifact_id=candidate.artifact.id,
                    source_name=candidate.artifact.source_name,
                    line_start=candidate.line_number,
                    line_end=candidate.line_number,
                    snippet=candidate.line_text,
                    confidence_score=0.5 if candidate.uncertain else 1.0,
                )
            )
            self._session.add(event)
        self._session.flush()
        return None

    def _run_artifacts(self, run: AnalysisRun) -> list[Artifact]:
        # The included-artifact set is immutable once a run starts, so both
        # stages share one query. Tiebreak on Artifact.id: artifacts added in
        # one start_run share a created_at, so id keeps processing (and
        # inferred-event) order stable and deterministic across identical input.
        cached = self._artifacts_cache.get(run.id)
        if cached is not None:
            return cached
        stmt = (
            select(Artifact)
            .join(RunArtifact, RunArtifact.artifact_id == Artifact.id)
            .where(RunArtifact.run_id == run.id)
            .order_by(RunArtifact.created_at.asc(), Artifact.id.asc())
        )
        artifacts = list(self._session.scalars(stmt))
        self._artifacts_cache[run.id] = artifacts
        return artifacts

    def _clear_timeline(self, run: AnalysisRun) -> None:
        existing = self._session.scalars(
            select(TimelineEvent).where(TimelineEvent.run_id == run.id)
        )
        for event in existing:
            self._session.delete(event)  # cascade removes its EvidenceRefs
        self._session.flush()


class _Candidate:
    __slots__ = (
        "artifact",
        "line_number",
        "line_text",
        "original_ts_text",
        "normalized_ts",
        "uncertain",
    )

    def __init__(
        self,
        artifact: Artifact,
        line_number: int,
        line_text: str,
        original_ts_text: str,
        normalized_ts,
        uncertain: bool,
    ) -> None:
        self.artifact = artifact
        self.line_number = line_number
        self.line_text = line_text
        self.original_ts_text = original_ts_text
        self.normalized_ts = normalized_ts
        self.uncertain = uncertain

    @property
    def description(self) -> str:
        # The event description is the cited line with its timestamp prefix
        # stripped, so the timeline reads as events rather than raw log lines.
        text = self.line_text.strip()
        if text.startswith(self.original_ts_text):
            text = text[len(self.original_ts_text):]
        return text.strip(" \t-:[]") or self.line_text.strip()


def _order_candidates(candidates: list[_Candidate]) -> list[_Candidate]:
    """Normalized timestamps first, in chronological order; inferred after.

    Inferred candidates keep their discovery order (a stable proxy for source
    order) because they have no comparable absolute time.
    """
    dated = [c for c in candidates if c.normalized_ts is not None]
    undated = [c for c in candidates if c.normalized_ts is None]
    dated.sort(key=lambda c: c.normalized_ts)
    return dated + undated


def _dedupe(values: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        if value not in seen:
            seen.add(value)
            result.append(value)
    return result
