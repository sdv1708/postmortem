"""Advisory Hypothesis Ranking tests (ADR 0037, PRD #26 user stories 17-25).

These exercise the final substep of stage 3 through the deep stage with
deterministic fake Reasoning Roles: after every initial and proposed hypothesis
is challenged, the run produces one ordinal advisory ranking that reorders
candidates by plausibility, keeps the builder order for audit, never counts
unsupported evidence as positive support, labels a critically challenged leader,
and fails the stage when a candidate is missing from the ranking.
"""

from __future__ import annotations

import json

from postmortem.falsification import HypothesisChallengeOutput
from postmortem.llm import FakeLLMClient
from postmortem.models import Hypothesis
from postmortem.schemas import AnalysisRunCreate, ArtifactCreate, IncidentCreate
from postmortem.services import AnalysisService, ArtifactService, IncidentService
from postmortem.services.analysis import hypothesis_read
from postmortem.verification import ClaimSupportJudgment, ClaimSupportStatus, ClaimToVerify

from tests._fakes import (
    FakeAdvisoryRanker,
    FakeClaimSupportVerifier,
    FakeFalsifier,
    FakeIncidentFactExtractor,
)


BODY = (
    "2026-05-09T14:28:31Z deploy v184 rolled out\n"
    "2026-05-09T14:31:10Z db connection pool exhausted\n"
    "2026-05-09T14:32:02Z api 500 rate climbing\n"
    "2026-05-09T14:33:40Z cache node evicted under memory pressure"
)


def _incident(session):
    return IncidentService(session).create(IncidentCreate(title="Ambiguous outage"))


def _add(session, incident_id):
    return ArtifactService(session).create(
        incident_id,
        ArtifactCreate(source_type="logs", source_name="api.log", body=BODY),
    )


def _two_hypotheses(artifact_id: str) -> str:
    return json.dumps(
        {
            "hypotheses": [
                {
                    "title": "Alpha",
                    "summary": "Cause alpha.",
                    "supporting_evidence": [
                        {"artifact_id": artifact_id, "line_start": 1, "line_end": 2}
                    ],
                },
                {
                    "title": "Beta",
                    "summary": "Cause beta.",
                    "supporting_evidence": [
                        {"artifact_id": artifact_id, "line_start": 3, "line_end": 4}
                    ],
                },
            ]
        }
    )


def _one_hypothesis(artifact_id: str) -> str:
    return json.dumps(
        {
            "hypotheses": [
                {
                    "title": "Solo",
                    "summary": "The single suspected cause.",
                    "supporting_evidence": [
                        {"artifact_id": artifact_id, "line_start": 1, "line_end": 2}
                    ],
                }
            ]
        }
    )


def _hypotheses(session, run_id):
    return list(
        session.query(Hypothesis).filter(Hypothesis.run_id == run_id).order_by(Hypothesis.rank)
    )


def _run(
    session,
    incident_id,
    builder_json,
    *,
    falsifier,
    support_judge=None,
    ranker=None,
    builder_responses=1,
):
    return AnalysisService(
        session,
        llm_client=FakeLLMClient([builder_json] * builder_responses),
        claim_support_verifier=FakeClaimSupportVerifier(support_judge),
        incident_fact_extractor=FakeIncidentFactExtractor(),
        falsifier=falsifier,
        advisory_ranker=ranker,
    ).start_run(incident_id, AnalysisRunCreate())


