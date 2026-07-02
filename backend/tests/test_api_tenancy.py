"""Per-visitor data isolation (anonymous session workspaces, ADR 0017).

The frontend BFF proxy sends an opaque ``X-Postmortem-Session`` header; the
backend maps it to a private Workspace so one visitor never sees another's
incidents. These tests drive the API with different session headers and assert
the boundary holds across the incident surface and its nested resources.
"""

from __future__ import annotations

from fastapi.testclient import TestClient


def _auth(session_id: str | None = None) -> dict[str, str]:
    headers = {"Authorization": "Bearer test-token"}
    if session_id is not None:
        headers["X-Postmortem-Session"] = session_id
    return headers


def _create_incident(client: TestClient, session_id: str, title: str) -> str:
    resp = client.post("/api/incidents", json={"title": title}, headers=_auth(session_id))
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


def test_incident_list_is_isolated_per_session(client: TestClient):
    a_id = _create_incident(client, "alice", "Alice incident")
    b_id = _create_incident(client, "bob", "Bob incident")

    alice = client.get("/api/incidents", headers=_auth("alice"))
    bob = client.get("/api/incidents", headers=_auth("bob"))
    assert {i["id"] for i in alice.json()} == {a_id}
    assert {i["id"] for i in bob.json()} == {b_id}


def test_cross_session_incident_access_is_404(client: TestClient):
    a_id = _create_incident(client, "alice", "Alice incident")

    # Bob cannot read, update, or delete Alice's incident — indistinguishable
    # from not-found (no existence leak).
    assert client.get(f"/api/incidents/{a_id}", headers=_auth("bob")).status_code == 404
    assert (
        client.patch(
            f"/api/incidents/{a_id}", json={"severity": "sev1"}, headers=_auth("bob")
        ).status_code
        == 404
    )
    assert client.delete(f"/api/incidents/{a_id}", headers=_auth("bob")).status_code == 404
    # Alice still has full access to her own.
    assert client.get(f"/api/incidents/{a_id}", headers=_auth("alice")).status_code == 200


def test_nested_resources_are_guarded_across_sessions(client: TestClient):
    a_id = _create_incident(client, "alice", "Alice incident")

    # The router-level ownership guard blocks Bob from every nested route.
    assert (
        client.get(f"/api/incidents/{a_id}/artifacts", headers=_auth("bob")).status_code == 404
    )
    assert (
        client.post(
            f"/api/incidents/{a_id}/artifacts",
            json={"source_type": "logs", "source_name": "x.log", "body": "line"},
            headers=_auth("bob"),
        ).status_code
        == 404
    )
    assert (
        client.get(f"/api/incidents/{a_id}/analysis-runs", headers=_auth("bob")).status_code
        == 404
    )
    # Alice can use her own nested routes.
    assert (
        client.get(f"/api/incidents/{a_id}/artifacts", headers=_auth("alice")).status_code == 200
    )


def test_seeded_scenario_lands_in_callers_workspace(client: TestClient):
    seeded = client.post("/api/scenarios/deploy-ambiguity/seed", headers=_auth("alice"))
    assert seeded.status_code == 201, seeded.text
    incident_id = seeded.json()["incident_id"]

    assert incident_id in {i["id"] for i in client.get("/api/incidents", headers=_auth("alice")).json()}
    assert incident_id not in {i["id"] for i in client.get("/api/incidents", headers=_auth("bob")).json()}


def test_no_session_header_uses_shared_default_workspace(client: TestClient):
    # Backwards compatible: a request without a session header still works, landing
    # in the shared default workspace (the anonymous bucket).
    resp = client.post("/api/incidents", json={"title": "Anon"}, headers=_auth())
    assert resp.status_code == 201, resp.text
    anon_id = resp.json()["id"]
    listed = client.get("/api/incidents", headers=_auth())
    assert anon_id in {i["id"] for i in listed.json()}
