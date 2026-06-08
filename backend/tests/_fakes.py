from __future__ import annotations

from typing import Callable

from postmortem.drafting import PostmortemComposerContext, PostmortemDraft
from postmortem.verification import (
    ClaimSupportJudgment,
    ClaimSupportStatus,
    ClaimToVerify,
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
