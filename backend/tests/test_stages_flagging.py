from __future__ import annotations

import json

from postmortem.incident_facts import FactsImpactClaim
from postmortem.llm import FakeLLMClient
from postmortem.models import Hypothesis, ImpactClaim, RunStageEvent
from postmortem.rca import RcaEvidenceRef
from postmortem.schemas import AnalysisRunCreate, ArtifactCreate, IncidentCreate
from postmortem.services import AnalysisService, ArtifactService, IncidentService, StagedRunExecutor
from postmortem.services.stages import PipelineStageRunner
from postmortem.verification import (
    CITATION_VERIFIER_VERSION,
    CitationIntegrityStatus,
    ClaimSupportJudgment,
    ClaimSupportStatus,
)

from tests._fakes import (
    FakeClaimSupportVerifier,
    FakeFalsifier,
    FakeIncidentFactExtractor,
)


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


def _impact_facts(artifact_id: str) -> list[FactsImpactClaim]:
    # Run-level impact is produced by stage 2 now (ADR 0033), not nested in RCA.
    return [
        FactsImpactClaim(
            description="Users saw 500s",
            evidence=[RcaEvidenceRef(artifact_id=artifact_id, line_start=2, line_end=2)],
        )
    ]


def _impact(session, run_id):
    return list(
        session.query(ImpactClaim)
        .filter(ImpactClaim.run_id == run_id)
        .order_by(ImpactClaim.sequence)
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


class _BrokenCitationVerifier:
    def verify(self, target, artifact_bodies):
        return CitationIntegrityStatus.SNIPPET_MISMATCH


def test_flagging_classifies_each_major_claim(fresh_session):
    incident = _incident(fresh_session)
    artifact = _add(fresh_session, incident.id)
    fresh_session.commit()

    verifier = FakeClaimSupportVerifier(_judge)
    fake = FakeLLMClient([_rca_json(artifact.id)], label="fake-model")
    run = AnalysisService(
        fresh_session,
        llm_client=fake,
        claim_support_verifier=verifier,
        incident_fact_extractor=FakeIncidentFactExtractor(_impact_facts(artifact.id)),
        falsifier=FakeFalsifier(),
    ).start_run(incident.id, AnalysisRunCreate())
    fresh_session.commit()

    assert run.status == "succeeded"
    hyps = _hypotheses(fresh_session, run.id)
    by_title = {h.title: h for h in hyps}

    # Cited claims are classified by the semantic verifier (ADR 0014).
    assert by_title["Deploy regressed the pool"].support_status == "supported"
    assert by_title["Cache pressure cascaded"].support_status == "unsupported"

    # The run-level impact claim is classified too (ADR 0033).
    impact = _impact(fresh_session, run.id)
    assert impact[0].support_status == "partial"
    assert impact[0].support_rationale == "Correlated, not causal."

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


def test_flagging_does_not_treat_broken_citations_as_support(fresh_session):
    incident = _incident(fresh_session)
    artifact = _add(fresh_session, incident.id)
    fresh_session.commit()

    claim_support = FakeClaimSupportVerifier()
    runner = PipelineStageRunner(
        fresh_session,
        llm_client=FakeLLMClient([_rca_json(artifact.id)]),
        verifier=_BrokenCitationVerifier(),
        claim_support_verifier=claim_support,
        incident_fact_extractor=FakeIncidentFactExtractor(),
        falsifier=FakeFalsifier(),
    )
    run = AnalysisService(
        fresh_session, executor=StagedRunExecutor(stage_runner=runner)
    ).start_run(incident.id, AnalysisRunCreate())
    fresh_session.commit()

    assert run.status == "succeeded"
    by_title = {h.title: h for h in _hypotheses(fresh_session, run.id)}
    assert by_title["Deploy regressed the pool"].support_status == "unsupported"
    assert by_title["Cache pressure cascaded"].support_status == "unsupported"
    assert "No verified supporting citations" in by_title["Deploy regressed the pool"].support_rationale
    assert claim_support.calls == []
    assert _flag_event(fresh_session, run.id).warning_codes == ["unsupported_claim"]


def test_all_supported_emits_no_warnings(fresh_session):
    incident = _incident(fresh_session)
    artifact = _add(fresh_session, incident.id)
    fresh_session.commit()

    # Default fake judges every cited claim SUPPORTED; only the uncited "Vague
    # guess" remains unsupported.
    fake = FakeLLMClient([_rca_json(artifact.id)], label="fake-model")
    run = AnalysisService(
        fresh_session,
        llm_client=fake,
        claim_support_verifier=FakeClaimSupportVerifier(),
        incident_fact_extractor=FakeIncidentFactExtractor(),
        falsifier=FakeFalsifier(),
    ).start_run(incident.id, AnalysisRunCreate())
    fresh_session.commit()

    assert run.status == "succeeded"
    by_title = {h.title: h for h in _hypotheses(fresh_session, run.id)}
    assert by_title["Deploy regressed the pool"].support_status == "supported"
    assert by_title["Cache pressure cascaded"].support_status == "supported"
    # The uncited assumption is still flagged.
    event = _flag_event(fresh_session, run.id)
    assert event.warning_codes == ["unsupported_claim"]


def test_run_metadata_records_injected_claim_support_verifier_version(fresh_session):
    incident = _incident(fresh_session)
    artifact = _add(fresh_session, incident.id)
    fresh_session.commit()

    verifier = FakeClaimSupportVerifier()
    run = AnalysisService(
        fresh_session,
        llm_client=FakeLLMClient([_rca_json(artifact.id)]),
        claim_support_verifier=verifier,
        incident_fact_extractor=FakeIncidentFactExtractor(),
        falsifier=FakeFalsifier(),
    ).start_run(incident.id, AnalysisRunCreate())
    fresh_session.commit()

    assert run.verifier_version == f"{CITATION_VERIFIER_VERSION}+{verifier.version}"


def test_flagging_is_idempotent_across_retry(fresh_session):
    incident = _incident(fresh_session)
    artifact = _add(fresh_session, incident.id)
    fresh_session.commit()

    verifier = FakeClaimSupportVerifier(_judge)
    real = PipelineStageRunner(
        fresh_session,
        llm_client=FakeLLMClient([_rca_json(artifact.id)]),
        claim_support_verifier=verifier,
        incident_fact_extractor=FakeIncidentFactExtractor(_impact_facts(artifact.id)),
        falsifier=FakeFalsifier(),
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
