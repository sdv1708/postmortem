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
    "extracting_incident_facts",
    "analyzing_causal_hypotheses",
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
    # The recorded Reasoning Budget the Causal Analysis Stage ran under (ADR 0043):
    # per-role and stage limits for retrieval, tokens, and calls, with one reserved
    # Targeted Repair per role. Null on runs created before the budget existed.
    reasoning_budget: dict | None = None


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
    # Controlled Causal Analysis Stage failure diagnostics (ADR 0043): a
    # machine-readable code and the failed role/invocation, set only when stage 3
    # fails through an exhausted Targeted Repair or Reasoning Budget. The failed-run
    # UI explains the failure from these without exposing Sensitive Evidence.
    failure_code: str | None = None
    failed_substep: str | None = None
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
    """A run-level, evidence-backed impact statement (ADR 0013 / 0033).

    Impact is an incident fact owned by the Analysis Run, shown once regardless of
    how many RCA Hypotheses exist. ``support_status`` carries the semantic
    claim-support judgment so the Review Surface can separate supported impact
    from partial/unsupported (ADR 0014).
    """

    id: str
    sequence: int
    description: str
    assumption: bool
    support_status: ClaimSupportStatus
    support_rationale: str | None
    evidence_refs: list[EvidenceRefRead]


# The review lifecycle of a generated Remediation Proposal (ADR 0041): the
# generated default 'proposed', then a human disposition. An 'accepted' proposal
# carries a link to a Causal Factor or Evidence Gap; the others carry none.
RemediationStatus = Literal["proposed", "accepted", "rejected", "deferred"]
# What an accepted proposal points at (ADR 0041, PRD story 53).
RemediationLinkKind = Literal["causal_factor", "evidence_gap"]


class RemediationLinkRead(BaseModel):
    """The Causal Factor or Evidence Gap an accepted proposal links to (ADR 0041).

    Resolved for display: a ``causal_factor`` link carries the factor's role and
    its hypothesis provenance; an ``evidence_gap`` link carries the
    ``(challenge, index)`` reference and the gap text resolved from the immutable
    challenge. ``label`` is a ready-to-render one-line summary of the target.
    """

    kind: RemediationLinkKind
    label: str
    causal_factor_id: str | None = None
    causal_factor_role: str | None = None
    hypothesis_id: str | None = None
    hypothesis_title: str | None = None
    evidence_gap_challenge_id: str | None = None
    evidence_gap_index: int | None = None
    evidence_gap_text: str | None = None


class ActionItemRead(BaseModel):
    """A generated Remediation Proposal with its human decision overlay (ADR 0041).

    The generated ``description`` and ``evidence_refs`` are immutable (ADR 0016);
    ``review_status`` and the decision provenance record the human's disposition.
    ``link`` is present only on an ``accepted`` proposal and points at why the work
    matters (PRD story 53).
    """

    id: str
    sequence: int
    description: str
    evidence_refs: list[EvidenceRefRead]
    review_status: RemediationStatus = "proposed"
    decision_rationale: str | None = None
    decided_by: str | None = None
    decided_by_display: str | None = None
    decided_at: datetime | None = None
    link: RemediationLinkRead | None = None


class RemediationLinkCreate(BaseModel):
    """The link an accepted Remediation Proposal must supply (ADR 0041).

    Exactly one target: a ``causal_factor`` link sets ``causal_factor_id``; an
    ``evidence_gap`` link sets ``evidence_gap_challenge_id`` and
    ``evidence_gap_index``. The service validates the target belongs to the
    reviewed incident.
    """

    kind: RemediationLinkKind
    causal_factor_id: str | None = None
    evidence_gap_challenge_id: str | None = None
    evidence_gap_index: int | None = None


class RemediationDecisionCreate(BaseModel):
    """Command payload to accept, reject, or defer a Remediation Proposal (ADR 0041).

    A decision never edits the generated remediation text (ADR 0016). ``link`` is
    required when ``decision`` is ``accepted`` and must be omitted otherwise; the
    service enforces the contract. ``rationale`` is optional reviewer context.
    """

    decision: RemediationStatus
    rationale: str | None = Field(default=None, max_length=4000)
    link: RemediationLinkCreate | None = None


