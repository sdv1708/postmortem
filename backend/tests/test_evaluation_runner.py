from __future__ import annotations

import pytest

from postmortem.models import EvaluationRun, Incident
from postmortem.services.evaluation import EvaluationRunner

from tests._fakes import FakePostmortemJudge


NORMAL_SCENARIOS = ["deploy-ambiguity", "dependency-failure", "config-drift"]
ALL_SCENARIOS = [*NORMAL_SCENARIOS, "insufficient-evidence"]


@pytest.mark.parametrize("scenario_id", NORMAL_SCENARIOS)
def test_run_and_record_passes_the_deterministic_floor(fresh_session, scenario_id):
    runner = EvaluationRunner(fresh_session, judge=FakePostmortemJudge())
    row = runner.run_and_record(scenario_id)
    fresh_session.commit()

    assert row.scenario_id == scenario_id
    assert row.status == "succeeded"
    assert row.analysis_run_status == "succeeded"
    # Every deterministic check passed and every citation verified (ADR 0010).
    assert row.passed is True
    assert {c["name"] for c in row.checks} == {
        "citation_integrity",
        "required_outputs",
        "timeline_ordering",
        "hypothesis_multiplicity",
        "insufficient_evidence_refusal",
    }
    assert all(c["passed"] for c in row.checks)
    assert row.citation_total > 0
    assert row.citation_verified == row.citation_total
    # Warning Codes are aggregated for experiment tracking (ADR 0025): each
    # scenario carries an uncited assumption hypothesis and a partial claim.
    assert row.warning_code_counts.get("uncited_claim", 0) >= 1
    assert row.warning_code_counts.get("partial_claim_support", 0) >= 1
    # The replay is recorded honestly in Experiment Metadata (ADR 0025).
    assert row.model_provider == f"scenario-replay:{scenario_id}"
    # The judge ran and was recorded, separate from the citation floor.
    assert row.judge_version == "fake-judge-0"
    assert row.judge_scores is not None
    assert set(row.judge_scores["scores"]) == {
        "timeline_accuracy",
        "root_cause_quality",
        "evidence_grounding",
        "uncertainty_honesty",
    }


def test_insufficient_evidence_scenario_passes_by_refusing_hypotheses(fresh_session):
    runner = EvaluationRunner(fresh_session, judge=FakePostmortemJudge())
    row = runner.run_and_record("insufficient-evidence")
    fresh_session.commit()

    assert row.status == "succeeded"
    assert row.analysis_run_status == "succeeded"
    assert row.passed is True
    checks = {c["name"]: c for c in row.checks}
    assert checks["citation_integrity"]["passed"] is True
    assert checks["citation_integrity"]["detail"] == "0/0 citations verified"
    assert checks["required_outputs"]["passed"] is True
    assert checks["hypothesis_multiplicity"]["passed"] is True
    assert "expected refusal" in checks["hypothesis_multiplicity"]["detail"]
    # The product refused, and the positive refusal check confirms it (AC #4).
    assert checks["insufficient_evidence_refusal"]["passed"] is True
    assert "refused as insufficient" in checks["insufficient_evidence_refusal"]["detail"]
    assert row.citation_total == 0
    assert row.citation_verified == 0
    # Drafting emitted the refusal Warning Code, aggregated for the scenario (AC #4).
    assert row.warning_code_counts == {"insufficient_evidence": 1}


def test_evaluation_is_independent_of_product_incident_data(fresh_session):
    # Running every scenario records Evaluation Runs but leaves no product
    # Incident/Analysis rows behind — eval uses an ephemeral database (AC #1).
    rows = EvaluationRunner(fresh_session, judge=FakePostmortemJudge()).run_all()
    fresh_session.commit()

    assert len(rows) == len(ALL_SCENARIOS)
    assert fresh_session.query(EvaluationRun).count() == len(ALL_SCENARIOS)
    assert fresh_session.query(Incident).count() == 0


def test_judge_is_optional_and_never_the_citation_authority(fresh_session):
    # With no judge configured, the deterministic floor still records full
    # citation validity — the judge is not the source of truth (ADR 0010 / AC #5).
    row = EvaluationRunner(fresh_session, judge=None).run_and_record("deploy-ambiguity")
    fresh_session.commit()

    assert row.judge_version is None
    assert row.judge_scores is None
    assert row.passed is True
    assert row.citation_verified == row.citation_total > 0


def test_judge_receives_generated_postmortem_and_ground_truth(fresh_session):
    judge = FakePostmortemJudge()
    EvaluationRunner(fresh_session, judge=judge).run_and_record("config-drift")

    assert len(judge.calls) == 1
    payload = judge.calls[0]
    assert payload.scenario_id == "config-drift"
    assert payload.generated_summary
    assert payload.generated_hypotheses
    # The Ground-Truth Postmortem (eval reference material) is handed to the judge.
    assert "ground truth" in payload.ground_truth_postmortem.lower()
