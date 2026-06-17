from __future__ import annotations

import json

from postmortem.llm import FakeLLMClient
from postmortem.models import Artifact, EvidenceRef, Hypothesis, Postmortem, RunStageEvent
from postmortem.schemas import AnalysisRunCreate, ArtifactCreate, IncidentCreate
from postmortem.services import AnalysisService, ArtifactService, IncidentService, StagedRunExecutor
from postmortem.services.stages import PipelineStageRunner

from tests._fakes import (
    FakeClaimSupportVerifier,
    FakeIncidentFactExtractor,
    FakePostmortemComposer,
)


BODY = "deploy v184 rolled out\napi 500 rate climbing\ncache evicted under pressure"


def _incident(session):
    return IncidentService(session).create(IncidentCreate(title="Drafting", severity="sev1"))


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
                    "remediation_items": [{"description": "Add a pool alert"}],
                    "unknowns": ["Was the pool size changed in v184?"],
                },
                {
                    "title": "Vague guess",
                    "summary": "Something in the deploy, but we cannot cite it.",
                    "supporting_evidence": [],
                    "unknowns": ["What else changed at 14:28?"],
                },
            ]
        }
    )


def _postmortem(session, run_id) -> Postmortem:
    return session.query(Postmortem).filter(Postmortem.run_id == run_id).one()


def _start(session, incident_id, *, composer=None, verifier=None):
    artifact = session.query(Artifact).filter_by(incident_id=incident_id).one()
    return AnalysisService(
        session,
        llm_client=FakeLLMClient([_rca_json(artifact.id)]),
        claim_support_verifier=verifier or FakeClaimSupportVerifier(),
        postmortem_composer=composer,
        incident_fact_extractor=FakeIncidentFactExtractor(),
    ).start_run(incident_id, AnalysisRunCreate())


def test_drafting_persists_one_structured_postmortem(fresh_session):
    incident = _incident(fresh_session)
    _add(fresh_session, incident.id)
    fresh_session.commit()

    run = _start(fresh_session, incident.id)
    fresh_session.commit()

    assert run.status == "succeeded"
    postmortem = _postmortem(fresh_session, run.id)
    # Composed from the verified structured outputs (ADR 0012): the summary
    # restates real counts but does not name a leading hypothesis before support
    # filtering. Lessons are the hypotheses' unknowns.
    assert "2 root-cause hypotheses were generated for evidence review" in postmortem.summary
    assert "Deploy regressed the pool" not in postmortem.summary
    assert "Vague guess" not in postmortem.summary
    assert postmortem.lessons_learned == [
        "Was the pool size changed in v184?",
        "What else changed at 14:28?",
    ]
    assert postmortem.composer_version == "postmortem-template-1"


def test_drafting_marks_a_cited_run_sufficient_without_a_warning(fresh_session):
    incident = _incident(fresh_session)
    _add(fresh_session, incident.id)
    fresh_session.commit()

    run = _start(fresh_session, incident.id)
    fresh_session.commit()

    postmortem = _postmortem(fresh_session, run.id)
    assert postmortem.evidence_sufficiency == "sufficient"
    assert postmortem.evidence_gaps == []
    assert postmortem.next_validation_steps == []
    drafting = (
        fresh_session.query(RunStageEvent)
        .filter_by(run_id=run.id, stage="drafting_postmortem")
        .one()
    )
    assert "insufficient_evidence" not in (drafting.warning_codes or [])


def test_drafting_refuses_when_the_model_returns_no_hypotheses(fresh_session):
    incident = _incident(fresh_session)
    _add(fresh_session, incident.id)
    fresh_session.commit()

    # An empty RCA result (no evidence-backed hypotheses) must produce a refusal,
    # not a confident postmortem (ADR 0032 / 0015).
    run = AnalysisService(
        fresh_session,
        llm_client=FakeLLMClient(['{"hypotheses": []}']),
        claim_support_verifier=FakeClaimSupportVerifier(),
        incident_fact_extractor=FakeIncidentFactExtractor(),
    ).start_run(incident.id, AnalysisRunCreate())
    fresh_session.commit()

    assert run.status == "succeeded"
    postmortem = _postmortem(fresh_session, run.id)
    assert postmortem.evidence_sufficiency == "insufficient"
    assert "not enough evidence to write a confident postmortem" in postmortem.summary
    assert postmortem.evidence_gaps
    assert postmortem.next_validation_steps
    # The refusal is surfaced as a non-fatal Warning Code on the drafting stage.
    drafting = (
        fresh_session.query(RunStageEvent)
        .filter_by(run_id=run.id, stage="drafting_postmortem")
        .one()
    )
    assert "insufficient_evidence" in drafting.warning_codes


