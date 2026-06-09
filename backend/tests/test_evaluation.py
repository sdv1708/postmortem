from __future__ import annotations

import json
from datetime import datetime, timezone

import pytest

from postmortem.evaluation import (
    HypothesisView,
    JudgeHypothesis,
    JudgeInput,
    LLMPostmortemJudge,
    RunOutputSnapshot,
    TimelineView,
    aggregate_warning_codes,
    build_judge_prompt,
    check_citation_integrity,
    check_hypothesis_multiplicity,
    check_required_outputs,
    check_timeline_ordering,
    citation_tally,
)
from postmortem.llm import FakeLLMClient


_T1 = datetime(2026, 5, 9, 14, 28, tzinfo=timezone.utc)
_T2 = datetime(2026, 5, 9, 14, 31, tzinfo=timezone.utc)


def _snapshot(**overrides) -> RunOutputSnapshot:
    base = dict(
        summary="A real composed summary.",
        timeline=(TimelineView(1, _T1), TimelineView(2, _T2)),
        hypotheses=(
            HypothesisView(1, "supported", 3),
            HypothesisView(2, "partial", 2),
            HypothesisView(3, "unsupported", 0),
        ),
        citation_statuses=("verified", "verified", "verified"),
        warning_codes=("uncited_claim", "uncited_claim", "partial_claim_support"),
        expected_hypothesis_count=3,
    )
    base.update(overrides)
    return RunOutputSnapshot(**base)


def test_citation_integrity_passes_only_when_all_verified():
    assert check_citation_integrity(_snapshot()).passed is True
    broken = _snapshot(citation_statuses=("verified", "snippet_mismatch", "verified"))
    result = check_citation_integrity(broken)
    assert result.passed is False
    assert "2/3" in result.detail
    # No citations at all is not a pass — there is nothing proven.
    assert check_citation_integrity(_snapshot(citation_statuses=())).passed is False


def test_required_outputs_reports_missing_sections():
    assert check_required_outputs(_snapshot()).passed is True
    missing = check_required_outputs(_snapshot(summary="", hypotheses=()))
    assert missing.passed is False
    assert "summary" in missing.detail and "hypotheses" in missing.detail


def test_timeline_ordering_detects_out_of_order_dated_events():
    assert check_timeline_ordering(_snapshot()).passed is True
    # Sequence 1 carries the later timestamp than sequence 2 → out of order.
    jumbled = _snapshot(timeline=(TimelineView(1, _T2), TimelineView(2, _T1)))
    assert check_timeline_ordering(jumbled).passed is False
    # Undated events never break ordering.
    assert check_timeline_ordering(_snapshot(timeline=(TimelineView(1, None),))).passed is True


def test_hypothesis_multiplicity_requires_multiple_competing_hypotheses():
    assert check_hypothesis_multiplicity(_snapshot()).passed is True
    single = _snapshot(hypotheses=(HypothesisView(1, "supported", 2),))
    assert check_hypothesis_multiplicity(single).passed is False
    # Floor is 2 even when a scenario declares fewer expected families.
    two = _snapshot(
        hypotheses=(HypothesisView(1, "supported", 1), HypothesisView(2, "partial", 1)),
        expected_hypothesis_count=0,
    )
    assert check_hypothesis_multiplicity(two).passed is True


def test_warning_code_aggregation_and_citation_tally():
    assert aggregate_warning_codes(_snapshot()) == {
        "uncited_claim": 2,
        "partial_claim_support": 1,
    }
    assert citation_tally(_snapshot()) == (3, 3)
    assert citation_tally(_snapshot(citation_statuses=("verified", "artifact_missing"))) == (2, 1)


def _judge_input() -> JudgeInput:
    return JudgeInput(
        scenario_id="deploy-ambiguity",
        generated_summary="Summary of the generated postmortem.",
        generated_hypotheses=(
            JudgeHypothesis("Deploy regressed", "v184 caused pool exhaustion.", "supported"),
        ),
        ground_truth_postmortem="Ground truth says the deploy is the leading cause.",
    )


def test_judge_prompt_excludes_citation_validity_from_the_rubric():
    system, user = build_judge_prompt(_judge_input())
    # The judge is explicitly told not to assess citation integrity (ADR 0010).
    assert "citation integrity is" in system.lower()
    assert "Ground-Truth" in user or "GROUND-TRUTH" in user
    assert "Deploy regressed" in user


def test_llm_judge_validates_strict_output_and_computes_overall():
    payload = json.dumps(
        {
            "scores": {
                "timeline_accuracy": 5,
                "root_cause_quality": 4,
                "evidence_grounding": 4,
                "uncertainty_honesty": 5,
            },
            "rationale": "Strong, evidence-grounded, honest about ambiguity.",
        }
    )
    judge = LLMPostmortemJudge(FakeLLMClient([payload]))
    result = judge.judge(_judge_input())
    assert result.scores["timeline_accuracy"] == 5
    assert result.overall == 4.5
    assert result.version == "llm-judge-1"


def test_llm_judge_rejects_schema_invalid_output():
    # Score out of the 1-5 range must not become a recorded score.
    bad = json.dumps(
        {
            "scores": {
                "timeline_accuracy": 9,
                "root_cause_quality": 4,
                "evidence_grounding": 4,
                "uncertainty_honesty": 5,
            },
            "rationale": "x",
        }
    )
    with pytest.raises(ValueError, match="schema validation"):
        LLMPostmortemJudge(FakeLLMClient([bad])).judge(_judge_input())
    with pytest.raises(ValueError, match="schema validation"):
        LLMPostmortemJudge(FakeLLMClient(["{ not json"])).judge(_judge_input())
