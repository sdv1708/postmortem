from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import JSON, Boolean, CheckConstraint, DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .db import (
    Base,
    EVIDENCE_REF_OWNER_CHECK,
    EVIDENCE_REF_ROLE_CHECK,
    HYPOTHESIS_CHALLENGE_SEVERITY_CHECK,
)


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
    # Impact Claims are run-level incident facts (ADR 0033): produced once per run
    # by the "extracting incident facts" stage and independent of how many RCA
    # Hypotheses the causal stage later generates.
    impact_claims: Mapped[list["ImpactClaim"]] = relationship(
        back_populates="run", cascade="all, delete-orphan", order_by="ImpactClaim.sequence"
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


class Hypothesis(Base):
    """A ranked RCA Hypothesis generated for ambiguous incident evidence.

    Produced by the "generating RCA hypotheses" stage (ADR 0026) from a strict
    structured model output (ADR 0028). The hypothesis statement is a Major Claim,
    so it carries supporting EvidenceRefs or is normalized to ``assumption=true``
    with an `uncited_claim` warning (ADR 0013). Contradicting evidence, unknowns,
    and validation steps are persisted so a reviewer can judge it like an engineer
    would, and remediation items hang off the hypothesis context (PRD stage 3).
    Impact Claims are no longer owned by a hypothesis — they are run-level incident
    facts (ADR 0033). Reviewers accept/reject without rewriting the generated claims
    (ADR 0016); ``review_status`` records that decision separately.
    """

    __tablename__ = "hypotheses"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    run_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("analysis_runs.id", ondelete="CASCADE"), nullable=False, index=True
    )
    # 1-based generation order assigned by the builder/expansion substeps: initial
    # hypotheses in builder order, then proposed alternatives. Preserved as the
    # audit record of how the analysis first ordered candidates, distinct from the
    # post-challenge Advisory Hypothesis Ranking below (ADR 0037, PRD #26 story 20).
    rank: Mapped[int] = mapped_column(Integer, nullable=False)
    # 1-based ordinal position in the post-challenge Advisory Hypothesis Ranking
    # (ADR 0037): lower is more plausible. Null until the ranking substep runs (it
    # is the last substep of stage 3). The ranking is advisory only — a review aid,
    # never a Root Cause Conclusion (PRD #26 stories 17-22). ``ranking_rationale``
    # holds the per-dimension explanation (support strength, counterevidence
    # severity, explanatory coverage, evidence gaps, assumption dependence) so the
    # ordering is explainable; plausibility is ordinal, never a probability.
    advisory_rank: Mapped[int | None] = mapped_column(Integer, nullable=True)
    ranking_rationale: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    # Provenance within the Causal Analysis Stage (ADR 0036, PRD #26 / #30):
    # 'initial' for a builder-generated hypothesis, 'proposed' for a missed
    # alternative the falsifier introduced in the one bounded expansion round. A
    # proposed alternative still travels the full citation/support/challenge/review
    # path; origin only distinguishes how it entered, never its trust level.
    origin: Mapped[str] = mapped_column(String(16), nullable=False, default="initial")
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    summary: Mapped[str] = mapped_column(Text, nullable=False)
    # True when the statement has no supporting citation (ADR 0013). The narrative
    # stays auditable but is not presented as an evidence-backed claim.
    assumption: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    # Human review decision (ADR 0016): proposed | accepted | rejected. Kept apart
    # from the generated claims so accepting/rejecting never edits the output.
    review_status: Mapped[str] = mapped_column(String(16), nullable=False, default="proposed")
    # Open questions and how to confirm/refute the hypothesis. These are reviewer
    # context, not factual incident claims, so they are plain string lists rather
    # than cited claims.
    unknowns: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    validation_steps: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    # Semantic claim-support outcome stamped by the flagging stage (ADR 0014):
    # unevaluated | supported | partial | unsupported, with a one-line rationale.
    # A derived, mutable annotation (not an invariant), so no DB CHECK constraint.
    support_status: Mapped[str] = mapped_column(String(16), nullable=False, default="unevaluated")
    support_rationale: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, nullable=False)

    run: Mapped[AnalysisRun] = relationship()
    evidence_refs: Mapped[list["EvidenceRef"]] = relationship(
        back_populates="hypothesis",
        cascade="all, delete-orphan",
        order_by="(EvidenceRef.role, EvidenceRef.line_start)",
    )
    action_items: Mapped[list["ActionItem"]] = relationship(
        back_populates="hypothesis",
        cascade="all, delete-orphan",
        order_by="ActionItem.sequence",
    )
    reviewer_notes: Mapped[list["ReviewerNote"]] = relationship(
        back_populates="hypothesis",
        cascade="all, delete-orphan",
        order_by="ReviewerNote.created_at",
    )
    # The bounded falsifier persists exactly one Hypothesis Challenge per
    # hypothesis before stage 3 can succeed (ADR 0034). uselist=False makes the
    # 1:1 explicit; the cascade removes the challenge (and its counterclaims) when
    # a retry clears and regenerates hypotheses.
    challenge: Mapped["HypothesisChallenge | None"] = relationship(
        back_populates="hypothesis",
        cascade="all, delete-orphan",
        uselist=False,
    )


