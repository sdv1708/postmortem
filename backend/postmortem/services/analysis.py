from __future__ import annotations

import logging
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..chunking import CHUNKING_STRATEGY_VERSION
from ..config import DEFAULT_EXPERIMENT_METADATA
from ..drafting import PostmortemComposer
from ..falsification import Falsifier
from ..incident_facts import IncidentFactExtractor
from ..llm import LLMClient
from ..logging import log_event
from ..models import (
    AnalysisRun,
    Artifact,
    Hypothesis,
    ImpactClaim,
    Postmortem,
    ReviewerNote,
    RunArtifact,
    TimelineEvent,
)
from ..rca import PROMPT_VERSION
from ..retrieval import RETRIEVAL_STRATEGY_VERSION, RetrievalStrategy
from ..schemas import AnalysisRunCreate, ReviewerNoteCreate
from ..verification import (
    CITATION_VERIFIER_VERSION,
    CLAIM_SUPPORT_VERIFIER_VERSION,
    ClaimSupportVerifier,
)
from .artifacts import ArtifactNotFoundError
from .incidents import IncidentService
from .run_executor import RunExecutor, StagedRunExecutor, StageRecorder
from .stages import PipelineStageRunner


class AnalysisRunNotFoundError(LookupError):
    pass


class HypothesisNotFoundError(LookupError):
    pass


class PostmortemNotFoundError(LookupError):
    """Raised when a run has not yet produced a structured Postmortem."""


class NoArtifactsError(ValueError):
    """Raised when a run is started with no Artifacts to analyze."""


