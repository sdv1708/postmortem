from __future__ import annotations

import json

from fastapi.testclient import TestClient

from postmortem.llm import FakeLLMClient
from postmortem.schemas import AnalysisRunCreate
from postmortem.services import AnalysisService


def create_incident(client: TestClient, auth_headers) -> str:
    resp = client.post("/api/incidents", json={"title": "Hyp incident"}, headers=auth_headers)
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


def add_artifact(client: TestClient, auth_headers, incident_id: str) -> str:
    resp = client.post(
        f"/api/incidents/{incident_id}/artifacts",
        json={"source_type": "logs", "source_name": "api.log", "body": "alpha line\nbeta line"},
        headers=auth_headers,
    )
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


def _seed_run_with_hypotheses(app, client, auth_headers):
    """Start a run via HTTP but execute it with a seeded provider.

    The scheduler is stubbed so the POST only queues the run; the run is then
    executed against the app's own DB with a FakeLLMClient so the HTTP read
    endpoints surface real persisted hypotheses (the configured provider is not
    called in tests).
    """
    captured: list[str] = []
    app.state.run_scheduler = lambda background_tasks, session_factory, run_id: captured.append(
        run_id
    )

    incident_id = create_incident(client, auth_headers)
    artifact_id = add_artifact(client, auth_headers, incident_id)
    start = client.post(
        f"/api/incidents/{incident_id}/analysis-runs", json={}, headers=auth_headers
    )
    assert start.status_code == 201, start.text
    run_id = start.json()["id"]

    payload = json.dumps(
        {
            "hypotheses": [
                {
                    "title": "Primary cause",
                    "summary": "Most-supported explanation.",
                    "supporting_evidence": [
                        {"artifact_id": artifact_id, "line_start": 1, "line_end": 1}
                    ],
                    "contradicting_evidence": [
                        {"artifact_id": artifact_id, "line_start": 2, "line_end": 2}
                    ],
                    "unknowns": ["one open question"],
                    "validation_steps": ["confirm via metrics"],
                    "impact_claims": [
                        {
                            "description": "Customers errored",
                            "evidence": [
                                {"artifact_id": artifact_id, "line_start": 2, "line_end": 2}
                            ],
                        }
                    ],
                    "remediation_items": [{"description": "Roll back", "evidence": []}],
                },
                {
                    "title": "Alternative cause",
                    "summary": "A competing explanation.",
                    "supporting_evidence": [
                        {"artifact_id": artifact_id, "line_start": 1, "line_end": 1}
                    ],
                },
            ]
        }
    )
    session = app.state.session_factory()
    try:
        AnalysisService(
            session, llm_client=FakeLLMClient([payload], label="fake-model")
        ).execute_run(run_id, commit_progress=True)
        session.commit()
    finally:
        session.close()

    return incident_id, run_id


def test_list_hypotheses_returns_ranked_with_split_evidence(app, client: TestClient, auth_headers):
    incident_id, run_id = _seed_run_with_hypotheses(app, client, auth_headers)

    resp = client.get(
        f"/api/incidents/{incident_id}/analysis-runs/{run_id}/hypotheses", headers=auth_headers
    )
    assert resp.status_code == 200, resp.text
    hyps = resp.json()
    assert [h["rank"] for h in hyps] == [1, 2]

    top = hyps[0]
    assert top["title"] == "Primary cause"
    assert top["review_status"] == "proposed"
    assert len(top["supporting_evidence"]) == 1
    assert len(top["contradicting_evidence"]) == 1
    # Snippets are resolved from the stored artifact lines (ADR 0024).
    assert top["supporting_evidence"][0]["snippet"] == "alpha line"
    assert top["contradicting_evidence"][0]["snippet"] == "beta line"
    # The deterministic citation-integrity pass ran (stage 4) and stamped each
    # citation verified, so the Review Surface can show citation trust (ADR 0014).
    assert top["supporting_evidence"][0]["verifier_status"] == "verified"
    assert top["contradicting_evidence"][0]["verifier_status"] == "verified"
    assert top["impact_claims"][0]["evidence_refs"][0]["verifier_status"] == "verified"
    assert top["impact_claims"][0]["description"] == "Customers errored"
    assert top["action_items"][0]["description"] == "Roll back"
    assert top["unknowns"] == ["one open question"]
    assert top["validation_steps"] == ["confirm via metrics"]


def test_review_hypothesis_sets_status_without_altering_claims(
    app, client: TestClient, auth_headers
):
    incident_id, run_id = _seed_run_with_hypotheses(app, client, auth_headers)
    base = f"/api/incidents/{incident_id}/analysis-runs/{run_id}/hypotheses"
    before = client.get(base, headers=auth_headers).json()[0]

    resp = client.post(
        f"{base}/{before['id']}/review", json={"decision": "accepted"}, headers=auth_headers
    )
    assert resp.status_code == 200, resp.text
    updated = resp.json()
    assert updated["review_status"] == "accepted"
    # The accept decision flips status only; claims and citations are unchanged.
    assert updated["title"] == before["title"]
    assert updated["summary"] == before["summary"]
    assert [r["id"] for r in updated["supporting_evidence"]] == [
        r["id"] for r in before["supporting_evidence"]
    ]
    assert updated["impact_claims"] == before["impact_claims"]

    # The new status is durable on the next read.
    after = client.get(base, headers=auth_headers).json()[0]
    assert after["review_status"] == "accepted"


def test_review_unknown_hypothesis_returns_404(app, client: TestClient, auth_headers):
    incident_id, run_id = _seed_run_with_hypotheses(app, client, auth_headers)
    resp = client.post(
        f"/api/incidents/{incident_id}/analysis-runs/{run_id}/hypotheses/nope/review",
        json={"decision": "accepted"},
        headers=auth_headers,
    )
    assert resp.status_code == 404
    assert resp.json()["detail"] == "hypothesis not found"


def test_list_hypotheses_for_unknown_run_returns_404(client: TestClient, auth_headers):
    incident_id = create_incident(client, auth_headers)
    resp = client.get(
        f"/api/incidents/{incident_id}/analysis-runs/nope/hypotheses", headers=auth_headers
    )
    assert resp.status_code == 404
    assert resp.json()["detail"] == "analysis run not found"


def test_hypotheses_require_auth(client: TestClient):
    resp = client.get("/api/incidents/whatever/analysis-runs/whatever/hypotheses")
    assert resp.status_code == 401
