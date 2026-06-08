from __future__ import annotations

from fastapi.testclient import TestClient


def test_list_scenarios_requires_auth(client: TestClient):
    assert client.get("/api/scenarios").status_code == 401


def test_list_scenarios_returns_the_canonical_demo(client: TestClient, auth_headers):
    res = client.get("/api/scenarios", headers=auth_headers)
    assert res.status_code == 200
    scenarios = res.json()
    canonical = next(s for s in scenarios if s["id"] == "deploy-ambiguity")
    assert canonical["evidence_count"] == 4
    assert canonical["severity"] == "sev2"
    assert "deploy-regression" in canonical["expected_hypothesis_families"]


def test_seed_unknown_scenario_returns_404(client: TestClient, auth_headers):
    res = client.post("/api/scenarios/nope/seed", headers=auth_headers)
    assert res.status_code == 404


def test_seed_scenario_populates_the_review_surface(client: TestClient, auth_headers):
    res = client.post("/api/scenarios/deploy-ambiguity/seed", headers=auth_headers)
    assert res.status_code == 201
    body = res.json()
    assert body["run_status"] == "succeeded"
    incident_id = body["incident_id"]
    run_id = body["run_id"]

    # The seeded incident exists with its four evidence artifacts.
    artifacts = client.get(
        f"/api/incidents/{incident_id}/artifacts", headers=auth_headers
    ).json()
    assert len(artifacts) == 4

    # The Review Surface endpoints serve a multi-hypothesis postmortem with
    # exact, verified citations (the core differentiator, ADR 0002).
    hypotheses = client.get(
        f"/api/incidents/{incident_id}/analysis-runs/{run_id}/hypotheses",
        headers=auth_headers,
    ).json()
    assert len(hypotheses) == 3
    top = hypotheses[0]
    assert top["supporting_evidence"]
    assert top["contradicting_evidence"]
    assert all(
        ref["verifier_status"] == "verified" for ref in top["supporting_evidence"]
    )

    postmortem = client.get(
        f"/api/incidents/{incident_id}/analysis-runs/{run_id}/postmortem",
        headers=auth_headers,
    )
    assert postmortem.status_code == 200
    assert postmortem.json()["summary"]
