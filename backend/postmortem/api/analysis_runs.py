from __future__ import annotations

import logging

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request, status
from sqlalchemy.orm import Session, sessionmaker

from ..auth import require_user
from ..config import Settings
from ..llm import build_llm_client
from ..logging import log_event
from ..markdown_export import ExportMode, render_markdown
from ..schemas import (
    AnalysisRunCreate,
    AnalysisRunRead,
    HypothesisRead,
    HypothesisReviewCreate,
    ImpactClaimRead,
    MarkdownExportCreate,
    MarkdownExportRead,
    PostmortemRead,
    ReviewerNoteCreate,
    ReviewerNoteRead,
    RunDiagnosticsRead,
    TimelineEventRead,
)
from ..services import (
    AnalysisRunNotFoundError,
    AnalysisService,
    ArtifactNotFoundError,
    HypothesisNotFoundError,
    IncidentNotFoundError,
    NoArtifactsError,
    PostmortemNotFoundError,
    analysis_run_read,
    hypothesis_read,
    impact_claim_read,
    reviewer_note_read,
    timeline_event_read,
)
from .deps import get_db


logger = logging.getLogger("postmortem.api.analysis_runs")


router = APIRouter(
    prefix="/api/incidents/{incident_id}/analysis-runs",
    tags=["analysis-runs"],
    dependencies=[Depends(require_user)],
)


def execute_analysis_run_background(
    session_factory: sessionmaker[Session], run_id: str, settings: Settings | None = None
) -> None:
    # The RCA stage runs in this fresh background session, so build the configured
    # generation provider here (ADR 0011). The optional fallback keeps direct
    # invocations compatible with the offline environment default.
    settings = settings or Settings.from_env()
    client = build_llm_client(settings)
    session = session_factory()
    log_event(
        logger,
        logging.INFO,
        "analysis_run_background_started",
        run_id=run_id,
        model_provider=client.label,
    )
    try:
        AnalysisService(session, llm_client=client).execute_run(run_id, commit_progress=True)
        session.commit()
        log_event(logger, logging.INFO, "analysis_run_background_completed", run_id=run_id)
    except Exception:
        session.rollback()
        log_event(logger, logging.ERROR, "analysis_run_background_failed", run_id=run_id)
        raise
    finally:
        session.close()


def schedule_analysis_run(
    background_tasks: BackgroundTasks,
    session_factory: sessionmaker[Session],
    run_id: str,
    settings: Settings,
) -> None:
    log_event(logger, logging.INFO, "analysis_run_background_scheduled", run_id=run_id)
    background_tasks.add_task(execute_analysis_run_background, session_factory, run_id, settings)


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
        scheduler = getattr(request.app.state, "run_scheduler", None)
        if scheduler is None:
            schedule_analysis_run(
                background_tasks,
                request.app.state.session_factory,
                run.id,
                request.app.state.settings,
            )
        else:
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


@router.get("/{run_id}/impact", response_model=list[ImpactClaimRead])
def list_run_impact_claims(
    incident_id: str, run_id: str, db: Session = Depends(get_db)
) -> list[ImpactClaimRead]:
    """Run-level Impact Claims for a run, shown once regardless of hypothesis count (ADR 0033)."""
    try:
        claims = AnalysisService(db).list_impact_claims(incident_id, run_id)
    except IncidentNotFoundError:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="incident not found")
    except AnalysisRunNotFoundError:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="analysis run not found")
    return [ImpactClaimRead.model_validate(impact_claim_read(claim)) for claim in claims]


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


@router.get("/{run_id}/postmortem", response_model=PostmortemRead)
def get_run_postmortem(
    incident_id: str, run_id: str, db: Session = Depends(get_db)
) -> PostmortemRead:
    """The structured Postmortem, the primary Review Surface artifact (ADR 0012).

    404 until the run has reached the drafting stage; the timeline and hypotheses
    are composed from the run's existing structured rows.
    """
    try:
        document = AnalysisService(db).get_postmortem_document(incident_id, run_id)
    except IncidentNotFoundError:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="incident not found")
    except AnalysisRunNotFoundError:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="analysis run not found")
    except PostmortemNotFoundError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="this run has not produced a postmortem yet",
        )
    return PostmortemRead.model_validate(document)


@router.get("/{run_id}/diagnostics", response_model=RunDiagnosticsRead)
def get_run_diagnostics(
    incident_id: str, run_id: str, db: Session = Depends(get_db)
) -> RunDiagnosticsRead:
    """Restricted reasoning/retrieval provenance for a run (ADR 0038).

    Authenticated through the single-user gate (router-level ``require_user``) like
    every other run resource. Exposes Model Call Records and Retrieval Traces —
    component versions, ordered retrieved Chunk references, token usage, hashes,
    and structured outcomes — so causal reasoning is diagnosable without opening
    restricted debug logs (PRD #26 user stories 69-73, 88-89). It is a separate
    resource, so the normal Review Surface workflow is unchanged.
    """
    try:
        diagnostics = AnalysisService(db).get_run_diagnostics(incident_id, run_id)
    except IncidentNotFoundError:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="incident not found")
    except AnalysisRunNotFoundError:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="analysis run not found")
    return RunDiagnosticsRead.model_validate(diagnostics)


@router.post("/{run_id}/postmortem/export", response_model=MarkdownExportRead)
def export_run_postmortem(
    incident_id: str,
    run_id: str,
    payload: MarkdownExportCreate,
    db: Session = Depends(get_db),
) -> MarkdownExportRead:
    """Render Markdown from the structured Postmortem on request (ADR 0022).

    Rendering is a command, not a resource read: the Markdown is derived from the
    structured source of truth and is never parsed back into truth (ADR 0012). A
    clean export omits unsupported claims and assumptions; an audit export retains
    them, labeled, for review (ADR 0015).
    """
    try:
        document = AnalysisService(db).get_postmortem_document(incident_id, run_id)
    except IncidentNotFoundError:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="incident not found")
    except AnalysisRunNotFoundError:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="analysis run not found")
    except PostmortemNotFoundError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="this run has not produced a postmortem yet",
        )
    postmortem = PostmortemRead.model_validate(document)
    markdown = render_markdown(postmortem, ExportMode(payload.mode))
    return MarkdownExportRead(
        run_id=run_id,
        mode=payload.mode,
        filename=f"postmortem-{run_id}-{payload.mode}.md",
        markdown=markdown,
    )


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


@router.post("/{run_id}/review-notes", response_model=ReviewerNoteRead, status_code=status.HTTP_201_CREATED)
def add_run_reviewer_note(
    incident_id: str,
    run_id: str,
    payload: ReviewerNoteCreate,
    db: Session = Depends(get_db),
) -> ReviewerNoteRead:
    """Record a Reviewer Note without editing generated claims (ADR 0016)."""
    try:
        note = AnalysisService(db).add_reviewer_note(incident_id, run_id, payload)
    except IncidentNotFoundError:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="incident not found")
    except AnalysisRunNotFoundError:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="analysis run not found")
    except HypothesisNotFoundError:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="hypothesis not found")
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc))
    return ReviewerNoteRead.model_validate(reviewer_note_read(note))
