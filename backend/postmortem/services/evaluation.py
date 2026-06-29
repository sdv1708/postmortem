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
    CausalExpectationsView,
    CheckResult,
    CitationRange,
    CounterevidenceView,
    ExpectedFactorView,
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
    run_floor_checks,
)
from ..logging import log_event
from ..models import (
    ActionItem,
    AnalysisRun,
    EvaluationRun,
    EvidenceRef,
    Hypothesis,
    ImpactClaim,
    Incident,
    ModelCallRecord,
    Postmortem,
    RunStageEvent,
    TimelineEvent,
)
from ..scenarios import CausalEvaluationExpectations, LoadedScenario, list_scenarios, load_scenario
from .scenarios import ScenarioSeedService


logger = logging.getLogger("postmortem.evaluation")

# The two Evaluation Run configurations compared under matched scenario, model,
# prompt family, and retrieval constraints (PRD #38, ADR 0044). The multi-pass run
# is the product configuration; the Builder-Only Baseline skips the Falsification
# Round so the value of multi-pass causal analysis is measured rather than assumed.
ANALYSIS_MODE_MULTI_PASS: str = "multi_pass"
ANALYSIS_MODE_BUILDER_ONLY: str = "builder_only"
ANALYSIS_MODES: tuple[str, ...] = (ANALYSIS_MODE_MULTI_PASS, ANALYSIS_MODE_BUILDER_ONLY)

# Evaluation kinds (EvaluationRun.evaluation_kind): a bundled demo scenario graded
# against ground truth, or a real product incident's Analysis Run graded only on
# the ground-truth-free deterministic floor (no judge, no expectation checks).
EVALUATION_KIND_SCENARIO: str = "scenario"
EVALUATION_KIND_INCIDENT: str = "incident"

# The analysis_mode recorded for a real-incident evaluation: it is not one of the
# scenario A/B configurations, so it stands on its own.
ANALYSIS_MODE_INCIDENT: str = "incident"


class IncidentEvaluationError(Exception):
    """A real-incident evaluation could not be run (run missing or not finished)."""


