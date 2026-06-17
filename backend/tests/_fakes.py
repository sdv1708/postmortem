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