# Hypothesis review decisions a reviewer may record (ADR 0016). Accepting or
# rejecting never edits the generated claims; it only sets this status.
HYPOTHESIS_REVIEW_STATUSES: frozenset[str] = frozenset({"accepted", "rejected", "proposed"})
logger = logging.getLogger("postmortem.analysis")


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class AnalysisService:
    """Owns the Analysis Run lifecycle (ADR 0004 kept interface).

    The web routes and the future CLI both call `start_run` rather than
    duplicating orchestration in transport code. A run is created as durable,
    pollable async product state (ADR 0003): it is persisted as ``queued``, its
    included Artifacts are locked immutable (ADR 0018), then a RunExecutor
    advances it through the six DB-persisted stages (ADR 0026), recording a Run
    Stage Event per attempt before the next stage. Service callers can keep
    inline execution for tests/CLI-style flows; the HTTP route creates the run
    first and executes it in a background session so status polling can observe
    progress.
    """

    def __init__(
        self,
        session: Session,
        executor: RunExecutor | None = None,
        llm_client: LLMClient | None = None,
        claim_support_verifier: ClaimSupportVerifier | None = None,
        postmortem_composer: PostmortemComposer | None = None,
        retrieval_strategy: RetrievalStrategy | None = None,
        incident_fact_extractor: IncidentFactExtractor | None = None,
        falsifier: Falsifier | None = None,
    ) -> None:
        self._session = session
        self._llm_client = llm_client
        self._retrieval_strategy_version = (
            retrieval_strategy.version
            if retrieval_strategy is not None
            else RETRIEVAL_STRATEGY_VERSION
        )
        self._claim_support_verifier_version = (
            claim_support_verifier.version
            if claim_support_verifier is not None
            else CLAIM_SUPPORT_VERIFIER_VERSION
        )
        # Default to the real six-stage pipeline whose stage work (chunking,
        # timeline extraction, RCA generation, verification, flagging) reads and
        # writes through this session (ADR 0026). The RCA and claim-support stages
        # use the injected LLMClient, or the offline default when none is
        # configured (ADR 0011). Tests inject their own executor, client, and/or a
        # fake claim-support verifier to exercise edge cases deterministically.
        self._executor = executor or StagedRunExecutor(
            stage_runner=PipelineStageRunner(
                session,
                llm_client=llm_client,
                claim_support_verifier=claim_support_verifier,
                postmortem_composer=postmortem_composer,
                retrieval_strategy=retrieval_strategy,
                incident_fact_extractor=incident_fact_extractor,
                falsifier=falsifier,
            )
        )

    def start_run(
        self,
        incident_id: str,
        payload: AnalysisRunCreate,
        *,
        execute_inline: bool = True,
    ) -> AnalysisRun:
        log_event(
            logger,
            logging.INFO,
            "analysis_run_create_requested",
            incident_id=incident_id,
            selected_artifacts=("all" if payload.artifact_ids is None else len(payload.artifact_ids)),
            execute_inline=execute_inline,
        )
        IncidentService(self._session).get(incident_id)
        artifacts = self._resolve_artifacts(incident_id, payload.artifact_ids)

        # Record which strategies actually ran (ADR 0025): the chunking version,
        # the RCA prompt version, and the configured model behind the LLMClient
        # (ADR 0011). When no client is injected the model defaults stay as the
        # offline placeholder.
        # The chunker and both verifier passes (deterministic citation integrity +
        # semantic claim support) always run, so stamp their real versions; the
        # model/prompt only when a provider is injected (ADR 0025).
        metadata = {
            **DEFAULT_EXPERIMENT_METADATA,
            "chunking_strategy": CHUNKING_STRATEGY_VERSION,
            "retrieval_strategy": self._retrieval_strategy_version,
            "verifier_version": f"{CITATION_VERIFIER_VERSION}+{self._claim_support_verifier_version}",
        }
        if self._llm_client is not None:
            metadata["model_provider"] = self._llm_client.label
            metadata["prompt_version"] = PROMPT_VERSION
        run = AnalysisRun(
            incident_id=incident_id,
            status="queued",
            **metadata,
        )
        self._session.add(run)
        self._session.flush()

        # Lock the included Artifacts before any execution so their bodies
        # remain the citation source of truth for the life of the run.
        for artifact in artifacts:
            self._session.add(RunArtifact(run_id=run.id, artifact_id=artifact.id))
            artifact.included_in_analysis_run = True
        self._session.flush()
        log_event(
            logger,
            logging.INFO,
            "analysis_run_created",
            run_id=run.id,
            incident_id=incident_id,
            artifact_count=len(artifacts),
            model_provider=metadata["model_provider"],
            retrieval_strategy=metadata["retrieval_strategy"],
            chunking_strategy=metadata["chunking_strategy"],
            verifier_version=metadata["verifier_version"],
        )

        if execute_inline:
            self.execute_run(run.id)
        return run

    def execute_run(self, run_id: str, *, commit_progress: bool = False) -> AnalysisRun:
        log_event(logger, logging.INFO, "analysis_run_execute_requested", run_id=run_id)
        run = self._session.get(AnalysisRun, run_id)
        if run is None:
            log_event(logger, logging.WARNING, "analysis_run_execute_missing", run_id=run_id)
            raise AnalysisRunNotFoundError(run_id)
        if run.status in {"running", "succeeded", "failed"}:
            log_event(
                logger,
                logging.INFO,
                "analysis_run_execute_skipped",
                run_id=run.id,
                status=run.status,
            )
            return run
        self._execute(run, commit_progress=commit_progress)
        return run

    def get_run(self, incident_id: str, run_id: str) -> AnalysisRun:
        IncidentService(self._session).get(incident_id)
        run = self._session.get(AnalysisRun, run_id)
        if run is None or run.incident_id != incident_id:
            raise AnalysisRunNotFoundError(run_id)
        return run

    def list_runs(self, incident_id: str) -> list[AnalysisRun]:
        IncidentService(self._session).get(incident_id)
        stmt = (
            select(AnalysisRun)
            .where(AnalysisRun.incident_id == incident_id)
            .order_by(AnalysisRun.created_at.desc())
        )
        return list(self._session.scalars(stmt))

    def list_timeline(self, incident_id: str, run_id: str) -> list[TimelineEvent]:
        """Sorted Timeline Events for a run, with their EvidenceRefs (ADR 0019).

        Validates the run belongs to the incident first so the endpoint cannot
        leak another incident's timeline.
        """
        self.get_run(incident_id, run_id)
        stmt = (
            select(TimelineEvent)
            .where(TimelineEvent.run_id == run_id)
            .order_by(TimelineEvent.sequence.asc())
        )
        return list(self._session.scalars(stmt))

    def list_impact_claims(self, incident_id: str, run_id: str) -> list[ImpactClaim]:
        """Run-level Impact Claims for a run, with their EvidenceRefs (ADR 0033).

        Impact is an incident fact owned by the run and shown once regardless of
        hypothesis count (PRD user stories 1-2). Validates the run belongs to the
        incident first so the endpoint cannot leak another incident's impact.
        """
        self.get_run(incident_id, run_id)
        stmt = (
            select(ImpactClaim)
            .where(ImpactClaim.run_id == run_id)
            .order_by(ImpactClaim.sequence.asc())
        )
        return list(self._session.scalars(stmt))

    def list_hypotheses(self, incident_id: str, run_id: str) -> list[Hypothesis]:
        """Ranked RCA Hypotheses for a run, with their claims and citations.

        Validates the run belongs to the incident first so the endpoint cannot
        leak another incident's hypotheses.
        """
        self.get_run(incident_id, run_id)
        stmt = (
            select(Hypothesis)
            .where(Hypothesis.run_id == run_id)
            .order_by(Hypothesis.rank.asc())
        )
        return list(self._session.scalars(stmt))

    def get_postmortem(self, incident_id: str, run_id: str) -> Postmortem:
        """The structured Postmortem composed for a run (ADR 0012).

        Validates the run belongs to the incident first so the endpoint cannot
        leak another incident's postmortem. Raises if the run has not reached the
        drafting stage (e.g. it failed earlier, or is still running).
        """
        self.get_run(incident_id, run_id)
        postmortem = self._session.scalar(
            select(Postmortem).where(Postmortem.run_id == run_id)
        )
        if postmortem is None:
            raise PostmortemNotFoundError(run_id)
        return postmortem

    def get_postmortem_document(self, incident_id: str, run_id: str) -> dict:
        """Assemble the full structured Postmortem read model for a run.

        Composes the persisted Postmortem row (summary + lessons) with the run's
        timeline and ranked hypotheses (impact + remediation hang off each
        hypothesis). The structured document is the single source of truth that
        both the Review Surface and the Markdown export render from (ADR 0012).
        """
        postmortem = self.get_postmortem(incident_id, run_id)
        timeline = list(
            self._session.scalars(
                select(TimelineEvent)
                .where(TimelineEvent.run_id == run_id)
                .order_by(TimelineEvent.sequence.asc())
            )
        )
        impact_claims = list(
            self._session.scalars(
                select(ImpactClaim)
                .where(ImpactClaim.run_id == run_id)
                .order_by(ImpactClaim.sequence.asc())
            )
        )
        hypotheses = list(
            self._session.scalars(
                select(Hypothesis).where(Hypothesis.run_id == run_id).order_by(Hypothesis.rank.asc())
            )
        )
        return postmortem_read(
            postmortem, postmortem.run.incident, timeline, impact_claims, hypotheses
        )

    def review_hypothesis(
        self, incident_id: str, run_id: str, hypothesis_id: str, decision: str
    ) -> Hypothesis:
        """Record an accept/reject decision without rewriting the claim (ADR 0016)."""
        self.get_run(incident_id, run_id)
        hypothesis = self._session.get(Hypothesis, hypothesis_id)
        if hypothesis is None or hypothesis.run_id != run_id:
            raise HypothesisNotFoundError(hypothesis_id)
        if decision not in HYPOTHESIS_REVIEW_STATUSES:
            raise ValueError(f"invalid review decision: {decision}")
        hypothesis.review_status = decision
        self._session.flush()
        log_event(
            logger,
            logging.INFO,
            "hypothesis_review_recorded",
            run_id=run_id,
            incident_id=incident_id,
            hypothesis_id=hypothesis_id,
            decision=decision,
        )
        return hypothesis

    def add_reviewer_note(
        self, incident_id: str, run_id: str, payload: ReviewerNoteCreate
    ) -> ReviewerNote:
        """Record a human review note without rewriting generated claims (ADR 0016)."""
        self.get_run(incident_id, run_id)
        hypothesis = None
        if payload.hypothesis_id is not None:
            hypothesis = self._session.get(Hypothesis, payload.hypothesis_id)
            if hypothesis is None or hypothesis.run_id != run_id:
                raise HypothesisNotFoundError(payload.hypothesis_id)
        body = payload.body.strip()
        if not body:
            raise ValueError("reviewer note body cannot be blank")
        note = ReviewerNote(run_id=run_id, hypothesis_id=payload.hypothesis_id, body=body)
        if hypothesis is None:
            self._session.add(note)
        else:
            hypothesis.reviewer_notes.append(note)
        self._session.flush()
        log_event(
            logger,
            logging.INFO,
            "reviewer_note_added",
            run_id=run_id,
            incident_id=incident_id,
            hypothesis_id=payload.hypothesis_id,
            body_chars=len(body),
        )
        return note

    def _resolve_artifacts(
        self, incident_id: str, artifact_ids: list[str] | None
    ) -> list[Artifact]:
        if artifact_ids is None:
            stmt = (
                select(Artifact)
                .where(Artifact.incident_id == incident_id)
                .order_by(Artifact.created_at.asc())
            )
            artifacts = list(self._session.scalars(stmt))
        else:
            artifacts = []
            for artifact_id in artifact_ids:
                artifact = self._session.get(Artifact, artifact_id)
                if artifact is None or artifact.incident_id != incident_id:
                    raise ArtifactNotFoundError(artifact_id)
                artifacts.append(artifact)

        if not artifacts:
            raise NoArtifactsError(incident_id)
        return artifacts

    def _execute(self, run: AnalysisRun, *, commit_progress: bool = False) -> None:
        started = _utcnow()
        run.status = "running"
        run.started_at = started
        self._session.flush()
        if commit_progress:
            self._session.commit()
        log_event(
            logger,
            logging.INFO,
            "analysis_run_started",
            run_id=run.id,
            incident_id=run.incident_id,
            commit_progress=commit_progress,
        )
        recorder = StageRecorder(self._session, run, commit_on_change=commit_progress)
        try:
            self._executor.execute(run, recorder)
        except Exception as exc:  # ADR 0029: a stage that fails its retry fails the run
            # Prior stage events and the Artifact lock are left intact and
            # inspectable; later stages were never started.
            run.status = "failed"
            run.error = str(exc) or exc.__class__.__name__
            run.completed_at = _utcnow()
            self._session.flush()
            if commit_progress:
                self._session.commit()
            log_event(
                logger,
                logging.ERROR,
                "analysis_run_failed",
                run_id=run.id,
                incident_id=run.incident_id,
                error=run.error,
                duration_ms=_elapsed_ms(started, run.completed_at),
            )
            return
        run.status = "succeeded"
        run.completed_at = _utcnow()
        self._session.flush()
        if commit_progress:
            self._session.commit()
        log_event(
            logger,
            logging.INFO,
            "analysis_run_succeeded",
            run_id=run.id,
            incident_id=run.incident_id,
            duration_ms=_elapsed_ms(started, run.completed_at),
        )


