from __future__ import annotations

from datetime import datetime, timezone

from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..chunking import ChunkingStrategy, SourceAwareLineWindowChunker
from ..llm import LLMClient, OfflineLLMClient
from ..models import (
    ActionItem,
    AnalysisRun,
    Artifact,
    EvidenceChunk,
    EvidenceRef,
    Hypothesis,
    ImpactClaim,
    TimelineEvent,
    RunArtifact,
)
from ..rca import RcaEvidenceRef, RcaGenerationOutput, build_rca_prompt
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

    def __init__(
        self,
        session: Session,
        chunker: ChunkingStrategy | None = None,
        llm_client: LLMClient | None = None,
    ) -> None:
        self._session = session
        self._chunker = chunker or SourceAwareLineWindowChunker()
        # Default to the offline client so deterministic stages still complete a
        # run when no provider is configured; real runs inject a configured
        # client (ADR 0011).
        self._llm = llm_client or OfflineLLMClient()
        self._artifacts_cache: dict[str, list[Artifact]] = {}

    def __call__(self, stage: str, attempt: int, run: AnalysisRun) -> dict | None:
        if stage == "normalizing_evidence":
            return self._normalize_evidence(run)
        if stage == "extracting_timeline_candidates":
            return self._extract_timeline(run)
        if stage == "generating_rca_hypotheses":
            return self._generate_rca(run)
        # Stages 4-6 (verification, drafting, flagging) stay no-ops until later
        # slices wire them up.
        return None

    def _normalize_evidence(self, run: AnalysisRun) -> dict | None:
        """Chunk every included Artifact into source-aware line windows.

        Chunks are retrieval aids, not citation targets (ADR 0027), but they
        are persisted as the inspectable output of this stage (ADR 0026). The
        timeline stage and all EvidenceRefs still cite Artifact line ranges.
        """
        self._clear_chunks(run)
        artifacts = self._run_artifacts(run)
        warning_codes: list[str] = []
        total_chunks = 0
        sequence = 1
        for artifact in artifacts:
            chunks = self._chunker.chunk(artifact.source_type, artifact.source_name, artifact.body)
            total_chunks += len(chunks)
            if not chunks:
                warning_codes.append("chunk_count_anomaly")
            for chunk in chunks:
                self._session.add(
                    EvidenceChunk(
                        run_id=run.id,
                        artifact_id=artifact.id,
                        sequence=sequence,
                        source_type=chunk.source_type,
                        source_name=chunk.source_name,
                        line_start=chunk.line_start,
                        line_end=chunk.line_end,
                        text=chunk.text,
                        chunking_strategy=self._chunker.version,
                    )
                )
                sequence += 1
        if total_chunks == 0:
            warning_codes.append("chunk_count_anomaly")
        self._session.flush()
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

    def _generate_rca(self, run: AnalysisRun) -> dict | None:
        """Generate ranked RCA Hypotheses from the run's cited evidence.

        Calls the configured LLMClient (ADR 0011), validates its output against a
        strict JSON schema (ADR 0028) — invalid JSON or a schema violation raises,
        which the executor turns into a stage failure with one retry (ADR 0029) —
        then persists hypotheses, their impact claims, and remediation items with
        EvidenceRefs resolved from the actual Artifact lines (ADR 0024). Any Major
        Claim left without supporting evidence is normalized to an assumption and
        counted as an `uncited_claim` warning (ADR 0013); that does not fail the
        run.

        Idempotent across the single retry: prior hypotheses for the run are
        cleared first, and the chunk/timeline outputs from earlier stages are
        untouched, so a failed-then-retried RCA never duplicates or corrupts state.
        """
        self._clear_hypotheses(run)
        artifacts = self._run_artifacts(run)
        if not artifacts:
            return None

        timeline = list(
            self._session.scalars(
                select(TimelineEvent)
                .where(TimelineEvent.run_id == run.id)
                .order_by(TimelineEvent.sequence.asc())
            )
        )
        system, user = build_rca_prompt(artifacts, timeline)
        response = self._llm.complete(system=system, user=user)
        try:
            output = RcaGenerationOutput.model_validate_json(response.text)
        except ValidationError as exc:
            # Schema-invalid (or non-JSON) model output fails the stage rather
            # than becoming pipeline state (ADR 0028).
            raise ValueError(f"RCA output failed schema validation: {exc}") from exc

        by_id = {artifact.id: artifact for artifact in artifacts}
        warning_codes: list[str] = []
        for rank, hyp in enumerate(output.hypotheses, start=1):
            supporting = self._resolve_refs(by_id, hyp.supporting_evidence, "supporting")
            contradicting = self._resolve_refs(by_id, hyp.contradicting_evidence, "contradicting")
            assumption = not supporting
            if assumption:
                warning_codes.append("uncited_claim")
            hypothesis = Hypothesis(
                run_id=run.id,
                rank=rank,
                title=hyp.title,
                summary=hyp.summary,
                assumption=assumption,
                review_status="proposed",
                unknowns=list(hyp.unknowns),
                validation_steps=list(hyp.validation_steps),
            )
            hypothesis.evidence_refs.extend(supporting)
            hypothesis.evidence_refs.extend(contradicting)
            for sequence, impact in enumerate(hyp.impact_claims, start=1):
                evidence = self._resolve_refs(by_id, impact.evidence, "supporting")
                impact_assumption = not evidence
                if impact_assumption:
                    warning_codes.append("uncited_claim")
                claim = ImpactClaim(
                    sequence=sequence,
                    description=impact.description,
                    assumption=impact_assumption,
                )
                claim.evidence_refs.extend(evidence)
                hypothesis.impact_claims.append(claim)
            for sequence, remediation in enumerate(hyp.remediation_items, start=1):
                item = ActionItem(sequence=sequence, description=remediation.description)
                item.evidence_refs.extend(
                    self._resolve_refs(by_id, remediation.evidence, "supporting")
                )
                hypothesis.action_items.append(item)
            self._session.add(hypothesis)

        self._session.flush()
        outcome: dict = {}
        if warning_codes:
            outcome["warning_codes"] = _dedupe(warning_codes)
        if response.usage:
            outcome["usage"] = response.usage
        return outcome or None

    def _resolve_refs(
        self, by_id: dict[str, Artifact], refs: list[RcaEvidenceRef], role: str
    ) -> list[EvidenceRef]:
        resolved: list[EvidenceRef] = []
        for ref in refs:
            evidence_ref = self._resolve_ref(by_id, ref, role)
            if evidence_ref is not None:
                resolved.append(evidence_ref)
        return resolved

    def _resolve_ref(
        self, by_id: dict[str, Artifact], ref: RcaEvidenceRef, role: str
    ) -> EvidenceRef | None:
        """Turn a model-cited line range into a citation with an exact snippet.

        The snippet is read from the stored Artifact lines, never from the model,
        so the citation remains the source of truth (ADR 0024). A ref to an
        artifact outside the run or to out-of-range lines is dropped here;
        deterministic citation-integrity verification arrives in a later slice.
        """
        artifact = by_id.get(ref.artifact_id)
        if artifact is None:
            return None
        lines = artifact.body.split("\n")
        if ref.line_start < 1 or ref.line_end < ref.line_start or ref.line_end > len(lines):
            return None
        snippet = "\n".join(lines[ref.line_start - 1 : ref.line_end])
        return EvidenceRef(
            artifact_id=artifact.id,
            source_name=artifact.source_name,
            line_start=ref.line_start,
            line_end=ref.line_end,
            snippet=snippet,
            confidence_score=ref.confidence_score,
            role=role,
        )

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

    def _clear_chunks(self, run: AnalysisRun) -> None:
        existing = self._session.scalars(
            select(EvidenceChunk).where(EvidenceChunk.run_id == run.id)
        )
        for chunk in existing:
            self._session.delete(chunk)
        self._session.flush()

    def _clear_hypotheses(self, run: AnalysisRun) -> None:
        existing = self._session.scalars(
            select(Hypothesis).where(Hypothesis.run_id == run.id)
        )
        for hypothesis in existing:
            # cascade removes impact claims, action items, and all EvidenceRefs
            self._session.delete(hypothesis)
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
