from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Final, Protocol

from pydantic import BaseModel, ConfigDict, Field

logger = logging.getLogger("postmortem.ranking")

# Versioned prompt/role identity for the advisory ranker (ADR 0025 / 0037). Bump
# when the ranking contract or its rationale dimensions change so runs stay
# comparable. The ranker is a separate Reasoning Role from the builder, falsifier,
# and support verifier (PRD #26 user stories 17-25, 74): its own contract and
# version even when backed by the same configured model. The MVP default is the
# deterministic ranker below — explainable and offline — behind the swappable
# ``AdvisoryRanker`` boundary.
ADVISORY_RANKER_VERSION: Final[str] = "deterministic-advisory-ranker-1"

# The bounded final advisory list (ADR 0036 / 0037, Hypothesis Budget): at most
# five initial plus two proposed hypotheses, so the advisory ranking orders at
# most this many candidates.
MAX_RANKED_HYPOTHESES: Final[int] = 7

# The five assessment dimensions every candidate's ranking rationale must cover
# (PRD user story 19, ADR 0037). Ordering is explained across these, never as a
# probability or percentage (PRD user story 18).
RANKING_DIMENSIONS: Final[tuple[str, ...]] = (
    "support_strength",
    "counterevidence_severity",
    "explanatory_coverage",
    "evidence_gaps",
    "assumption_dependence",
)


@dataclass(frozen=True)
class RankingCandidate:
    """The persisted, structured handoff the ranker receives per hypothesis.

    A Role Handoff (ADR 0037): the ranker consumes persisted, post-challenge facts
    — never another role's hidden chain-of-thought (PRD user story 75). ORM-free
    so the ranker boundary stays swappable and unit-testable (ADR 0009).

    ``supported_citation_count`` counts only citations that passed the Incremental
    Citation Check (verified) AND back the claim, so a broken or semantically
    unsupported citation cannot be counted as positive ranking support (PRD user
    story 23, issue #31 AC). ``support_status`` is the provisional semantic-support
    judgment produced before ranking; ``builder_rank`` preserves the original
    generation order for stable tie-breaking and audit (PRD user story 20).
    """

    hypothesis_id: str
    title: str
    origin: str
    builder_rank: int
    support_status: str
    supported_citation_count: int
    challenge_severity: str | None
    counterclaim_count: int
    evidence_gap_count: int
    assumption: bool


# --- Strict structured output contract (ADR 0028) ---------------------------
#
# A ranker returns this shape and nothing else. The ordinal ranking is the ORDER
# of ``rankings`` (position 1 = most plausible). There is deliberately no numeric
# probability field anywhere in the contract: plausibility is ordinal and
# evidence-explained, never a percentage (PRD user story 18). The stage applies a
# Runtime Reasoning Gate over this output (every candidate exactly once) so a
# misbehaving ranker fails the stage rather than producing a partial ranking.


class StrictRankingModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class RankingRationale(StrictRankingModel):
    """Per-candidate, per-dimension explanation of where a hypothesis ranks.

    Each dimension is a short evidence-explained sentence (PRD user story 19). All
    five are required and non-empty so a schema-valid ranking always shows its
    work across every dimension — the Runtime Reasoning Gate does not need a
    separate "dimensioned rationale" check because the schema enforces it.
    """

    support_strength: str = Field(min_length=1)
    counterevidence_severity: str = Field(min_length=1)
    explanatory_coverage: str = Field(min_length=1)
    evidence_gaps: str = Field(min_length=1)
    assumption_dependence: str = Field(min_length=1)
    summary: str = Field(min_length=1)


class RankedCandidate(StrictRankingModel):
    """One candidate's place in the advisory ranking, referenced by id."""

    hypothesis_id: str = Field(min_length=1)
    rationale: RankingRationale


class AdvisoryRankingOutput(StrictRankingModel):
    """The post-challenge Advisory Hypothesis Ranking for a run (ADR 0037).

    ``rankings`` is ordered most-plausible-first; its position is the candidate's
    ordinal advisory rank. The list covers every candidate exactly once — the
    stage enforces that against the persisted hypotheses.
    """

    rankings: list[RankedCandidate] = Field(default_factory=list)


class AdvisoryRanker(Protocol):
    """Swappable advisory-ranker boundary (ADR 0009 / 0037).

    A separate Reasoning Role (PRD user story 74): the MVP default is the
    deterministic ranker below; an LLM-backed ranker can replace it behind this
    same surface. ``version`` feeds Experiment Metadata so a ranked run records
    which role ordered it.
    """

    @property
    def version(self) -> str: ...

    def rank(self, candidates: list[RankingCandidate]) -> AdvisoryRankingOutput: ...


# Support tiers as ordinal plausibility weight. A provisionally UNSUPPORTED claim
# (no verified citation backs it, or the evidence does not support it) contributes
# negative weight, so broken/unsupported evidence can never lift a hypothesis above
# a genuinely supported one (PRD user story 23, issue #31 AC).
_SUPPORT_WEIGHT: Final[dict[str, float]] = {
    "supported": 3.0,
    "partial": 1.0,
    "unsupported": -2.0,
    "unevaluated": 0.0,
}

# Counterevidence severity penalty (ADR 0034 severity → plausibility cost). A
# critical challenge sharply reduces plausibility but does not force last place,
# so a critically challenged hypothesis may still lead — labeled "Leading but
# critically challenged" wherever it is rendered (PRD user stories 21-22).
_SEVERITY_PENALTY: Final[dict[str, float]] = {
    "critical": -2.0,
    "material": -0.5,
    "minor": 0.0,
}