def _elapsed_ms(start: datetime | None, end: datetime | None) -> int | None:
    if start is None or end is None:
        return None
    return max(0, int((end - start).total_seconds() * 1000))


def run_artifact_ids(run: AnalysisRun) -> list[str]:
    return [ref.artifact_id for ref in run.run_artifacts]


def timeline_event_read(event: TimelineEvent) -> dict:
    """Shape a TimelineEvent (with EvidenceRefs) for TimelineEventRead.

    ``normalized_ts`` is stored naive UTC (see stages._as_naive_utc); re-attach
    the UTC tz on the way out so the API emits an unambiguous ``...Z`` instant.
    """
    normalized = event.normalized_ts
    if normalized is not None and normalized.tzinfo is None:
        normalized = normalized.replace(tzinfo=timezone.utc)
    return {
        "id": event.id,
        "sequence": event.sequence,
        "normalized_ts": normalized,
        "original_ts_text": event.original_ts_text,
        "uncertain": event.uncertain,
        "description": event.description,
        "evidence_refs": list(event.evidence_refs),
    }


def impact_claim_read(claim) -> dict:
    return {
        "id": claim.id,
        "sequence": claim.sequence,
        "description": claim.description,
        "assumption": claim.assumption,
        "support_status": claim.support_status,
        "support_rationale": claim.support_rationale,
        "evidence_refs": list(claim.evidence_refs),
    }


