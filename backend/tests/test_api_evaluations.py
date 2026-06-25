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
    # Four scenarios × two configurations (multi-pass + Builder-Only Baseline).
    assert len(runs) == 8
    # Group by (scenario, mode) so the comparison columns are addressable.
    by_key = {(r["scenario_id"], r["analysis_mode"]): r for r in runs}
    assert {
        "deploy-ambiguity",
        "dependency-failure",
        "config-drift",
        "insufficient-evidence",
    } <= {scenario for scenario, _ in by_key}

    deploy = by_key[("deploy-ambiguity", "multi_pass")]
    assert deploy["passed"] is True
    # Citation validity is a deterministic column, present regardless of the judge.
    assert deploy["citation_verified"] == deploy["citation_total"] > 0
    assert any(c["name"] == "citation_integrity" and c["passed"] for c in deploy["checks"])
    assert any(
        c["name"] == "causal_challenge_coverage" and c["passed"] for c in deploy["checks"]
    )
    assert deploy["warning_code_counts"]
    assert deploy["judge_scores"]["overall"] > 0
    assert deploy["experiment_metadata"]["model_provider"] == "scenario-replay:deploy-ambiguity"
    # Cost metrics are recorded beside the quality signals (PRD #38).
    assert deploy["model_calls"] > 0
    assert deploy["latency_ms"] >= 0
    assert "total_tokens" in deploy

    # The Builder-Only Baseline for the same scenario fails challenge coverage at
    # strictly fewer model calls — the comparison signal the dashboard renders.
    baseline = by_key[("deploy-ambiguity", "builder_only")]
    assert baseline["passed"] is False
    assert any(
        c["name"] == "causal_challenge_coverage" and not c["passed"]
        for c in baseline["checks"]
    )
    # The baseline raises no Counterclaims, so it cannot surface the scenario's
    # known counterevidence — the multi-pass run does (PRD #38).
    assert any(
        c["name"] == "counterevidence_coverage" and c["passed"] for c in deploy["checks"]
    )
    assert any(
        c["name"] == "counterevidence_coverage" and not c["passed"]
        for c in baseline["checks"]
    )
    assert baseline["model_calls"] < deploy["model_calls"]

    refusal = by_key[("insufficient-evidence", "multi_pass")]
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
    assert len(listed.json()) == 8


def test_run_single_scenario(client: TestClient, app, auth_headers):
    app.state.evaluation_judge = FakePostmortemJudge()
    res = client.post(
        "/api/evaluations", json={"scenario_id": "config-drift"}, headers=auth_headers
    )
    assert res.status_code == 201
    runs = res.json()
    # Both configurations of the single scenario are recorded (PRD #38).
    assert len(runs) == 2
    assert {r["scenario_id"] for r in runs} == {"config-drift"}
    assert {r["analysis_mode"] for r in runs} == {"multi_pass", "builder_only"}


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
