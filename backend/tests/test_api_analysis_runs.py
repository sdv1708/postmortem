from __future__ import annotations

from fastapi.testclient import TestClient


def create_incident(client: TestClient, auth_headers) -> str:
    resp = client.post("/api/incidents", json={"title": "Run test incident"}, headers=auth_headers)
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


def add_artifact(client: TestClient, auth_headers, incident_id: str, body: str = "line one\nline two") -> str:
    resp = client.post(
        f"/api/incidents/{incident_id}/artifacts",
        json={"source_type": "logs", "source_name": "api.log", "body": body},
        headers=auth_headers,
    )
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


def test_start_run_returns_pollable_status(client: TestClient, auth_headers):
    incident_id = create_incident(client, auth_headers)
    artifact_id = add_artifact(client, auth_headers, incident_id)

    start = client.post(
        f"/api/incidents/{incident_id}/analysis-runs", json={}, headers=auth_headers
    )
    assert start.status_code == 201, start.text
    run = start.json()
    assert run["status"] in {"queued", "running", "succeeded"}
    assert run["artifact_ids"] == [artifact_id]
    assert run["experiment_metadata"]["pipeline_version"] == "mvp-0"

    status_resp = client.get(
        f"/api/incidents/{incident_id}/analysis-runs/{run['id']}", headers=auth_headers
    )
    assert status_resp.status_code == 200
    assert status_resp.json()["status"] == "succeeded"
    assert status_resp.json()["completed_at"] is not None


def test_started_run_locks_artifact_against_delete_and_replace(client: TestClient, auth_headers):
    incident_id = create_incident(client, auth_headers)
    artifact_id = add_artifact(client, auth_headers, incident_id)

    client.post(f"/api/incidents/{incident_id}/analysis-runs", json={}, headers=auth_headers)

    locked = client.get(
        f"/api/incidents/{incident_id}/artifacts/{artifact_id}", headers=auth_headers
    )
    assert locked.json()["included_in_analysis_run"] is True

    delete_resp = client.delete(
        f"/api/incidents/{incident_id}/artifacts/{artifact_id}", headers=auth_headers
    )
    assert delete_resp.status_code == 409

    replace_resp = client.put(
        f"/api/incidents/{incident_id}/artifacts/{artifact_id}",
        json={"source_type": "logs", "source_name": "api.log", "body": "tampered"},
        headers=auth_headers,
    )
    assert replace_resp.status_code == 409


def test_locked_artifact_body_remains_citation_source_of_truth(client: TestClient, auth_headers):
    incident_id = create_incident(client, auth_headers)
    original = "14:28 deploy started\n14:32 api 500s spike"
    artifact_id = add_artifact(client, auth_headers, incident_id, body=original)

    client.post(f"/api/incidents/{incident_id}/analysis-runs", json={}, headers=auth_headers)

    fetched = client.get(
        f"/api/incidents/{incident_id}/artifacts/{artifact_id}", headers=auth_headers
    )
    assert fetched.json()["body"] == original
    assert fetched.json()["lines"][1] == {"number": 2, "text": "14:32 api 500s spike"}


def test_start_run_without_artifacts_is_rejected(client: TestClient, auth_headers):
    incident_id = create_incident(client, auth_headers)
    resp = client.post(
        f"/api/incidents/{incident_id}/analysis-runs", json={}, headers=auth_headers
    )
    assert resp.status_code == 422
    assert resp.json()["detail"] == "cannot start an analysis run without artifacts"


def test_start_run_with_unknown_artifact_returns_404(client: TestClient, auth_headers):
    incident_id = create_incident(client, auth_headers)
    add_artifact(client, auth_headers, incident_id)
    resp = client.post(
        f"/api/incidents/{incident_id}/analysis-runs",
        json={"artifact_ids": ["does-not-exist"]},
        headers=auth_headers,
    )
    assert resp.status_code == 404
    assert resp.json()["detail"] == "artifact not found"


def test_start_run_for_unknown_incident_returns_404(client: TestClient, auth_headers):
    resp = client.post(
        "/api/incidents/does-not-exist/analysis-runs", json={}, headers=auth_headers
    )
    assert resp.status_code == 404


def test_list_runs_returns_started_runs_newest_first(client: TestClient, auth_headers):
    incident_id = create_incident(client, auth_headers)
    add_artifact(client, auth_headers, incident_id)

    first = client.post(
        f"/api/incidents/{incident_id}/analysis-runs", json={}, headers=auth_headers
    ).json()
    second = client.post(
        f"/api/incidents/{incident_id}/analysis-runs", json={}, headers=auth_headers
    ).json()

    resp = client.get(f"/api/incidents/{incident_id}/analysis-runs", headers=auth_headers)
    assert resp.status_code == 200
    ids = [run["id"] for run in resp.json()]
    assert ids[:2] == [second["id"], first["id"]]


def test_unknown_run_returns_404(client: TestClient, auth_headers):
    incident_id = create_incident(client, auth_headers)
    resp = client.get(
        f"/api/incidents/{incident_id}/analysis-runs/nope", headers=auth_headers
    )
    assert resp.status_code == 404


def test_analysis_runs_require_auth(client: TestClient):
    resp = client.get("/api/incidents/whatever/analysis-runs")
    assert resp.status_code == 401
