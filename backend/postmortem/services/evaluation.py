from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from ..db import Base, make_session_factory
from ..evaluation import (
    EVAL_CHECK_SUITE_VERSION,
    CheckResult,
    HypothesisView,
    JudgeHypothesis,
    JudgeInput,
    JudgeResult,
    PostmortemJudge,
    RunOutputSnapshot,
    TimelineView,
    aggregate_warning_codes,
    citation_tally,
    run_deterministic_checks,
)
from ..logging import log_event
from ..models import (
    ActionItem,
    AnalysisRun,
    EvaluationRun,
    EvidenceRef,
    Hypothesis,
    ImpactClaim,
    Postmortem,
    RunStageEvent,
    TimelineEvent,
)
from ..scenarios import LoadedScenario, list_scenarios, load_scenario
from .scenarios import ScenarioSeedService


logger = logging.getLogger("postmortem.evaluation")


@dataclass(frozen=True)
class EvaluationResult:
    """ORM-free outcome of evaluating one scenario, ready to persist."""

    scenario_id: str
    scenario_title: str
    analysis_run_status: str
    metadata: dict
    checks: tuple[CheckResult, ...]
    warning_code_counts: dict
    citation_total: int
    citation_verified: int
    judge: JudgeResult | None

    @property
    def passed(self) -> bool:
        return all(check.passed for check in self.checks)


