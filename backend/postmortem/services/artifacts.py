from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import Artifact
from ..schemas import ArtifactCreate, ArtifactLine, ArtifactRead, ArtifactReplace
from .incidents import IncidentNotFoundError, IncidentService


class ArtifactNotFoundError(LookupError):
    pass


class ArtifactLockedError(RuntimeError):
    pass


def canonicalize_body(body: str) -> str:
    return body.replace("\r\n", "\n").replace("\r", "\n")


def artifact_lines(body: str) -> list[ArtifactLine]:
    return [ArtifactLine(number=index, text=line) for index, line in enumerate(body.split("\n"), start=1)]


def line_count(body: str) -> int:
    return len(body.split("\n"))


def artifact_read(artifact: Artifact) -> ArtifactRead:
    return ArtifactRead.model_validate(
        {
            "id": artifact.id,
            "incident_id": artifact.incident_id,
            "source_type": artifact.source_type,
            "source_name": artifact.source_name,
            "body": artifact.body,
            "line_count": artifact.line_count,
            "included_in_analysis_run": artifact.included_in_analysis_run,
            "created_at": artifact.created_at,
            "updated_at": artifact.updated_at,
            "lines": artifact_lines(artifact.body),
        }
    )


class ArtifactService:
    """Owns Artifact evidence behavior under Incidents."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def create(self, incident_id: str, payload: ArtifactCreate) -> Artifact:
        IncidentService(self._session).get(incident_id)
        body = canonicalize_body(payload.body)
        artifact = Artifact(
            incident_id=incident_id,
            source_type=payload.source_type,
            source_name=payload.source_name,
            body=body,
            line_count=line_count(body),
        )
        self._session.add(artifact)
        self._session.flush()
        return artifact

    def list(self, incident_id: str) -> list[Artifact]:
        IncidentService(self._session).get(incident_id)
        stmt = select(Artifact).where(Artifact.incident_id == incident_id).order_by(Artifact.created_at.asc())
        return list(self._session.scalars(stmt))

    def get(self, incident_id: str, artifact_id: str) -> Artifact:
        IncidentService(self._session).get(incident_id)
        artifact = self._session.get(Artifact, artifact_id)
        if artifact is None or artifact.incident_id != incident_id:
            raise ArtifactNotFoundError(artifact_id)
        return artifact

    def delete(self, incident_id: str, artifact_id: str) -> None:
        artifact = self.get(incident_id, artifact_id)
        self._ensure_mutable(artifact)
        self._session.delete(artifact)
        self._session.flush()

    def replace(self, incident_id: str, artifact_id: str, payload: ArtifactReplace) -> Artifact:
        artifact = self.get(incident_id, artifact_id)
        self._ensure_mutable(artifact)
        body = canonicalize_body(payload.body)
        artifact.body = body
        artifact.line_count = line_count(body)
        if payload.source_type is not None:
            artifact.source_type = payload.source_type
        if payload.source_name is not None:
            artifact.source_name = payload.source_name
        self._session.flush()
        return artifact

    def _ensure_mutable(self, artifact: Artifact) -> None:
        if artifact.included_in_analysis_run:
            raise ArtifactLockedError(artifact.id)