class ReviewerNoteRead(BaseModel):
    """A human-authored review annotation separate from generated claims."""

    model_config = ConfigDict(from_attributes=True)

    id: str
    run_id: str
    hypothesis_id: str | None
    body: str
    created_at: datetime


# Challenge Severity advises causal-role suitability (ADR 0034): critical blocks
# use as the Failure Mechanism, material limits the causal role, minor qualifies.
ChallengeSeverity = Literal["critical", "material", "minor"]


class CounterclaimRead(BaseModel):
    """A factual statement that weakens a hypothesis (ADR 0034).

    A Counterclaim is a Major Claim: its EvidenceRefs are exact, verifiable
    citations, and ``assumption`` marks one normalized for lack of a resolvable
    citation (ADR 0013) so the falsifier cannot smuggle in unchecked facts.
    """

    id: str
    sequence: int
    statement: str
    assumption: bool
    evidence_refs: list[EvidenceRefRead]


class HypothesisChallengeRead(BaseModel):
    """The bounded falsifier's challenge of one RCA Hypothesis (ADR 0034).

    Exposes the structured falsification output for the Review Surface — the
    challenged claim, its advisory ``severity``, cited Counterclaims, and the
    procedural Evidence Gaps and Falsification Tests — without exposing any hidden
    reasoning or chat history (PRD user story 75 / 89).
    """

    id: str
    challenged_claim: str
    severity: ChallengeSeverity
    counterclaims: list[CounterclaimRead]
    evidence_gaps: list[str]
    falsification_tests: list[str]


class RankingRationaleRead(BaseModel):
    """Per-dimension explanation of a hypothesis's advisory rank (ADR 0037).

    The five assessment dimensions the ranker explains plus a one-line summary
    (PRD user story 19). Ordering is explained through these, never as a
    probability or percentage (PRD user story 18).
    """

    support_strength: str
    counterevidence_severity: str
    explanatory_coverage: str
    evidence_gaps: str
    assumption_dependence: str
    summary: str


class HypothesisRead(BaseModel):
    """A ranked RCA Hypothesis for the Review Surface (PRD stage 3).

    Supporting and contradicting evidence are pre-split so the reviewer sees both
    sides without re-deriving the distinction. ``assumption`` marks a hypothesis
    that carried no supporting citation and was normalized (ADR 0013), and
    ``review_status`` records the human accept/reject decision (ADR 0016).
    ``challenge`` is the bounded falsifier's persisted Hypothesis Challenge
    (ADR 0034), present on every hypothesis in a successful run.

    ``advisory_rank`` is the post-challenge Advisory Hypothesis Ranking position
    and drives display order; ``rank`` is the original builder/generation order,
    retained for audit (ADR 0037, PRD user story 20). ``ranking_rationale``
    explains the advisory rank across the five assessment dimensions, and
    ``leading_but_critically_challenged`` flags the advisory leader when its
    challenge is critical so the ranking is never mistaken for confidence
    (PRD user stories 21-22).
    """

    id: str
    run_id: str
    rank: int
    advisory_rank: int | None = None
    ranking_rationale: RankingRationaleRead | None = None
    leading_but_critically_challenged: bool = False
    # Provenance within the Causal Analysis Stage (ADR 0036): 'initial' for a
    # builder hypothesis, 'proposed' for a falsifier-introduced missed alternative.
    # The Review Surface distinguishes the two without treating either as a
    # conclusion (PRD #30 user story 14-15).
    origin: Literal["initial", "proposed"]
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
    action_items: list[ActionItemRead]
    reviewer_notes: list[ReviewerNoteRead] = Field(default_factory=list)
    challenge: HypothesisChallengeRead | None = None


class HypothesisReviewCreate(BaseModel):
    """Command payload to accept or reject a hypothesis (ADR 0016 / 0022)."""

    decision: Literal["accepted", "rejected", "proposed"]


