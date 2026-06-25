from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.orm import Session

from ..auth import require_user
from ..evaluation import LLMPostmortemJudge, PostmortemJudge
from ..llm import build_llm_client
from ..scenarios import ScenarioNotFoundError, ScenarioValidationError
from ..schemas import EvaluationRunCreate, EvaluationRunRead
from ..services.evaluation import EvaluationRunner, evaluation_run_read
from .deps import get_db


router = APIRouter(prefix="/api/evaluations", tags=["evaluations"], dependencies=[Depends(require_user)])


def _resolve_judge(request: Request) -> PostmortemJudge | None:
    """Build the judge for evaluation, or None when no model is configured.

    A test/dev hook (``app.state.evaluation_judge``) takes precedence so the judge
    can be replayed deterministically; otherwise the configured provider drives an
    ``LLMPostmortemJudge`` (ADR 0011), and an offline environment scores no judge —
    the deterministic check floor stands alone (ADR 0010).
    """
    injected = getattr(request.app.state, "evaluation_judge", None)
    if injected is not None:
        return injected
    settings = request.app.state.settings
    if settings.llm_api_key:
        return LLMPostmortemJudge(build_llm_client(settings))
    return None


@router.get("", response_model=list[EvaluationRunRead])
def list_evaluations(db: Session = Depends(get_db)) -> list[EvaluationRunRead]:
    """Past Evaluation Runs for the dev dashboard, newest first (ADR 0010)."""
    runs = EvaluationRunner(db).list_recorded()
    return [EvaluationRunRead.model_validate(evaluation_run_read(run)) for run in runs]


@router.post("", response_model=list[EvaluationRunRead], status_code=status.HTTP_201_CREATED)
def run_evaluations(
    payload: EvaluationRunCreate, request: Request, db: Session = Depends(get_db)
) -> list[EvaluationRunRead]:
    """Run evaluation over one or all scenarios and record the results (ADR 0022).

    Each scenario is run in an ephemeral database independent of product Incident
    data; only the Evaluation Run results are persisted.
    """
    runner = EvaluationRunner(db, judge=_resolve_judge(request))
    try:
        # Each scenario records both the multi-pass and Builder-Only Baseline
        # configurations (PRD #38), so both shapes return a list of rows.
        if payload.scenario_id is not None:
            recorded = runner.run_and_record(payload.scenario_id)
        else:
            recorded = runner.run_all()
    except ScenarioNotFoundError:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="scenario not found")
    except ScenarioValidationError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc))
    return [EvaluationRunRead.model_validate(evaluation_run_read(run)) for run in recorded]
