"""Unit tests for the deterministic Advisory Ranker (ADR 0037, PRD #26).

These exercise the ranker as a pure Reasoning Role over ORM-free handoffs: it
orders candidates by an explainable, evidence-derived plausibility score, keeps
builder order on ties, never emits a probability, and explains every candidate
across all five assessment dimensions.
"""

from __future__ import annotations

from postmortem.ranking import (
    RANKING_DIMENSIONS,
    AdvisoryRankingOutput,
    DeterministicAdvisoryRanker,
    RankingCandidate,
)


def _candidate(
    hypothesis_id: str,
    *,
    builder_rank: int,
    support_status: str = "supported",
    supported_citation_count: int = 2,
    challenge_severity: str | None = "material",
    counterclaim_count: int = 1,
    evidence_gap_count: int = 1,
    assumption: bool = False,
    title: str | None = None,
) -> RankingCandidate:
    return RankingCandidate(
        hypothesis_id=hypothesis_id,
        title=title or f"Hypothesis {hypothesis_id}",
        origin="initial",
        builder_rank=builder_rank,
        support_status=support_status,
        supported_citation_count=supported_citation_count,
        challenge_severity=challenge_severity,
        counterclaim_count=counterclaim_count,
        evidence_gap_count=evidence_gap_count,
        assumption=assumption,
    )


def _order(output: AdvisoryRankingOutput) -> list[str]:
    return [entry.hypothesis_id for entry in output.rankings]


def test_supported_outranks_partial_outranks_unsupported():
    ranker = DeterministicAdvisoryRanker()
    candidates = [
        _candidate("partial", builder_rank=1, support_status="partial"),
        _candidate("unsupported", builder_rank=2, support_status="unsupported"),
        _candidate("supported", builder_rank=3, support_status="supported"),
    ]
    assert _order(ranker.rank(candidates)) == ["supported", "partial", "unsupported"]


def test_ties_preserve_builder_order():
    ranker = DeterministicAdvisoryRanker()
    # Three identical candidates: only builder_rank differs, so the ranking must
    # equal the generation order (PRD user story 20 — an unchanged ranking is the
    # honest signal that falsification did not move a candidate).
    candidates = [
        _candidate("a", builder_rank=1),
        _candidate("b", builder_rank=2),
        _candidate("c", builder_rank=3),
    ]
    assert _order(ranker.rank(candidates)) == ["a", "b", "c"]


def test_unsupported_evidence_is_not_counted_as_support():
    ranker = DeterministicAdvisoryRanker()
    # The unsupported candidate carries many citations, the partial one only a
    # few; support tier must still dominate so broken/unsupported evidence cannot
    # be counted as positive ranking support (issue #31 AC, PRD user story 23).
    candidates = [
        _candidate(
            "unsupported",
            builder_rank=1,
            support_status="unsupported",
            supported_citation_count=4,
        ),
        _candidate(
            "partial",
            builder_rank=2,
            support_status="partial",
            supported_citation_count=1,
        ),
    ]
    assert _order(ranker.rank(candidates)) == ["partial", "unsupported"]


def test_critical_challenge_reduces_but_does_not_force_last():
    ranker = DeterministicAdvisoryRanker()
    # A critically challenged but supported candidate may still outrank a partial
    # one: critical reduces plausibility without forcing last place (PRD #26
    # user stories 21-22).
    candidates = [
        _candidate(
            "critical_supported",
            builder_rank=1,
            support_status="supported",
            challenge_severity="critical",
        ),
        _candidate(
            "partial",
            builder_rank=2,
            support_status="partial",
            challenge_severity="minor",
        ),
    ]
    assert _order(ranker.rank(candidates)) == ["critical_supported", "partial"]


def test_rationale_covers_every_dimension_and_carries_no_probability():
    ranker = DeterministicAdvisoryRanker()
    output = ranker.rank([_candidate("a", builder_rank=1)])
    rationale = output.rankings[0].rationale
    payload = rationale.model_dump()
    for dimension in RANKING_DIMENSIONS:
        assert payload[dimension].strip(), f"missing rationale dimension {dimension}"
    assert payload["summary"].strip()
    # Plausibility is ordinal, never a percentage (PRD user story 18): no field
    # should read like a probability.
    assert "%" not in " ".join(str(v) for v in payload.values())


def test_empty_candidate_list_produces_empty_ranking():
    assert DeterministicAdvisoryRanker().rank([]).rankings == []
