from __future__ import annotations

import json

import pytest

from postmortem.config import Settings
from postmortem.llm import (
    FakeLLMClient,
    OfflineLLMClient,
    OpenAICompatibleLLMClient,
    build_llm_client,
)
from postmortem.rca import PROMPT_VERSION
from postmortem.schemas import AnalysisRunCreate, ArtifactCreate, IncidentCreate
from postmortem.services import (
    AnalysisService,
    ArtifactService,
    HypothesisNotFoundError,
    IncidentService,
    hypothesis_read,
)

from tests._fakes import FakeClaimSupportVerifier


def _run_with_hypotheses(session):
    incident = IncidentService(session).create(IncidentCreate(title="Ambiguous"))
    artifact = ArtifactService(session).create(
        incident.id,
        ArtifactCreate(
            source_type="logs",
            source_name="api.log",
            body="line one\nline two\nline three",
        ),
    )
    session.commit()
    payload = json.dumps(
        {
            "hypotheses": [
                {
                    "title": "Primary cause",
                    "summary": "Most-supported explanation.",
                    "supporting_evidence": [
                        {"artifact_id": artifact.id, "line_start": 1, "line_end": 1}
                    ],
                    "contradicting_evidence": [
                        {"artifact_id": artifact.id, "line_start": 2, "line_end": 2}
                    ],
                    "impact_claims": [
                        {
                            "description": "Customers saw errors",
                            "evidence": [
                                {"artifact_id": artifact.id, "line_start": 3, "line_end": 3}
                            ],
                        }
                    ],
                    "remediation_items": [{"description": "Roll back", "evidence": []}],
                },
                {
                    "title": "Alternative cause",
                    "summary": "A competing explanation.",
                    "supporting_evidence": [
                        {"artifact_id": artifact.id, "line_start": 3, "line_end": 3}
                    ],
                },
            ]
        }
    )
    service = AnalysisService(
        session,
        llm_client=FakeLLMClient([payload], label="fake-model"),
        claim_support_verifier=FakeClaimSupportVerifier(),
    )
    run = service.start_run(incident.id, AnalysisRunCreate())
    session.commit()
    assert run.status == "succeeded"
    return service, incident, run


def test_list_hypotheses_returns_ranked_with_split_evidence(fresh_session):
    service, incident, run = _run_with_hypotheses(fresh_session)

    hyps = service.list_hypotheses(incident.id, run.id)
    assert [h.rank for h in hyps] == [1, 2]

    shaped = hypothesis_read(hyps[0])
    # hypothesis_read splits the flat evidence list by role so the Review Surface
    # renders supporting and contradicting separately (PRD stage 3).
    assert len(shaped["supporting_evidence"]) == 1
    assert len(shaped["contradicting_evidence"]) == 1
    assert shaped["supporting_evidence"][0].role == "supporting"
    assert shaped["contradicting_evidence"][0].role == "contradicting"
    assert shaped["impact_claims"][0]["description"] == "Customers saw errors"
    assert shaped["action_items"][0]["description"] == "Roll back"
    assert shaped["review_status"] == "proposed"


def test_review_records_decision_without_rewriting_claims(fresh_session):
    service, incident, run = _run_with_hypotheses(fresh_session)
    target = service.list_hypotheses(incident.id, run.id)[0]
    before = hypothesis_read(target)

    accepted = service.review_hypothesis(incident.id, run.id, target.id, "accepted")
    fresh_session.commit()
    assert accepted.review_status == "accepted"

    rejected = service.review_hypothesis(incident.id, run.id, target.id, "rejected")
    fresh_session.commit()
    assert rejected.review_status == "rejected"

    # Accept/reject only flips review_status; the generated claim and its
    # citations are untouched (ADR 0016).
    after = hypothesis_read(
        service.list_hypotheses(incident.id, run.id)[0]
    )
    assert after["title"] == before["title"]
    assert after["summary"] == before["summary"]
    assert [r.id for r in after["supporting_evidence"]] == [
        r.id for r in before["supporting_evidence"]
    ]
    assert [c["description"] for c in after["impact_claims"]] == [
        c["description"] for c in before["impact_claims"]
    ]


def test_review_rejects_invalid_decision(fresh_session):
    service, incident, run = _run_with_hypotheses(fresh_session)
    target = service.list_hypotheses(incident.id, run.id)[0]
    with pytest.raises(ValueError):
        service.review_hypothesis(incident.id, run.id, target.id, "maybe")


def test_review_unknown_hypothesis_raises(fresh_session):
    service, incident, run = _run_with_hypotheses(fresh_session)
    with pytest.raises(HypothesisNotFoundError):
        service.review_hypothesis(incident.id, run.id, "nope", "accepted")


def test_metadata_records_configured_provider_and_prompt(fresh_session):
    incident = IncidentService(fresh_session).create(IncidentCreate(title="Meta"))
    ArtifactService(fresh_session).create(
        incident.id, ArtifactCreate(source_type="logs", source_name="a.log", body="x")
    )
    fresh_session.commit()

    fake = FakeLLMClient([json.dumps({"hypotheses": []})], label="my-model")
    run = AnalysisService(fresh_session, llm_client=fake).start_run(
        incident.id, AnalysisRunCreate()
    )
    fresh_session.commit()

    # The run records which model produced its hypotheses (ADR 0025).
    assert run.model_provider == "my-model"
    assert run.prompt_version == PROMPT_VERSION


def test_offline_default_metadata_when_no_client(fresh_session):
    incident = IncidentService(fresh_session).create(IncidentCreate(title="Meta"))
    ArtifactService(fresh_session).create(
        incident.id, ArtifactCreate(source_type="logs", source_name="a.log", body="x")
    )
    fresh_session.commit()

    run = AnalysisService(fresh_session).start_run(incident.id, AnalysisRunCreate())
    fresh_session.commit()
    # No client injected at the service: the default placeholder metadata stays.
    assert run.model_provider == "none"


def test_build_llm_client_is_provider_agnostic():
    # No key → safe offline default so runs still complete (ADR 0011).
    offline = build_llm_client(
        Settings(database_url="sqlite://", api_token=None, dev_bypass=True, cors_origins=())
    )
    assert isinstance(offline, OfflineLLMClient)

    # Switching provider/model is config-only: the label captures both endpoint
    # identity and model so Experiment Metadata distinguishes provider swaps.
    configured = build_llm_client(
        Settings(
            database_url="sqlite://",
            api_token=None,
            dev_bypass=True,
            cors_origins=(),
            llm_base_url="https://example.test/v1",
            llm_api_key="secret",
            llm_model="some-other-model",
        )
    )
    assert isinstance(configured, OpenAICompatibleLLMClient)
    assert configured.label == "openai-compatible:example.test:some-other-model"