class ReviewerNoteCreate(BaseModel):
    """Command payload to add a Reviewer Note (ADR 0016 / 0022)."""

    body: str = Field(min_length=1, max_length=4000)
    hypothesis_id: str | None = None


# The causal role a Causal Factor plays in a Root Cause Conclusion (ADR 0039).
# Every conclusion has exactly one failure_mechanism; triggers and amplifying
# conditions are optional and repeatable.
CausalRole = Literal["failure_mechanism", "trigger", "amplifying_condition"]


class CausalFactorCreate(BaseModel):
    """One accepted hypothesis the reviewer assigns a causal role (ADR 0039 / 0042).

    A partially supported factor must carry a ``partial_support_acknowledgment``
    describing what is supported and what remains uncertain (PRD #26 stories 38-39);
    a critically challenged Failure Mechanism must carry a ``critical_challenge_override``
    addressing the unresolved critical challenge (stories 40-41). The service enforces
    when each is required; both are optional here so a fully supported, uncontested
    factor needs neither.
    """

    hypothesis_id: str
    role: CausalRole
    partial_support_acknowledgment: str | None = Field(default=None, max_length=4000)
    critical_challenge_override: str | None = Field(default=None, max_length=4000)


class RootCauseConclusionCreate(BaseModel):
    """Command payload to finalize a human Root Cause Conclusion (ADR 0039 / 0042 / 0022).

    The reviewer supplies a structured causal ``summary`` and one or more
    ``factors`` drawn from accepted RCA Hypotheses. The service enforces the trust
    floor: exactly one Failure Mechanism, each factor an accepted hypothesis with
    verified citations and supported/partial claim support (PRD #26 stories 31-37),
    a Partial-Support Acknowledgment for each partial factor and a Critical-Challenge
    Override for a critically challenged Failure Mechanism (stories 38-41).

    ``human_assumptions`` are unevidenced reviewer beliefs recorded separately from
    the evidence-backed factors so they never render as established fact (story 38).
    """

    summary: str = Field(min_length=1, max_length=4000)
    factors: list[CausalFactorCreate] = Field(min_length=1)
    human_assumptions: list[str] = Field(default_factory=list)


class HumanAssumptionRead(BaseModel):
    """A labeled, unevidenced reviewer belief recorded with a conclusion (ADR 0042).

    Stored separately from the evidence-backed Causal Factors and always rendered as
    an explicit assumption, never as established fact (PRD #26 story 38).
    """

    id: str
    statement: str
    created_at: datetime


class CausalFactorRead(BaseModel):
    """A Causal Factor in a finalized conclusion, with its hypothesis provenance.

    Carries the linked hypothesis's title/summary, semantic support, advisory rank,
    and verified supporting citations so the conclusion is navigable to exact
    evidence and visibly preserves generated provenance (PRD #26 stories 36-37).

    ``partial_support_acknowledgment`` and ``critical_challenge_override`` preserve
    the reviewer's qualifications (PRD #26 stories 38-41); ``challenge`` is the factor
    hypothesis's full persisted Hypothesis Challenge — challenged claim, severity,
    cited Counterclaims, Evidence Gaps, Falsification Tests — so the Review Surface
    and exports preserve the actual critical challenge wherever the factor is
    rendered, and an override can be audited against the concern it addresses (story
    41), not just a severity label.
    """

    id: str
    role: CausalRole
    hypothesis_id: str
    title: str
    summary: str
    support_status: ClaimSupportStatus
    advisory_rank: int | None
    supporting_evidence: list[EvidenceRefRead]
    partial_support_acknowledgment: str | None = None
    critical_challenge_override: str | None = None
    challenge: HypothesisChallengeRead | None = None


class ConclusionDiscrepancyCreate(BaseModel):
    """Command payload to flag a finalized conclusion as disputed (ADR 0040 / 0022).

    A reviewer supplies the ``explanation`` of what is wrong with the immutable Root
    Cause Conclusion. Creating it never edits the conclusion (PRD #26 stories 44-46).
    """

    explanation: str = Field(min_length=1, max_length=4000)


