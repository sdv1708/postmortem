from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from ..models import (
    ActionItem,
    AnalysisRun,
    Artifact,
    Counterclaim,
    EvidenceChunk,
    EvidenceRef,
    Hypothesis,
    HypothesisChallenge,
    ImpactClaim,
    Incident,
    ModelCallRecord,
    Postmortem,
    RetrievalTrace,
    ReviewerNote,
    RootCauseConclusion,
    RunArtifact,
    RunStageEvent,
    TimelineEvent,
)
from ..schemas import IncidentCreate, IncidentUpdate
from .workspaces import ensure_default_workspace

# Lifecycle states that mean the incident is no longer active; entering one stamps
# resolved_at, leaving one clears it, so the column always reflects the status.
_RESOLVED_STATUSES = frozenset({"resolved", "closed"})


class IncidentNotFoundError(LookupError):
    pass


class IncidentHasFinalizedConclusionsError(RuntimeError):
    pass


class IncidentService:
    """Owns Incident creation, fetch, and listing.

    Routes and the future CLI both call this — never the ORM directly (ADR 0004).
    """

    def __init__(self, session: Session, workspace_id: str | None = None) -> None:
        """``workspace_id`` scopes this service to one visitor's sandbox.

        Request handlers pass the caller's workspace so create/list/get are
        isolated per visitor (ADR 0017). Internal callers (nested-resource
        existence checks, the ephemeral evaluation harness, tests) omit it and get
        the prior unscoped behavior: create lands in the default workspace, list
        returns every incident, and get is an existence check only. Tenancy for
        nested routes is enforced separately by ``require_owned_incident``.
        """
        self._session = session
        self._workspace_id = workspace_id

    def create(self, payload: IncidentCreate) -> Incident:
        workspace_id = self._workspace_id or ensure_default_workspace(self._session).id
        incident = Incident(
            workspace_id=workspace_id,
            title=payload.title.strip(),
            summary=payload.summary.strip() if payload.summary else None,
            severity=payload.severity,
            status=payload.status,
            started_at=payload.started_at,
            detected_at=payload.detected_at,
            resolved_at=payload.resolved_at,
        )
        self._session.add(incident)
        self._session.flush()
        return incident

    def get(self, incident_id: str) -> Incident:
        incident = self._session.get(Incident, incident_id)
        if incident is None:
            raise IncidentNotFoundError(incident_id)
        # When scoped to a workspace, an incident in another sandbox is treated as
        # not-found (no existence leak). Unscoped callers get an existence check.
        if self._workspace_id is not None and incident.workspace_id != self._workspace_id:
            raise IncidentNotFoundError(incident_id)
        return incident

    def update(self, incident_id: str, payload: IncidentUpdate) -> Incident:
        """Apply a partial update to a human-managed Incident field set.

        Only the fields present on ``payload`` change. Moving the status into a
        resolved/closed state stamps ``resolved_at``; moving back out clears it,
        so the timestamp never contradicts the status.
        """
        incident = self.get(incident_id)
        if payload.status is not None and payload.status != incident.status:
            incident.status = payload.status
            if payload.status in _RESOLVED_STATUSES:
                if incident.resolved_at is None:
                    incident.resolved_at = datetime.now(timezone.utc)
            else:
                incident.resolved_at = None
        if payload.severity is not None:
            incident.severity = payload.severity
        if payload.summary is not None:
            summary = payload.summary.strip()
            incident.summary = summary or None
        self._session.flush()
        return incident

    def delete(self, incident_id: str) -> None:
        incident = self.get(incident_id)
        conclusion_id = self._session.scalar(
            select(RootCauseConclusion.id)
            .join(AnalysisRun, AnalysisRun.id == RootCauseConclusion.run_id)
            .where(AnalysisRun.incident_id == incident_id)
            .limit(1)
        )
        if conclusion_id is not None:
            raise IncidentHasFinalizedConclusionsError(incident_id)
        self._delete_analysis_history(incident_id)
        self._session.delete(incident)
        self._session.flush()

    def list(self) -> list[Incident]:
        stmt = select(Incident).order_by(Incident.created_at.desc())
        if self._workspace_id is not None:
            stmt = stmt.where(Incident.workspace_id == self._workspace_id)
        return list(self._session.scalars(stmt))

    def _delete_analysis_history(self, incident_id: str) -> None:
        run_ids = select(AnalysisRun.id).where(AnalysisRun.incident_id == incident_id)
        artifact_ids = select(Artifact.id).where(Artifact.incident_id == incident_id)
        hypothesis_ids = select(Hypothesis.id).where(Hypothesis.run_id.in_(run_ids))
        challenge_ids = select(HypothesisChallenge.id).where(
            HypothesisChallenge.run_id.in_(run_ids)
        )

        # Citations point back to locked Artifacts through RESTRICT FKs, so remove
        # them before deleting any run output or incident evidence.
        self._session.execute(delete(EvidenceRef).where(EvidenceRef.artifact_id.in_(artifact_ids)))
        self._session.execute(delete(ActionItem).where(ActionItem.hypothesis_id.in_(hypothesis_ids)))
        self._session.execute(delete(Counterclaim).where(Counterclaim.challenge_id.in_(challenge_ids)))
        self._session.execute(delete(HypothesisChallenge).where(HypothesisChallenge.run_id.in_(run_ids)))
        self._session.execute(delete(ReviewerNote).where(ReviewerNote.run_id.in_(run_ids)))
        self._session.execute(delete(Hypothesis).where(Hypothesis.run_id.in_(run_ids)))
        self._session.execute(delete(ImpactClaim).where(ImpactClaim.run_id.in_(run_ids)))
        self._session.execute(delete(TimelineEvent).where(TimelineEvent.run_id.in_(run_ids)))
        self._session.execute(delete(Postmortem).where(Postmortem.run_id.in_(run_ids)))
        self._session.execute(delete(ModelCallRecord).where(ModelCallRecord.run_id.in_(run_ids)))
        self._session.execute(delete(RetrievalTrace).where(RetrievalTrace.run_id.in_(run_ids)))
        self._session.execute(delete(EvidenceChunk).where(EvidenceChunk.run_id.in_(run_ids)))
        self._session.execute(delete(RunStageEvent).where(RunStageEvent.run_id.in_(run_ids)))
        self._session.execute(delete(RunArtifact).where(RunArtifact.run_id.in_(run_ids)))
        self._session.execute(delete(AnalysisRun).where(AnalysisRun.incident_id == incident_id))
        self._session.execute(delete(Artifact).where(Artifact.incident_id == incident_id))
