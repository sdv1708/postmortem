from __future__ import annotations

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request, status
from sqlalchemy.orm import Session, sessionmaker

from ..auth import require_user
from ..config import Settings
from ..llm import build_llm_client
from ..schemas import (
    AnalysisRunCreate,
    AnalysisRunRead,
    HypothesisRead,
    HypothesisReviewCreate,
    TimelineEventRead,
)
from ..services import (
    AnalysisRunNotFoundError,
    AnalysisService,
    ArtifactNotFoundError,
    HypothesisNotFoundError,
    IncidentNotFoundError,
    NoArtifactsError,
    analysis_run_read,
    hypothesis_read,
    timeline_event_read,
)
from .deps import get_db


router = APIRouter(
    prefix="/api/incidents/{incident_id}/analysis-runs",
    tags=["analysis-runs"],
    dependencies=[Depends(require_user)],
)


def execute_analysis_run_background(
    session_factory: sessionmaker[Session], run_id: str, settings: Settings | None = None
) -> None:
    # The RCA stage runs in this fresh background session, so build the configured
    # generation provider here (ADR 0011). Settings default to the environment so
    # the unchanged 2-arg call site (and tests) resolve the offline client when no
    # provider is configured.
    settings = settings or Settings.from_env()
    client = build_llm_client(settings)
    session = session_factory()
    try:
        AnalysisService(session, llm_client=client).execute_run(run_id, commit_progress=True)
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def schedule_analysis_run(
    background_tasks: BackgroundTasks,
    session_factory: sessionmaker[Session],
    run_id: str,
) -> None:
    background_tasks.add_task(execute_analysis_run_background, session_factory, run_id)


@router.post("", response_model=AnalysisRunRead, status_code=status.HTTP_201_CREATED)
def start_analysis_run(
    incident_id: str,
    payload: AnalysisRunCreate,
    background_tasks: BackgroundTasks,
    request: Request,
    db: Session = Depends(get_db),
) -> AnalysisRunRead:
    """Command endpoint that starts an Analysis Run (ADR 0022).

    The response is the durable, pollable run; clients fetch status afterward
    rather than streaming (ADR 0003).
    """
    try:
        # Stamp the configured provider/prompt onto the run's experiment metadata
        # at creation (ADR 0025) so pollers see the real provider before the
        # background session runs the RCA stage with the same client (ADR 0011).
        client = build_llm_client(request.app.state.settings)
        run = AnalysisService(db, llm_client=client).start_run(
            incident_id, payload, execute_inline=False
        )
        # Commit the queued run and locked Artifact state before scheduling work
        # in a fresh session. External pollers can then observe queued/running
        # and stage-event transitions instead of waiting for the POST transaction.
        db.commit()
        scheduler = getattr(request.app.state, "run_scheduler", schedule_analysis_run)
        scheduler(background_tasks, request.app.state.session_factory, run.id)
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


@router.get("/{run_id}/timeline", response_model=list[TimelineEventRead])
def list_run_timeline(
    incident_id: str, run_id: str, db: Session = Depends(get_db)
) -> list[TimelineEventRead]:
    """Sorted Timeline Events for a run, each citing exact Artifact lines."""
    try:
        events = AnalysisService(db).list_timeline(incident_id, run_id)
    except IncidentNotFoundError:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="incident not found")
    except AnalysisRunNotFoundError:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="analysis run not found")
    return [TimelineEventRead.model_validate(timeline_event_read(event)) for event in events]


@router.get("/{run_id}/hypotheses", response_model=list[HypothesisRead])
def list_run_hypotheses(
    incident_id: str, run_id: str, db: Session = Depends(get_db)
) -> list[HypothesisRead]:
    """Ranked RCA Hypotheses for the Review Surface, with split evidence (PRD stage 3)."""
    try:
        hypotheses = AnalysisService(db).list_hypotheses(incident_id, run_id)
    except IncidentNotFoundError:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="incident not found")
    except AnalysisRunNotFoundError:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="analysis run not found")
    return [HypothesisRead.model_validate(hypothesis_read(h)) for h in hypotheses]


@router.post("/{run_id}/hypotheses/{hypothesis_id}/review", response_model=HypothesisRead)
def review_run_hypothesis(
    incident_id: str,
    run_id: str,
    hypothesis_id: str,
    payload: HypothesisReviewCreate,
    db: Session = Depends(get_db),
) -> HypothesisRead:
    """Record an accept/reject decision without rewriting the claim (ADR 0016)."""
    try:
        hypothesis = AnalysisService(db).review_hypothesis(
            incident_id, run_id, hypothesis_id, payload.decision
        )
    except IncidentNotFoundError:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="incident not found")
    except AnalysisRunNotFoundError:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="analysis run not found")
    except HypothesisNotFoundError:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="hypothesis not found")
    return HypothesisRead.model_validate(hypothesis_read(hypothesis))