class HypothesisChallenge(Base):
    """A persisted falsification review of one RCA Hypothesis (ADR 0034).

    The bounded falsifier challenges every initial RCA Hypothesis before the
    Causal Analysis Stage can succeed (PRD #28). A challenge identifies what
    weakens the hypothesis without accepting or rejecting it: its ``severity``
    advises causal-role suitability, ``counterclaims`` are cited Major Claims that
    weaken it, and ``evidence_gaps`` / ``falsification_tests`` are procedural
    guidance (no citations). Exactly one challenge per hypothesis (``hypothesis_id``
    unique). Only structured Role Handoff outputs are persisted — never the
    falsifier's hidden reasoning or chat history.
    """

    __tablename__ = "hypothesis_challenges"
    __table_args__ = (
        CheckConstraint(
            HYPOTHESIS_CHALLENGE_SEVERITY_CHECK,
            name="ck_hypothesis_challenges_severity",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    # Denormalized run id so the falsifier substep's output is queryable per run
    # (audit / stage-4 citation walk) without joining through the hypothesis.
    run_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("analysis_runs.id", ondelete="CASCADE"), nullable=False, index=True
    )
    hypothesis_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("hypotheses.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
        index=True,
    )
    # The specific hypothesis claim the falsifier challenged.
    challenged_claim: Mapped[str] = mapped_column(Text, nullable=False)
    # critical | material | minor (ADR 0034), enforced by the table CHECK above.
    severity: Mapped[str] = mapped_column(String(16), nullable=False)
    # Procedural guidance about missing evidence and how to confirm/refute the
    # hypothesis. Not factual incident claims, so plain string lists with no
    # citations (CONTEXT "Counterclaim vs Evidence Gap vs Falsification Test").
    evidence_gaps: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    falsification_tests: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    # Versioned falsifier identity (ADR 0025 / 0034) so a challenged run records
    # which role produced its challenges.
    falsifier_version: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, nullable=False)

    hypothesis: Mapped["Hypothesis"] = relationship(back_populates="challenge")
    counterclaims: Mapped[list["Counterclaim"]] = relationship(
        back_populates="challenge",
        cascade="all, delete-orphan",
        order_by="Counterclaim.sequence",
    )


class Counterclaim(Base):
    """A factual statement in a Hypothesis Challenge that weakens it (ADR 0034).

    A Counterclaim is a Major Claim (CONTEXT): it carries supporting EvidenceRefs
    resolved from immutable artifact lines, or is normalized to ``assumption=true``
    with an ``uncited_claim`` warning (ADR 0013) so the falsifier cannot introduce
    unchecked incident facts. Citations resolve from stored artifact lines, never
    from model text, and are audited by the Final Citation Audit like any other
    EvidenceRef.
    """

    __tablename__ = "counterclaims"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    challenge_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("hypothesis_challenges.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    statement: Mapped[str] = mapped_column(Text, nullable=False)
    # True when the counterclaim carried no supporting citation (ADR 0013); it
    # stays auditable but is not presented as an evidence-backed fact.
    assumption: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, nullable=False)

    challenge: Mapped[HypothesisChallenge] = relationship(back_populates="counterclaims")
    evidence_refs: Mapped[list["EvidenceRef"]] = relationship(
        back_populates="counterclaim",
        cascade="all, delete-orphan",
        order_by="EvidenceRef.line_start",
    )


class ReviewerNote(Base):
    """A human-authored review annotation separate from generated claims.

    Reviewer Notes capture review context without editing hypotheses, citations,
    verifier statuses, or generated postmortem text (ADR 0016). A note is scoped
    to the Analysis Run and may optionally attach to a specific hypothesis so the
    Review Surface can show it near the claim being discussed.
    """

    __tablename__ = "reviewer_notes"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    run_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("analysis_runs.id", ondelete="CASCADE"), nullable=False, index=True
    )
    hypothesis_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("hypotheses.id", ondelete="CASCADE"), nullable=True, index=True
    )
    body: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, nullable=False)

    run: Mapped[AnalysisRun] = relationship()
    hypothesis: Mapped[Hypothesis | None] = relationship(back_populates="reviewer_notes")