def _action_item_read(item) -> dict:
    return {
        "id": item.id,
        "sequence": item.sequence,
        "description": item.description,
        "evidence_refs": list(item.evidence_refs),
    }


def reviewer_note_read(note: ReviewerNote) -> dict:
    """Shape a ReviewerNote with unambiguous UTC timestamps."""
    created_at = note.created_at
    if created_at is not None and created_at.tzinfo is None:
        created_at = created_at.replace(tzinfo=timezone.utc)
    return {
        "id": note.id,
        "run_id": note.run_id,
        "hypothesis_id": note.hypothesis_id,
        "body": note.body,
        "created_at": created_at,
    }


def hypothesis_read(hypothesis: Hypothesis) -> dict:
    """Shape a Hypothesis (with claims/citations) for HypothesisRead.

    Supporting and contradicting evidence are split by ``role`` so the Review
    Surface can render them separately (PRD stage 3) rather than the client
    re-deriving the split from a flat list.
    """
    supporting = [ref for ref in hypothesis.evidence_refs if ref.role != "contradicting"]
    contradicting = [ref for ref in hypothesis.evidence_refs if ref.role == "contradicting"]
    return {
        "id": hypothesis.id,
        "run_id": hypothesis.run_id,
        "rank": hypothesis.rank,
        "origin": hypothesis.origin or "initial",
        "title": hypothesis.title,
        "summary": hypothesis.summary,
        "assumption": hypothesis.assumption,
        "review_status": hypothesis.review_status,
        "support_status": hypothesis.support_status,
        "support_rationale": hypothesis.support_rationale,
        "unknowns": list(hypothesis.unknowns),
        "validation_steps": list(hypothesis.validation_steps),
        "supporting_evidence": supporting,
        "contradicting_evidence": contradicting,
        "action_items": [_action_item_read(item) for item in hypothesis.action_items],
        "reviewer_notes": [reviewer_note_read(note) for note in hypothesis.reviewer_notes],
        # The bounded falsifier's persisted challenge (ADR 0034), or None until a
        # run reaches stage 3. Structured Role Handoff output only — never hidden
        # reasoning or chat history (PRD user story 75).
        "challenge": challenge_read(hypothesis.challenge) if hypothesis.challenge else None,
    }