class ConclusionDiscrepancyRead(BaseModel):
    """An append-only flag disputing a Root Cause Conclusion (ADR 0040).

    Records the reviewer's ``explanation`` plus who raised it and when. An open
    discrepancy makes its conclusion a Disputed Conclusion, withheld from
    authoritative presentation while preserved for audit.
    """

    id: str
    conclusion_id: str
    run_id: str
    explanation: str
    raised_by: str
    raised_by_display: str | None
    created_at: datetime


class RootCauseConclusionRead(BaseModel):
    """A finalized human Root Cause Conclusion for the Review Surface (ADR 0039).

    Distinct from the Advisory Hypothesis Ranking: a ranking recommends plausible
    candidates, while this is the human's decision (PRD #26 stories 30, 90). Every
    conclusion has exactly one ``failure_mechanism`` plus optional repeatable
    ``triggers`` and ``amplifying_conditions``. Conclusion Provenance records who
    finalized it, when, and from which run; the conclusion is immutable.

    ``disputed`` is true when at least one append-only Conclusion Discrepancy has been
    raised against it (ADR 0040): the conclusion is then preserved for audit but is no
    longer authoritative, and the incident has returned to unresolved review.
    """

    id: str
    run_id: str
    incident_id: str
    summary: str
    finalized_by: str
    finalized_by_display: str | None
    finalized_at: datetime
    failure_mechanism: CausalFactorRead
    triggers: list[CausalFactorRead]
    amplifying_conditions: list[CausalFactorRead]
    human_assumptions: list[HumanAssumptionRead] = Field(default_factory=list)
    disputed: bool
    discrepancies: list[ConclusionDiscrepancyRead]
    created_at: datetime


# How a Markdown export treats unsupported/assumption claims (ADR 0015).
ExportMode = Literal["clean", "audit"]


class PostmortemRead(BaseModel):
    """The structured Postmortem for the Review Surface (ADR 0012).

    The composed ``summary`` and ``lessons_learned`` come from the Postmortem
    row; ``timeline``, run-level ``impact_claims``, and ``hypotheses`` (with their
    nested remediation) are composed from the run's existing structured rows so
    the citation source of truth stays the EvidenceRefs (ADR 0024). Impact is a
    run-level incident fact shown once, independent of hypothesis count (ADR 0033).
    """

    id: str
    run_id: str
    incident_title: str
    incident_severity: str | None
    summary: str
    lessons_learned: list[str]
    # Refusal assessment (ADR 0032 / 0015): 'sufficient' or 'insufficient'. On
    # refusal, ``evidence_gaps`` and ``next_validation_steps`` tell the reviewer
    # what is missing and what to collect next, while no confident root cause is
    # asserted.
    evidence_sufficiency: Literal["sufficient", "insufficient"]
    evidence_gaps: list[str]
    next_validation_steps: list[str]
    # Lifecycle state of the automated draft (ADR 0035 / 0039 / 0040, PRD #26).
    # 'provisional' means no human Root Cause Conclusion exists yet, so the Review
    # Surface and exports label it "Draft: Root cause not finalized". 'finalized'
    # means a human finalized one. 'disputed' is derived (ADR 0040): a finalized
    # conclusion carrying an open Conclusion Discrepancy is no longer authoritative
    # and the incident has returned to unresolved review.
    conclusion_status: Literal["provisional", "finalized", "disputed"]
    composer_version: str
    timeline: list[TimelineEventRead]
    impact_claims: list[ImpactClaimRead]
    hypotheses: list[HypothesisRead]
    # The finalized human Root Cause Conclusion (ADR 0039), present only once a
    # reviewer finalizes one (``conclusion_status == "finalized"``); null while the
    # draft is provisional. Rendered distinctly from the Advisory Hypothesis Ranking.
    conclusion: RootCauseConclusionRead | None = None
    created_at: datetime


