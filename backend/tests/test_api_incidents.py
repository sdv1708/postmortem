from __future__ import annotations

from fastapi.testclient import TestClient


def test_create_and_fetch_incident(client: TestClient, auth_headers):
    payload = {"title": "Deploy ambiguity API spike", "severity": "sev2"}
    create_resp = client.post("/api/incidents", json=payload, headers=auth_headers)
    assert create_resp.status_code == 201, create_resp.text
    body = create_resp.json()
    assert body["title"] == payload["title"]
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
