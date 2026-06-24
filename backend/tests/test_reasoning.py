"""Unit tests for the bounded causal-analysis primitives (ADR 0043).

These cover the Reasoning Budget ledger and the Targeted Repair helper in
isolation — call/repair/total/token/retrieval accounting and the single bounded
re-invocation contract — without driving the whole stage. The deep-stage
behavior (successful repair, failed repair, budget exhaustion, preserved
outputs, no degraded builder-only success) is exercised in test_stages_repair.py.
"""

from __future__ import annotations

import pytest

from postmortem.reasoning import (
    DEFAULT_REASONING_BUDGET,
    FAILURE_BUDGET_EXHAUSTED,
    FAILURE_REPAIR_EXHAUSTED,
    GATE_SCHEMA_INVALID,
    REASONING_BUDGET_VERSION,
    BudgetLedger,
    CausalAnalysisError,
    ReasoningBudget,
    ReasoningGateError,
    targeted_repair,
)


def _ledger(**overrides) -> BudgetLedger:
    return BudgetLedger(ReasoningBudget(**overrides))


def test_budget_as_metadata_round_trips_limits():
    budget = ReasoningBudget(max_calls_per_role=3, max_total_calls=10)
    meta = budget.as_metadata()
    assert meta["version"] == REASONING_BUDGET_VERSION
    assert meta["max_calls_per_role"] == 3
    assert meta["max_total_calls"] == 10
    assert meta["repair_calls_per_role"] == 1


def test_normal_calls_cannot_consume_the_reserved_repair_budget():
    # One normal call allowed, plus one reserved repair: a second *normal* call is
    # rejected even though the repair slot is still free (ADR 0043).
    ledger = _ledger(max_calls_per_role=1, repair_calls_per_role=1, max_total_calls=10)
    ledger.charge_call("builder", "builder:generate")
    with pytest.raises(CausalAnalysisError) as excinfo:
        ledger.charge_call("builder", "builder:generate")
    assert excinfo.value.code == FAILURE_BUDGET_EXHAUSTED
    assert excinfo.value.substep == "builder:generate"
    # The reserved repair slot is independent and still available.
    ledger.charge_repair("builder", "builder:generate")
    with pytest.raises(CausalAnalysisError) as second:
        ledger.charge_repair("builder", "builder:generate")
    assert second.value.code == FAILURE_BUDGET_EXHAUSTED


def test_total_call_budget_is_enforced_across_roles():
    ledger = _ledger(max_calls_per_role=5, max_total_calls=2)
    ledger.charge_call("builder", "builder:generate")
    ledger.charge_call("falsifier", "challenge:initial:1")
    with pytest.raises(CausalAnalysisError) as excinfo:
        ledger.charge_call("ranker", "ranker:rank")
    assert excinfo.value.code == FAILURE_BUDGET_EXHAUSTED
    assert "total call budget" in excinfo.value.detail


def test_token_budget_accumulates_and_fails_when_exceeded():
    ledger = _ledger(max_input_tokens_per_role=100)
    ledger.observe_usage("builder", {"prompt_tokens": 60}, "builder:generate")
    with pytest.raises(CausalAnalysisError) as excinfo:
        ledger.observe_usage("builder", {"input_tokens": 50}, "builder:generate")
    assert excinfo.value.code == FAILURE_BUDGET_EXHAUSTED
    assert "input-token budget" in excinfo.value.detail


def test_zero_token_budget_is_unmetered():
    # The default leaves token budgets at 0 ("unmetered") so an offline/fake role
    # that reports usage is never failed for it.
    ledger = BudgetLedger(DEFAULT_REASONING_BUDGET)
    ledger.observe_usage("builder", {"prompt_tokens": 10_000_000}, "builder:generate")


def test_retrieval_budget_bounds_single_retrieval_breadth_not_the_sum():
    ledger = _ledger(max_retrieval_chunks_per_role=5)
    # Two retrievals of 5 chunks each are fine — the cap is per retrieval, so a role
    # that revisits the same evidence is not penalized (the falsifier re-retrieves).
    ledger.observe_retrieval("falsifier", 5, "challenge:initial:1")
    ledger.observe_retrieval("falsifier", 5, "challenge:initial:2")
    with pytest.raises(CausalAnalysisError) as excinfo:
        ledger.observe_retrieval("falsifier", 6, "challenge:initial:3")
    assert excinfo.value.code == FAILURE_BUDGET_EXHAUSTED


