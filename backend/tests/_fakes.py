from __future__ import annotations

from typing import Callable

from postmortem.drafting import PostmortemComposerContext, PostmortemDraft
from postmortem.evaluation import JudgeInput, JudgeResult
from postmortem.falsification import (
    FalsificationCounterclaim,
    HypothesisChallengeOutput,
    HypothesisToChallenge,
)
from postmortem.incident_facts import FactsImpactClaim, IncidentFactsOutput
from postmortem.ranking import (
    AdvisoryRankingOutput,
    DeterministicAdvisoryRanker,
    RankedCandidate,
    RankingCandidate,
    RankingRationale,
)
from postmortem.verification import (
    ClaimSupportJudgment,
    ClaimSupportStatus,
    ClaimToVerify,
)


class FakePostmortemJudge:
    """Deterministic LLM-as-judge for tests (ADR 0009 / 0010 swappability).

    Proves the judge boundary is real without a live model. Records the inputs it
    was handed so a test can assert what the evaluation runner fed it, and returns
    fixed rubric scores by default.
    """

    version = "fake-judge-0"

    def __init__(
        self,
        *,
        scores: dict[str, int] | None = None,
        rationale: str = "Fake judge rationale.",
    ) -> None:
        self._scores = scores or {
            "timeline_accuracy": 5,
            "root_cause_quality": 4,
            "evidence_grounding": 5,
            "uncertainty_honesty": 5,
        }
        self._rationale = rationale
        self.calls: list[JudgeInput] = []

    def judge(self, payload: JudgeInput) -> JudgeResult:
        self.calls.append(payload)
        overall = round(sum(self._scores.values()) / len(self._scores), 2)
        return JudgeResult(
            scores=dict(self._scores),
            overall=overall,
            rationale=self._rationale,
            version=self.version,
        )


class FakeIncidentFactExtractor:
    """Deterministic incident-facts extractor for tests (ADR 0009 / 0033).

    Proves the stage-2 extractor boundary is real without a live model and,
    crucially, lets RCA-focused pipeline tests run stage 2 without consuming the
    LLM responses they seeded for the RCA stage. By default it extracts no impact
    claims; pass ``impact_claims`` (a list of ``(description, [(source_name?,
    artifact_id, line_start, line_end)])``)-shaped fixtures, or pre-built
    ``FactsImpactClaim`` objects, to drive run-level impact.
    """

    version = "fake-incident-facts-0"

    def __init__(self, impact_claims: list[FactsImpactClaim] | None = None) -> None:
        self._impact_claims = impact_claims or []
        self.calls = 0

    def extract(self, *, artifacts, timeline_events) -> IncidentFactsOutput:
        self.calls += 1
        return IncidentFactsOutput(impact_claims=list(self._impact_claims))


class FakeFalsifier:
    """Deterministic falsifier for tests (ADR 0009 / 0034 swappability).

    Proves the falsifier boundary is real without a live model and lets
    hypothesis-producing pipeline tests run stage 3's mandatory challenge substep
    without seeding LLM responses for it. By default it returns a trivial
    ``material`` challenge with no counterclaims. Pass ``challenge`` to drive a
    per-hypothesis ``HypothesisChallengeOutput`` (e.g. keyed off
    ``hypothesis.title``), or ``raise_for`` (a set of titles) to simulate a
    falsifier that cannot challenge a hypothesis — the stage must then fail.
    """

    version = "fake-falsifier-0"

    def __init__(
        self,
        challenge: Callable[[HypothesisToChallenge], HypothesisChallengeOutput] | None = None,
        *,
        severity: str = "material",
        counterclaims: list[FalsificationCounterclaim] | None = None,
        evidence_gaps: list[str] | None = None,
        falsification_tests: list[str] | None = None,
        raise_for: set[str] | None = None,
    ) -> None:
        self._challenge = challenge
        self._severity = severity
        self._counterclaims = counterclaims or []
        self._evidence_gaps = evidence_gaps or []
        self._falsification_tests = falsification_tests or []
        self._raise_for = raise_for or set()
        self.calls: list[HypothesisToChallenge] = []

    def challenge(
        self,
        *,
        hypothesis: HypothesisToChallenge,
        artifacts,
        timeline_events,
        allow_proposals: bool = True,
    ) -> HypothesisChallengeOutput:
        self.calls.append(hypothesis)
        self.last_allow_proposals = allow_proposals
        if hypothesis.title in self._raise_for:
            raise ValueError(f"fake falsifier cannot challenge {hypothesis.title!r}")
        if self._challenge is not None:
            return self._challenge(hypothesis)
        return HypothesisChallengeOutput(
            challenged_claim=f"Challenge of: {hypothesis.title}",
            severity=self._severity,
            counterclaims=list(self._counterclaims),
            evidence_gaps=list(self._evidence_gaps),
            falsification_tests=list(self._falsification_tests),
        )


