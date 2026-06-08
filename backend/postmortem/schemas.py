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


HypothesisReviewStatus = Literal["proposed", "accepted", "rejected"]

# Semantic claim-support judgment surfaced on each Major Claim (ADR 0014).
# ``unevaluated`` is the pre-flagging default; the rest are ClaimSupportStatus.
ClaimSupportStatus = Literal["unevaluated", "supported", "partial", "unsupported"]

# Deterministic citation-integrity status surfaced beside each citation (ADR 0014).
# ``unverified`` is the pre-stage-4 default; the rest are CitationIntegrityStatus.
CitationVerifierStatus = Literal[
    "unverified",
    "verified",
    "artifact_missing",
    "line_range_invalid",
    "snippet_mismatch",
]


class EvidenceRefRead(BaseModel):
    """A relational citation to exact Artifact lines (ADR 0024).

    ``verifier_status`` is the deterministic citation-integrity outcome so the
    Review Surface can show whether a citation provably resolves to its exact
    immutable lines (ADR 0014).
    """

    model_config = ConfigDict(from_attributes=True)

    id: str
    artifact_id: str
    source_name: str
    line_start: int
    line_end: int
    snippet: str
    confidence_score: float
    verifier_status: CitationVerifierStatus


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


class ImpactClaimRead(BaseModel):
    """An evidence-backed impact statement tied to a hypothesis (ADR 0013).

    ``support_status`` carries the semantic claim-support judgment so the Review
    Surface can separate supported impact from partial/unsupported (ADR 0014).
    """

    id: str
    sequence: int
    description: str
    assumption: bool
    support_status: ClaimSupportStatus
    support_rationale: str | None
    evidence_refs: list[EvidenceRefRead]


class ActionItemRead(BaseModel):
    """A remediation item tied to a hypothesis (PRD user story 16)."""

    id: str
    sequence: int
    description: str
    evidence_refs: list[EvidenceRefRead]


class HypothesisRead(BaseModel):
    """A ranked RCA Hypothesis for the Review Surface (PRD stage 3).

    Supporting and contradicting evidence are pre-split so the reviewer sees both
    sides without re-deriving the distinction. ``assumption`` marks a hypothesis
    that carried no supporting citation and was normalized (ADR 0013), and
    ``review_status`` records the human accept/reject decision (ADR 0016).
    """

    id: str
    run_id: str
    rank: int
    title: str
    summary: str
    assumption: bool
    review_status: HypothesisReviewStatus
    support_status: ClaimSupportStatus
    support_rationale: str | None
    unknowns: list[str]
    validation_steps: list[str]
    supporting_evidence: list[EvidenceRefRead]
    contradicting_evidence: list[EvidenceRefRead]
    impact_claims: list[ImpactClaimRead]
    action_items: list[ActionItemRead]


class HypothesisReviewCreate(BaseModel):
    """Command payload to accept or reject a hypothesis (ADR 0016 / 0022)."""

    decision: Literal["accepted", "rejected", "proposed"]


# How a Markdown export treats unsupported/assumption claims (ADR 0015).
ExportMode = Literal["clean", "audit"]


class PostmortemRead(BaseModel):
    """The structured Postmortem for the Review Surface (ADR 0012).

    The composed ``summary`` and ``lessons_learned`` come from the Postmortem
    row; ``timeline`` and ``hypotheses`` (with their nested impact analysis and
    remediation) are composed from the run's existing structured rows so the
    citation source of truth stays the EvidenceRefs (ADR 0024).
    """

    id: str
    run_id: str
    incident_title: str
    incident_severity: str | None
    summary: str
    lessons_learned: list[str]
    composer_version: str
    timeline: list[TimelineEventRead]
    hypotheses: list[HypothesisRead]
    created_at: datetime


class MarkdownExportCreate(BaseModel):
    """Command payload to render a Markdown export (ADR 0015 / 0022).

    Defaults to the clean, shareable postmortem; ``audit`` additionally surfaces
    unsupported claims and assumptions for review.
    """

    mode: ExportMode = "clean"


class MarkdownExportRead(BaseModel):
    """A rendered Markdown export (ADR 0012): derived from structured data only."""

    run_id: str
    mode: ExportMode
    filename: str
    markdown: str


class ScenarioSummaryRead(BaseModel):
    """A file-based Incident Scenario the demo operator can seed (ADR 0006 / 0007)."""

    id: str
    title: str
    severity: str | None
    summary: str | None
    ambiguity_notes: str | None
    evaluation_tags: list[str]
    expected_hypothesis_families: list[str]
    evidence_count: int


class ScenarioSeedRead(BaseModel):
    """Result of seeding a scenario: the created Incident and its started run."""

    scenario_id: str
    incident_id: str
    run_id: str
    run_status: RunStatus