@dataclass(frozen=True)
class EvaluationResult:
    """ORM-free outcome of evaluating one scenario configuration, ready to persist."""

    scenario_id: str
    scenario_title: str
    analysis_run_status: str
    # "multi_pass" or "builder_only" (PRD #38): which configuration produced this.
    analysis_mode: str
    metadata: dict
    checks: tuple[CheckResult, ...]
    warning_code_counts: dict
    citation_total: int
    citation_verified: int
    judge: JudgeResult | None
    # Cost metrics recorded beside the quality results so improvement is never
    # achieved through unbounded cost (PRD stories 87): persisted Model Call
    # Records, summed model token usage, and total stage latency (ms).
    model_calls: int
    total_tokens: int
    latency_ms: int

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
        """Record both configurations for every scenario (PRD #38).

        Each scenario runs under the multi-pass *and* the Builder-Only Baseline
        configuration so the dashboard can compare quality and cost side by side.
        """
        scenarios = list_scenarios(self._base_dir)
        log_event(logger, logging.INFO, "evaluation_run_all_started", scenario_count=len(scenarios))
        rows: list[EvaluationRun] = []
        for scenario in scenarios:
            rows.extend(self.run_and_record(scenario.id))
        log_event(logger, logging.INFO, "evaluation_run_all_completed", recorded_count=len(rows))
        return rows

    def run_and_record(self, scenario_id: str) -> list[EvaluationRun]:
        """Evaluate and record one scenario under both configurations (PRD #38).

        Returns the multi-pass row first, then the Builder-Only Baseline row, both
        run under matched scenario, model, prompt family, and retrieval constraints.
        """
        log_event(logger, logging.INFO, "evaluation_record_started", scenario_id=scenario_id)
        return [self._record_mode(scenario_id, mode) for mode in ANALYSIS_MODES]

    def latest_incident_evaluation(
        self, incident_id: str, analysis_run_id: str
    ) -> EvaluationRun | None:
        """The most recent recorded floor evaluation of one incident Analysis Run."""
        return self._session.scalars(
            select(EvaluationRun)
            .where(
                EvaluationRun.evaluation_kind == EVALUATION_KIND_INCIDENT,
                EvaluationRun.incident_id == incident_id,
                EvaluationRun.analysis_run_id == analysis_run_id,
            )
            .order_by(EvaluationRun.created_at.desc())
        ).first()

    def evaluate_incident_run(self, incident_id: str, analysis_run_id: str) -> EvaluationRun:
        """Evaluate a real product incident's Analysis Run on the deterministic floor.

        Unlike scenario evaluation, this reads the *product* session directly — the
        run already exists with persisted outputs — and grades only the
        ground-truth-free checks (``run_floor_checks``). A real incident ships no
        reference postmortem, so no judge runs and the expectation-driven checks are
        not applicable; recording them as passes would be a misleading green (ADR
        0010). The result is persisted as an ``evaluation_kind='incident'`` row.

        Raises ``IncidentEvaluationError`` when the run does not exist under the
        incident or has not finished successfully (no outputs to evaluate).
        """
        run = self._session.scalar(
            select(AnalysisRun).where(
                AnalysisRun.id == analysis_run_id,
                AnalysisRun.incident_id == incident_id,
            )
        )
        if run is None:
            raise IncidentEvaluationError("analysis run not found for incident")
        if run.status != "succeeded":
            raise IncidentEvaluationError(
                f"analysis run is {run.status!r}; only a succeeded run can be evaluated"
            )
        incident = self._session.scalar(select(Incident).where(Incident.id == incident_id))
        if incident is None:
            raise IncidentEvaluationError("incident not found")

        log_event(
            logger,
            logging.INFO,
            "incident_evaluation_started",
            incident_id=incident_id,
            analysis_run_id=analysis_run_id,
        )
        # A genuine refusal run carries no evidence-backed hypotheses; deriving the
        # refusal expectation from the run's own sufficiency keeps the multiplicity
        # and citation floor checks correct for both confident and refused runs.
        run_postmortem = self._session.scalar(
            select(Postmortem).where(Postmortem.run_id == run.id)
        )
        refused = (
            run_postmortem is not None
            and run_postmortem.evidence_sufficiency == "insufficient"
        )
        snapshot, _postmortem, _hypotheses = self._build_snapshot(
            self._session,
            run,
            analysis_mode=ANALYSIS_MODE_INCIDENT,
            expectations=None,
            expected_hypothesis_count=0,
            insufficient_evidence_expected=refused,
        )
        checks = tuple(run_floor_checks(snapshot))
        total, verified = citation_tally(snapshot)
        model_calls, total_tokens, latency_ms = self._cost_metrics(self._session, run)
        passed = all(check.passed for check in checks)

        row = EvaluationRun(
            evaluation_kind=EVALUATION_KIND_INCIDENT,
            incident_id=incident_id,
            analysis_run_id=analysis_run_id,
            # Mirror the incident id/title into the scenario columns so the existing
            # grouping and dashboard read paths work unchanged for incident rows.
            scenario_id=incident_id,
            scenario_title=incident.title,
            status="succeeded",
            analysis_run_status=run.status,
            analysis_mode=ANALYSIS_MODE_INCIDENT,
            passed=passed,
            judge_version=None,
            citation_total=total,
            citation_verified=verified,
            model_calls=model_calls,
            total_tokens=total_tokens,
            latency_ms=latency_ms,
            checks=[{"name": c.name, "passed": c.passed, "detail": c.detail} for c in checks],
            warning_code_counts=aggregate_warning_codes(snapshot),
            judge_scores=None,
            pipeline_version=run.pipeline_version,
            prompt_version=run.prompt_version,
            model_provider=run.model_provider,
            retrieval_strategy=run.retrieval_strategy,
            chunking_strategy=run.chunking_strategy,
            verifier_version=run.verifier_version,
        )
        self._session.add(row)
        self._session.flush()
        log_event(
            logger,
            logging.INFO,
            "incident_evaluation_completed",
            incident_id=incident_id,
            analysis_run_id=analysis_run_id,
            evaluation_run_id=row.id,
            passed=passed,
            citation_verified=verified,
            citation_total=total,
        )
        return row

    def _record_mode(self, scenario_id: str, analysis_mode: str) -> EvaluationRun:
        result = self.evaluate(scenario_id, analysis_mode=analysis_mode)
        row = EvaluationRun(
            scenario_id=result.scenario_id,
            scenario_title=result.scenario_title,
            status="succeeded",
            analysis_run_status=result.analysis_run_status,
            analysis_mode=result.analysis_mode,
            passed=result.passed,
            judge_version=result.judge.version if result.judge is not None else None,
            citation_total=result.citation_total,
            citation_verified=result.citation_verified,
            model_calls=result.model_calls,
            total_tokens=result.total_tokens,
            latency_ms=result.latency_ms,
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
            analysis_mode=analysis_mode,
            evaluation_run_id=row.id,
            passed=row.passed,
            citation_verified=row.citation_verified,
            citation_total=row.citation_total,
            model_calls=row.model_calls,
            latency_ms=row.latency_ms,
            warning_codes=",".join(sorted(row.warning_code_counts.keys()))
            if row.warning_code_counts
            else None,
        )
        return row

    def evaluate(
        self, scenario_id: str, *, analysis_mode: str = ANALYSIS_MODE_MULTI_PASS
    ) -> EvaluationResult:
        """Materialize a scenario run in an ephemeral DB and compute its results.

        ``analysis_mode`` selects the multi-pass product configuration or the
        Builder-Only Baseline (PRD #38). Raises ``ScenarioNotFoundError`` /
        ``ScenarioValidationError`` for a bad scenario id before anything is recorded.
        """
        log_event(
            logger,
            logging.INFO,
            "evaluation_started",
            scenario_id=scenario_id,
            analysis_mode=analysis_mode,
        )
        scenario = load_scenario(scenario_id, self._base_dir)
        falsification_enabled = analysis_mode == ANALYSIS_MODE_MULTI_PASS
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
                    scenario_id, falsification_enabled=falsification_enabled
                )
                snapshot, judge_input = self._distill(session, run, scenario, analysis_mode)
                model_calls, total_tokens, latency_ms = self._cost_metrics(session, run)
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
            analysis_mode=analysis_mode,
            analysis_run_status=run.status,
            passed=all(check.passed for check in checks),
            citation_verified=verified,
            citation_total=total,
            model_calls=model_calls,
            judge_ran=judge is not None,
        )
        return EvaluationResult(
            scenario_id=scenario.id,
            scenario_title=scenario.title,
            analysis_run_status=run.status,
            analysis_mode=analysis_mode,
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
            model_calls=model_calls,
            total_tokens=total_tokens,
            latency_ms=latency_ms,
        )

    @staticmethod
    def _cost_metrics(session: Session, run: AnalysisRun) -> tuple[int, int, int]:
        """Cost signals for one run: model calls, token usage, and latency (PRD #38).

        ``model_calls`` is the count of persisted Model Call Records — one per
        Reasoning Role invocation (builder, each falsifier challenge, each support
        judgment, ranker) — so it falls naturally for the Builder-Only Baseline.
        ``total_tokens`` sums each call's provider usage (zero on an offline replay,
        which is honest — the plumbing populates with a real model). ``latency_ms``
        sums the persisted Run Stage Event durations.
        """
        records = list(
            session.scalars(select(ModelCallRecord).where(ModelCallRecord.run_id == run.id))
        )
        total_tokens = sum(_usage_tokens(record.usage) for record in records)
        latency_ms = sum(
            event.duration_ms or 0
            for event in session.scalars(
                select(RunStageEvent).where(RunStageEvent.run_id == run.id)
            )
        )
        return len(records), total_tokens, latency_ms

    def _build_snapshot(
        self,
        session: Session,
        run: AnalysisRun,
        *,
        analysis_mode: str,
        expectations: CausalEvaluationExpectations | None,
        expected_hypothesis_count: int,
        insufficient_evidence_expected: bool,
    ) -> tuple[RunOutputSnapshot, Postmortem | None, list[Hypothesis]]:
        """Reduce a run's persisted outputs to the ORM-free deterministic snapshot.

        Shared by scenario evaluation (which supplies the scenario's expectations)
        and real-incident evaluation (which has none). Also returns the run's
        Postmortem and ordered Hypotheses so the caller can build a judge input
        without re-querying when a ground-truth reference is available.
        """
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
                advisory_rank=h.advisory_rank,
                # Falsification coverage signal (PRD #38): a Builder-Only Baseline
                # hypothesis carries no challenge, which fails challenge coverage.
                has_challenge=h.challenge is not None,
                origin=h.origin or "initial",
                title=h.title,
                summary=h.summary,
            )
            for h in hypotheses
        )
        warning_codes: list[str] = []
        for event in session.scalars(
            select(RunStageEvent).where(RunStageEvent.run_id == run.id)
        ):
            warning_codes.extend(event.warning_codes or [])

        # Every Counterclaim citation the run's challenges raised (source + lines),
        # so the counterevidence-coverage check can match declared known
        # counterevidence by line overlap (PRD #38). A Builder-Only Baseline has no
        # challenges, so this is empty and it cannot surface known counterevidence.
        counterclaim_citations = tuple(
            CitationRange(
                source_name=ref.source_name,
                line_start=ref.line_start,
                line_end=ref.line_end,
            )
            for h in hypotheses
            if h.challenge is not None
            for counterclaim in h.challenge.counterclaims
            for ref in counterclaim.evidence_refs
        )

        snapshot = RunOutputSnapshot(
            summary=postmortem.summary if postmortem is not None else None,
            timeline=tuple(
                TimelineView(sequence=event.sequence, normalized_ts=event.normalized_ts)
                for event in timeline
            ),
            hypotheses=hypothesis_views,
            citation_statuses=tuple(ref.verifier_status for ref in refs),
            warning_codes=tuple(warning_codes),
            expected_hypothesis_count=expected_hypothesis_count,
            insufficient_evidence_expected=insufficient_evidence_expected,
            evidence_sufficiency=(
                postmortem.evidence_sufficiency if postmortem is not None else "sufficient"
            ),
            analysis_mode=analysis_mode,
            causal_expectations=_causal_expectations_view(expectations),
            counterclaim_citations=counterclaim_citations,
        )
        return snapshot, postmortem, hypotheses

    def _distill(
        self,
        session: Session,
        run: AnalysisRun,
        scenario: LoadedScenario,
        analysis_mode: str,
    ) -> tuple[RunOutputSnapshot, JudgeInput]:
        """Reduce a run's persisted outputs to the ORM-free snapshot + judge input."""
        expectations = scenario.causal_evaluation
        snapshot, postmortem, hypotheses = self._build_snapshot(
            session,
            run,
            analysis_mode=analysis_mode,
            expectations=expectations,
            expected_hypothesis_count=len(scenario.expected_hypothesis_families),
            insufficient_evidence_expected="insufficient-evidence" in scenario.evaluation_tags,
        )
        judge_input = JudgeInput(
            scenario_id=scenario.id,
            generated_summary=postmortem.summary if postmortem is not None else "",
            generated_hypotheses=tuple(
                JudgeHypothesis(
                    title=h.title,
                    summary=h.summary,
                    support_status=h.support_status,
                    has_challenge=h.challenge is not None,
                    challenge_severity=h.challenge.severity if h.challenge is not None else None,
                    counterclaim_count=(
                        len(h.challenge.counterclaims) if h.challenge is not None else 0
                    ),
                )
                for h in hypotheses
            ),
            ground_truth_postmortem=scenario.ground_truth_postmortem,
            # Reference signals for the falsification_quality / explanatory_coverage
            # judge dimensions (PRD #38); empty when the scenario declares no block.
            known_counterevidence=tuple(
                item.description for item in expectations.known_counterevidence
            )
            if expectations is not None
            else (),
            critical_evidence_gaps=(
                expectations.critical_evidence_gaps if expectations is not None else ()
            ),
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


_INPUT_TOKEN_KEYS: tuple[str, ...] = ("prompt_tokens", "input_tokens")
_OUTPUT_TOKEN_KEYS: tuple[str, ...] = ("completion_tokens", "output_tokens")


def _usage_tokens(usage: dict | None) -> int:
    """Sum a model call's input + output tokens across common provider key shapes."""
    if not usage:
        return 0
    total = 0
    for keys in (_INPUT_TOKEN_KEYS, _OUTPUT_TOKEN_KEYS):
        for key in keys:
            value = usage.get(key)
            if isinstance(value, (int, float)):
                total += int(value)
                break
    return total


def _causal_expectations_view(
    expectations: CausalEvaluationExpectations | None,
) -> CausalExpectationsView | None:
    """Distill a scenario's Causal Evaluation Expectations into the ORM-free view.

    Keeps the deterministic checks free of the scenario-loading types (PRD #38),
    mirroring how the run outputs are reduced to ``RunOutputSnapshot``.
    """
    if expectations is None:
        return None
    return CausalExpectationsView(
        expected_factors=tuple(
            ExpectedFactorView(family=factor.family, role=factor.role)
            for factor in expectations.expected_factors
        ),
        plausible_rejected_alternatives=expectations.plausible_rejected_alternatives,
        expected_refusal=expectations.expected_refusal,
        unacceptable_overclaims=expectations.unacceptable_overclaims,
        known_counterevidence=tuple(
            CounterevidenceView(
                description=item.description,
                source_name=item.source_name,
                line_start=item.line_start,
                line_end=item.line_end,
            )
            for item in expectations.known_counterevidence
        ),
        critical_evidence_gaps=expectations.critical_evidence_gaps,
    )


def evaluation_run_read(row: EvaluationRun) -> dict:
    """Shape an EvaluationRun for the EvaluationRunRead schema (ADR 0025)."""
    return {
        "id": row.id,
        "evaluation_kind": row.evaluation_kind,
        "incident_id": row.incident_id,
        "analysis_run_id": row.analysis_run_id,
        "scenario_id": row.scenario_id,
        "scenario_title": row.scenario_title,
        "status": row.status,
        "analysis_run_status": row.analysis_run_status,
        "analysis_mode": row.analysis_mode,
        "passed": row.passed,
        "experiment_metadata": row,
        "check_suite_version": EVAL_CHECK_SUITE_VERSION,
        "judge_version": row.judge_version,
        "citation_total": row.citation_total,
        "citation_verified": row.citation_verified,
        "model_calls": row.model_calls,
        "total_tokens": row.total_tokens,
        "latency_ms": row.latency_ms,
        "checks": list(row.checks),
        "warning_code_counts": dict(row.warning_code_counts),
        "judge_scores": row.judge_scores,
        "error": row.error,
        "created_at": row.created_at,
    }
