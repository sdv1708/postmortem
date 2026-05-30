from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import JSON, Boolean, DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .db import Base


def _uuid() -> str:
    return str(uuid.uuid4())


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Workspace(Base):
    __tablename__ = "workspaces"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    slug: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, nullable=False)

    incidents: Mapped[list["Incident"]] = relationship(back_populates="workspace")


class Incident(Base):
    __tablename__ = "incidents"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    workspace_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("workspaces.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    severity: Mapped[str | None] = mapped_column(String(32), nullable=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="open")
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    detected_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, onupdate=_utcnow, nullable=False
    )

    workspace: Mapped[Workspace] = relationship(back_populates="incidents")
    artifacts: Mapped[list["Artifact"]] = relationship(
        back_populates="incident", cascade="all, delete-orphan", order_by="Artifact.created_at"
    )


class Artifact(Base):
    __tablename__ = "artifacts"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    incident_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("incidents.id", ondelete="CASCADE"), nullable=False, index=True
    )
    source_type: Mapped[str] = mapped_column(String(32), nullable=False)
    source_name: Mapped[str] = mapped_column(String(255), nullable=False)
    body: Mapped[str] = mapped_column(Text, nullable=False)
    line_count: Mapped[int] = mapped_column(Integer, nullable=False)
    included_in_analysis_run: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, onupdate=_utcnow, nullable=False
    )

    incident: Mapped[Incident] = relationship(back_populates="artifacts")


class AnalysisRun(Base):
    """An asynchronous analysis run started from an Incident (ADR 0003).

    Runs are async at the product/API level: clients start a run and then poll
    Run Status. Versioned Experiment Metadata is recorded per run (ADR 0025) so
    prompt and pipeline tradeoffs are comparable later. Six-stage pipeline
    behavior and Run Stage Events land in slice #5; this slice persists the
    durable run lifecycle and the locked Artifact references.
    """

    __tablename__ = "analysis_runs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    incident_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("incidents.id", ondelete="CASCADE"), nullable=False, index=True
    )
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="queued")
    error: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Experiment Metadata defaults (ADR 0025). Scenario id, deterministic check
    # results, and judge scores attach in later eval slices.
    pipeline_version: Mapped[str] = mapped_column(String(64), nullable=False)
    prompt_version: Mapped[str] = mapped_column(String(64), nullable=False)
    model_provider: Mapped[str] = mapped_column(String(64), nullable=False)
    retrieval_strategy: Mapped[str] = mapped_column(String(64), nullable=False)
    chunking_strategy: Mapped[str] = mapped_column(String(64), nullable=False)
    verifier_version: Mapped[str] = mapped_column(String(64), nullable=False)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, onupdate=_utcnow, nullable=False
    )
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    incident: Mapped[Incident] = relationship()
    run_artifacts: Mapped[list["RunArtifact"]] = relationship(
        back_populates="run", cascade="all, delete-orphan", order_by="RunArtifact.created_at"
    )
    stage_events: Mapped[list["RunStageEvent"]] = relationship(
        back_populates="run", cascade="all, delete-orphan", order_by="RunStageEvent.sequence"
    )


class RunArtifact(Base):
    """Immutable reference from an Analysis Run to an included Artifact.

    The Artifact body remains the citation source of truth and cannot change
    once referenced (ADR 0018); corrections require a new Artifact and new run.
    """

    __tablename__ = "run_artifacts"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    run_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("analysis_runs.id", ondelete="CASCADE"), nullable=False, index=True
    )
    artifact_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("artifacts.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, nullable=False)

    run: Mapped[AnalysisRun] = relationship(back_populates="run_artifacts")
    artifact: Mapped[Artifact] = relationship()


class RunStageEvent(Base):
    """A persisted Run Stage Event for run-centric observability (ADR 0021).

    The RunExecutor persists one event per stage attempt before moving to the
    next stage (ADR 0026), so the status page and evaluation harness can observe
    progress, durations, retries, and Warning Codes by polling. Heavy debug
    context (full prompts, raw responses, stack traces) belongs in logs keyed by
    run_id, not in this table.
    """

    __tablename__ = "run_stage_events"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    run_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("analysis_runs.id", ondelete="CASCADE"), nullable=False, index=True
    )
    # Position in the six-stage pipeline (1-based), used as the stable sort key
    # for the status page even before timestamps differ.
    sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    stage: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    # Which attempt produced this event: 1 = first try, 2 = the single retry
    # allowed by ADR 0029.
    attempt: Mapped[int] = mapped_column(Integer, nullable=False, default=1)

    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    duration_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)

    # Model/token usage when available (ADR 0021). Null until an LLM is wired
    # into the pipeline (#7); the contract exists now so events are uniform.
    usage: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    # Controlled Warning Codes such as `uncited_claim` (ADR 0021). Stored as a
    # JSON list; empty list means no warnings.
    warning_codes: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, nullable=False)

    run: Mapped[AnalysisRun] = relationship(back_populates="stage_events")


