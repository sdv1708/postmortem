from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from ..auth import require_user
from ..scenarios import (
    LoadedScenario,
    ScenarioNotFoundError,
    ScenarioValidationError,
)
from ..schemas import ScenarioSeedRead, ScenarioSummaryRead
from ..services.scenarios import ScenarioSeedService
from .deps import get_db


router = APIRouter(prefix="/api/scenarios", tags=["scenarios"], dependencies=[Depends(require_user)])


def _summary(scenario: LoadedScenario) -> ScenarioSummaryRead:
    return ScenarioSummaryRead(
        id=scenario.id,
        title=scenario.title,
        severity=scenario.severity,
        summary=scenario.summary,
        ambiguity_notes=scenario.ambiguity_notes,
        evaluation_tags=list(scenario.evaluation_tags),
        expected_hypothesis_families=list(scenario.expected_hypothesis_families),
        evidence_count=len(scenario.evidence),
    )


@router.get("", response_model=list[ScenarioSummaryRead])
def list_demo_scenarios(db: Session = Depends(get_db)) -> list[ScenarioSummaryRead]:
    """The synthetic Incident Scenarios available to seed for a demo (ADR 0007)."""
    return [_summary(scenario) for scenario in ScenarioSeedService(db).list_available()]


@router.post("/{scenario_id}/seed", response_model=ScenarioSeedRead, status_code=status.HTTP_201_CREATED)
def seed_demo_scenario(scenario_id: str, db: Session = Depends(get_db)) -> ScenarioSeedRead:
    """Seed a scenario into product data and run it with its bundled replay.

    A Command Endpoint (ADR 0022): it creates the Incident + Artifacts and starts
    a deterministic Analysis Run so the operator can open the Review Surface on a
    populated, multi-hypothesis postmortem without a live model (ADR 0011).
    """
    try:
        incident, run = ScenarioSeedService(db).seed_and_run(scenario_id)
    except ScenarioNotFoundError:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="scenario not found")
    except ScenarioValidationError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc))
    return ScenarioSeedRead(
        scenario_id=scenario_id,
        incident_id=incident.id,
        run_id=run.id,
        run_status=run.status,
    )
