from __future__ import annotations

import json

from postmortem.llm import FakeLLMClient
from postmortem.models import Hypothesis, RunStageEvent
from postmortem.schemas import AnalysisRunCreate, ArtifactCreate, IncidentCreate
from postmortem.services import AnalysisService, ArtifactService, IncidentService, StagedRunExecutor
from postmortem.services.stages import PipelineStageRunner
from postmortem.verification import ClaimSupportJudgment, ClaimSupportStatus

from tests._fakes import FakeClaimSupportVerifier


BODY = "deploy v184 rolled out\napi 500 rate climbing\ncache evicted under pressure"


def _incident(session):
    return IncidentService(session).create(IncidentCreate(title="Flagging"))


def _add(session, incident_id):
    return ArtifactService(session).create(
        incident_id, ArtifactCreate(source_type="logs", source_name="api.log", body=BODY)
    )


def _rca_json(artifact_id: str) -> str:
    return json.dumps(
        {
            "hypotheses": [
                {
                    "title": "Deploy regressed the pool",
                    "summary": "v184 preceded the spike.",
                    "supporting_evidence": [
                        {"artifact_id": artifact_id, "line_start": 1, "line_end": 1}
                    ],
                    "impact_claims": [
                        {
                            "description": "Users saw 500s",
                            "evidence": [
                                {"artifact_id": artifact_id, "line_start": 2, "line_end": 2}
                            ],
                        }
                    ],
                },
                {
                    "title": "Cache pressure cascaded",
                    "summary": "A cache eviction drove load.",
                    "supporting_evidence": [
                        {"artifact_id": artifact_id, "line_start": 3, "line_end": 3}
                    ],
                },
                {
                    "title": "Vague guess",
                    "summary": "Something in the deploy, but we cannot cite it.",
                    "supporting_evidence": [],
                },
            ]
        }
    )


def _judge(claim):
    if claim.claim_text.startswith("Deploy regressed the pool"):
        return ClaimSupportJudgment(ClaimSupportStatus.SUPPORTED, "Deploy precedes the spike.")
    if claim.claim_text == "Users saw 500s":
        return ClaimSupportJudgment(ClaimSupportStatus.PARTIAL, "Correlated, not causal.")
    if claim.claim_text.startswith("Cache pressure"):
        return ClaimSupportJudgment(ClaimSupportStatus.UNSUPPORTED, "Snippet does not establish cause.")
    raise AssertionError(f"unexpected claim sent to verifier: {claim.claim_text!r}")


def _hypotheses(session, run_id):
    return list(
        session.query(Hypothesis).filter(Hypothesis.run_id == run_id).order_by(Hypothesis.rank)
    )


def _flag_event(session, run_id):
    return (
        session.query(RunStageEvent)
        .filter(
            RunStageEvent.run_id == run_id,
            RunStageEvent.stage == "flagging_unsupported_claims",
        )
        .order_by(RunStageEvent.sequence.desc())
        .first()
    )


def test_flagging_classifies_each_major_claim(fresh_session):
    incident = _incident(fresh_session)
    artifact = _add(fresh_session, incident.id)
    fresh_session.commit()

    verifier = FakeClaimSupportVerifier(_judge)
    fake = FakeLLMClient([_rca_json(artifact.id)], label="fake-model")
    run = AnalysisService(
        fresh_session, llm_client=fake, claim_support_verifier=verifier
    ).start_run(incident.id, AnalysisRunCreate())
    fresh_session.commit()

    assert run.status == "succeeded"
    hyps = _hypotheses(fresh_session, run.id)
    by_title = {h.title: h for h in hyps}

    # Cited claims are classified by the semantic verifier (ADR 0014).
    assert by_title["Deploy regressed the pool"].support_status == "supported"
    assert by_title["Deploy regressed the pool"].impact_claims[0].support_status == "partial"
    assert by_title["Deploy regressed the pool"].impact_claims[0].support_rationale == (
        "Correlated, not causal."
    )
    assert by_title["Cache pressure cascaded"].support_status == "unsupported"

    # The uncited hypothesis is an assumption: marked unsupported without ever
    # calling the model (ADR 0013).
    vague = by_title["Vague guess"]
    assert vague.assumption is True
    assert vague.support_status == "unsupported"
    assert "assumption" in vague.support_rationale
    judged = {c.claim_text for c in verifier.calls}
    assert not any(text.startswith("Vague guess") for text in judged)

    # Stage 6 flags the weak claims with Warning Codes but the run still succeeds
    # (ADR 0015 / 0029): no automatic failure or retry.
    event = _flag_event(fresh_session, run.id)
    assert event.status == "succeeded"
    assert event.attempt == 1
    assert set(event.warning_codes) == {"unsupported_claim", "partial_claim_support"}


def test_all_supported_emits_no_warnings(fresh_session):
    incident = _incident(fresh_session)
    artifact = _add(fresh_session, incident.id)
    fresh_session.commit()

    # Default fake judges every cited claim SUPPORTED; only the uncited "Vague
    # guess" remains unsupported.
    fake = FakeLLMClient([_rca_json(artifact.id)], label="fake-model")
    run = AnalysisService(
        fresh_session, llm_client=fake, claim_support_verifier=FakeClaimSupportVerifier()
    ).start_run(incident.id, AnalysisRunCreate())
    fresh_session.commit()

    assert run.status == "succeeded"
    by_title = {h.title: h for h in _hypotheses(fresh_session, run.id)}
    assert by_title["Deploy regressed the pool"].support_status == "supported"
    assert by_title["Cache pressure cascaded"].support_status == "supported"
    # The uncited assumption is still flagged.
    event = _flag_event(fresh_session, run.id)
    assert event.warning_codes == ["unsupported_claim"]


def test_flagging_is_idempotent_across_retry(fresh_session):
    incident = _incident(fresh_session)
    artifact = _add(fresh_session, incident.id)
    fresh_session.commit()

    verifier = FakeClaimSupportVerifier(_judge)
    real = PipelineStageRunner(
        fresh_session, llm_client=FakeLLMClient([_rca_json(artifact.id)]), claim_support_verifier=verifier
    )

    def flaky(stage, attempt, run):
        if stage == "flagging_unsupported_claims" and attempt == 1:
            real(stage, attempt, run)  # classify, then fail to force the retry
            raise RuntimeError("boom after flagging")
        return real(stage, attempt, run)

    run = AnalysisService(
        fresh_session, executor=StagedRunExecutor(stage_runner=flaky)
    ).start_run(incident.id, AnalysisRunCreate())
    fresh_session.commit()

    assert run.status == "succeeded"
    # The retry overwrote support fields in place — no duplicate hypotheses, and
    # the final classification stands (ADR 0029).
    hyps = _hypotheses(fresh_session, run.id)
    assert [h.rank for h in hyps] == [1, 2, 3]
    by_title = {h.title: h for h in hyps}
    assert by_title["Deploy regressed the pool"].support_status == "supported"
    assert by_title["Cache pressure cascaded"].support_status == "unsupported"
    assert _flag_event(fresh_session, run.id).attempt == 2