_CITATION_WEIGHT: Final[float] = 0.5
_CITATION_CAP: Final[int] = 4
_COUNTERCLAIM_PENALTY: Final[float] = 0.25
_GAP_PENALTY: Final[float] = 0.1
_ASSUMPTION_PENALTY: Final[float] = 1.0


class DeterministicAdvisoryRanker:
    """Orders candidates by an explainable, evidence-derived plausibility score.

    The MVP advisory ranker (ADR 0037). It needs no model and makes no LLM call,
    so the canonical demo and evaluations rank deterministically and offline while
    the boundary stays swappable for a later LLM-backed ranker. The score is built
    only from post-challenge facts already verified by earlier substeps — support
    tier, count of *verified* supporting citations, challenge severity, counter-
    claim count, open evidence gaps, and assumption dependence — the same five
    dimensions the rationale explains (PRD user story 19). Ties keep the original
    builder order, so an unchanged ranking is the honest signal that falsification
    did not move a candidate (PRD user story 20). Plausibility is expressed
    ordinally; the ranker never emits a probability (PRD user story 18).
    """

    version: Final[str] = ADVISORY_RANKER_VERSION

    def rank(self, candidates: list[RankingCandidate]) -> AdvisoryRankingOutput:
        # Sort by descending plausibility, breaking ties by ascending builder rank
        # so equal candidates keep their generation order (stable, auditable).
        ordered = sorted(
            candidates,
            key=lambda c: (-self._score(c), c.builder_rank),
        )
        return AdvisoryRankingOutput(
            rankings=[
                RankedCandidate(
                    hypothesis_id=candidate.hypothesis_id,
                    rationale=self._rationale(candidate),
                )
                for candidate in ordered
            ]
        )

    def _score(self, candidate: RankingCandidate) -> float:
        score = _SUPPORT_WEIGHT.get(candidate.support_status, 0.0)
        # Only verified supporting citations count toward support strength; broken
        # or unsupported evidence is excluded before it reaches the ranker.
        score += _CITATION_WEIGHT * min(candidate.supported_citation_count, _CITATION_CAP)
        if candidate.challenge_severity is not None:
            score += _SEVERITY_PENALTY.get(candidate.challenge_severity, 0.0)
        score -= _COUNTERCLAIM_PENALTY * candidate.counterclaim_count
        score -= _GAP_PENALTY * candidate.evidence_gap_count
        if candidate.assumption:
            score -= _ASSUMPTION_PENALTY
        return score

    def _rationale(self, candidate: RankingCandidate) -> RankingRationale:
        return RankingRationale(
            support_strength=self._support_strength(candidate),
            counterevidence_severity=self._counterevidence(candidate),
            explanatory_coverage=self._coverage(candidate),
            evidence_gaps=self._gaps(candidate),
            assumption_dependence=self._assumption(candidate),
            summary=self._summary(candidate),
        )

    def _support_strength(self, candidate: RankingCandidate) -> str:
        cites = candidate.supported_citation_count
        noun = "verified citation" if cites == 1 else "verified citations"
        if candidate.support_status == "supported":
            return f"Supported by {cites} {noun} that back the claim."
        if candidate.support_status == "partial":
            return (
                f"Partially supported: {cites} {noun} are consistent with the claim "
                "but do not fully establish it."
            )
        if candidate.support_status == "unsupported":
            return "Unsupported: no verified citation establishes this claim."
        return f"Support not yet judged; {cites} {noun} cited."

    def _counterevidence(self, candidate: RankingCandidate) -> str:
        counters = candidate.counterclaim_count
        noun = "counterclaim" if counters == 1 else "counterclaims"
        severity = candidate.challenge_severity
        if severity == "critical":
            return (
                f"Critically challenged ({counters} {noun}): if the challenge holds, "
                "this cannot serve as the failure mechanism."
            )
        if severity == "material":
            return (
                f"Materially challenged ({counters} {noun}): plausibility is reduced "
                "or the causal role is limited."
            )
        if severity == "minor":
            return f"Only minor qualifications raised ({counters} {noun})."
        return "No persisted challenge weighed against this hypothesis."

    def _coverage(self, candidate: RankingCandidate) -> str:
        if candidate.support_status in ("supported", "partial") and (
            candidate.supported_citation_count > 0
        ):
            return (
                "Explains the incident with citations spanning the collected evidence."
            )
        return (
            "Limited explanatory coverage: little or no verified evidence ties it to "
            "the incident."
        )

    def _gaps(self, candidate: RankingCandidate) -> str:
        gaps = candidate.evidence_gap_count
        if gaps == 0:
            return "No open evidence gaps were recorded against this hypothesis."
        noun = "gap" if gaps == 1 else "gaps"
        return f"{gaps} open evidence {noun} remain before this can be confirmed."

    def _assumption(self, candidate: RankingCandidate) -> str:
        if candidate.assumption:
            return "Depends on an uncited assumption rather than cited evidence."
        return "Grounded in cited evidence rather than an unsupported assumption."

    def _summary(self, candidate: RankingCandidate) -> str:
        origin = "proposed alternative" if candidate.origin == "proposed" else "initial hypothesis"
        if candidate.support_status == "unsupported":
            return (
                f"Ranked low: an {origin} resting on unsupported claims, retained for "
                "review but not part of the evidence-backed narrative."
            )
        if candidate.challenge_severity == "critical":
            return (
                f"An {origin} with notable support but an unresolved critical challenge; "
                "plausibility is qualified accordingly."
            )
        return (
            f"An {origin} ranked on its verified support weighed against the "
            "challenge raised."
        )