def test_drafting_introduces_no_new_factual_claims(fresh_session):
    incident = _incident(fresh_session)
    artifact = _add(fresh_session, incident.id)
    fresh_session.commit()

    counts: dict[str, int] = {}
    real = PipelineStageRunner(
        fresh_session,
        llm_client=FakeLLMClient([_rca_json(artifact.id)]),
        claim_support_verifier=FakeClaimSupportVerifier(),
        incident_fact_extractor=FakeIncidentFactExtractor(),
    )

    def spy(stage, attempt, run):
        if stage == "drafting_postmortem":
            counts["refs_before"] = fresh_session.query(EvidenceRef).count()
            counts["hyps_before"] = fresh_session.query(Hypothesis).count()
            result = real(stage, attempt, run)
            counts["refs_after"] = fresh_session.query(EvidenceRef).count()
            counts["hyps_after"] = fresh_session.query(Hypothesis).count()
            return result
        return real(stage, attempt, run)

    run = AnalysisService(
        fresh_session, executor=StagedRunExecutor(stage_runner=spy)
    ).start_run(incident.id, AnalysisRunCreate())
    fresh_session.commit()

    assert run.status == "succeeded"
    # Drafting only composes existing claims (ADR 0026): it adds no citations and
    # no hypotheses, and the Postmortem itself owns no EvidenceRefs.
    assert counts["refs_before"] == counts["refs_after"]
    assert counts["hyps_before"] == counts["hyps_after"]
    assert not hasattr(_postmortem(fresh_session, run.id), "evidence_refs")


def test_drafting_composer_is_swappable(fresh_session):
    incident = _incident(fresh_session)
    _add(fresh_session, incident.id)
    fresh_session.commit()

    composer = FakePostmortemComposer(summary="Injected summary.", lessons=("Injected lesson.",))
    run = _start(fresh_session, incident.id, composer=composer)
    fresh_session.commit()

    assert run.status == "succeeded"
    # The injected template produced the persisted postmortem, and it was handed
    # the run's structured outputs (ADR 0009).
    assert len(composer.calls) == 1
    context = composer.calls[0]
    assert context.incident_title == "Drafting"
    assert {h.title for h in context.hypotheses} == {"Deploy regressed the pool", "Vague guess"}
    postmortem = _postmortem(fresh_session, run.id)
    assert postmortem.summary == "Injected summary."
    assert postmortem.lessons_learned == ["Injected lesson."]
    assert postmortem.composer_version == "fake-template-0"


def test_drafting_is_idempotent_across_retry(fresh_session):
    incident = _incident(fresh_session)
    artifact = _add(fresh_session, incident.id)
    fresh_session.commit()

    real = PipelineStageRunner(
        fresh_session,
        llm_client=FakeLLMClient([_rca_json(artifact.id)]),
        claim_support_verifier=FakeClaimSupportVerifier(),
        incident_fact_extractor=FakeIncidentFactExtractor(),
    )

    def flaky(stage, attempt, run):
        if stage == "drafting_postmortem" and attempt == 1:
            real(stage, attempt, run)  # draft once, then fail to force the retry
            raise RuntimeError("boom after drafting")
        return real(stage, attempt, run)

    run = AnalysisService(
        fresh_session, executor=StagedRunExecutor(stage_runner=flaky)
    ).start_run(incident.id, AnalysisRunCreate())
    fresh_session.commit()

    assert run.status == "succeeded"
    # The retry replaced the draft in place — exactly one Postmortem for the run.
    assert fresh_session.query(Postmortem).filter(Postmortem.run_id == run.id).count() == 1