def counterclaim_read(counterclaim) -> dict:
    """Shape a Counterclaim (with its citations) for CounterclaimRead.

    A Counterclaim is a Major Claim: its EvidenceRefs are the citation source of
    truth (ADR 0024), and ``assumption`` marks one normalized for lack of a
    resolvable citation (ADR 0013).
    """
    return {
        "id": counterclaim.id,
        "sequence": counterclaim.sequence,
        "statement": counterclaim.statement,
        "assumption": counterclaim.assumption,
        "evidence_refs": list(counterclaim.evidence_refs),
    }


def challenge_read(challenge) -> dict:
    """Shape a HypothesisChallenge for HypothesisChallengeRead (ADR 0034).

    Surfaces the falsifier's structured output — challenged claim, severity, cited
    Counterclaims, Evidence Gaps, Falsification Tests — so the Review Surface can
    show the analysis's work without exposing hidden reasoning (PRD user story 89).
    """
    return {
        "id": challenge.id,
        "challenged_claim": challenge.challenged_claim,
        "severity": challenge.severity,
        "counterclaims": [counterclaim_read(c) for c in challenge.counterclaims],
        "evidence_gaps": list(challenge.evidence_gaps),
        "falsification_tests": list(challenge.falsification_tests),
    }


def postmortem_read(postmortem, incident, timeline_events, impact_claims, hypotheses) -> dict:
    """Shape a Postmortem (with its run's timeline/impact/hypotheses) for PostmortemRead.

    The factual sections are composed from the existing structured rows rather
    than duplicated onto the Postmortem, so the citation source of truth stays
    the EvidenceRefs (ADR 0024). Impact Claims are run-level incident facts shown
    once, independent of hypothesis count (ADR 0033). ``incident`` provides the
    title/severity header.
    """
    return {
        "id": postmortem.id,
        "run_id": postmortem.run_id,
        "incident_title": incident.title if incident is not None else "Incident",
        "incident_severity": incident.severity if incident is not None else None,
        "summary": postmortem.summary,
        "lessons_learned": list(postmortem.lessons_learned),
        "evidence_sufficiency": postmortem.evidence_sufficiency or "sufficient",
        "evidence_gaps": list(postmortem.evidence_gaps or []),
        "next_validation_steps": list(postmortem.next_validation_steps or []),
        "conclusion_status": postmortem.conclusion_status or "provisional",
        "composer_version": postmortem.composer_version,
        "timeline": [timeline_event_read(event) for event in timeline_events],
        "impact_claims": [impact_claim_read(claim) for claim in impact_claims],
        "hypotheses": [hypothesis_read(hypothesis) for hypothesis in hypotheses],
        "created_at": postmortem.created_at,
    }


def analysis_run_read(run: AnalysisRun) -> dict:
    """Shape an AnalysisRun for the AnalysisRunRead schema."""
    return {
        "id": run.id,
        "incident_id": run.incident_id,
        "status": run.status,
        "error": run.error,
        "experiment_metadata": run,
        "artifact_ids": run_artifact_ids(run),
        "stage_events": list(run.stage_events),
        "created_at": run.created_at,
        "updated_at": run.updated_at,
        "started_at": run.started_at,
        "completed_at": run.completed_at,
    }
