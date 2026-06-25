from __future__ import annotations

import pytest

from postmortem.models import EvaluationRun, Incident
from postmortem.services.evaluation import (
    ANALYSIS_MODE_BUILDER_ONLY,
    ANALYSIS_MODE_MULTI_PASS,
    EvaluationRunner,
)

from tests._fakes import FakePostmortemJudge


NORMAL_SCENARIOS = ["deploy-ambiguity", "dependency-failure", "config-drift"]
ALL_SCENARIOS = [*NORMAL_SCENARIOS, "insufficient-evidence"]

# The full deterministic check suite after the causal checks were added (PRD #38).
EXPECTED_CHECK_NAMES = {
    "citation_integrity",
    "required_outputs",
    "timeline_ordering",
    "hypothesis_multiplicity",
    "insufficient_evidence_refusal",
    "advisory_ranking_coverage",
    "causal_challenge_coverage",
    "counterevidence_coverage",
    "alternative_consideration",
    "unsupported_causal_claims",
    "causal_refusal",
    "causal_role_constraints",
    "unacceptable_overclaims",
}


def _multi_pass(rows):
    """The multi-pass row from a both-configuration ``run_and_record`` result."""
    return next(r for r in rows if r.analysis_mode == ANALYSIS_MODE_MULTI_PASS)


def _builder_only(rows):
    return next(r for r in rows if r.analysis_mode == ANALYSIS_MODE_BUILDER_ONLY)


@pytest.mark.parametrize("scenario_id", NORMAL_SCENARIOS)
def test_run_and_record_passes_the_deterministic_floor(fresh_session, scenario_id):
    runner = EvaluationRunner(fresh_session, judge=FakePostmortemJudge())
    rows = runner.run_and_record(scenario_id)
    fresh_session.commit()

    # Both configurations are recorded for the scenario (PRD #38).
    assert {r.analysis_mode for r in rows} == {
        ANALYSIS_MODE_MULTI_PASS,
        ANALYSIS_MODE_BUILDER_ONLY,
    }
    row = _multi_pass(rows)

    assert row.scenario_id == scenario_id
    assert row.status == "succeeded"
    assert row.analysis_run_status == "succeeded"
    # Every deterministic check passed and every citation verified (ADR 0010).
    assert row.passed is True
    assert {c["name"] for c in row.checks} == EXPECTED_CHECK_NAMES
    assert all(c["passed"] for c in row.checks)
    assert row.citation_total > 0
    assert row.citation_verified == row.citation_total
    # Warning Codes are aggregated for experiment tracking (ADR 0025): each
    # scenario carries an uncited assumption hypothesis and a partial claim.
    assert row.warning_code_counts.get("uncited_claim", 0) >= 1
    assert row.warning_code_counts.get("partial_claim_support", 0) >= 1
    # The replay is recorded honestly in Experiment Metadata (ADR 0025).
    assert row.model_provider == f"scenario-replay:{scenario_id}"
    # The judge ran and was recorded, separate from the citation floor. The rubric
    # now includes the causal-depth dimensions (PRD #38).
    assert row.judge_version == "fake-judge-0"
    assert row.judge_scores is not None
    assert {"explanatory_coverage", "falsification_quality"} <= set(
        row.judge_scores["scores"]
    )


@pytest.mark.parametrize("scenario_id", NORMAL_SCENARIOS)
def test_builder_only_baseline_fails_challenge_coverage_at_lower_cost(
    fresh_session, scenario_id
):
    # The Builder-Only Baseline skips the Falsification Round, so its hypotheses
    # are unchallenged — the challenge-coverage check fails while the multi-pass
    # run passes, and the baseline makes strictly fewer model calls (PRD #38).
    rows = EvaluationRunner(fresh_session, judge=FakePostmortemJudge()).run_and_record(
        scenario_id
    )
    fresh_session.commit()
    multi, baseline = _multi_pass(rows), _builder_only(rows)

    assert multi.passed is True
    assert baseline.passed is False
    baseline_checks = {c["name"]: c for c in baseline.checks}
    assert baseline_checks["causal_challenge_coverage"]["passed"] is False
    # Citation validity still holds for the baseline — it generates and ranks real
    # hypotheses, it just never challenges them.
    assert baseline.citation_verified == baseline.citation_total > 0
    # Strictly fewer model calls than the multi-pass configuration — the
    # deterministic cost signal (latency is wall-clock-derived and timing-dependent,
    # so its ordering is not asserted; both are still recorded as cost metrics).
    assert baseline.model_calls < multi.model_calls
    assert baseline.latency_ms >= 0 and multi.latency_ms >= 0