class EvidenceChunk(Base):
    """A persisted normalized evidence chunk for one Analysis Run.

    Chunks are retrieval aids (ADR 0027), not citation targets. They are
    persisted so the `normalizing_evidence` stage has inspectable output before
    timeline extraction (ADR 0026), while EvidenceRefs continue to cite immutable
    Artifact line ranges.
    """

    __tablename__ = "evidence_chunks"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    run_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("analysis_runs.id", ondelete="CASCADE"), nullable=False, index=True
    )
    artifact_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("artifacts.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    source_type: Mapped[str] = mapped_column(String(32), nullable=False)
    source_name: Mapped[str] = mapped_column(String(255), nullable=False)
    line_start: Mapped[int] = mapped_column(Integer, nullable=False)
    line_end: Mapped[int] = mapped_column(Integer, nullable=False)
    text: Mapped[str] = mapped_column(Text, nullable=False)
    chunking_strategy: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, nullable=False)

    run: Mapped[AnalysisRun] = relationship()
    artifact: Mapped[Artifact] = relationship()


class TimelineEvent(Base):
    """A time-anchored event extracted from a run's normalized evidence.

    Produced by the "extracting timeline candidates" stage (ADR 0026). Stores a
    normalized UTC timestamp when one could be parsed and always preserves the
    original timestamp text so the claim stays auditable (ADR 0019). Inferred or
    ambiguous timestamps are flagged ``uncertain`` rather than presented as
    equally precise.
    """

    __tablename__ = "timeline_events"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    run_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("analysis_runs.id", ondelete="CASCADE"), nullable=False, index=True
    )
    # Stable display/sort order assigned at extraction time (chronological with
    # normalized events first, then inferred). Distinct from the timestamp so the
    # status page has a deterministic order even for unparseable timestamps.
    sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    normalized_ts: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    original_ts_text: Mapped[str | None] = mapped_column(String(128), nullable=True)
    uncertain: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, nullable=False)

    run: Mapped[AnalysisRun] = relationship()
    evidence_refs: Mapped[list["EvidenceRef"]] = relationship(
        back_populates="timeline_event",
        cascade="all, delete-orphan",
        order_by="EvidenceRef.line_start",
    )


class EvidenceRef(Base):
    """A relational citation to an exact Artifact line range (ADR 0024 / 0027).

    EvidenceRefs point to Artifact line ranges rather than chunk ids, because
    chunk boundaries can change across Chunking Strategy versions while line
    addresses stay stable. The relational shape (not JSON) is what the citation
    panel, eval aggregation, and referential integrity depend on. ``snippet`` is
    the exact stored text of those lines so later citation-integrity
    verification can confirm an exact match.
    """

    __tablename__ = "evidence_refs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    # Nullable owner FK: timeline events cite evidence now; hypotheses, impact
    # claims, etc. reuse this table in later slices.
    timeline_event_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("timeline_events.id", ondelete="CASCADE"), nullable=True, index=True
    )
    artifact_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("artifacts.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    source_name: Mapped[str] = mapped_column(String(255), nullable=False)
    line_start: Mapped[int] = mapped_column(Integer, nullable=False)
    line_end: Mapped[int] = mapped_column(Integer, nullable=False)
    snippet: Mapped[str] = mapped_column(Text, nullable=False)
    confidence_score: Mapped[float] = mapped_column(Float, nullable=False, default=1.0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, nullable=False)

    timeline_event: Mapped["TimelineEvent"] = relationship(back_populates="evidence_refs")
    artifact: Mapped[Artifact] = relationship()