class ImpactClaim(Base):
    """A run-level, evidence-backed statement of incident impact (ADR 0033).

    Impact is an incident fact, not a causal interpretation: it describes observed
    user/system consequences once per Analysis Run and is independent of any RCA
    Hypothesis (PRD user stories 1-2). It is produced by the "extracting incident
    facts" stage before causal analysis begins. Impact is a Major Claim
    (severity/customer impact must not be invented), so it follows the same
    citation-or-assumption contract as a hypothesis (ADR 0013).
    """

    __tablename__ = "impact_claims"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    run_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("analysis_runs.id", ondelete="CASCADE"), nullable=False, index=True
    )
    sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    assumption: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    # Semantic claim-support outcome stamped by the flagging stage (ADR 0014),
    # mirroring Hypothesis: unevaluated | supported | partial | unsupported.
    support_status: Mapped[str] = mapped_column(String(16), nullable=False, default="unevaluated")
    support_rationale: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, nullable=False)

    run: Mapped[AnalysisRun] = relationship(back_populates="impact_claims")
    evidence_refs: Mapped[list["EvidenceRef"]] = relationship(
        back_populates="impact_claim",
        cascade="all, delete-orphan",
        order_by="EvidenceRef.line_start",
    )


class ActionItem(Base):
    """A remediation item tied to a hypothesis's context (PRD user story 16).

    Remediation items are forward-looking actions rather than factual claims
    about the incident, so they may cite supporting evidence but are not subject
    to the Major-Claim citation contract.
    """

    __tablename__ = "action_items"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    hypothesis_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("hypotheses.id", ondelete="CASCADE"), nullable=False, index=True
    )
    sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, nullable=False)

    hypothesis: Mapped[Hypothesis] = relationship(back_populates="action_items")
    evidence_refs: Mapped[list["EvidenceRef"]] = relationship(
        back_populates="action_item",
        cascade="all, delete-orphan",
        order_by="EvidenceRef.line_start",
    )


class Postmortem(Base):
    """The structured Postmortem composed for one Analysis Run (ADR 0012).

    Produced by the ``drafting_postmortem`` stage from already-verified structured
    outputs (ADR 0026): it stores the composed narrative that is not itself a
    structured claim — the ``summary`` overview and ``lessons_learned`` follow-ups
    (CONTEXT "Major Claim vs Generic Text"). The factual sections (timeline,
    hypotheses, impact, remediation) remain their own run-scoped rows and are
    composed into the read model and Markdown export, never duplicated here.

    Exactly one Postmortem per run (``run_id`` unique). ``composer_version``
    records which template produced it for experiment tracking (ADR 0025).
    """

    __tablename__ = "postmortems"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    run_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("analysis_runs.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
        index=True,
    )
    summary: Mapped[str] = mapped_column(Text, nullable=False)
    # Reflective follow-ups, stored as a JSON string list like a hypothesis's
    # unknowns; not Major Claims, so they carry no citations.
    lessons_learned: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    # Deterministic refusal assessment (ADR 0032 / 0015): 'sufficient' when at
    # least one hypothesis is backed by cited evidence, else 'insufficient' so the
    # Review Surface withholds a confident root cause instead of asserting an
    # unsupported one. ``evidence_gaps`` / ``next_validation_steps`` are procedural
    # guidance about evidence completeness (not new factual incident claims,
    # ADR 0026); meaningfully populated only on refusal.
    evidence_sufficiency: Mapped[str] = mapped_column(String(16), nullable=False, default="sufficient")
    evidence_gaps: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    next_validation_steps: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    # Provisional vs finalized lifecycle (ADR 0035, PRD #26 stories 26-28). An
    # automated Analysis Run only ever produces a 'provisional' draft: it presents
    # hypotheses and uncertainty but never a Root Cause Conclusion, which is a
    # separate human finalization action. The value stays 'provisional' until a
    # human finalizes; the column exists now so the provisional state is explicit
    # product data and distinguishable from a future finalized conclusion.
    conclusion_status: Mapped[str] = mapped_column(String(16), nullable=False, default="provisional")
    composer_version: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, nullable=False)

    run: Mapped[AnalysisRun] = relationship()


