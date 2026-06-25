from __future__ import annotations

import json
import logging
from pathlib import Path

from sqlalchemy.orm import Session

from ..logging import log_event
from ..models import AnalysisRun, Incident
from ..scenarios import (
    LoadedScenario,
    ScenarioNotFoundError,
    ScenarioReplayClaimSupportVerifier,
    ScenarioReplayFalsifier,
    ScenarioReplayIncidentFactExtractor,
    ScenarioReplayLLMClient,
    list_scenarios,
    load_scenario,
    resolve_replay_rca,
)
from ..schemas import AnalysisRunCreate, ArtifactCreate, IncidentCreate
from .analysis import AnalysisService
from .artifacts import ArtifactService
from .incidents import IncidentService


logger = logging.getLogger("postmortem.scenarios")


class ScenarioSeedService:
    """Seeds a file-based Incident Scenario into product data and runs it.

    The demo/dev entry point for the canonical scenario (ADR 0006 / 0007):
    fixtures are files, but seeding creates real Incident + Artifact product rows
    (scenario fixture vs product data) through the same service layer the web UI
    and a future CLI use (ADR 0004). The run is driven by the scenario's bundled
    replay so the founder-demo trust path is deterministic and offline (ADR 0011).
    """

    def __init__(self, session: Session, base_dir: Path | None = None) -> None:
        self._session = session
        self._base_dir = base_dir

    def list_available(self) -> list[LoadedScenario]:
        return list_scenarios(self._base_dir)

    def get(self, scenario_id: str) -> LoadedScenario:
        return load_scenario(scenario_id, self._base_dir)

    def seed_and_run(
        self,
        scenario_id: str,
        *,
        execute_inline: bool = True,
        falsification_enabled: bool = True,
    ) -> tuple[Incident, AnalysisRun]:
        """Create the Incident + Artifacts and start an Analysis Run.

        Raises ``ScenarioNotFoundError`` for an unknown id and
        ``ScenarioValidationError`` for a malformed fixture (surfaced before any
        product rows are written).

        ``falsification_enabled=False`` drives the Builder-Only Baseline (PRD #38):
        the bundled falsifier replay is simply never consulted, so the same scenario
        runs under both configurations with matched model and retrieval constraints.
        """
        scenario = self.get(scenario_id)
        log_event(
            logger,
            logging.INFO,
            "scenario_seed_started",
            scenario_id=scenario.id,
            evidence_count=len(scenario.evidence),
            execute_inline=execute_inline,
        )

        incident = IncidentService(self._session).create(
            IncidentCreate(
                title=scenario.title,
                summary=scenario.summary,
                severity=scenario.severity,
                status=scenario.status,
                started_at=scenario.started_at,
                detected_at=scenario.detected_at,
                resolved_at=scenario.resolved_at,
            )
        )

        artifacts = ArtifactService(self._session)
        source_name_to_id: dict[str, str] = {}
        for evidence in scenario.evidence:
            artifact = artifacts.create(
                incident.id,
                ArtifactCreate(
                    source_type=evidence.source_type,
                    source_name=evidence.source_name,
                    body=evidence.body,
                ),
            )
            source_name_to_id[evidence.source_name] = artifact.id

        # Resolve the replay citations to the freshly seeded artifact ids, then
        # drive the run with the scenario's bundled replay (ADR 0011). The RCA
        # stage still validates the output and resolves snippets from the stored
        # lines (ADR 0024); claim support uses the scenario's replay verifier.
        rca_json = json.dumps(resolve_replay_rca(scenario.rca_replay, source_name_to_id))
        # Resolve the run-level incident-facts replay the same way so stage 2
        # produces the scenario's impact claims through its own Reasoning Role
        # (ADR 0033), leaving the RCA replay client consulted once for stage 3.
        incident_facts = resolve_replay_rca(scenario.incident_facts_replay, source_name_to_id)
        # Resolve the falsifier replay the same way so stage 3 challenges every
        # hypothesis through its own Reasoning Role (ADR 0034), keyed by title to
        # the builder replay's hypotheses.
        falsification = resolve_replay_rca(scenario.falsification_replay, source_name_to_id)
        run = AnalysisService(
            self._session,
            llm_client=ScenarioReplayLLMClient(scenario.id, rca_json),
            claim_support_verifier=ScenarioReplayClaimSupportVerifier(
                scenario.claim_support_overrides
            ),
            incident_fact_extractor=ScenarioReplayIncidentFactExtractor(
                scenario.id, incident_facts
            ),
            falsifier=ScenarioReplayFalsifier(scenario.id, falsification),
            falsification_enabled=falsification_enabled,
        ).start_run(incident.id, AnalysisRunCreate(), execute_inline=execute_inline)
        log_event(
            logger,
            logging.INFO,
            "scenario_seed_completed",
            scenario_id=scenario.id,
            incident_id=incident.id,
            run_id=run.id,
            run_status=run.status,
            artifact_count=len(source_name_to_id),
        )
        return incident, run


__all__ = ["ScenarioSeedService", "ScenarioNotFoundError"]
