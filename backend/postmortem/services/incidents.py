from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import Incident
from ..schemas import IncidentCreate
from .workspaces import ensure_default_workspace


class IncidentNotFoundError(LookupError):
    pass


class IncidentService:
    """Owns Incident creation, fetch, and listing.

    Routes and the future CLI both call this — never the ORM directly (ADR 0004).
    """

    def __init__(self, session: Session) -> None:
        self._session = session

    def create(self, payload: IncidentCreate) -> Incident:
        workspace = ensure_default_workspace(self._session)
        incident = Incident(
            workspace_id=workspace.id,
            title=payload.title,
            summary=payload.summary,
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
        return incident

    def list(self) -> list[Incident]:
        stmt = select(Incident).order_by(Incident.created_at.desc())
        return list(self._session.scalars(stmt))
