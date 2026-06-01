from __future__ import annotations

from fastapi import BackgroundTasks
from fastapi.testclient import TestClient

from postmortem.api.analysis_runs import execute_analysis_run_background, schedule_analysis_run


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


def test_run_status_exposes_six_ordered_stage_events(client: TestClient, auth_headers):
    incident_id = create_incident(client, auth_headers)
    add_artifact(client, auth_headers, incident_id)

    run = client.post(
        f"/api/incidents/{incident_id}/analysis-runs", json={}, headers=auth_headers
    ).json()

    status_resp = client.get(
        f"/api/incidents/{incident_id}/analysis-runs/{run['id']}", headers=auth_headers
    )
    assert status_resp.status_code == 200
    body = status_resp.json()
    stages = [event["stage"] for event in body["stage_events"]]
    assert stages == [
        "normalizing_evidence",
        "extracting_timeline_candidates",
        "generating_rca_hypotheses",
        "verifying_citations",
        "drafting_postmortem",
        "flagging_unsupported_claims",
    ]
    assert all(event["status"] == "succeeded" for event in body["stage_events"])
    assert all(event["duration_ms"] is not None for event in body["stage_events"])
    # Usage stays null until an LLM is wired in (#7); the field exists now.
    assert all(event["usage"] is None for event in body["stage_events"])


def test_run_status_is_terminal_and_pollable_after_start(client: TestClient, auth_headers):
    # The MVP executor runs synchronously, so the very first poll already shows
    # the terminal succeeded state with all six stage events persisted. The
    # contract the UI polls against (status + stage_events) is what we assert.
    incident_id = create_incident(client, auth_headers)
    add_artifact(client, auth_headers, incident_id)
    run = client.post(
        f"/api/incidents/{incident_id}/analysis-runs", json={}, headers=auth_headers
    ).json()

    first_poll = client.get(
        f"/api/incidents/{incident_id}/analysis-runs/{run['id']}", headers=auth_headers
    ).json()
    second_poll = client.get(
        f"/api/incidents/{incident_id}/analysis-runs/{run['id']}", headers=auth_headers
    ).json()

    assert first_poll["status"] == "succeeded"
    assert len(first_poll["stage_events"]) == 6
    # Polling is idempotent: repeated reads return stable terminal state.
    assert second_poll["status"] == "succeeded"
    assert second_poll["stage_events"] == first_poll["stage_events"]


def test_start_run_returns_queued_state_before_background_execution(
    app, client: TestClient, auth_headers
):
    scheduled: list[tuple[object, str]] = []

    def capture_background_task(background_tasks, session_factory, run_id):
        scheduled.append((session_factory, run_id))

    app.state.run_scheduler = capture_background_task

    incident_id = create_incident(client, auth_headers)
    artifact_id = add_artifact(client, auth_headers, incident_id)

    start = client.post(
        f"/api/incidents/{incident_id}/analysis-runs", json={}, headers=auth_headers
    )

    assert start.status_code == 201, start.text
    queued = start.json()
    assert queued["status"] == "queued"
    assert queued["artifact_ids"] == [artifact_id]
    assert queued["stage_events"] == []
    assert len(scheduled) == 1

    first_poll = client.get(
        f"/api/incidents/{incident_id}/analysis-runs/{queued['id']}", headers=auth_headers
    ).json()
    assert first_poll["status"] == "queued"
    assert first_poll["stage_events"] == []

    session_factory, run_id = scheduled[0]
    execute_analysis_run_background(session_factory, run_id)

    terminal = client.get(
        f"/api/incidents/{incident_id}/analysis-runs/{queued['id']}", headers=auth_headers
    ).json()
    assert terminal["status"] == "succeeded"
    assert [event["stage"] for event in terminal["stage_events"]] == [
        "normalizing_evidence",
        "extracting_timeline_candidates",
        "generating_rca_hypotheses",
        "verifying_citations",
        "drafting_postmortem",
        "flagging_unsupported_claims",
    ]


def test_default_scheduler_threads_app_settings_into_background_execution(settings):
    background_tasks = BackgroundTasks()
    session_factory = object()

    schedule_analysis_run(background_tasks, session_factory, "run-id", settings)

    task = background_tasks.tasks[0]
    assert task.args == (session_factory, "run-id", settings)


def test_run_records_chunking_strategy_version(client: TestClient, auth_headers):
    incident_id = create_incident(client, auth_headers)
    add_artifact(client, auth_headers, incident_id)
    run = client.post(
        f"/api/incidents/{incident_id}/analysis-runs", json={}, headers=auth_headers
    ).json()
    assert run["experiment_metadata"]["chunking_strategy"] == "source-aware-1"


def test_timeline_endpoint_returns_sorted_cited_events(client: TestClient, auth_headers):
    incident_id = create_incident(client, auth_headers)
    add_artifact(
        client,
        auth_headers,
        incident_id,
        body=(
            "2026-05-09T14:32:02Z api 500 rate climbing\n"
            "2026-05-09T14:28:31Z deploy v184 rolled out"
        ),
    )
    run = client.post(
        f"/api/incidents/{incident_id}/analysis-runs", json={}, headers=auth_headers
    ).json()

    resp = client.get(
        f"/api/incidents/{incident_id}/analysis-runs/{run['id']}/timeline",
        headers=auth_headers,
    )
    assert resp.status_code == 200
    events = resp.json()
    assert [e["sequence"] for e in events] == [1, 2]
    # Chronological: the 14:28 event sorts before the 14:32 event.
    assert events[0]["normalized_ts"] < events[1]["normalized_ts"]
    first_ref = events[0]["evidence_refs"][0]
    assert first_ref["line_start"] == 2  # the 14:28 line is line 2 of the body
    assert first_ref["snippet"] == "2026-05-09T14:28:31Z deploy v184 rolled out"
    assert first_ref["confidence_score"] == 1.0


def test_timeline_endpoint_marks_inferred_timestamps_uncertain(client: TestClient, auth_headers):
    incident_id = create_incident(client, auth_headers)
    add_artifact(client, auth_headers, incident_id, body="14:40 dashboards went red")
    run = client.post(
        f"/api/incidents/{incident_id}/analysis-runs", json={}, headers=auth_headers
    ).json()

    events = client.get(
        f"/api/incidents/{incident_id}/analysis-runs/{run['id']}/timeline",
        headers=auth_headers,
    ).json()
    assert len(events) == 1
    assert events[0]["uncertain"] is True
    assert events[0]["normalized_ts"] is None
    assert events[0]["original_ts_text"] == "14:40"


def test_timeline_endpoint_unknown_run_returns_404(client: TestClient, auth_headers):
    incident_id = create_incident(client, auth_headers)
    resp = client.get(
        f"/api/incidents/{incident_id}/analysis-runs/nope/timeline", headers=auth_headers
    )
    assert resp.status_code == 404


def test_timeline_endpoint_requires_auth(client: TestClient):
    resp = client.get("/api/incidents/x/analysis-runs/y/timeline")
    assert resp.status_code == 401