class RetrievalTraceChunkRead(BaseModel):
    """One ordered Chunk reference in a Retrieval Trace (ADR 0038).

    A reference only — chunk id, owning artifact, source order, line span, and
    whether the role cited it — never chunk or Artifact text, so the diagnostics
    view never exposes duplicated Sensitive Evidence (PRD user stories 70-71).
    """

    chunk_id: str
    artifact_id: str
    sequence: int
    line_start: int
    line_end: int
    cited: bool


class RetrievalTraceRead(BaseModel):
    """The evidence a Reasoning Role received for one substep (ADR 0038).

    ``chunk_count`` / ``cited_count`` summarize the ordered ``chunks``;
    retrieved-but-uncited chunks (``chunk_count - cited_count``) are what let a
    diagnostician separate a retrieval omission from a model omission (PRD user
    story 70).
    """

    id: str
    sequence: int
    role: str
    substep: str
    query: str
    strategy_version: str
    chunk_count: int
    cited_count: int
    chunks: list[RetrievalTraceChunkRead]


class ModelCallRecordRead(BaseModel):
    """Reproducibility metadata for one Reasoning Role invocation (ADR 0038).

    Carries role/substep identity, prompt and schema versions, model identity,
    token ``usage``, prompt/response hashes, the validated ``structured_output``,
    and the linked ``retrieval_trace_id`` — never the prompt, raw response, hidden
    reasoning, or duplicated Artifact text (PRD user stories 71, 73). A
    deterministic role reports its own version as ``model_identity`` with null
    usage/hashes.
    """

    id: str
    sequence: int
    role: str
    substep: str
    prompt_version: str
    schema_version: str
    model_identity: str
    input_hash: str | None
    output_hash: str | None
    usage: dict | None
    structured_output: dict | None
    retrieval_trace_id: str | None
    created_at: datetime


class RunDiagnosticsRead(BaseModel):
    """Restricted reasoning/retrieval provenance for one Analysis Run (ADR 0038).

    The diagnostics resource backing the run-diagnostics view: every Model Call
    Record and Retrieval Trace for the run, in execution order, so causal
    reasoning is diagnosable without opening restricted debug logs (PRD #26 user
    stories 57, 69-73, 88-89). It exposes no prompts, raw responses, or Artifact
    text — provenance references and hashes only.
    """

    run_id: str
    model_call_records: list[ModelCallRecordRead]
    retrieval_traces: list[RetrievalTraceRead]


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


class EvaluationCheckRead(BaseModel):
    """One deterministic check outcome in an Evaluation Run (ADR 0010)."""

    name: str
    passed: bool
    detail: str


class JudgeScoresRead(BaseModel):
    """Semantic judge rubric scores; never the citation-validity authority (ADR 0010)."""

    scores: dict[str, int]
    overall: float
    rationale: str


class EvaluationRunCreate(BaseModel):
    """Command payload to run evaluation (ADR 0022 / 0010).

    Omit ``scenario_id`` to evaluate every available scenario fixture.
    """

    scenario_id: str | None = None


class EvaluationRunRead(BaseModel):
    """A recorded Evaluation Run for the dev dashboard (ADR 0010 / 0025).

    Citation validity lives in ``citation_verified`` / the ``citation_integrity``
    check, never in ``judge_scores`` — which may be null when no model is
    configured.
    """

    id: str
    scenario_id: str
    scenario_title: str
    status: str
    analysis_run_status: RunStatus
    # The configuration that produced the run (PRD #38): the product "multi_pass"
    # or the "builder_only" baseline, compared side by side in the dashboard.
    analysis_mode: str
    passed: bool
    experiment_metadata: ExperimentMetadata
    check_suite_version: str
    judge_version: str | None
    citation_total: int
    citation_verified: int
    # Cost metrics recorded beside quality so improvement is not bought with
    # unbounded cost (PRD #38 stories 87).
    model_calls: int
    total_tokens: int
    latency_ms: int
    checks: list[EvaluationCheckRead]
    warning_code_counts: dict[str, int]
    judge_scores: JudgeScoresRead | None
    error: str | None
    created_at: datetime
