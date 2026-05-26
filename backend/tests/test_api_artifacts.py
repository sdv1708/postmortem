from __future__ import annotations

from fastapi.testclient import TestClient

from postmortem.models import Artifact


def create_incident(client: TestClient, auth_headers) -> str:
    resp = client.post("/api/incidents", json={"title": "Artifact test incident"}, headers=auth_headers)
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


def test_create_and_fetch_artifact_with_line_numbers(client: TestClient, auth_headers):
    incident_id = create_incident(client, auth_headers)

    create_resp = client.post(
        f"/api/incidents/{incident_id}/artifacts",
        json={
            "source_type": "logs",
            "source_name": "api.log",
            "body": "first line\r\nsecond line\nthird line",
        },
        headers=auth_headers,
    )

    assert create_resp.status_code == 201, create_resp.text
    body = create_resp.json()
    assert body["source_type"] == "logs"
    assert body["source_name"] == "api.log"
    assert body["body"] == "first line\nsecond line\nthird line"
    assert body["line_count"] == 3
    assert body["lines"] == [
        {"number": 1, "text": "first line"},
        {"number": 2, "text": "second line"},
        {"number": 3, "text": "third line"},
    ]

    artifact_id = body["id"]
    get_resp = client.get(
        f"/api/incidents/{incident_id}/artifacts/{artifact_id}",
        headers=auth_headers,
    )
    assert get_resp.status_code == 200
    assert get_resp.json()["id"] == artifact_id
    assert get_resp.json()["lines"][1] == {"number": 2, "text": "second line"}


def test_list_artifacts_requires_existing_incident(client: TestClient, auth_headers):
    resp = client.get("/api/incidents/does-not-exist/artifacts", headers=auth_headers)
    assert resp.status_code == 404
    assert resp.json()["detail"] == "incident not found"


def test_list_artifacts_returns_created_artifacts(client: TestClient, auth_headers):
    incident_id = create_incident(client, auth_headers)
    client.post(
        f"/api/incidents/{incident_id}/artifacts",
        json={"source_type": "incident_notes", "source_name": "notes", "body": "note"},
        headers=auth_headers,
    )
    client.post(
        f"/api/incidents/{incident_id}/artifacts",
        json={"source_type": "deployment_notes", "source_name": "deploy", "body": "deploy"},
        headers=auth_headers,
    )

    resp = client.get(f"/api/incidents/{incident_id}/artifacts", headers=auth_headers)
    assert resp.status_code == 200
    artifacts = resp.json()
    assert [artifact["source_name"] for artifact in artifacts] == ["notes", "deploy"]


def test_delete_artifact_before_analysis_use(client: TestClient, auth_headers):
    incident_id = create_incident(client, auth_headers)
    create_resp = client.post(
        f"/api/incidents/{incident_id}/artifacts",
        json={"source_type": "logs", "source_name": "api.log", "body": "line"},
        headers=auth_headers,
    )
    artifact_id = create_resp.json()["id"]

    delete_resp = client.delete(
        f"/api/incidents/{incident_id}/artifacts/{artifact_id}",
        headers=auth_headers,
    )
    assert delete_resp.status_code == 204

    get_resp = client.get(
        f"/api/incidents/{incident_id}/artifacts/{artifact_id}",
        headers=auth_headers,
    )
    assert get_resp.status_code == 404


def test_replace_artifact_before_analysis_use(client: TestClient, auth_headers):
    incident_id = create_incident(client, auth_headers)
    create_resp = client.post(
        f"/api/incidents/{incident_id}/artifacts",
        json={"source_type": "logs", "source_name": "old.log", "body": "old"},
        headers=auth_headers,
    )
    artifact_id = create_resp.json()["id"]

    replace_resp = client.put(
        f"/api/incidents/{incident_id}/artifacts/{artifact_id}",
        json={"source_type": "stack_trace", "source_name": "trace.txt", "body": "frame 1\nframe 2"},
        headers=auth_headers,
    )

    assert replace_resp.status_code == 200, replace_resp.text
    body = replace_resp.json()
    assert body["source_type"] == "stack_trace"
    assert body["source_name"] == "trace.txt"
    assert body["body"] == "frame 1\nframe 2"
    assert body["line_count"] == 2


def test_delete_and_replace_locked_artifact_return_conflict(client: TestClient, session, auth_headers):
    incident_id = create_incident(client, auth_headers)
    create_resp = client.post(
        f"/api/incidents/{incident_id}/artifacts",
        json={"source_type": "logs", "source_name": "api.log", "body": "line"},
        headers=auth_headers,
    )
    artifact_id = create_resp.json()["id"]
    artifact = session.get(Artifact, artifact_id)
    assert artifact is not None
    artifact.included_in_analysis_run = True
    session.commit()

    delete_resp = client.delete(
        f"/api/incidents/{incident_id}/artifacts/{artifact_id}",
        headers=auth_headers,
    )
    assert delete_resp.status_code == 409

    replace_resp = client.put(
        f"/api/incidents/{incident_id}/artifacts/{artifact_id}",
        json={"source_type": "logs", "source_name": "api.log", "body": "new"},
        headers=auth_headers,
    )
    assert replace_resp.status_code == 409


def test_artifact_cannot_be_created_for_unknown_incident(client: TestClient, auth_headers):
    resp = client.post(
        "/api/incidents/does-not-exist/artifacts",
        json={"source_type": "logs", "source_name": "api.log", "body": "line"},
        headers=auth_headers,
    )
    assert resp.status_code == 404


def test_empty_artifact_body_is_rejected(client: TestClient, auth_headers):
    incident_id = create_incident(client, auth_headers)
    resp = client.post(
        f"/api/incidents/{incident_id}/artifacts",
        json={"source_type": "logs", "source_name": "api.log", "body": ""},
        headers=auth_headers,
    )
    assert resp.status_code == 422