class FakeClaimSupportVerifier:
    """Deterministic claim-support verifier for tests (ADR 0009 swappability).

    Proves the semantic-verifier boundary is real without a live model. By
    default every claim is judged SUPPORTED, which lets pipeline tests that do
    not care about support classification run stage 6 without seeding LLM
    responses. Pass ``judge`` to drive SUPPORTED / PARTIAL / UNSUPPORTED per
    claim (e.g. keyed off ``claim.claim_text``).
    """

    version = "fake-claim-support-0"

    def __init__(
        self,
        judge: Callable[[ClaimToVerify], ClaimSupportJudgment] | None = None,
        *,
        status: ClaimSupportStatus = ClaimSupportStatus.SUPPORTED,
        rationale: str = "The cited evidence supports the claim.",
    ) -> None:
        self._judge = judge
        self._status = status
        self._rationale = rationale
        self.calls: list[ClaimToVerify] = []

    def verify(self, claim: ClaimToVerify) -> ClaimSupportJudgment:
        self.calls.append(claim)
        if self._judge is not None:
            return self._judge(claim)
        return ClaimSupportJudgment(status=self._status, rationale=self._rationale)


def _trivial_rationale(candidate: RankingCandidate) -> RankingRationale:
    return RankingRationale(
        support_strength=f"support={candidate.support_status}",
        counterevidence_severity=f"severity={candidate.challenge_severity}",
        explanatory_coverage="coverage",
        evidence_gaps=f"gaps={candidate.evidence_gap_count}",
        assumption_dependence=f"assumption={candidate.assumption}",
        summary=f"Ranked {candidate.title}.",
    )


class FakeAdvisoryRanker:
    """Deterministic advisory ranker for tests (ADR 0009 / 0037 swappability).

    Proves the ranker boundary is real without a live model and lets stage-3 tests
    drive ranking behavior precisely. By default it delegates ordering to the
    production ``DeterministicAdvisoryRanker`` (so a pipeline test gets a sensible
    ranking for free), but ``order`` can fix the output order by hypothesis title,
    and ``drop`` can omit a candidate by title to exercise the missing-candidate
    Runtime Reasoning Gate.
    """

    version = "fake-advisory-ranker-0"

    def __init__(
        self,
        *,
        order: list[str] | None = None,
        drop: set[str] | None = None,
        duplicate: str | None = None,
    ) -> None:
        self._order = order
        self._drop = drop or set()
        self._duplicate = duplicate
        self.calls: list[list[RankingCandidate]] = []

    def rank(self, candidates: list[RankingCandidate]) -> AdvisoryRankingOutput:
        self.calls.append(list(candidates))
        kept = [c for c in candidates if c.title not in self._drop]
        if self._order is not None:
            by_title = {c.title: c for c in kept}
            ordered = [by_title[title] for title in self._order if title in by_title]
        else:
            # Reuse the production ordering so the fake is realistic by default.
            ranked = DeterministicAdvisoryRanker().rank(kept)
            by_id = {c.hypothesis_id: c for c in kept}
            ordered = [by_id[entry.hypothesis_id] for entry in ranked.rankings]
        rankings = [
            RankedCandidate(hypothesis_id=c.hypothesis_id, rationale=_trivial_rationale(c))
            for c in ordered
        ]
        if self._duplicate is not None:
            for candidate in ordered:
                if candidate.title == self._duplicate:
                    rankings.append(
                        RankedCandidate(
                            hypothesis_id=candidate.hypothesis_id,
                            rationale=_trivial_rationale(candidate),
                        )
                    )
                    break
        return AdvisoryRankingOutput(rankings=rankings)


class FakePostmortemComposer:
    """Deterministic Postmortem composer for tests (ADR 0009 swappability).

    Proves the drafting-stage template boundary is real without coupling tests to
    the production composition. Records the contexts it was handed so a test can
    assert what structured outputs drafting fed it.
    """

    version = "fake-template-0"

    def __init__(
        self,
        *,
        summary: str = "Fake composed summary.",
        lessons: tuple[str, ...] = ("Fake lesson.",),
    ) -> None:
        self._summary = summary
        self._lessons = lessons
        self.calls: list[PostmortemComposerContext] = []

    def compose(self, context: PostmortemComposerContext) -> PostmortemDraft:
        self.calls.append(context)
        return PostmortemDraft(summary=self._summary, lessons_learned=self._lessons)