class EvaluationRun(Base):
    """A recorded evaluation of one scenario fixture (ADR 0010 / 0025).

    The EvaluationRunner materializes a scenario in an ephemeral database (so eval
    never depends on product Incident data), runs the replay pipeline, and records
    the outcome here: the deterministic check floor, Warning Code counts, the
    semantic judge scores, and the same Experiment Metadata as the underlying
    Analysis Run so prompt/pipeline tradeoffs are comparable (ADR 0025).

    ``judge_scores`` is null when no model is configured: citation validity comes
    from the deterministic ``checks`` / ``citation_verified`` columns, never the
    judge (ADR 0010).
    """

    __tablename__ = "evaluation_runs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    scenario_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    scenario_title: Mapped[str] = mapped_column(String(255), nullable=False)
    # Evaluation execution status, distinct from the underlying run's status.
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="succeeded")
    analysis_run_status: Mapped[str] = mapped_column(String(16), nullable=False)
    # True when every deterministic check passed (the trust floor, ADR 0010).
    passed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    # Experiment Metadata mirrored from the Analysis Run (ADR 0025).
    pipeline_version: Mapped[str] = mapped_column(String(64), nullable=False)
    prompt_version: Mapped[str] = mapped_column(String(64), nullable=False)
    model_provider: Mapped[str] = mapped_column(String(64), nullable=False)
    retrieval_strategy: Mapped[str] = mapped_column(String(64), nullable=False)
    chunking_strategy: Mapped[str] = mapped_column(String(64), nullable=False)
    verifier_version: Mapped[str] = mapped_column(String(64), nullable=False)
    # Null when no judge ran (no model configured). The deterministic floor stands
    # on its own without it.
    judge_version: Mapped[str | None] = mapped_column(String(64), nullable=True)

    citation_total: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    citation_verified: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    # Deterministic check results: [{"name", "passed", "detail"}].
    checks: Mapped[list[dict]] = mapped_column(JSON, nullable=False, default=list)
    # Warning Code counts aggregated across the run's stage events: {code: count}.
    warning_code_counts: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    # Judge rubric scores: {"scores": {...}, "overall": float, "rationale": str}
    # or null when no judge ran.
    judge_scores: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, nullable=False)


class EvidenceRef(Base):
    """A relational citation to an exact Artifact line range (ADR 0024 / 0027).

    EvidenceRefs point to Artifact line ranges rather than chunk ids, because
    chunk boundaries can change across Chunking Strategy versions while line
    addresses stay stable. The relational shape (not JSON) is what the citation
    panel, eval aggregation, and referential integrity depend on. ``snippet`` is
    the exact stored text of those lines so later citation-integrity
    verification can confirm an exact match.

    One ref belongs to exactly one owner via the nullable owner FKs below
    (timeline event, hypothesis, impact claim, action item, or counterclaim).
    ``role`` lets a hypothesis distinguish ``supporting`` evidence from
    ``contradicting`` evidence (PRD stage 3); other owners use ``supporting`` —
    a Counterclaim's own evidence supports the counterclaim statement (ADR 0034).
    """

    __tablename__ = "evidence_refs"
    __table_args__ = (
        CheckConstraint(
            EVIDENCE_REF_OWNER_CHECK,
            name="ck_evidence_refs_exactly_one_owner",
        ),
        CheckConstraint(
            EVIDENCE_REF_ROLE_CHECK,
            name="ck_evidence_refs_allowed_role",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    timeline_event_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("timeline_events.id", ondelete="CASCADE"), nullable=True, index=True
    )
    hypothesis_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("hypotheses.id", ondelete="CASCADE"), nullable=True, index=True
    )
    impact_claim_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("impact_claims.id", ondelete="CASCADE"), nullable=True, index=True
    )
    action_item_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("action_items.id", ondelete="CASCADE"), nullable=True, index=True
    )
    counterclaim_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("counterclaims.id", ondelete="CASCADE"), nullable=True, index=True
    )
    # supporting | contradicting (ADR 0024 / PRD stage 3). Defaults to supporting
    # for non-hypothesis owners.
    role: Mapped[str] = mapped_column(String(16), nullable=False, default="supporting")
    artifact_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("artifacts.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    source_name: Mapped[str] = mapped_column(String(255), nullable=False)
    line_start: Mapped[int] = mapped_column(Integer, nullable=False)
    line_end: Mapped[int] = mapped_column(Integer, nullable=False)
    snippet: Mapped[str] = mapped_column(Text, nullable=False)
    confidence_score: Mapped[float] = mapped_column(Float, nullable=False, default=1.0)
    # Deterministic citation-integrity outcome stamped by the verifying_citations
    # stage (ADR 0014). ``unverified`` until that stage runs; afterwards one of the
    # CitationIntegrityStatus values. A derived, mutable status (not an ownership
    # invariant), so it is not encoded as a DB CHECK constraint.
    verifier_status: Mapped[str] = mapped_column(String(24), nullable=False, default="unverified")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, nullable=False)

    timeline_event: Mapped["TimelineEvent"] = relationship(back_populates="evidence_refs")
    hypothesis: Mapped["Hypothesis"] = relationship(back_populates="evidence_refs")
    impact_claim: Mapped["ImpactClaim"] = relationship(back_populates="evidence_refs")
    action_item: Mapped["ActionItem"] = relationship(back_populates="evidence_refs")
    counterclaim: Mapped["Counterclaim"] = relationship(back_populates="evidence_refs")
    artifact: Mapped[Artifact] = relationship()
