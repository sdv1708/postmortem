from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from ..auth import require_user
from ..schemas import AnalysisRunCreate, AnalysisRunRead
from ..services import (
    AnalysisRunNotFoundError,
    AnalysisService,
    ArtifactNotFoundError,
    IncidentNotFoundError,
    NoArtifactsError,
    analysis_run_read,
)
from .deps import get_db


router = APIRouter(
    prefix="/api/incidents/{incident_id}/analysis-runs",
    tags=["analysis-runs"],
    dependencies=[Depends(require_user)],
)


@router.post("", response_model=AnalysisRunRead, status_code=status.HTTP_201_CREATED)
def start_analysis_run(
    incident_id: str, payload: AnalysisRunCreate, db: Session = Depends(get_db)
) -> AnalysisRunRead:
    """Command endpoint that starts an Analysis Run (ADR 0022).

    The response is the durable, pollable run; clients fetch status afterward
    rather than streaming (ADR 0003).
    """
    try:
        run = AnalysisService(db).start_run(incident_id, payload)
    except IncidentNotFoundError:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="incident not found")
    except ArtifactNotFoundError:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="artifact not found")
    except NoArtifactsError:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="cannot start an analysis run without artifacts",
        )
    return AnalysisRunRead.model_validate(analysis_run_read(run))


@router.get("", response_model=list[AnalysisRunRead])
def list_analysis_runs(incident_id: str, db: Session = Depends(get_db)) -> list[AnalysisRunRead]:
    try:
        runs = AnalysisService(db).list_runs(incident_id)
    except IncidentNotFoundError:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="incident not found")
    return [AnalysisRunRead.model_validate(analysis_run_read(run)) for run in runs]


@router.get("/{run_id}", response_model=AnalysisRunRead)
def get_analysis_run(
    incident_id: str, run_id: str, db: Session = Depends(get_db)
) -> AnalysisRunRead:
    try:
        run = AnalysisService(db).get_run(incident_id, run_id)
    except IncidentNotFoundError:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="incident not found")
    except AnalysisRunNotFoundError:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="analysis run not found")
    return AnalysisRunRead.model_validate(analysis_run_read(run))
