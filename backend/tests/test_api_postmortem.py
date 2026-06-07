from __future__ import annotations

import json

from fastapi.testclient import TestClient

from postmortem.llm import FakeLLMClient
from postmortem.services import AnalysisService
from postmortem.verification import ClaimSupportJudgment, ClaimSupportStatus

from tests._fakes import FakeClaimSupportVerifier


def _create_incident(client: TestClient, auth_headers) -> str:
    resp = client.post("/api/incidents", json={"title": "PM incident", "severity": "sev1"}, headers=auth_headers)
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


def _add_artifact(client: TestClient, auth_headers, incident_id: str) -> str:
    resp = client.post(
        f"/api/incidents/{incident_id}/artifacts",
        json={"source_type": "logs", "source_name": "api.log", "body": "alpha line\nbeta line"},
        headers=auth_headers,
    )
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


def _queue_run(app, client, auth_headers):
    """Start a run via HTTP, leaving it queued (scheduler stubbed)."""
    app.state.run_scheduler = lambda background_tasks, session_factory, run_id: None
    incident_id = _create_incident(client, auth_headers)
    artifact_id = _add_artifact(client, auth_headers, incident_id)
    start = client.post(
        f"/api/incidents/{incident_id}/analysis-runs", json={}, headers=auth_headers
    )
    assert start.status_code == 201, start.text
    return incident_id, artifact_id, start.json()["id"]


def _judge(claim):
    # The competing hypothesis is unsupported so clean exports must drop it.
    if claim.claim_text.startswith("Alternative cause"):
        return ClaimSupportJudgment(ClaimSupportStatus.UNSUPPORTED, "Evidence does not establish this.")
    return ClaimSupportJudgment(ClaimSupportStatus.SUPPORTED, "The cited evidence supports the claim.")


def _seed_drafted_run(app, client, auth_headers):
    incident_id, artifact_id, run_id = _queue_run(app, client, auth_headers)
    payload = json.dumps(
        {
            "hypotheses": [
                {
                    "title": "Primary cause",
                    "summary": "Most-supported explanation.",
                    "supporting_evidence": [
                        {"artifact_id": artifact_id, "line_start": 1, "line_end": 1}
                    ],
                    "impact_claims": [
                        {
                            "description": "Customers errored",
                            "evidence": [
                                {"artifact_id": artifact_id, "line_start": 2, "line_end": 2}
                            ],
                        }
                    ],
                    "remediation_items": [{"description": "Roll back the deploy"}],
                    "unknowns": ["why did alpha happen"],
                },
                {
                    "title": "Alternative cause",
                    "summary": "A competing, unsupported explanation.",
                    "supporting_evidence": [
                        {"artifact_id": artifact_id, "line_start": 1, "line_end": 1}
                    ],
                    "unknowns": ["why did beta happen"],
                },
            ]
        }
    )
    session = app.state.session_factory()
    try:
        run = AnalysisService(
            session,
            llm_client=FakeLLMClient([payload], label="fake-model"),
            claim_support_verifier=FakeClaimSupportVerifier(_judge),
        ).execute_run(run_id, commit_progress=True)
        assert run.status == "succeeded"
        session.commit()
    finally:
        session.close()
    return incident_id, run_id


def test_get_postmortem_returns_structured_document(app, client: TestClient, auth_headers):
    incident_id, run_id = _seed_drafted_run(app, client, auth_headers)
    resp = client.get(
        f"/api/incidents/{incident_id}/analysis-runs/{run_id}/postmortem", headers=auth_headers
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["incident_title"] == "PM incident"
    assert body["composer_version"] == "postmortem-template-1"
    assert "2 root-cause hypotheses were generated for evidence review" in body["summary"]
    assert "Primary cause" not in body["summary"]
    assert "Alternative cause" not in body["summary"]
    # Lessons are the hypotheses' unknowns, deduped in rank order.
    assert body["lessons_learned"] == ["why did alpha happen", "why did beta happen"]
    # The structured read is the full source of truth — it includes all
    # hypotheses (the clean/audit split is an export concern, not a read concern).
    assert {h["title"] for h in body["hypotheses"]} == {"Primary cause", "Alternative cause"}
    assert body["hypotheses"][0]["impact_claims"][0]["description"] == "Customers errored"


def test_get_postmortem_404_before_drafting(app, client: TestClient, auth_headers):
    incident_id, _artifact_id, run_id = _queue_run(app, client, auth_headers)
    resp = client.get(
        f"/api/incidents/{incident_id}/analysis-runs/{run_id}/postmortem", headers=auth_headers
    )
    assert resp.status_code == 404
    assert resp.json()["detail"] == "this run has not produced a postmortem yet"


def test_get_postmortem_unknown_run_404(client: TestClient, auth_headers):
    resp = client.post("/api/incidents", json={"title": "x"}, headers=auth_headers)
    incident_id = resp.json()["id"]
    resp = client.get(
        f"/api/incidents/{incident_id}/analysis-runs/nope/postmortem", headers=auth_headers
    )
    assert resp.status_code == 404
    assert resp.json()["detail"] == "analysis run not found"


def test_clean_export_omits_unsupported_hypothesis(app, client: TestClient, auth_headers):
    incident_id, run_id = _seed_drafted_run(app, client, auth_headers)
    resp = client.post(
        f"/api/incidents/{incident_id}/analysis-runs/{run_id}/postmortem/export",
        json={"mode": "clean"},
        headers=auth_headers,
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["mode"] == "clean"
    assert body["filename"] == f"postmortem-{run_id}-clean.md"
    markdown = body["markdown"]
    assert "# Postmortem — PM incident" in markdown
    assert "Primary cause" in markdown
    # Unsupported claims never appear as fact in a clean export (ADR 0015).
    assert "Alternative cause" not in markdown
    assert "Review findings" not in markdown


def test_audit_export_includes_unsupported_hypothesis(app, client: TestClient, auth_headers):
    incident_id, run_id = _seed_drafted_run(app, client, auth_headers)
    resp = client.post(
        f"/api/incidents/{incident_id}/analysis-runs/{run_id}/postmortem/export",
        json={"mode": "audit"},
        headers=auth_headers,
    )
    assert resp.status_code == 200, resp.text
    markdown = resp.json()["markdown"]
    assert "Review findings (unsupported & assumptions)" in markdown
    assert "Alternative cause" in markdown
    assert "Evidence does not establish this." in markdown


def test_export_defaults_to_clean(app, client: TestClient, auth_headers):
    incident_id, run_id = _seed_drafted_run(app, client, auth_headers)
    resp = client.post(
        f"/api/incidents/{incident_id}/analysis-runs/{run_id}/postmortem/export",
        json={},
        headers=auth_headers,
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["mode"] == "clean"


def test_postmortem_requires_auth(client: TestClient):
    resp = client.get("/api/incidents/x/analysis-runs/y/postmortem")
    assert resp.status_code == 401
    resp = client.post("/api/incidents/x/analysis-runs/y/postmortem/export", json={})
    assert resp.status_code == 401
