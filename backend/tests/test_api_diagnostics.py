"""API tests for the restricted run-diagnostics resource (ADR 0038, PRD #26).

The diagnostics endpoint exposes reasoning/retrieval provenance for one run —
component versions, ordered retrieved Chunk references, token usage, hashes, and
structured outcomes — behind the single-user gate, without changing the normal
Review Surface workflow.
"""

from __future__ import annotations

import json

from fastapi.testclient import TestClient

from postmortem.llm import FakeLLMClient
from postmortem.services import AnalysisService

from tests._fakes import (
    FakeClaimSupportVerifier,
    FakeFalsifier,
    FakeIncidentFactExtractor,
)


MARKER = "ZZSENSITIVEMARKERZZ"


def _create_incident(client: TestClient, auth_headers, title="Diag incident") -> str:
    resp = client.post("/api/incidents", json={"title": title}, headers=auth_headers)
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


def _add_artifact(client: TestClient, auth_headers, incident_id: str) -> str:
    resp = client.post(
        f"/api/incidents/{incident_id}/artifacts",
        json={
            "source_type": "logs",
            "source_name": "api.log",
            "body": f"alpha {MARKER} line\nbeta line",
        },
        headers=auth_headers,
    )
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


def _seed_run(app, client, auth_headers):
    """Queue a run over HTTP, then execute it with seeded fakes in the app DB."""
    captured: list[str] = []
    app.state.run_scheduler = lambda background_tasks, session_factory, run_id: captured.append(
        run_id
    )
    incident_id = _create_incident(client, auth_headers)
    artifact_id = _add_artifact(client, auth_headers, incident_id)
    start = client.post(
        f"/api/incidents/{incident_id}/analysis-runs", json={}, headers=auth_headers
    )
    assert start.status_code == 201, start.text
    run_id = start.json()["id"]

    builder = json.dumps(
        {
            "hypotheses": [
                {
                    "title": "Primary cause",
                    "summary": "Most-supported explanation.",
                    "supporting_evidence": [
                        {"artifact_id": artifact_id, "line_start": 1, "line_end": 1}
                    ],
                }
            ]
        }
    )
    session = app.state.session_factory()
    try:
        run = AnalysisService(
            session,
            llm_client=FakeLLMClient([builder], label="fake-model", usage={"total_tokens": 9}),
            claim_support_verifier=FakeClaimSupportVerifier(),
            incident_fact_extractor=FakeIncidentFactExtractor(),
            falsifier=FakeFalsifier(),
        ).execute_run(run_id, commit_progress=True)
        assert run.status == "succeeded"
        session.commit()
    finally:
        session.close()
    return incident_id, run_id


def test_diagnostics_exposes_model_calls_and_retrieval_traces(app, client, auth_headers):
    incident_id, run_id = _seed_run(app, client, auth_headers)

    resp = client.get(
        f"/api/incidents/{incident_id}/analysis-runs/{run_id}/diagnostics",
        headers=auth_headers,
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["run_id"] == run_id

    roles = {r["role"] for r in body["model_call_records"]}
    assert {"incident_facts", "builder", "falsifier", "support_verifier", "ranker"} <= roles

    builder = next(r for r in body["model_call_records"] if r["role"] == "builder")
    assert builder["model_identity"] == "fake-model"
    assert builder["prompt_version"] == "rca-4"
    assert builder["schema_version"] == "rca-output-1"
    assert builder["input_hash"] and builder["output_hash"]
    assert builder["usage"] == {"total_tokens": 9}
    assert builder["retrieval_trace_id"] is not None

    # Retrieval Traces carry ordered chunk references with cited/total counts.
    assert body["retrieval_traces"]
    builder_trace = next(t for t in body["retrieval_traces"] if t["role"] == "builder")
    assert builder_trace["chunk_count"] >= 1
    assert builder_trace["cited_count"] <= builder_trace["chunk_count"]
    assert builder_trace["chunks"]
    assert builder_trace["strategy_version"]


def test_diagnostics_does_not_leak_sensitive_evidence(app, client, auth_headers):
    incident_id, run_id = _seed_run(app, client, auth_headers)
    resp = client.get(
        f"/api/incidents/{incident_id}/analysis-runs/{run_id}/diagnostics",
        headers=auth_headers,
    )
    assert resp.status_code == 200, resp.text
    # The diagnostics payload exposes references and hashes only — never the
    # artifact text, prompts, or raw responses (PRD user stories 71, 73).
    assert MARKER not in resp.text


def test_diagnostics_requires_authentication(app, client):
    incident_id, run_id = _seed_run(app, client, {"Authorization": "Bearer test-token"})
    resp = client.get(
        f"/api/incidents/{incident_id}/analysis-runs/{run_id}/diagnostics"
    )
    assert resp.status_code == 401, resp.text


def test_diagnostics_404_for_run_in_another_incident(app, client, auth_headers):
    incident_id, run_id = _seed_run(app, client, auth_headers)
    other_incident = _create_incident(client, auth_headers, title="Other incident")
    resp = client.get(
        f"/api/incidents/{other_incident}/analysis-runs/{run_id}/diagnostics",
        headers=auth_headers,
    )
    assert resp.status_code == 404, resp.text