def test_deploy_baseline_misses_known_counterevidence(fresh_session):
    # The deploy scenario declares known counterevidence cited to real evidence
    # lines. The multi-pass run surfaces it through Counterclaims; the Builder-Only
    # Baseline raises no Counterclaims, so it fails counterevidence coverage — the
    # second deterministic signal that the falsification pass adds value (PRD #38).
    rows = EvaluationRunner(fresh_session, judge=FakePostmortemJudge()).run_and_record(
        "deploy-ambiguity"
    )
    fresh_session.commit()
    multi = {c["name"]: c for c in _multi_pass(rows).checks}
    baseline = {c["name"]: c for c in _builder_only(rows).checks}

    assert multi["counterevidence_coverage"]["passed"] is True
    assert "3/3" in multi["counterevidence_coverage"]["detail"]
    assert baseline["counterevidence_coverage"]["passed"] is False
    # And the declared alternative is genuinely weighed and ranked below the lead.
    assert multi["alternative_consideration"]["passed"] is True


def test_insufficient_evidence_scenario_passes_by_refusing_hypotheses(fresh_session):
    runner = EvaluationRunner(fresh_session, judge=FakePostmortemJudge())
    rows = runner.run_and_record("insufficient-evidence")
    fresh_session.commit()

    # A refusal scenario has no hypotheses to challenge, so both configurations
    # pass identically (PRD #38).
    for row in rows:
        assert row.status == "succeeded"
        assert row.analysis_run_status == "succeeded"
        assert row.passed is True
        checks = {c["name"]: c for c in row.checks}
        assert checks["citation_integrity"]["passed"] is True
        assert checks["citation_integrity"]["detail"] == "0/0 citations verified"
        assert checks["required_outputs"]["passed"] is True
        assert checks["hypothesis_multiplicity"]["passed"] is True
        assert "expected refusal" in checks["hypothesis_multiplicity"]["detail"]
        # The product refused, and both the tag-based and the expectation-driven
        # refusal checks confirm it (AC #4).
        assert checks["insufficient_evidence_refusal"]["passed"] is True
        assert "refused as insufficient" in checks["insufficient_evidence_refusal"]["detail"]
        assert checks["causal_refusal"]["passed"] is True
        assert checks["causal_role_constraints"]["passed"] is True
        assert row.citation_total == 0
        assert row.citation_verified == 0
        # Drafting emitted the refusal Warning Code, aggregated for the scenario (AC #4).
        assert row.warning_code_counts == {"insufficient_evidence": 1}


def test_evaluation_is_independent_of_product_incident_data(fresh_session):
    # Running every scenario records an Evaluation Run per configuration but leaves
    # no product Incident/Analysis rows behind — eval uses an ephemeral DB (AC #1).
    rows = EvaluationRunner(fresh_session, judge=FakePostmortemJudge()).run_all()
    fresh_session.commit()

    assert len(rows) == len(ALL_SCENARIOS) * 2
    assert fresh_session.query(EvaluationRun).count() == len(ALL_SCENARIOS) * 2
    assert fresh_session.query(Incident).count() == 0


def test_judge_is_optional_and_never_the_citation_authority(fresh_session):
    # With no judge configured, the deterministic floor still records full
    # citation validity — the judge is not the source of truth (ADR 0010 / AC #5).
    rows = EvaluationRunner(fresh_session, judge=None).run_and_record("deploy-ambiguity")
    fresh_session.commit()
    row = _multi_pass(rows)

    assert row.judge_version is None
    assert row.judge_scores is None
    assert row.passed is True
    assert row.citation_verified == row.citation_total > 0


def test_judge_receives_generated_postmortem_and_ground_truth(fresh_session):
    judge = FakePostmortemJudge()
    EvaluationRunner(fresh_session, judge=judge).run_and_record("config-drift")

    # The judge is consulted once per configuration (multi-pass + baseline).
    assert len(judge.calls) == 2
    payload = judge.calls[0]
    assert payload.scenario_id == "config-drift"
    assert payload.generated_summary
    assert payload.generated_hypotheses
    # The Ground-Truth Postmortem (eval reference material) is handed to the judge.
    assert "ground truth" in payload.ground_truth_postmortem.lower()