def test_targeted_repair_returns_first_output_when_gate_passes():
    ledger = _ledger()
    calls: list[tuple[str, ...]] = []

    def produce(feedback):
        calls.append(feedback)
        return "ok"

    result = targeted_repair(
        role="builder",
        substep="builder:generate",
        ledger=ledger,
        produce=produce,
        validate=lambda output: None,
    )
    assert result == "ok"
    # Successful role is invoked exactly once — never re-run (AC #3).
    assert calls == [()]
    assert ledger.snapshot()["roles"]["builder"] == {
        "calls": 1,
        "repair_calls": 0,
        "input_tokens": 0,
        "output_tokens": 0,
        "retrieval_chunks": 0,
    }


def test_targeted_repair_repairs_once_with_validation_errors():
    ledger = _ledger()
    seen_feedback: list[tuple[str, ...]] = []
    outputs = iter(["bad", "good"])

    def produce(feedback):
        seen_feedback.append(feedback)
        return next(outputs)

    def validate(output):
        if output != "good":
            raise ReasoningGateError(GATE_SCHEMA_INVALID, ["output was not good"])

    result = targeted_repair(
        role="builder",
        substep="builder:generate",
        ledger=ledger,
        produce=produce,
        validate=validate,
    )
    assert result == "good"
    # The single repair is informed: it receives the gate's deterministic errors.
    assert seen_feedback == [(), ("output was not good",)]
    usage = ledger.snapshot()["roles"]["builder"]
    assert usage["calls"] == 1 and usage["repair_calls"] == 1


def test_targeted_repair_exhausts_after_one_repair():
    ledger = _ledger()
    attempts = 0

    def produce(feedback):
        nonlocal attempts
        attempts += 1
        return "bad"

    def validate(output):
        raise ReasoningGateError(GATE_SCHEMA_INVALID, ["still bad"])

    with pytest.raises(CausalAnalysisError) as excinfo:
        targeted_repair(
            role="builder",
            substep="builder:generate",
            ledger=ledger,
            produce=produce,
            validate=validate,
        )
    # Produced exactly twice: the original attempt plus one Targeted Repair.
    assert attempts == 2
    assert excinfo.value.code == FAILURE_REPAIR_EXHAUSTED
    assert excinfo.value.gate_code == GATE_SCHEMA_INVALID
    assert "still bad" in excinfo.value.detail


def test_targeted_repair_fails_when_repair_budget_is_gone():
    # No repair reservation: a first gate failure cannot be repaired and fails with
    # budget_exhausted rather than re-invoking the role.
    ledger = _ledger(repair_calls_per_role=0)
    attempts = 0

    def produce(feedback):
        nonlocal attempts
        attempts += 1
        return "bad"

    def validate(output):
        raise ReasoningGateError(GATE_SCHEMA_INVALID, ["bad"])

    with pytest.raises(CausalAnalysisError) as excinfo:
        targeted_repair(
            role="builder",
            substep="builder:generate",
            ledger=ledger,
            produce=produce,
            validate=validate,
        )
    assert attempts == 1
    assert excinfo.value.code == FAILURE_BUDGET_EXHAUSTED


def test_gate_error_raised_during_production_is_repaired():
    # A role that cannot produce valid output at all (raises a gate error while
    # producing, e.g. a falsifier that cannot challenge) still travels the single
    # repair path.
    ledger = _ledger()
    attempts = 0

    def produce(feedback):
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise ReasoningGateError(GATE_SCHEMA_INVALID, ["could not produce"])
        return "recovered"

    result = targeted_repair(
        role="falsifier",
        substep="challenge:initial:1",
        ledger=ledger,
        produce=produce,
        validate=lambda output: None,
    )
    assert result == "recovered"
    assert attempts == 2