def test_advisory_ranking_reorders_by_plausibility(fresh_session):
    incident = _incident(fresh_session)
    artifact = _add(fresh_session, incident.id)
    fresh_session.commit()

    # Beta is fully supported, Alpha only partially. The builder generated Alpha
    # first, but the post-challenge advisory ranking must promote Beta.
    def support(claim: ClaimToVerify) -> ClaimSupportJudgment:
        if "Cause beta" in claim.claim_text:
            return ClaimSupportJudgment(ClaimSupportStatus.SUPPORTED, "Fully supported.")
        return ClaimSupportJudgment(ClaimSupportStatus.PARTIAL, "Only partially supported.")

    run = _run(
        fresh_session,
        incident.id,
        _two_hypotheses(artifact.id),
        falsifier=FakeFalsifier(),
        support_judge=support,
    )
    fresh_session.commit()

    assert run.status == "succeeded"
    by_title = {h.title: h for h in _hypotheses(fresh_session, run.id)}
    # Builder order is retained for audit; the advisory ranking reorders.
    assert by_title["Alpha"].rank == 1 and by_title["Beta"].rank == 2
    assert by_title["Beta"].advisory_rank == 1
    assert by_title["Alpha"].advisory_rank == 2
    # Every candidate carries an explainable, dimensioned rationale.
    assert by_title["Beta"].ranking_rationale is not None
    assert by_title["Beta"].ranking_rationale["support_strength"]


def test_advisory_ranking_preserves_builder_order_when_equal(fresh_session):
    incident = _incident(fresh_session)
    artifact = _add(fresh_session, incident.id)
    fresh_session.commit()

    # Both supported, both materially challenged: nothing distinguishes them, so
    # the advisory order must equal the builder order (PRD user story 20).
    run = _run(
        fresh_session,
        incident.id,
        _two_hypotheses(artifact.id),
        falsifier=FakeFalsifier(),
    )
    fresh_session.commit()

    assert run.status == "succeeded"
    by_title = {h.title: h for h in _hypotheses(fresh_session, run.id)}
    assert by_title["Alpha"].advisory_rank == 1
    assert by_title["Beta"].advisory_rank == 2


def test_unsupported_hypothesis_ranks_last(fresh_session):
    incident = _incident(fresh_session)
    artifact = _add(fresh_session, incident.id)
    fresh_session.commit()

    # Beta's cited evidence does not support it semantically; even though it has a
    # verified citation, an unsupported claim cannot be counted as positive
    # ranking support and must sink below the supported Alpha (issue #31 AC #5).
    def support(claim: ClaimToVerify) -> ClaimSupportJudgment:
        if "Cause beta" in claim.claim_text:
            return ClaimSupportJudgment(ClaimSupportStatus.UNSUPPORTED, "Not supported.")
        return ClaimSupportJudgment(ClaimSupportStatus.SUPPORTED, "Supported.")

    run = _run(
        fresh_session,
        incident.id,
        _two_hypotheses(artifact.id),
        falsifier=FakeFalsifier(),
        support_judge=support,
    )
    fresh_session.commit()

    assert run.status == "succeeded"
    by_title = {h.title: h for h in _hypotheses(fresh_session, run.id)}
    assert by_title["Alpha"].advisory_rank == 1
    assert by_title["Beta"].advisory_rank == 2
    assert by_title["Beta"].support_status == "unsupported"


def test_leading_critically_challenged_hypothesis_is_labeled(fresh_session):
    incident = _incident(fresh_session)
    artifact = _add(fresh_session, incident.id)
    fresh_session.commit()

    # The single supported hypothesis leads the ranking, but its challenge is
    # critical, so the derived "Leading but critically challenged" label must show
    # (PRD #26 user stories 21-22).
    def challenge(hypothesis):
        return HypothesisChallengeOutput(
            challenged_claim=f"Challenge of {hypothesis.title}",
            severity="critical",
        )

    run = _run(
        fresh_session,
        incident.id,
        _one_hypothesis(artifact.id),
        falsifier=FakeFalsifier(challenge),
    )
    fresh_session.commit()

    assert run.status == "succeeded"
    [solo] = _hypotheses(fresh_session, run.id)
    assert solo.advisory_rank == 1
    payload = hypothesis_read(solo)
    assert payload["leading_but_critically_challenged"] is True


