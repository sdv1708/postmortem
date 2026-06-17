"""Bounded alternative-expansion round tests (ADR 0036, PRD #26 / #30).

These exercise the second pass of the Falsification Round through the deep stage
with deterministic fake Reasoning Roles: the falsifier may introduce at most two
Proposed RCA Hypotheses while challenging the initial ones, each proposed
alternative travels the full citation/challenge/review path exactly once, and the
round never recurses. Over-budget or recursive proposals fail the stage through
the bounded repair/failure contract available at this point (one retry, ADR 0029).
"""

from __future__ import annotations

import json

from postmortem.falsification import HypothesisChallengeOutput
from postmortem.llm import FakeLLMClient
from postmortem.models import Hypothesis
from postmortem.rca import RcaEvidenceRef, RcaHypothesis
from postmortem.schemas import AnalysisRunCreate, ArtifactCreate, IncidentCreate
from postmortem.services import AnalysisService, ArtifactService, IncidentService

from tests._fakes import (
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


def _add(session, incident_id, body=BODY, source_name="api.log"):
    return ArtifactService(session).create(
        incident_id,
        ArtifactCreate(source_type="logs", source_name=source_name, body=body),
    )


def _one_hypothesis(artifact_id: str) -> str:
    return json.dumps(
        {
            "hypotheses": [
                {
                    "title": "Deploy v184 regressed connection handling",
                    "summary": "The v184 deploy preceded pool exhaustion and 500s.",
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


def _proposal(artifact_id: str, title: str) -> RcaHypothesis:
    return RcaHypothesis(
        title=title,
        summary=f"Alternative: {title}.",
        supporting_evidence=[RcaEvidenceRef(artifact_id=artifact_id, line_start=4, line_end=4)],
    )


def _run(session, incident_id, artifact_id, falsifier, *, builder_responses=1):
    # Seed the builder response once per expected stage attempt. The stage retries
    # once on failure (ADR 0029); a gate-failure test seeds twice so the retry
    # reproduces the same deterministic gate failure instead of exhausting the
    # fake client (which would mask the gate error on ``run.error``).
    return AnalysisService(
        session,
        llm_client=FakeLLMClient([_one_hypothesis(artifact_id)] * builder_responses),
        claim_support_verifier=FakeClaimSupportVerifier(),
        incident_fact_extractor=FakeIncidentFactExtractor(),
        falsifier=falsifier,
    ).start_run(incident_id, AnalysisRunCreate())


def test_proposed_alternative_is_persisted_and_fully_reviewed(fresh_session):
    incident = _incident(fresh_session)
    artifact = _add(fresh_session, incident.id)
    fresh_session.commit()

    proposed_title = "Cache eviction shifted read load onto the database"

    def challenge(hypothesis):
        proposals = []
        # Propose a missed alternative only while challenging the initial
        # hypothesis; the second-round challenge of the proposal stays empty.
        if hypothesis.title != proposed_title:
            proposals = [_proposal(artifact.id, proposed_title)]
        return HypothesisChallengeOutput(
            challenged_claim=f"Challenge of {hypothesis.title}",
            severity="material",
            proposed_hypotheses=proposals,
        )

    falsifier = FakeFalsifier(challenge)
    run = _run(fresh_session, incident.id, artifact.id, falsifier)
    fresh_session.commit()

    assert run.status == "succeeded"
    hyps = _hypotheses(fresh_session, run.id)
    # One builder hypothesis plus one proposed alternative.
    assert [h.origin for h in hyps] == ["initial", "proposed"]
    proposed = hyps[1]
    assert proposed.title == proposed_title
    assert proposed.rank == 2
    # It travelled the full path exactly once: resolved + verified citation, its
    # own challenge, a support verdict, and a pending review decision.
    assert [r for r in proposed.evidence_refs if r.role == "supporting"]
    assert all(r.verifier_status == "verified" for r in proposed.evidence_refs)
    assert proposed.challenge is not None
    assert proposed.support_status == "supported"
    assert proposed.review_status == "proposed"
    # The falsifier challenged 1 initial + 1 proposed hypothesis, and the
    # second-round challenge ran with proposals disabled (no recursion).
    assert len(falsifier.calls) == 2
    assert falsifier.last_allow_proposals is False


def test_more_than_two_proposals_fails_the_stage(fresh_session):
    incident = _incident(fresh_session)
    artifact = _add(fresh_session, incident.id)
    fresh_session.commit()

    def challenge(hypothesis):
        # A misbehaving falsifier that proposes three alternatives in one round —
        # over the bounded maximum of two (Runtime Reasoning Gate, AC #4).
        return HypothesisChallengeOutput(
            challenged_claim="x",
            severity="material",
            proposed_hypotheses=[
                _proposal(artifact.id, "Alt one"),
                _proposal(artifact.id, "Alt two"),
                _proposal(artifact.id, "Alt three"),
            ],
        )

    run = _run(
        fresh_session, incident.id, artifact.id, FakeFalsifier(challenge), builder_responses=2
    )
    fresh_session.commit()

    # The stage fails after its single retry; no successful run is presented.
    assert run.status == "failed"
    assert "exceeding the bounded maximum" in (run.error or "")


def test_second_expansion_round_is_rejected(fresh_session):
    incident = _incident(fresh_session)
    artifact = _add(fresh_session, incident.id)
    fresh_session.commit()

    proposed_title = "Cache eviction shifted read load onto the database"

    def challenge(hypothesis):
        # The initial hypothesis proposes one alternative; the proposed
        # hypothesis's own challenge then tries to propose again — a forbidden
        # second expansion round (AC #1/#4).
        return HypothesisChallengeOutput(
            challenged_claim=f"Challenge of {hypothesis.title}",
            severity="material",
            proposed_hypotheses=[_proposal(artifact.id, proposed_title)]
            if hypothesis.title != proposed_title
            else [_proposal(artifact.id, "A recursive second alternative")],
        )

    run = _run(
        fresh_session, incident.id, artifact.id, FakeFalsifier(challenge), builder_responses=2
    )
    fresh_session.commit()

    assert run.status == "failed"
    assert "second expansion round" in (run.error or "")


def test_zero_proposals_leaves_only_initial_hypotheses(fresh_session):
    incident = _incident(fresh_session)
    artifact = _add(fresh_session, incident.id)
    fresh_session.commit()

    # The default fake falsifier proposes nothing.
    run = _run(fresh_session, incident.id, artifact.id, FakeFalsifier())
    fresh_session.commit()

    assert run.status == "succeeded"
    hyps = _hypotheses(fresh_session, run.id)
    assert [h.origin for h in hyps] == ["initial"]
