from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import DEFAULT_EXPERIMENT_METADATA
from ..models import AnalysisRun, Artifact, RunArtifact
from ..schemas import AnalysisRunCreate
from .artifacts import ArtifactNotFoundError
from .incidents import IncidentService
from .run_executor import RunExecutor, StagedRunExecutor, StageRecorder


class AnalysisRunNotFoundError(LookupError):
    pass


class NoArtifactsError(ValueError):
    """Raised when a run is started with no Artifacts to analyze."""


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

    def __init__(self, session: Session, executor: RunExecutor | None = None) -> None:
        self._session = session
        self._executor = executor or StagedRunExecutor()

    def start_run(
        self,
        incident_id: str,
        payload: AnalysisRunCreate,
        *,
        execute_inline: bool = True,
    ) -> AnalysisRun:
        IncidentService(self._session).get(incident_id)
        artifacts = self._resolve_artifacts(incident_id, payload.artifact_ids)

        run = AnalysisRun(
            incident_id=incident_id,
            status="queued",
            **DEFAULT_EXPERIMENT_METADATA,
        )
        self._session.add(run)
        self._session.flush()

        # Lock the included Artifacts before any execution so their bodies
        # remain the citation source of truth for the life of the run.
        for artifact in artifacts:
            self._session.add(RunArtifact(run_id=run.id, artifact_id=artifact.id))
            artifact.included_in_analysis_run = True
        self._session.flush()

        if execute_inline:
            self.execute_run(run.id)
        return run

    def execute_run(self, run_id: str, *, commit_progress: bool = False) -> AnalysisRun:
        run = self._session.get(AnalysisRun, run_id)
        if run is None:
            raise AnalysisRunNotFoundError(run_id)
        if run.status in {"running", "succeeded", "failed"}:
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
        run.status = "running"
        run.started_at = _utcnow()
        self._session.flush()
        if commit_progress:
            self._session.commit()
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
            return
        run.status = "succeeded"
        run.completed_at = _utcnow()
        self._session.flush()
        if commit_progress:
            self._session.commit()


def run_artifact_ids(run: AnalysisRun) -> list[str]:
    return [ref.artifact_id for ref in run.run_artifacts]


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