def test_non_leading_critical_challenge_is_not_labeled_leading(fresh_session):
    incident = _incident(fresh_session)
    artifact = _add(fresh_session, incident.id)
    fresh_session.commit()

    # Alpha is supported with a minor challenge; Beta is supported but critically
    # challenged. Alpha leads, so only the leader question matters: Beta is
    # critically challenged but NOT the leader, so it is not labeled "leading".
    def challenge(hypothesis):
        severity = "critical" if hypothesis.title == "Beta" else "minor"
        return HypothesisChallengeOutput(
            challenged_claim=f"Challenge of {hypothesis.title}", severity=severity
        )

    run = _run(
        fresh_session,
        incident.id,
        _two_hypotheses(artifact.id),
        falsifier=FakeFalsifier(challenge),
    )
    fresh_session.commit()

    by_title = {h.title: h for h in _hypotheses(fresh_session, run.id)}
    assert by_title["Alpha"].advisory_rank == 1
    assert hypothesis_read(by_title["Alpha"])["leading_but_critically_challenged"] is False
    assert hypothesis_read(by_title["Beta"])["leading_but_critically_challenged"] is False


def test_support_judgment_is_canonical_and_audit_cannot_diverge(fresh_session):
    incident = _incident(fresh_session)
    artifact = _add(fresh_session, incident.id)
    fresh_session.commit()

    # A non-deterministic verifier that would judge "supported" during the stage-3
    # ranking substep but "unsupported" if called again during the stage-6 audit.
    # The audit must reuse the single ranking-time judgment, so the hypothesis can
    # never end up shown as unsupported while carrying a rank/rationale computed as
    # supported (the adversarial-review finding for issue #31 AC #5).
    calls = {"n": 0}

    def support(claim: ClaimToVerify) -> ClaimSupportJudgment:
        calls["n"] += 1
        if calls["n"] == 1:
            return ClaimSupportJudgment(ClaimSupportStatus.SUPPORTED, "Supported at ranking time.")
        return ClaimSupportJudgment(ClaimSupportStatus.UNSUPPORTED, "Diverged later.")

    run = _run(
        fresh_session,
        incident.id,
        _one_hypothesis(artifact.id),
        falsifier=FakeFalsifier(),
        support_judge=support,
    )
    fresh_session.commit()

    assert run.status == "succeeded"
    [solo] = _hypotheses(fresh_session, run.id)
    # Judged exactly once; the audit reused that judgment instead of re-invoking
    # the verifier (which would have flipped it to unsupported).
    assert calls["n"] == 1
    assert solo.support_status == "supported"
    assert solo.advisory_rank == 1
    # The persisted support status is consistent with the rationale the ranking
    # was built on — no stale "supported" rationale over an "unsupported" status.
    assert "Supported" in solo.ranking_rationale["support_strength"]


def test_missing_candidate_fails_the_stage(fresh_session):
    incident = _incident(fresh_session)
    artifact = _add(fresh_session, incident.id)
    fresh_session.commit()

    # A misbehaving ranker that omits a candidate fails the Runtime Reasoning Gate
    # rather than shipping a partial ranking (issue #31 AC #6). Seed the builder
    # twice so the single retry reproduces the same deterministic gate failure.
    run = _run(
        fresh_session,
        incident.id,
        _two_hypotheses(artifact.id),
        falsifier=FakeFalsifier(),
        ranker=FakeAdvisoryRanker(drop={"Beta"}),
        builder_responses=2,
    )
    fresh_session.commit()

    assert run.status == "failed"
    assert "cover every hypothesis exactly once" in (run.error or "")


def test_duplicate_candidate_fails_the_stage(fresh_session):
    incident = _incident(fresh_session)
    artifact = _add(fresh_session, incident.id)
    fresh_session.commit()

    run = _run(
        fresh_session,
        incident.id,
        _two_hypotheses(artifact.id),
        falsifier=FakeFalsifier(),
        ranker=FakeAdvisoryRanker(duplicate="Alpha"),
        builder_responses=2,
    )
    fresh_session.commit()

    assert run.status == "failed"
    assert "cover every hypothesis exactly once" in (run.error or "")
