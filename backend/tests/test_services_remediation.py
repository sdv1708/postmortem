from __future__ import annotations

import json

import pytest
from sqlalchemy.exc import IntegrityError

from postmortem.auth import Principal
from postmortem.falsification import FalsificationCounterclaim, HypothesisChallengeOutput
from postmortem.llm import FakeLLMClient
from postmortem.models import ActionItem, Hypothesis
from postmortem.schemas import AnalysisRunCreate, RemediationDecisionCreate
from postmortem.services import AnalysisService, RemediationService
from postmortem.services.artifacts import ArtifactService
from postmortem.services.incidents import IncidentService
from postmortem.schemas import ArtifactCreate, IncidentCreate

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

_PRINCIPAL = Principal(id="reviewer-1", display="Reviewer One")


def _builder_payload(artifact_id: str) -> str:
    return json.dumps(
        {
            "hypotheses": [
                {
                    "title": "Deploy v184 regressed connection handling",
                    "summary": "The v184 deploy preceded pool exhaustion and 500s.",
                    "supporting_evidence": [
                        {"artifact_id": artifact_id, "line_start": 1, "line_end": 2}
                    ],
                    "remediation_items": [
                        {"description": "Add a pool-saturation alert"},
                        {"description": "Add a deploy canary gate"},
                    ],
                }
            ]
        }
    )


def _run(session, falsifier):
    incident = IncidentService(session).create(IncidentCreate(title="Ambiguous outage"))
    artifact = ArtifactService(session).create(
        incident.id,
        ArtifactCreate(source_type="logs", source_name="api.log", body=BODY),
    )
    session.commit()
    service = AnalysisService(
        session,
        llm_client=FakeLLMClient([_builder_payload(artifact.id)]),
        claim_support_verifier=FakeClaimSupportVerifier(),
        incident_fact_extractor=FakeIncidentFactExtractor(),
        falsifier=falsifier,
    )
    run = service.start_run(incident.id, AnalysisRunCreate())
    assert run.status == "succeeded"
    return incident.id, run.id


def test_falsification_round_never_touches_remediation(fresh_session):
    """The Falsification Round challenges causal reasoning only (ADR 0041).

    A falsifier that emits counterclaims, evidence gaps, and a proposed alternative
    runs to completion, yet every generated Remediation Proposal is left in its
    generated 'proposed' state with no decision — remediation review is a separate
    human action after the run (CONTEXT "Causal Falsification vs Remediation Review").
    """
    counterclaim = FalsificationCounterclaim(statement="No deploy diff exists", evidence=[])

    def challenge(hypothesis):
        return HypothesisChallengeOutput(
            challenged_claim=f"Challenge of {hypothesis.title}",
            severity="material",
            counterclaims=[counterclaim],
            evidence_gaps=["Deploy diff missing"],
            falsification_tests=["Re-run the deploy in staging"],
        )

    incident_id, run_id = _run(fresh_session, FakeFalsifier(challenge))

    proposals = RemediationService(fresh_session).list_proposals(incident_id, run_id)
    assert len(proposals) == 2
    for proposal in proposals:
        assert proposal.review_status == "proposed"
        assert proposal.decided_by_principal is None
        assert proposal.decided_at is None
        assert proposal.causal_factor_id is None
        assert proposal.evidence_gap_challenge_id is None


def test_decision_preserves_generated_text(fresh_session):
    incident_id, run_id = _run(fresh_session, FakeFalsifier())
    service = RemediationService(fresh_session)
    proposal = service.list_proposals(incident_id, run_id)[0]
    original = proposal.description

    updated = service.decide(
        incident_id,
        run_id,
        proposal.id,
        RemediationDecisionCreate(decision="deferred", rationale="Revisit next quarter."),
        _PRINCIPAL,
    )
    # The generated text is never edited by a decision (ADR 0016).
    assert updated.description == original
    assert updated.review_status == "deferred"
    assert updated.decided_by_principal == "reviewer-1"
    assert updated.decision_rationale == "Revisit next quarter."


def test_list_proposals_rejects_cross_incident_run(fresh_session):
    incident_id, run_id = _run(fresh_session, FakeFalsifier())
    other_incident_id, _ = _run(fresh_session, FakeFalsifier())
    from postmortem.services import AnalysisRunNotFoundError

    # run_id belongs to the first incident, not the second.
    with pytest.raises(AnalysisRunNotFoundError):
        RemediationService(fresh_session).list_proposals(other_incident_id, run_id)


def test_db_check_blocks_accepted_without_link(fresh_session):
    """The accepted-link contract is a DB trust floor on fresh databases (ADR 0041)."""
    incident_id, run_id = _run(fresh_session, FakeFalsifier())
    hypothesis = (
        fresh_session.query(Hypothesis).filter(Hypothesis.run_id == run_id).first()
    )
    rogue = ActionItem(
        hypothesis_id=hypothesis.id,
        sequence=99,
        description="Bypass the service and accept without a link",
        review_status="accepted",
    )
    fresh_session.add(rogue)
    with pytest.raises(IntegrityError):
        fresh_session.flush()
    fresh_session.rollback()
