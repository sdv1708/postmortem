from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


Severity = Literal["sev0", "sev1", "sev2", "sev3", "sev4"]
IncidentStatus = Literal["open", "investigating", "mitigated", "resolved", "closed"]
ArtifactSourceType = Literal["incident_notes", "logs", "stack_trace", "deployment_notes", "other"]
RunStatus = Literal["queued", "running", "succeeded", "failed"]
RunStage = Literal[
    "normalizing_evidence",
    "extracting_timeline_candidates",
    "generating_rca_hypotheses",
    "verifying_citations",
    "drafting_postmortem",
    "flagging_unsupported_claims",
]
StageStatus = Literal["running", "succeeded", "failed"]


class IncidentCreate(BaseModel):
    title: str = Field(min_length=1, max_length=255)
    summary: str | None = None
    severity: Severity | None = None
    status: IncidentStatus = "open"
    started_at: datetime | None = None
    detected_at: datetime | None = None
    resolved_at: datetime | None = None


class IncidentRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    workspace_id: str
    title: str
    summary: str | None
    severity: str | None
    status: str
    started_at: datetime | None
    detected_at: datetime | None
    resolved_at: datetime | None
    created_at: datetime
    updated_at: datetime


class ArtifactLine(BaseModel):
    number: int
    text: str


class ArtifactCreate(BaseModel):
    source_type: ArtifactSourceType
    source_name: str = Field(min_length=1, max_length=255)
    body: str = Field(min_length=1)


class ArtifactReplace(BaseModel):
    source_type: ArtifactSourceType | None = None
    source_name: str | None = Field(default=None, min_length=1, max_length=255)
    body: str = Field(min_length=1)


class ArtifactRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    incident_id: str
    source_type: str
    source_name: str
    body: str
    line_count: int
    included_in_analysis_run: bool
    created_at: datetime
    updated_at: datetime
    lines: list[ArtifactLine]


class AnalysisRunCreate(BaseModel):
    """Command payload to start an Analysis Run (ADR 0022).

    `artifact_ids` selects the current Artifacts to include. When omitted, all
    of the Incident's current Artifacts are included.
    """

    artifact_ids: list[str] | None = None


class ExperimentMetadata(BaseModel):
    """Versioned metadata recorded per run for experiment tracking (ADR 0025)."""

    model_config = ConfigDict(from_attributes=True)

    pipeline_version: str
    prompt_version: str
    model_provider: str
    retrieval_strategy: str
    chunking_strategy: str
    verifier_version: str


class RunStageEventRead(BaseModel):
    """A persisted Run Stage Event surfaced for the status page (ADR 0021)."""

    model_config = ConfigDict(from_attributes=True)

    id: str
    sequence: int
    stage: RunStage
    status: StageStatus
    attempt: int
    started_at: datetime | None
    completed_at: datetime | None
    duration_ms: int | None
    usage: dict | None
    warning_codes: list[str]
    error: str | None


class AnalysisRunRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    incident_id: str
    status: RunStatus
    error: str | None
    experiment_metadata: ExperimentMetadata
    artifact_ids: list[str]
    stage_events: list[RunStageEventRead]
    created_at: datetime
    updated_at: datetime
    started_at: datetime | None
    completed_at: datetime | None


class EvidenceRefRead(BaseModel):
    """A relational citation to exact Artifact lines (ADR 0024)."""

    model_config = ConfigDict(from_attributes=True)

    id: str
    artifact_id: str
    source_name: str
    line_start: int
    line_end: int
    snippet: str
    confidence_score: float


class TimelineEventRead(BaseModel):
    """A timeline candidate with its citations (ADR 0019)."""

    model_config = ConfigDict(from_attributes=True)

    id: str
    sequence: int
    normalized_ts: datetime | None
    original_ts_text: str | None
    uncertain: bool
    description: str
    evidence_refs: list[EvidenceRefRead]
