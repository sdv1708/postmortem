from __future__ import annotations

from fastapi.testclient import TestClient

def test_create_and_fetch_incident(client: TestClient, auth_headers):
    payload = {
        "title": "  Deploy ambiguity API spike  ",
        "summary": "  Checkout latency increased after deploy.  ",
        "severity": "sev2",
    }
    create_resp = client.post("/api/incidents", json=payload, headers=auth_headers)
    assert create_resp.status_code == 201, create_resp.text
    body = create_resp.json()
    assert body["title"] == "Deploy ambiguity API spike"
    assert body["summary"] == "Checkout latency increased after deploy."
    assert body["severity"] == "sev2"
    assert body["status"] == "open"
    assert body["workspace_id"]
    incident_id = body["id"]

    get_resp = client.get(f"/api/incidents/{incident_id}", headers=auth_headers)
    assert get_resp.status_code == 200
    assert get_resp.json()["id"] == incident_id


def test_list_includes_created_incident(client: TestClient, auth_headers):
    client.post("/api/incidents", json={"title": "one"}, headers=auth_headers)
    client.post("/api/incidents", json={"title": "two"}, headers=auth_headers)

    list_resp = client.get("/api/incidents", headers=auth_headers)
    assert list_resp.status_code == 200
    titles = [i["title"] for i in list_resp.json()]
    assert titles == ["two", "one"]


def test_missing_token_is_rejected(client: TestClient):
    resp = client.get("/api/incidents")
    assert resp.status_code == 401


def test_wrong_token_is_rejected(client: TestClient):
    resp = client.get("/api/incidents", headers={"Authorization": "Bearer nope"})
    assert resp.status_code == 401


def test_unknown_incident_returns_404(client: TestClient, auth_headers):
    resp = client.get("/api/incidents/does-not-exist", headers=auth_headers)
    assert resp.status_code == 404


def test_delete_created_incident(client: TestClient, auth_headers):
    create_resp = client.post(
        "/api/incidents",
        json={"title": "discard me"},
        headers=auth_headers,
    )
    assert create_resp.status_code == 201, create_resp.text
    incident_id = create_resp.json()["id"]

    delete_resp = client.delete(f"/api/incidents/{incident_id}", headers=auth_headers)
    assert delete_resp.status_code == 204

    get_resp = client.get(f"/api/incidents/{incident_id}", headers=auth_headers)
    assert get_resp.status_code == 404


def test_delete_unknown_incident_returns_404(client: TestClient, auth_headers):
    resp = client.delete("/api/incidents/does-not-exist", headers=auth_headers)
    assert resp.status_code == 404


def test_delete_incident_with_analysis_run(client: TestClient, auth_headers):
    create_resp = client.post(
        "/api/incidents",
        json={"title": "delete analysis history"},
        headers=auth_headers,
    )
    assert create_resp.status_code == 201, create_resp.text
    incident_id = create_resp.json()["id"]
    artifact_resp = client.post(
        f"/api/incidents/{incident_id}/artifacts",
        json={"source_type": "logs", "source_name": "api.log", "body": "14:32 errors"},
        headers=auth_headers,
    )
    assert artifact_resp.status_code == 201, artifact_resp.text
    run_resp = client.post(
        f"/api/incidents/{incident_id}/analysis-runs",
        json={},
        headers=auth_headers,
    )
    assert run_resp.status_code == 201, run_resp.text

    delete_resp = client.delete(f"/api/incidents/{incident_id}", headers=auth_headers)
    assert delete_resp.status_code == 204, delete_resp.text

    get_resp = client.get(f"/api/incidents/{incident_id}", headers=auth_headers)
    assert get_resp.status_code == 404


def test_update_incident_status_sets_resolved_at(client: TestClient, auth_headers):
    create_resp = client.post(
        "/api/incidents",
        json={"title": "advance me"},
        headers=auth_headers,
    )
    assert create_resp.status_code == 201, create_resp.text
    incident_id = create_resp.json()["id"]
    assert create_resp.json()["status"] == "open"
    assert create_resp.json()["resolved_at"] is None

    resolve_resp = client.patch(
        f"/api/incidents/{incident_id}",
        json={"status": "resolved"},
        headers=auth_headers,
    )
    assert resolve_resp.status_code == 200, resolve_resp.text
    assert resolve_resp.json()["status"] == "resolved"
    assert resolve_resp.json()["resolved_at"] is not None

    # Moving back to an active state clears resolved_at so it never contradicts status.
    reopen_resp = client.patch(
        f"/api/incidents/{incident_id}",
        json={"status": "investigating"},
        headers=auth_headers,
    )
    assert reopen_resp.status_code == 200, reopen_resp.text
    assert reopen_resp.json()["status"] == "investigating"
    assert reopen_resp.json()["resolved_at"] is None


def test_update_unknown_incident_returns_404(client: TestClient, auth_headers):
    resp = client.patch(
        "/api/incidents/does-not-exist",
        json={"status": "resolved"},
        headers=auth_headers,
    )
    assert resp.status_code == 404


def test_update_incident_invalid_status_rejected(client: TestClient, auth_headers):
    create_resp = client.post(
        "/api/incidents", json={"title": "bad status"}, headers=auth_headers
    )
    incident_id = create_resp.json()["id"]
    resp = client.patch(
        f"/api/incidents/{incident_id}",
        json={"status": "done"},
        headers=auth_headers,
    )
    assert resp.status_code == 422


def test_dev_bypass_allows_unauthenticated(dev_bypass_app):
    with TestClient(dev_bypass_app) as c:
        resp = c.post("/api/incidents", json={"title": "no auth"})
        assert resp.status_code == 201
        assert c.get("/api/incidents").status_code == 200


def test_invalid_severity_rejected(client: TestClient, auth_headers):
    resp = client.post(
        "/api/incidents",
        json={"title": "bad sev", "severity": "sev99"},
        headers=auth_headers,
    )
    assert resp.status_code == 422