class EvaluationRunner:
    """Runs scenario fixtures through the deterministic floor + judge (ADR 0010).

    Each scenario is materialized in an ephemeral in-memory database and run with
    its bundled replay, so evaluation loads file-based scenarios independently of
    any product-created Incident data. Only the ``EvaluationRun`` result is
    persisted into the real session; the scratch incident/run never touch product
    data. The judge is optional and never decides citation validity (ADR 0010).
    """

    def __init__(
        self,
        session: Session,
        judge: PostmortemJudge | None = None,
        base_dir: Path | None = None,
    ) -> None:
        self._session = session
        self._judge = judge
        self._base_dir = base_dir

    def list_recorded(self) -> list[EvaluationRun]:
        return list(
            self._session.scalars(
                select(EvaluationRun).order_by(EvaluationRun.created_at.desc())
            )
        )

    def run_all(self) -> list[EvaluationRun]:
        scenarios = list_scenarios(self._base_dir)
        log_event(logger, logging.INFO, "evaluation_run_all_started", scenario_count=len(scenarios))
        rows = [
            self.run_and_record(scenario.id)
            for scenario in scenarios
        ]
        log_event(logger, logging.INFO, "evaluation_run_all_completed", recorded_count=len(rows))
        return rows

    def run_and_record(self, scenario_id: str) -> EvaluationRun:
        log_event(logger, logging.INFO, "evaluation_record_started", scenario_id=scenario_id)
        result = self.evaluate(scenario_id)
        row = EvaluationRun(
            scenario_id=result.scenario_id,
            scenario_title=result.scenario_title,
            status="succeeded",
            analysis_run_status=result.analysis_run_status,
            passed=result.passed,
            judge_version=result.judge.version if result.judge is not None else None,
            citation_total=result.citation_total,
            citation_verified=result.citation_verified,
            checks=[
                {"name": c.name, "passed": c.passed, "detail": c.detail}
                for c in result.checks
            ],
            warning_code_counts=result.warning_code_counts,
            judge_scores=(
                {
                    "scores": result.judge.scores,
                    "overall": result.judge.overall,
                    "rationale": result.judge.rationale,
                }
                if result.judge is not None
                else None
            ),
            **result.metadata,
        )
        self._session.add(row)
        self._session.flush()
        log_event(
            logger,
            logging.INFO,
            "evaluation_record_completed",
            scenario_id=scenario_id,
            evaluation_run_id=row.id,
            passed=row.passed,
            citation_verified=row.citation_verified,
            citation_total=row.citation_total,
            warning_codes=",".join(sorted(row.warning_code_counts.keys()))
            if row.warning_code_counts
            else None,
        )
        return row

    def evaluate(self, scenario_id: str) -> EvaluationResult:
        """Materialize a scenario run in an ephemeral DB and compute its results.

        Raises ``ScenarioNotFoundError`` / ``ScenarioValidationError`` for a bad
        scenario id before anything is recorded.
        """
        log_event(logger, logging.INFO, "evaluation_started", scenario_id=scenario_id)
        scenario = load_scenario(scenario_id, self._base_dir)
        engine = create_engine(
            "sqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
            future=True,
        )
        try:
            Base.metadata.create_all(engine)
            session = make_session_factory(engine)()
            try:
                incident, run = ScenarioSeedService(session, self._base_dir).seed_and_run(
                    scenario_id
                )
                snapshot, judge_input = self._distill(session, run, scenario)
            finally:
                session.close()
        finally:
            engine.dispose()

        checks = tuple(run_deterministic_checks(snapshot))
        total, verified = citation_tally(snapshot)
        judge = self._judge.judge(judge_input) if self._judge is not None else None
        log_event(
            logger,
            logging.INFO,
            "evaluation_completed",
            scenario_id=scenario.id,
            analysis_run_status=run.status,
            passed=all(check.passed for check in checks),
            citation_verified=verified,
            citation_total=total,
            judge_ran=judge is not None,
        )
        return EvaluationResult(
            scenario_id=scenario.id,
            scenario_title=scenario.title,
            analysis_run_status=run.status,
            metadata={
                "pipeline_version": run.pipeline_version,
                "prompt_version": run.prompt_version,
                "model_provider": run.model_provider,
                "retrieval_strategy": run.retrieval_strategy,
                "chunking_strategy": run.chunking_strategy,
                "verifier_version": run.verifier_version,
            },
            checks=checks,
            warning_code_counts=aggregate_warning_codes(snapshot),
            citation_total=total,
            citation_verified=verified,
            judge=judge,
        )

    def _distill(
        self, session: Session, run: AnalysisRun, scenario: LoadedScenario
    ) -> tuple[RunOutputSnapshot, JudgeInput]:
        """Reduce a run's persisted outputs to the ORM-free snapshot + judge input."""
        postmortem = session.scalar(select(Postmortem).where(Postmortem.run_id == run.id))
        timeline = list(
            session.scalars(
                select(TimelineEvent)
                .where(TimelineEvent.run_id == run.id)
                .order_by(TimelineEvent.sequence.asc())
            )
        )
        hypotheses = list(
            session.scalars(
                select(Hypothesis)
                .where(Hypothesis.run_id == run.id)
                .order_by(Hypothesis.rank.asc())
            )
        )
        refs = self._run_evidence_refs(session, run)

        hypothesis_views = tuple(
            HypothesisView(
                rank=h.rank,
                support_status=h.support_status,
                # Impact Claims are run-level now (ADR 0033), so a hypothesis's
                # citation count is its own supporting/contradicting evidence plus
                # its remediation items.
                citation_count=len(h.evidence_refs)
                + sum(len(item.evidence_refs) for item in h.action_items),
            )
            for h in hypotheses
        )
        warning_codes: list[str] = []
        for event in session.scalars(
            select(RunStageEvent).where(RunStageEvent.run_id == run.id)
        ):
            warning_codes.extend(event.warning_codes or [])

        snapshot = RunOutputSnapshot(
            summary=postmortem.summary if postmortem is not None else None,
            timeline=tuple(
                TimelineView(sequence=event.sequence, normalized_ts=event.normalized_ts)
                for event in timeline
            ),
            hypotheses=hypothesis_views,
            citation_statuses=tuple(ref.verifier_status for ref in refs),
            warning_codes=tuple(warning_codes),
            expected_hypothesis_count=len(scenario.expected_hypothesis_families),
            insufficient_evidence_expected="insufficient-evidence" in scenario.evaluation_tags,
            evidence_sufficiency=(
                postmortem.evidence_sufficiency if postmortem is not None else "sufficient"
            ),
        )
        judge_input = JudgeInput(
            scenario_id=scenario.id,
            generated_summary=postmortem.summary if postmortem is not None else "",
            generated_hypotheses=tuple(
                JudgeHypothesis(title=h.title, summary=h.summary, support_status=h.support_status)
                for h in hypotheses
            ),
            ground_truth_postmortem=scenario.ground_truth_postmortem,
        )
        return snapshot, judge_input

    @staticmethod
    def _run_evidence_refs(session: Session, run: AnalysisRun) -> list[EvidenceRef]:
        """Every EvidenceRef owned by the run, across all four owner types."""
        refs: list[EvidenceRef] = list(
            session.scalars(
                select(EvidenceRef)
                .join(TimelineEvent, EvidenceRef.timeline_event_id == TimelineEvent.id)
                .where(TimelineEvent.run_id == run.id)
            )
        )
        refs += session.scalars(
            select(EvidenceRef)
            .join(Hypothesis, EvidenceRef.hypothesis_id == Hypothesis.id)
            .where(Hypothesis.run_id == run.id)
        )
        refs += session.scalars(
            select(EvidenceRef)
            .join(ImpactClaim, EvidenceRef.impact_claim_id == ImpactClaim.id)
            .where(ImpactClaim.run_id == run.id)
        )
        refs += session.scalars(
            select(EvidenceRef)
            .join(ActionItem, EvidenceRef.action_item_id == ActionItem.id)
            .join(Hypothesis, ActionItem.hypothesis_id == Hypothesis.id)
            .where(Hypothesis.run_id == run.id)
        )
        return refs


def evaluation_run_read(row: EvaluationRun) -> dict:
    """Shape an EvaluationRun for the EvaluationRunRead schema (ADR 0025)."""
    return {
        "id": row.id,
        "scenario_id": row.scenario_id,
        "scenario_title": row.scenario_title,
        "status": row.status,
        "analysis_run_status": row.analysis_run_status,
        "passed": row.passed,
        "experiment_metadata": row,
        "check_suite_version": EVAL_CHECK_SUITE_VERSION,
        "judge_version": row.judge_version,
        "citation_total": row.citation_total,
        "citation_verified": row.citation_verified,
        "checks": list(row.checks),
        "warning_code_counts": dict(row.warning_code_counts),
        "judge_scores": row.judge_scores,
        "error": row.error,
        "created_at": row.created_at,
    }
