from __future__ import annotations

from fastapi.testclient import TestClient

from tests._fakes import FakePostmortemJudge


def test_evaluations_require_auth(client: TestClient):
    assert client.get("/api/evaluations").status_code == 401
    assert client.post("/api/evaluations", json={}).status_code == 401


def test_run_all_scenarios_and_list_them(client: TestClient, app, auth_headers):
    # Inject a deterministic judge so the dashboard shows judge scores offline.
    app.state.evaluation_judge = FakePostmortemJudge()

    res = client.post("/api/evaluations", json={}, headers=auth_headers)
    assert res.status_code == 201
    runs = res.json()
    assert len(runs) == 4
    by_scenario = {r["scenario_id"]: r for r in runs}
    assert {
        "deploy-ambiguity",
        "dependency-failure",
        "config-drift",
        "insufficient-evidence",
    } <= set(by_scenario)

    deploy = by_scenario["deploy-ambiguity"]
    assert deploy["passed"] is True
    # Citation validity is a deterministic column, present regardless of the judge.
    assert deploy["citation_verified"] == deploy["citation_total"] > 0
    assert any(c["name"] == "citation_integrity" and c["passed"] for c in deploy["checks"])
    assert deploy["warning_code_counts"]
    assert deploy["judge_scores"]["overall"] > 0
    assert deploy["experiment_metadata"]["model_provider"] == "scenario-replay:deploy-ambiguity"

    refusal = by_scenario["insufficient-evidence"]
    assert refusal["passed"] is True
    assert refusal["citation_total"] == 0
    assert refusal["citation_verified"] == 0
    assert any(
        c["name"] == "hypothesis_multiplicity"
        and c["passed"]
        and "expected refusal" in c["detail"]
        for c in refusal["checks"]
    )

    listed = client.get("/api/evaluations", headers=auth_headers)
    assert listed.status_code == 200
    assert len(listed.json()) == 4


def test_run_single_scenario(client: TestClient, app, auth_headers):
    app.state.evaluation_judge = FakePostmortemJudge()
    res = client.post(
        "/api/evaluations", json={"scenario_id": "config-drift"}, headers=auth_headers
    )
    assert res.status_code == 201
    runs = res.json()
    assert len(runs) == 1
    assert runs[0]["scenario_id"] == "config-drift"


def test_unknown_scenario_returns_404(client: TestClient, auth_headers):
    res = client.post(
        "/api/evaluations", json={"scenario_id": "ghost"}, headers=auth_headers
    )
    assert res.status_code == 404


def test_judge_is_not_required_for_citation_validity(client: TestClient, auth_headers):
    # No judge injected and no model configured (test settings) → judge_scores is
    # null, but the deterministic citation floor is still reported (ADR 0010).
    res = client.post(
        "/api/evaluations", json={"scenario_id": "deploy-ambiguity"}, headers=auth_headers
    )
    assert res.status_code == 201
    run = res.json()[0]
    assert run["judge_scores"] is None
    assert run["judge_version"] is None
    assert run["passed"] is True
    assert run["citation_verified"] == run["citation_total"] > 0
