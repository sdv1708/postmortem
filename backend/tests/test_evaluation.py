from __future__ import annotations

import json
from datetime import datetime, timezone

import pytest

from postmortem.evaluation import (
    CausalExpectationsView,
    CitationRange,
    CounterevidenceView,
    ExpectedFactorView,
    HypothesisView,
    JudgeHypothesis,
    JudgeInput,
    LLMPostmortemJudge,
    RunOutputSnapshot,
    TimelineView,
    aggregate_warning_codes,
    build_judge_prompt,
    check_alternative_consideration,
    check_causal_challenge_coverage,
    check_causal_refusal,
    check_causal_role_constraints,
    check_citation_integrity,
    check_counterevidence_coverage,
    check_hypothesis_multiplicity,
    check_insufficient_evidence_refusal,
    check_required_outputs,
    check_timeline_ordering,
    check_unacceptable_overclaims,
    check_unsupported_causal_claims,
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
    # Refusal scenarios may have zero citations or verified partial/timeline
    # citations; any present citation still has to verify.
    assert check_citation_integrity(
        _snapshot(citation_statuses=(), insufficient_evidence_expected=True)
    ).passed is True
    assert check_citation_integrity(
        _snapshot(citation_statuses=("verified",), insufficient_evidence_expected=True)
    ).passed is True
    assert check_citation_integrity(
        _snapshot(citation_statuses=("snippet_mismatch",), insufficient_evidence_expected=True)
    ).passed is False


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
    # A refusal scenario may emit no hypotheses or uncited assumptions, but it
    # must not emit evidence-backed confident hypotheses.
    refusal_with_assumptions = _snapshot(
        hypotheses=(HypothesisView(1, "unsupported", 0),),
        insufficient_evidence_expected=True,
    )
    assert check_hypothesis_multiplicity(refusal_with_assumptions).passed is True
    refusal_with_cited_hypothesis = _snapshot(
        hypotheses=(HypothesisView(1, "supported", 1),),
        insufficient_evidence_expected=True,
    )
    assert check_hypothesis_multiplicity(refusal_with_cited_hypothesis).passed is False


def test_insufficient_evidence_refusal_check_both_directions():
    # A normal run must not refuse.
    assert check_insufficient_evidence_refusal(_snapshot()).passed is True
    spurious = _snapshot(evidence_sufficiency="insufficient")
    assert check_insufficient_evidence_refusal(spurious).passed is False

    # A refusal scenario must actually refuse with no evidence-backed hypotheses.
    refused = _snapshot(
        hypotheses=(),
        citation_statuses=(),
        timeline=(),
        insufficient_evidence_expected=True,
        evidence_sufficiency="insufficient",
    )
    result = check_insufficient_evidence_refusal(refused)
    assert result.passed is True
    assert "refused as insufficient" in result.detail
    refused_with_assumption = _snapshot(
        hypotheses=(HypothesisView(1, "unsupported", 0),),
        insufficient_evidence_expected=True,
        evidence_sufficiency="insufficient",
    )
    assert check_insufficient_evidence_refusal(refused_with_assumption).passed is True
    refused_with_evidence_backed_hypothesis = _snapshot(
        hypotheses=(HypothesisView(1, "supported", 1),),
        insufficient_evidence_expected=True,
        evidence_sufficiency="insufficient",
    )
    assert check_insufficient_evidence_refusal(refused_with_evidence_backed_hypothesis).passed is False
    # A refusal scenario that did NOT refuse fails the check.
    did_not_refuse = _snapshot(
        insufficient_evidence_expected=True, evidence_sufficiency="sufficient"
    )
    assert check_insufficient_evidence_refusal(did_not_refuse).passed is False


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


# --- Causal-analysis deterministic checks (PRD #38 / ADR 0044) --------------


def _expectations(**overrides) -> CausalExpectationsView:
    base = dict(
        expected_factors=(
            ExpectedFactorView("connection-pool-capacity", "failure_mechanism"),
            ExpectedFactorView("deploy-regression", "trigger"),
        ),
        plausible_rejected_alternatives=("upstream-dependency",),
        expected_refusal=False,
        unacceptable_overclaims=("the deploy was definitively the root cause",),
        known_counterevidence=(
            CounterevidenceView("max_connections unchanged", "deploy-notes.md", 4, 4),
        ),
        critical_evidence_gaps=("no per-endpoint error metrics",),
    )
    base.update(overrides)
    return CausalExpectationsView(**base)


def test_causal_challenge_coverage_distinguishes_baseline():
    # Multi-pass: every hypothesis carries a challenge → pass.
    multi = _snapshot(
        hypotheses=(
            HypothesisView(1, "supported", 3, advisory_rank=1, has_challenge=True),
            HypothesisView(2, "partial", 2, advisory_rank=2, has_challenge=True),
        )
    )
    assert check_causal_challenge_coverage(multi).passed is True
    # Builder-only: no challenges → fail (the comparison signal).
    baseline = _snapshot(
        hypotheses=(
            HypothesisView(1, "supported", 3, advisory_rank=1, has_challenge=False),
            HypothesisView(2, "partial", 2, advisory_rank=2, has_challenge=False),
        )
    )
    result = check_causal_challenge_coverage(baseline)
    assert result.passed is False
    assert "0/2" in result.detail
    # No hypotheses (refusal) → nothing to challenge, trivially passes.
    assert check_causal_challenge_coverage(_snapshot(hypotheses=())).passed is True


def test_alternative_consideration_requires_the_declared_alternative_considered():
    exp = _expectations()  # declares the "upstream-dependency" alternative
    # The declared alternative is represented by a non-leading hypothesis → pass.
    considered = _snapshot(
        hypotheses=(
            HypothesisView(1, "supported", 3, advisory_rank=1, title="Connection pool saturated"),
            HypothesisView(
                2, "partial", 2, advisory_rank=2, title="An upstream dependency degraded"
            ),
        ),
        causal_expectations=exp,
    )
    assert check_alternative_consideration(considered).passed is True
    # Two candidates, but neither is the declared alternative → still fails: the
    # check is about the *declared* alternative, not raw count (review finding #2).
    wrong_two = _snapshot(
        hypotheses=(
            HypothesisView(1, "supported", 3, advisory_rank=1, title="Connection pool saturated"),
            HypothesisView(2, "partial", 2, advisory_rank=2, title="Cache eviction storm"),
        ),
        causal_expectations=exp,
    )
    result = check_alternative_consideration(wrong_two)
    assert result.passed is False
    assert "upstream-dependency" in result.detail
    # The declared alternative present but as the advisory *leader* is not "rejected".
    as_leader = _snapshot(
        hypotheses=(
            HypothesisView(1, "supported", 3, advisory_rank=1, title="An upstream dependency degraded"),
        ),
        causal_expectations=exp,
    )
    assert check_alternative_consideration(as_leader).passed is False
    # No expectations declared → trivial pass.
    assert check_alternative_consideration(_snapshot()).passed is True


def test_counterevidence_coverage_requires_challenges_to_surface_known_counterevidence():
    exp = _expectations()  # declares counterevidence at deploy-notes.md:4
    # A challenge raised a counterclaim citing the same lines → surfaced → pass.
    surfaced = _snapshot(
        hypotheses=(HypothesisView(1, "supported", 3, advisory_rank=1, has_challenge=True),),
        causal_expectations=exp,
        counterclaim_citations=(CitationRange("deploy-notes.md", 3, 5),),
    )
    assert check_counterevidence_coverage(surfaced).passed is True
    # No counterclaims at all (the Builder-Only Baseline) → known counterevidence
    # is never surfaced → fail (review finding #1).
    baseline = _snapshot(
        hypotheses=(HypothesisView(1, "supported", 3, advisory_rank=1),),
        causal_expectations=exp,
        counterclaim_citations=(),
    )
    result = check_counterevidence_coverage(baseline)
    assert result.passed is False
    assert "deploy-notes.md:4-4" in result.detail
    # A counterclaim on the wrong lines does not count as surfacing it.
    wrong_lines = _snapshot(
        causal_expectations=exp,
        counterclaim_citations=(CitationRange("deploy-notes.md", 1, 2),),
    )
    assert check_counterevidence_coverage(wrong_lines).passed is False
    # No counterevidence declared → trivial pass.
    assert check_counterevidence_coverage(_snapshot()).passed is True


def test_unsupported_causal_claims_fails_when_leader_is_unsupported():
    leader_ok = _snapshot(
        hypotheses=(
            HypothesisView(1, "supported", 3, advisory_rank=1),
            HypothesisView(2, "unsupported", 0, advisory_rank=2),
        )
    )
    assert check_unsupported_causal_claims(leader_ok).passed is True
    leader_bad = _snapshot(
        hypotheses=(
            HypothesisView(1, "unsupported", 1, advisory_rank=1),
            HypothesisView(2, "supported", 3, advisory_rank=2),
        )
    )
    assert check_unsupported_causal_claims(leader_bad).passed is False


def test_causal_refusal_follows_the_expectation_flag():
    refusal_exp = _expectations(expected_refusal=True, expected_factors=())
    refused = _snapshot(
        hypotheses=(), evidence_sufficiency="insufficient", causal_expectations=refusal_exp
    )
    assert check_causal_refusal(refused).passed is True
    # Expected to refuse but produced an evidence-backed hypothesis → fail.
    overclaimed = _snapshot(
        hypotheses=(HypothesisView(1, "supported", 2, advisory_rank=1),),
        evidence_sufficiency="sufficient",
        causal_expectations=refusal_exp,
    )
    assert check_causal_refusal(overclaimed).passed is False
    # A non-refusal scenario must not spuriously refuse.
    spurious = _snapshot(
        evidence_sufficiency="insufficient", causal_expectations=_expectations()
    )
    assert check_causal_refusal(spurious).passed is False
    # No expectations → trivial pass.
    assert check_causal_refusal(_snapshot()).passed is True


def test_causal_role_constraints_requires_finalizable_candidate():
    ok = _snapshot(
        hypotheses=(HypothesisView(1, "partial", 2, advisory_rank=1),),
        causal_expectations=_expectations(),
    )
    assert check_causal_role_constraints(ok).passed is True
    # No supported/partial candidate to finalize as a Failure Mechanism → fail.
    none_finalizable = _snapshot(
        hypotheses=(HypothesisView(1, "unsupported", 0, advisory_rank=1),),
        causal_expectations=_expectations(),
    )
    assert check_causal_role_constraints(none_finalizable).passed is False
    # Refusal scenario must have no evidence-backed candidates.
    refusal_exp = _expectations(expected_refusal=True, expected_factors=())
    assert check_causal_role_constraints(
        _snapshot(hypotheses=(), causal_expectations=refusal_exp)
    ).passed is True


def test_unacceptable_overclaims_scans_summary_and_hypotheses():
    exp = _expectations(unacceptable_overclaims=("definitively the root cause",))
    clean = _snapshot(
        summary="The deploy and the pool are both plausible; none is proven.",
        hypotheses=(HypothesisView(1, "partial", 2, advisory_rank=1, title="Pool", summary="ok"),),
        causal_expectations=exp,
    )
    assert check_unacceptable_overclaims(clean).passed is True
    dirty = _snapshot(
        summary="This was definitively the root cause.",
        causal_expectations=exp,
    )
    result = check_unacceptable_overclaims(dirty)
    assert result.passed is False
    assert "definitively the root cause" in result.detail
    # Overclaim hidden in a hypothesis summary is also caught.
    in_hypothesis = _snapshot(
        summary="Measured summary.",
        hypotheses=(
            HypothesisView(
                1, "supported", 2, advisory_rank=1,
                title="Pool", summary="This was definitively the root cause.",
            ),
        ),
        causal_expectations=exp,
    )
    assert check_unacceptable_overclaims(in_hypothesis).passed is False
    # None declared → trivial pass.
    assert check_unacceptable_overclaims(_snapshot()).passed is True


def test_judge_prompt_excludes_citation_validity_from_the_rubric():
    system, user = build_judge_prompt(_judge_input())
    # The judge is explicitly told not to assess citation integrity (ADR 0010).
    assert "citation integrity is" in system.lower()
    assert "Ground-Truth" in user or "GROUND-TRUTH" in user
    assert "Deploy regressed" in user


def test_judge_prompt_surfaces_falsification_context():
    # The causal-depth dimensions are in the rubric, and a hypothesis's challenge
    # status is surfaced so the judge can score falsification quality (PRD #38).
    system, _user = build_judge_prompt(_judge_input())
    assert "explanatory_coverage" in system
    assert "falsification_quality" in system

    challenged = JudgeInput(
        scenario_id="deploy-ambiguity",
        generated_summary="s",
        generated_hypotheses=(
            JudgeHypothesis(
                "Pool", "saturated", "supported",
                has_challenge=True, challenge_severity="material", counterclaim_count=2,
            ),
            JudgeHypothesis("Deploy", "v184", "partial", has_challenge=False),
        ),
        ground_truth_postmortem="gt",
        known_counterevidence=("max_connections was left unchanged",),
        critical_evidence_gaps=("no per-endpoint error metrics",),
    )
    _system, user = build_judge_prompt(challenged)
    assert "material severity, 2 counterclaim(s)" in user
    assert "not challenged" in user
    # The reference signals for the falsification/explanatory dimensions surface.
    assert "max_connections was left unchanged" in user
    assert "no per-endpoint error metrics" in user


def test_llm_judge_validates_strict_output_and_computes_overall():
    payload = json.dumps(
        {
            "scores": {
                "timeline_accuracy": 5,
                "root_cause_quality": 4,
                "evidence_grounding": 4,
                "uncertainty_honesty": 5,
                # Causal-depth dimensions added for the multi-pass comparison (PRD #38).
                "explanatory_coverage": 4,
                "falsification_quality": 2,
            },
            "rationale": "Strong, evidence-grounded, honest about ambiguity.",
        }
    )
    judge = LLMPostmortemJudge(FakeLLMClient([payload]))
    result = judge.judge(_judge_input())
    assert result.scores["timeline_accuracy"] == 5
    assert result.scores["falsification_quality"] == 2
    # Overall is the mean of all six rubric dimensions.
    assert result.overall == round((5 + 4 + 4 + 5 + 4 + 2) / 6, 2)
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
