from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy.orm import Session

from ..auth import require_user
from ..schemas import ArtifactCreate, ArtifactRead, ArtifactReplace
from ..services import (
    ArtifactLockedError,
    ArtifactNotFoundError,
    ArtifactService,
    IncidentNotFoundError,
    artifact_read,
)
from .deps import get_db, require_owned_incident


router = APIRouter(
    prefix="/api/incidents/{incident_id}/artifacts",
    tags=["artifacts"],
    # require_user gates auth; require_owned_incident enforces per-visitor tenancy so
    # every artifact route only touches an incident in the caller's workspace.
    dependencies=[Depends(require_user), Depends(require_owned_incident)],
)


@router.post("", response_model=ArtifactRead, status_code=status.HTTP_201_CREATED)
def create_artifact(
    incident_id: str, payload: ArtifactCreate, db: Session = Depends(get_db)
) -> ArtifactRead:
    try:
        artifact = ArtifactService(db).create(incident_id, payload)
    except IncidentNotFoundError:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="incident not found")
    return artifact_read(artifact)


@router.get("", response_model=list[ArtifactRead])
def list_artifacts(incident_id: str, db: Session = Depends(get_db)) -> list[ArtifactRead]:
    try:
        artifacts = ArtifactService(db).list(incident_id)
    except IncidentNotFoundError:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="incident not found")
    return [artifact_read(artifact) for artifact in artifacts]


@router.get("/{artifact_id}", response_model=ArtifactRead)
def get_artifact(incident_id: str, artifact_id: str, db: Session = Depends(get_db)) -> ArtifactRead:
    try:
        artifact = ArtifactService(db).get(incident_id, artifact_id)
    except IncidentNotFoundError:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="incident not found")
    except ArtifactNotFoundError:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="artifact not found")
    return artifact_read(artifact)


@router.put("/{artifact_id}", response_model=ArtifactRead)
def replace_artifact(
    incident_id: str, artifact_id: str, payload: ArtifactReplace, db: Session = Depends(get_db)
) -> ArtifactRead:
    try:
        artifact = ArtifactService(db).replace(incident_id, artifact_id, payload)
    except IncidentNotFoundError:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="incident not found")
    except ArtifactNotFoundError:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="artifact not found")
    except ArtifactLockedError:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="artifact has been included in an analysis run",
        )
    return artifact_read(artifact)


@router.delete("/{artifact_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_artifact(incident_id: str, artifact_id: str, db: Session = Depends(get_db)) -> Response:
    try:
        ArtifactService(db).delete(incident_id, artifact_id)
    except IncidentNotFoundError:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="incident not found")
    except ArtifactNotFoundError:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="artifact not found")
    except ArtifactLockedError:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="artifact has been included in an analysis run",
        )
    return Response(status_code=status.HTTP_204_NO_CONTENT)
