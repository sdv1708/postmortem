from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy.orm import Session

from ..auth import require_user
from ..schemas import IncidentCreate, IncidentRead, IncidentUpdate, RootCauseConclusionRead
from ..services import (
    ConclusionService,
    IncidentHasFinalizedConclusionsError,
    IncidentNotFoundError,
    IncidentService,
    conclusion_read,
)
from .deps import get_db


router = APIRouter(prefix="/api/incidents", tags=["incidents"], dependencies=[Depends(require_user)])


@router.post("", response_model=IncidentRead, status_code=status.HTTP_201_CREATED)
def create_incident(payload: IncidentCreate, db: Session = Depends(get_db)) -> IncidentRead:
    incident = IncidentService(db).create(payload)
    return IncidentRead.model_validate(incident)


@router.get("", response_model=list[IncidentRead])
def list_incidents(db: Session = Depends(get_db)) -> list[IncidentRead]:
    incidents = IncidentService(db).list()
    return [IncidentRead.model_validate(i) for i in incidents]


@router.get("/{incident_id}", response_model=IncidentRead)
def get_incident(incident_id: str, db: Session = Depends(get_db)) -> IncidentRead:
    try:
        incident = IncidentService(db).get(incident_id)
    except IncidentNotFoundError:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="incident not found")
    return IncidentRead.model_validate(incident)


@router.patch("/{incident_id}", response_model=IncidentRead)
def update_incident(
    incident_id: str, payload: IncidentUpdate, db: Session = Depends(get_db)
) -> IncidentRead:
    try:
        incident = IncidentService(db).update(incident_id, payload)
    except IncidentNotFoundError:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="incident not found")
    return IncidentRead.model_validate(incident)


@router.delete("/{incident_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_incident(incident_id: str, db: Session = Depends(get_db)) -> Response:
    try:
        IncidentService(db).delete(incident_id)
    except IncidentNotFoundError:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="incident not found")
    except IncidentHasFinalizedConclusionsError:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="incident has finalized conclusions and cannot be deleted",
        )
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get(
    "/{incident_id}/disputed-conclusions",
    response_model=list[RootCauseConclusionRead],
)
def list_incident_disputed_conclusions(
    incident_id: str, db: Session = Depends(get_db)
) -> list[RootCauseConclusionRead]:
    """Disputed, not-yet-superseded conclusions across the incident (ADR 0045).

    The candidates a reviewer may resolve with a Superseding Conclusion. Surfaced
    incident-wide so a *new* Analysis Run (the new-Evidence path) can supersede a
    predecessor from an earlier run, which a single run's conclusion view cannot
    offer (PRD #26 stories 47-49).
    """
    try:
        conclusions = ConclusionService(db).list_supersedable(incident_id)
    except IncidentNotFoundError:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="incident not found")
    return [RootCauseConclusionRead.model_validate(conclusion_read(c)) for c in conclusions]
