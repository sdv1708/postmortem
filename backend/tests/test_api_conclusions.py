from __future__ import annotations

import json

from fastapi.testclient import TestClient

from postmortem.incident_facts import FactsImpactClaim
from postmortem.llm import FakeLLMClient
from postmortem.rca import RcaEvidenceRef
from postmortem.services import AnalysisService
from postmortem.verification import ClaimSupportJudgment, ClaimSupportStatus

from tests._fakes import (
    FakeClaimSupportVerifier,
    FakeFalsifier,
    FakeIncidentFactExtractor,
)


def _partial_verifier(*titles):
    wanted = set(titles)

    def judge(claim):
        for title in wanted:
            if claim.claim_text.startswith(title):
                return ClaimSupportJudgment(ClaimSupportStatus.PARTIAL, "Partly shown.")
        return ClaimSupportJudgment(ClaimSupportStatus.SUPPORTED, "ok")

    return FakeClaimSupportVerifier(judge)


def _seed_succeeded_run(
    app,
    client,
    auth_headers,
    *,
    titles=("Primary cause", "Alternative cause"),
    verifier=None,
    falsifier=None,
):
    """Queue a run via HTTP, then execute it with seeded fakes (mirrors hypotheses tests)."""
    captured: list[str] = []
    app.state.run_scheduler = lambda background_tasks, session_factory, run_id: captured.append(
        run_id
    )

    incident_resp = client.post("/api/incidents", json={"title": "Conc"}, headers=auth_headers)
    incident_id = incident_resp.json()["id"]
    artifact_resp = client.post(
        f"/api/incidents/{incident_id}/artifacts",
        json={
            "source_type": "logs",
            "source_name": "api.log",
            "body": "alpha line\nbeta line\ngamma line\ndelta line",
        },
        headers=auth_headers,
    )
    artifact_id = artifact_resp.json()["id"]
    start = client.post(
        f"/api/incidents/{incident_id}/analysis-runs", json={}, headers=auth_headers
    )
    run_id = start.json()["id"]

    payload = json.dumps(
        {
            "hypotheses": [
                {
                    "title": title,
                    "summary": f"{title} explanation.",
                    "supporting_evidence": [
                        {"artifact_id": artifact_id, "line_start": index + 1, "line_end": index + 1}
                    ],
                }
                for index, title in enumerate(titles)
            ]
        }
    )
    impact = [
        FactsImpactClaim(
            description="Customers errored",
            evidence=[RcaEvidenceRef(artifact_id=artifact_id, line_start=1, line_end=1)],
        )
    ]
    session = app.state.session_factory()
    try:
        run = AnalysisService(
            session,
            llm_client=FakeLLMClient([payload], label="fake-model"),
            claim_support_verifier=verifier or FakeClaimSupportVerifier(),
            incident_fact_extractor=FakeIncidentFactExtractor(impact),
            falsifier=falsifier or FakeFalsifier(),
        ).execute_run(run_id, commit_progress=True)
        assert run.status == "succeeded"
        session.commit()
    finally:
        session.close()
    return incident_id, run_id


def _hypotheses(client, auth_headers, incident_id, run_id):
    resp = client.get(
        f"/api/incidents/{incident_id}/analysis-runs/{run_id}/hypotheses", headers=auth_headers
    )
    return {h["title"]: h for h in resp.json()}


def _accept(client, auth_headers, incident_id, run_id, hypothesis_id):
    resp = client.post(
        f"/api/incidents/{incident_id}/analysis-runs/{run_id}/hypotheses/{hypothesis_id}/review",
        json={"decision": "accepted"},
        headers=auth_headers,
    )
    assert resp.status_code == 200, resp.text


def _conclusion_url(incident_id, run_id):
    return f"/api/incidents/{incident_id}/analysis-runs/{run_id}/conclusion"


def test_finalize_conclusion_records_human_decision(app, client: TestClient, auth_headers):
    incident_id, run_id = _seed_succeeded_run(app, client, auth_headers)
    hyps = _hypotheses(client, auth_headers, incident_id, run_id)
    _accept(client, auth_headers, incident_id, run_id, hyps["Primary cause"]["id"])

    resp = client.post(
        _conclusion_url(incident_id, run_id),
        json={
            "summary": "The deploy regressed connection handling.",
            "factors": [
                {"hypothesis_id": hyps["Primary cause"]["id"], "role": "failure_mechanism"}
            ],
        },
        headers=auth_headers,
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["incident_id"] == incident_id
    assert body["run_id"] == run_id
    # Conclusion Provenance: the single-user gate's default principal (ADR 0017/0039).
    assert body["finalized_by"] == "single-user"
    assert body["failure_mechanism"]["title"] == "Primary cause"
    assert body["failure_mechanism"]["supporting_evidence"][0]["verifier_status"] == "verified"
    assert body["triggers"] == []
    assert body["amplifying_conditions"] == []

    # The postmortem read now exposes the finalized conclusion, distinct from the
    # advisory hypotheses, and the provisional draft state is gone.
    pm = client.get(
        f"/api/incidents/{incident_id}/analysis-runs/{run_id}/postmortem", headers=auth_headers
    ).json()
    assert pm["conclusion_status"] == "finalized"
    assert pm["conclusion"]["failure_mechanism"]["title"] == "Primary cause"

    # The GET resource returns the same conclusion.
    got = client.get(_conclusion_url(incident_id, run_id), headers=auth_headers)
    assert got.status_code == 200
    assert got.json()["id"] == body["id"]


def test_finalize_requires_exactly_one_failure_mechanism(app, client: TestClient, auth_headers):
    incident_id, run_id = _seed_succeeded_run(app, client, auth_headers)
    hyps = _hypotheses(client, auth_headers, incident_id, run_id)
    _accept(client, auth_headers, incident_id, run_id, hyps["Primary cause"]["id"])
    _accept(client, auth_headers, incident_id, run_id, hyps["Alternative cause"]["id"])

    # Zero failure mechanisms.
    zero = client.post(
        _conclusion_url(incident_id, run_id),
        json={
            "summary": "x",
            "factors": [{"hypothesis_id": hyps["Primary cause"]["id"], "role": "trigger"}],
        },
        headers=auth_headers,
    )
    assert zero.status_code == 422, zero.text

    # Two failure mechanisms.
    two = client.post(
        _conclusion_url(incident_id, run_id),
        json={
            "summary": "x",
            "factors": [
                {"hypothesis_id": hyps["Primary cause"]["id"], "role": "failure_mechanism"},
                {"hypothesis_id": hyps["Alternative cause"]["id"], "role": "failure_mechanism"},
            ],
        },
        headers=auth_headers,
    )
    assert two.status_code == 422, two.text


def test_finalize_rejects_unaccepted_hypothesis(app, client: TestClient, auth_headers):
    incident_id, run_id = _seed_succeeded_run(app, client, auth_headers)
    hyps = _hypotheses(client, auth_headers, incident_id, run_id)  # none accepted
    resp = client.post(
        _conclusion_url(incident_id, run_id),
        json={
            "summary": "x",
            "factors": [
                {"hypothesis_id": hyps["Primary cause"]["id"], "role": "failure_mechanism"}
            ],
        },
        headers=auth_headers,
    )
    assert resp.status_code == 422
    assert "accepted" in resp.json()["detail"]


def test_finalize_rejects_cross_run_hypothesis(app, client: TestClient, auth_headers):
    incident_id, run_id = _seed_succeeded_run(app, client, auth_headers)
    other_incident_id, other_run_id = _seed_succeeded_run(app, client, auth_headers)
    other = _hypotheses(client, auth_headers, other_incident_id, other_run_id)["Primary cause"]
    _accept(client, auth_headers, other_incident_id, other_run_id, other["id"])

    resp = client.post(
        _conclusion_url(incident_id, run_id),
        json={
            "summary": "x",
            "factors": [{"hypothesis_id": other["id"], "role": "failure_mechanism"}],
        },
        headers=auth_headers,
    )
    assert resp.status_code == 404
    assert resp.json()["detail"] == "hypothesis not found"


def test_finalize_is_immutable(app, client: TestClient, auth_headers):
    incident_id, run_id = _seed_succeeded_run(app, client, auth_headers)
    hyps = _hypotheses(client, auth_headers, incident_id, run_id)
    _accept(client, auth_headers, incident_id, run_id, hyps["Primary cause"]["id"])
    body = {
        "summary": "first",
        "factors": [{"hypothesis_id": hyps["Primary cause"]["id"], "role": "failure_mechanism"}],
    }
    first = client.post(_conclusion_url(incident_id, run_id), json=body, headers=auth_headers)
    assert first.status_code == 201

    # A second finalization is a conflict — the conclusion is immutable (ADR 0039).
    second = client.post(_conclusion_url(incident_id, run_id), json=body, headers=auth_headers)
    assert second.status_code == 409

    # No in-place edit or delete path exists.
    assert client.put(
        _conclusion_url(incident_id, run_id), json=body, headers=auth_headers
    ).status_code == 405
    assert client.delete(
        _conclusion_url(incident_id, run_id), headers=auth_headers
    ).status_code == 405


def test_get_conclusion_404_before_finalization(app, client: TestClient, auth_headers):
    incident_id, run_id = _seed_succeeded_run(app, client, auth_headers)
    resp = client.get(_conclusion_url(incident_id, run_id), headers=auth_headers)
    assert resp.status_code == 404
    assert "no finalized root cause conclusion" in resp.json()["detail"]


def test_finalized_conclusion_appears_in_clean_export(app, client: TestClient, auth_headers):
    incident_id, run_id = _seed_succeeded_run(app, client, auth_headers)
    hyps = _hypotheses(client, auth_headers, incident_id, run_id)
    _accept(client, auth_headers, incident_id, run_id, hyps["Primary cause"]["id"])
    client.post(
        _conclusion_url(incident_id, run_id),
        json={
            "summary": "The deploy regressed connection handling.",
            "factors": [
                {"hypothesis_id": hyps["Primary cause"]["id"], "role": "failure_mechanism"}
            ],
        },
        headers=auth_headers,
    )

    export = client.post(
        f"/api/incidents/{incident_id}/analysis-runs/{run_id}/postmortem/export",
        json={"mode": "clean"},
        headers=auth_headers,
    ).json()
    markdown = export["markdown"]
    assert "## Root Cause Conclusion" in markdown
    assert "The deploy regressed connection handling." in markdown
    assert "**Failure mechanism:**" in markdown
    assert "**Status:** finalized" in markdown
    # Once finalized, the provisional "Draft" label is gone (ADR 0035 → 0039).
    assert "Draft: Root cause not finalized" not in markdown


def test_finalize_requires_partial_support_acknowledgment(app, client: TestClient, auth_headers):
    incident_id, run_id = _seed_succeeded_run(
        app, client, auth_headers, verifier=_partial_verifier("Primary cause")
    )
    hyps = _hypotheses(client, auth_headers, incident_id, run_id)
    target = hyps["Primary cause"]
    assert target["support_status"] == "partial"
    _accept(client, auth_headers, incident_id, run_id, target["id"])

    # Without an acknowledgment the partial factor is rejected.
    missing = client.post(
        _conclusion_url(incident_id, run_id),
        json={
            "summary": "x",
            "factors": [{"hypothesis_id": target["id"], "role": "failure_mechanism"}],
        },
        headers=auth_headers,
    )
    assert missing.status_code == 422
    assert "partial-support acknowledgment" in missing.json()["detail"]

    # With one, finalization succeeds and the acknowledgment is preserved.
    ok = client.post(
        _conclusion_url(incident_id, run_id),
        json={
            "summary": "Partly evidenced mechanism.",
            "factors": [
                {
                    "hypothesis_id": target["id"],
                    "role": "failure_mechanism",
                    "partial_support_acknowledgment": (
                        "Pool exhaustion is shown; the deploy link is unconfirmed."
                    ),
                }
            ],
        },
        headers=auth_headers,
    )
    assert ok.status_code == 201, ok.text
    fm = ok.json()["failure_mechanism"]
    assert "unconfirmed" in fm["partial_support_acknowledgment"]


def test_finalize_requires_critical_challenge_override(app, client: TestClient, auth_headers):
    incident_id, run_id = _seed_succeeded_run(
        app, client, auth_headers, falsifier=FakeFalsifier(severity="critical")
    )
    hyps = _hypotheses(client, auth_headers, incident_id, run_id)
    target = hyps["Primary cause"]
    assert target["challenge"]["severity"] == "critical"
    _accept(client, auth_headers, incident_id, run_id, target["id"])

    # An incomplete (missing) override on a critically challenged failure mechanism.
    missing = client.post(
        _conclusion_url(incident_id, run_id),
        json={
            "summary": "x",
            "factors": [{"hypothesis_id": target["id"], "role": "failure_mechanism"}],
        },
        headers=auth_headers,
    )
    assert missing.status_code == 422
    assert "critical-challenge override" in missing.json()["detail"]

    # With an override the conclusion finalizes and preserves the critical challenge.
    ok = client.post(
        _conclusion_url(incident_id, run_id),
        json={
            "summary": "Concluded despite the open critical challenge.",
            "factors": [
                {
                    "hypothesis_id": target["id"],
                    "role": "failure_mechanism",
                    "critical_challenge_override": "Addressed by the rollback log at 14:55.",
                }
            ],
        },
        headers=auth_headers,
    )
    assert ok.status_code == 201, ok.text
    fm = ok.json()["failure_mechanism"]
    assert "rollback log" in fm["critical_challenge_override"]
    # The full critical challenge is preserved on the factor, not just its severity.
    assert fm["challenge"]["severity"] == "critical"
    assert fm["challenge"]["challenged_claim"] == "Challenge of: Primary cause"


def test_finalize_records_human_assumptions(app, client: TestClient, auth_headers):
    incident_id, run_id = _seed_succeeded_run(app, client, auth_headers)
    hyps = _hypotheses(client, auth_headers, incident_id, run_id)
    target = hyps["Primary cause"]
    _accept(client, auth_headers, incident_id, run_id, target["id"])

    resp = client.post(
        _conclusion_url(incident_id, run_id),
        json={
            "summary": "Concluded with a labeled assumption.",
            "factors": [{"hypothesis_id": target["id"], "role": "failure_mechanism"}],
            "human_assumptions": ["The on-call restarted the service manually."],
        },
        headers=auth_headers,
    )
    assert resp.status_code == 201, resp.text
    assumptions = resp.json()["human_assumptions"]
    assert len(assumptions) == 1
    assert assumptions[0]["statement"].startswith("The on-call")


def test_qualified_conclusion_export_preserves_qualifications(app, client: TestClient, auth_headers):
    # Exports preserve partial-support acknowledgments, critical challenges, override
    # rationale, non-definitive wording, and labeled human assumptions (AC).
    incident_id, run_id = _seed_succeeded_run(
        app,
        client,
        auth_headers,
        verifier=_partial_verifier("Primary cause"),
        falsifier=FakeFalsifier(severity="critical"),
    )
    hyps = _hypotheses(client, auth_headers, incident_id, run_id)
    target = hyps["Primary cause"]
    _accept(client, auth_headers, incident_id, run_id, target["id"])
    client.post(
        _conclusion_url(incident_id, run_id),
        json={
            "summary": "Qualified conclusion.",
            "factors": [
                {
                    "hypothesis_id": target["id"],
                    "role": "failure_mechanism",
                    "partial_support_acknowledgment": "Exhaustion shown; deploy link unconfirmed.",
                    "critical_challenge_override": "Addressed by the rollback log.",
                }
            ],
            "human_assumptions": ["The on-call restarted the service manually."],
        },
        headers=auth_headers,
    )

    markdown = client.post(
        f"/api/incidents/{incident_id}/analysis-runs/{run_id}/postmortem/export",
        json={"mode": "clean"},
        headers=auth_headers,
    ).json()["markdown"]
    assert "critically challenged" in markdown
    assert "deploy link unconfirmed" in markdown
    assert "not definitive" in markdown.lower() or "not\ndefinitive" in markdown.lower()
    assert "Addressed by the rollback log." in markdown
    # The actual critical challenge content is preserved in the export, so the
    # override can be audited against the concern it addresses (story 41).
    assert "Critical challenge: Challenge of: Primary cause" in markdown
    assert "Human assumptions (not evidence-backed):" in markdown
    assert "The on-call restarted the service manually." in markdown


def test_finalize_requires_auth(client: TestClient):
    resp = client.post(
        "/api/incidents/whatever/analysis-runs/whatever/conclusion",
        json={"summary": "x", "factors": []},
    )
    assert resp.status_code == 401


def test_get_conclusion_requires_auth(client: TestClient):
    resp = client.get("/api/incidents/whatever/analysis-runs/whatever/conclusion")
    assert resp.status_code == 401


def _finalize(client, auth_headers, incident_id, run_id):
    hyps = _hypotheses(client, auth_headers, incident_id, run_id)
    _accept(client, auth_headers, incident_id, run_id, hyps["Primary cause"]["id"])
    resp = client.post(
        _conclusion_url(incident_id, run_id),
        json={
            "summary": "The deploy regressed connection handling.",
            "factors": [
                {"hypothesis_id": hyps["Primary cause"]["id"], "role": "failure_mechanism"}
            ],
        },
        headers=auth_headers,
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


def _discrepancy_url(incident_id, run_id):
    return f"/api/incidents/{incident_id}/analysis-runs/{run_id}/conclusion/discrepancies"


def test_raise_discrepancy_disputes_conclusion(app, client: TestClient, auth_headers):
    incident_id, run_id = _seed_succeeded_run(app, client, auth_headers)
    _finalize(client, auth_headers, incident_id, run_id)

    resp = client.post(
        _discrepancy_url(incident_id, run_id),
        json={"explanation": "The cited deploy postdates the error spike."},
        headers=auth_headers,
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["explanation"] == "The cited deploy postdates the error spike."
    assert body["run_id"] == run_id
    # Conclusion Provenance for the dispute: the single-user gate's default principal.
    assert body["raised_by"] == "single-user"

    # The conclusion is now disputed and returns the review to unresolved: the
    # postmortem read model reports "disputed", not "finalized" (PRD #26 stories 44-46).
    pm = client.get(
        f"/api/incidents/{incident_id}/analysis-runs/{run_id}/postmortem", headers=auth_headers
    ).json()
    assert pm["conclusion_status"] == "disputed"
    assert pm["conclusion"]["disputed"] is True
    assert pm["conclusion"]["discrepancies"][0]["explanation"] == body["explanation"]

    # The GET conclusion resource exposes the same disputed state and discrepancy.
    got = client.get(_conclusion_url(incident_id, run_id), headers=auth_headers).json()
    assert got["disputed"] is True
    assert len(got["discrepancies"]) == 1


def test_raise_discrepancy_does_not_edit_immutable_conclusion(app, client: TestClient, auth_headers):
    incident_id, run_id = _seed_succeeded_run(app, client, auth_headers)
    finalized = _finalize(client, auth_headers, incident_id, run_id)

    client.post(
        _discrepancy_url(incident_id, run_id),
        json={"explanation": "Disagree with the mechanism."},
        headers=auth_headers,
    )
    got = client.get(_conclusion_url(incident_id, run_id), headers=auth_headers).json()
    # The immutable conclusion's own fields are untouched (ADR 0039/0040).
    assert got["id"] == finalized["id"]
    assert got["summary"] == finalized["summary"]
    assert got["finalized_at"] == finalized["finalized_at"]
    assert got["failure_mechanism"]["title"] == "Primary cause"


def test_discrepancies_are_append_only(app, client: TestClient, auth_headers):
    incident_id, run_id = _seed_succeeded_run(app, client, auth_headers)
    _finalize(client, auth_headers, incident_id, run_id)
    for explanation in ("First problem.", "Second problem."):
        resp = client.post(
            _discrepancy_url(incident_id, run_id),
            json={"explanation": explanation},
            headers=auth_headers,
        )
        assert resp.status_code == 201

    got = client.get(_conclusion_url(incident_id, run_id), headers=auth_headers).json()
    assert [d["explanation"] for d in got["discrepancies"]] == ["First problem.", "Second problem."]


def test_raise_discrepancy_retry_does_not_duplicate(app, client: TestClient, auth_headers):
    # A lost-response retry re-POSTs the identical payload; the append-only,
    # DB-irreversible record must not be duplicated (ADR 0040 retry-safety).
    incident_id, run_id = _seed_succeeded_run(app, client, auth_headers)
    _finalize(client, auth_headers, incident_id, run_id)
    body = {"explanation": "The cited deploy postdates the spike."}

    first = client.post(_discrepancy_url(incident_id, run_id), json=body, headers=auth_headers)
    assert first.status_code == 201
    retry = client.post(_discrepancy_url(incident_id, run_id), json=body, headers=auth_headers)
    assert retry.status_code == 201
    assert retry.json()["id"] == first.json()["id"]

    got = client.get(_conclusion_url(incident_id, run_id), headers=auth_headers).json()
    assert len(got["discrepancies"]) == 1


def test_raise_discrepancy_requires_finalized_conclusion(app, client: TestClient, auth_headers):
    incident_id, run_id = _seed_succeeded_run(app, client, auth_headers)
    resp = client.post(
        _discrepancy_url(incident_id, run_id),
        json={"explanation": "Nothing to dispute."},
        headers=auth_headers,
    )
    assert resp.status_code == 404
    assert "no finalized root cause conclusion to dispute" in resp.json()["detail"]


def test_raise_discrepancy_rejects_cross_incident(app, client: TestClient, auth_headers):
    incident_id, run_id = _seed_succeeded_run(app, client, auth_headers)
    _finalize(client, auth_headers, incident_id, run_id)
    other_incident_id, _other_run_id = _seed_succeeded_run(app, client, auth_headers)

    # The run does not belong to the other incident → not found, never a leak.
    resp = client.post(
        _discrepancy_url(other_incident_id, run_id),
        json={"explanation": "Wrong incident."},
        headers=auth_headers,
    )
    assert resp.status_code == 404


def test_raise_discrepancy_rejects_blank_explanation(app, client: TestClient, auth_headers):
    incident_id, run_id = _seed_succeeded_run(app, client, auth_headers)
    _finalize(client, auth_headers, incident_id, run_id)
    resp = client.post(
        _discrepancy_url(incident_id, run_id),
        json={"explanation": "   "},
        headers=auth_headers,
    )
    assert resp.status_code == 422


def test_raise_discrepancy_requires_auth(client: TestClient):
    resp = client.post(
        "/api/incidents/whatever/analysis-runs/whatever/conclusion/discrepancies",
        json={"explanation": "x"},
    )
    assert resp.status_code == 401


def _supersede_url(incident_id, run_id):
    return f"/api/incidents/{incident_id}/analysis-runs/{run_id}/conclusion/supersede"


def _seed_run_on_incident(app, client, auth_headers, incident_id, *, titles, source_name):
    """Start and execute a second succeeded run on an existing incident (new Evidence)."""
    app.state.run_scheduler = lambda background_tasks, session_factory, run_id: None
    artifact_id = client.post(
        f"/api/incidents/{incident_id}/artifacts",
        json={"source_type": "logs", "source_name": source_name, "body": "p\nq\nr\ns"},
        headers=auth_headers,
    ).json()["id"]
    run_id = client.post(
        f"/api/incidents/{incident_id}/analysis-runs", json={}, headers=auth_headers
    ).json()["id"]
    payload = json.dumps(
        {
            "hypotheses": [
                {
                    "title": title,
                    "summary": f"{title} explanation.",
                    "supporting_evidence": [
                        {"artifact_id": artifact_id, "line_start": i + 1, "line_end": i + 1}
                    ],
                }
                for i, title in enumerate(titles)
            ]
        }
    )
    impact = [
        FactsImpactClaim(
            description="Customers errored",
            evidence=[RcaEvidenceRef(artifact_id=artifact_id, line_start=1, line_end=1)],
        )
    ]
    session = app.state.session_factory()
    try:
        run = AnalysisService(
            session,
            llm_client=FakeLLMClient([payload], label="fake-model"),
            claim_support_verifier=FakeClaimSupportVerifier(),
            incident_fact_extractor=FakeIncidentFactExtractor(impact),
            falsifier=FakeFalsifier(),
        ).execute_run(run_id, commit_progress=True)
        assert run.status == "succeeded"
        session.commit()
    finally:
        session.close()
    return run_id


def test_supersede_same_run_reinterpretation(app, client: TestClient, auth_headers):
    incident_id, run_id = _seed_succeeded_run(app, client, auth_headers)
    hyps = _hypotheses(client, auth_headers, incident_id, run_id)
    _accept(client, auth_headers, incident_id, run_id, hyps["Primary cause"]["id"])
    _accept(client, auth_headers, incident_id, run_id, hyps["Alternative cause"]["id"])
    first = _finalize(client, auth_headers, incident_id, run_id)
    disc = client.post(
        _discrepancy_url(incident_id, run_id),
        json={"explanation": "The cited deploy postdates the spike."},
        headers=auth_headers,
    ).json()

    resp = client.post(
        _supersede_url(incident_id, run_id),
        json={
            "summary": "Reinterpreted: the alternative is the mechanism.",
            "factors": [
                {"hypothesis_id": hyps["Alternative cause"]["id"], "role": "failure_mechanism"}
            ],
            "supersedes_conclusion_id": first["id"],
            "discrepancy_id": disc["id"],
        },
        headers=auth_headers,
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["authoritative"] is True
    assert body["supersedes"]["id"] == first["id"]
    assert body["superseded_by"] is None
    assert [c["id"] for c in body["history"]] == [first["id"]]

    # The run now presents the successor as its finalized, authoritative conclusion.
    pm = client.get(
        f"/api/incidents/{incident_id}/analysis-runs/{run_id}/postmortem", headers=auth_headers
    ).json()
    assert pm["conclusion_status"] == "finalized"
    assert pm["conclusion"]["id"] == body["id"]
    # The GET resource returns the successor (the run's representative).
    got = client.get(_conclusion_url(incident_id, run_id), headers=auth_headers).json()
    assert got["id"] == body["id"]


def test_supersede_new_evidence_uses_new_run(app, client: TestClient, auth_headers):
    incident_id, run1 = _seed_succeeded_run(app, client, auth_headers)
    hyps = _hypotheses(client, auth_headers, incident_id, run1)
    _accept(client, auth_headers, incident_id, run1, hyps["Primary cause"]["id"])
    first = _finalize(client, auth_headers, incident_id, run1)
    disc = client.post(
        _discrepancy_url(incident_id, run1),
        json={"explanation": "Need fresh evidence."},
        headers=auth_headers,
    ).json()

    run2 = _seed_run_on_incident(
        app, client, auth_headers, incident_id, titles=("New mechanism",), source_name="b.log"
    )
    hyps2 = _hypotheses(client, auth_headers, incident_id, run2)
    _accept(client, auth_headers, incident_id, run2, hyps2["New mechanism"]["id"])

    resp = client.post(
        _supersede_url(incident_id, run2),
        json={
            "summary": "New evidence shows a different mechanism.",
            "factors": [
                {"hypothesis_id": hyps2["New mechanism"]["id"], "role": "failure_mechanism"}
            ],
            "supersedes_conclusion_id": first["id"],
            "discrepancy_id": disc["id"],
        },
        headers=auth_headers,
    )
    assert resp.status_code == 201, resp.text
    assert resp.json()["run_id"] == run2

    # The predecessor's run is superseded and points to the successor's run.
    pm1 = client.get(
        f"/api/incidents/{incident_id}/analysis-runs/{run1}/postmortem", headers=auth_headers
    ).json()
    assert pm1["conclusion_status"] == "superseded"
    assert pm1["conclusion"]["superseded_by"]["run_id"] == run2
    assert pm1["conclusion"]["authoritative"] is False

    # The new run holds the authoritative successor.
    pm2 = client.get(
        f"/api/incidents/{incident_id}/analysis-runs/{run2}/postmortem", headers=auth_headers
    ).json()
    assert pm2["conclusion_status"] == "finalized"
    assert pm2["conclusion"]["authoritative"] is True


def test_supersede_requires_disputed_predecessor(app, client: TestClient, auth_headers):
    incident_id, run_id = _seed_succeeded_run(app, client, auth_headers)
    hyps = _hypotheses(client, auth_headers, incident_id, run_id)
    _accept(client, auth_headers, incident_id, run_id, hyps["Primary cause"]["id"])
    _accept(client, auth_headers, incident_id, run_id, hyps["Alternative cause"]["id"])
    first = _finalize(client, auth_headers, incident_id, run_id)

    # No discrepancy raised → the predecessor is not disputed → 409 conflict.
    resp = client.post(
        _supersede_url(incident_id, run_id),
        json={
            "summary": "x",
            "factors": [
                {"hypothesis_id": hyps["Alternative cause"]["id"], "role": "failure_mechanism"}
            ],
            "supersedes_conclusion_id": first["id"],
            "discrepancy_id": "anything",
        },
        headers=auth_headers,
    )
    assert resp.status_code == 409, resp.text
    assert "disputed" in resp.json()["detail"]


def test_list_disputed_conclusions_surfaces_cross_run_candidates(
    app, client: TestClient, auth_headers
):
    incident_id, run1 = _seed_succeeded_run(app, client, auth_headers)
    hyps = _hypotheses(client, auth_headers, incident_id, run1)
    _accept(client, auth_headers, incident_id, run1, hyps["Primary cause"]["id"])
    first = _finalize(client, auth_headers, incident_id, run1)

    # Not disputed yet → no candidates.
    empty = client.get(
        f"/api/incidents/{incident_id}/disputed-conclusions", headers=auth_headers
    ).json()
    assert empty == []

    client.post(
        _discrepancy_url(incident_id, run1),
        json={"explanation": "Need fresh evidence."},
        headers=auth_headers,
    )
    listed = client.get(
        f"/api/incidents/{incident_id}/disputed-conclusions", headers=auth_headers
    ).json()
    assert [c["id"] for c in listed] == [first["id"]]
    assert listed[0]["disputed"] is True


def test_disputed_conclusions_requires_auth(client: TestClient):
    resp = client.get("/api/incidents/whatever/disputed-conclusions")
    assert resp.status_code == 401


def test_superseded_export_does_not_claim_authority_when_successor_disputed(
    app, client: TestClient, auth_headers
):
    # Defense for the adversarial finding: if the replacement conclusion is itself
    # disputed, the predecessor's clean export must not point to it as authoritative.
    incident_id, run1 = _seed_succeeded_run(app, client, auth_headers)
    hyps = _hypotheses(client, auth_headers, incident_id, run1)
    _accept(client, auth_headers, incident_id, run1, hyps["Primary cause"]["id"])
    first = _finalize(client, auth_headers, incident_id, run1)
    disc = client.post(
        _discrepancy_url(incident_id, run1),
        json={"explanation": "Need fresh evidence."},
        headers=auth_headers,
    ).json()
    run2 = _seed_run_on_incident(
        app, client, auth_headers, incident_id, titles=("New mechanism",), source_name="b.log"
    )
    hyps2 = _hypotheses(client, auth_headers, incident_id, run2)
    _accept(client, auth_headers, incident_id, run2, hyps2["New mechanism"]["id"])
    client.post(
        _supersede_url(incident_id, run2),
        json={
            "summary": "New evidence shows a different mechanism.",
            "factors": [
                {"hypothesis_id": hyps2["New mechanism"]["id"], "role": "failure_mechanism"}
            ],
            "supersedes_conclusion_id": first["id"],
            "discrepancy_id": disc["id"],
        },
        headers=auth_headers,
    )
    # Now dispute the successor too: the chain has no authoritative tail.
    client.post(
        _discrepancy_url(incident_id, run2),
        json={"explanation": "The new mechanism is also unconfirmed."},
        headers=auth_headers,
    )

    clean1 = client.post(
        f"/api/incidents/{incident_id}/analysis-runs/{run1}/postmortem/export",
        json={"mode": "clean"},
        headers=auth_headers,
    ).json()["markdown"]
    assert "**Status:** superseded" in clean1
    # It must NOT point at the disputed successor's run as authoritative.
    assert f"finalized in analysis run `{run2}`" not in clean1
    assert "no authoritative conclusion" in clean1


def test_supersede_requires_auth(client: TestClient):
    resp = client.post(
        "/api/incidents/whatever/analysis-runs/whatever/conclusion/supersede",
        json={"summary": "x", "factors": [], "supersedes_conclusion_id": "a", "discrepancy_id": "b"},
    )
    assert resp.status_code == 401


def test_superseded_conclusion_export_behavior(app, client: TestClient, auth_headers):
    incident_id, run1 = _seed_succeeded_run(app, client, auth_headers)
    hyps = _hypotheses(client, auth_headers, incident_id, run1)
    _accept(client, auth_headers, incident_id, run1, hyps["Primary cause"]["id"])
    first = _finalize(client, auth_headers, incident_id, run1)
    disc = client.post(
        _discrepancy_url(incident_id, run1),
        json={"explanation": "Need fresh evidence."},
        headers=auth_headers,
    ).json()
    run2 = _seed_run_on_incident(
        app, client, auth_headers, incident_id, titles=("New mechanism",), source_name="b.log"
    )
    hyps2 = _hypotheses(client, auth_headers, incident_id, run2)
    _accept(client, auth_headers, incident_id, run2, hyps2["New mechanism"]["id"])
    client.post(
        _supersede_url(incident_id, run2),
        json={
            "summary": "New evidence shows a different mechanism.",
            "factors": [
                {"hypothesis_id": hyps2["New mechanism"]["id"], "role": "failure_mechanism"}
            ],
            "supersedes_conclusion_id": first["id"],
            "discrepancy_id": disc["id"],
        },
        headers=auth_headers,
    )

    def export(run_id, mode):
        return client.post(
            f"/api/incidents/{incident_id}/analysis-runs/{run_id}/postmortem/export",
            json={"mode": mode},
            headers=auth_headers,
        ).json()["markdown"]

    # The superseded predecessor run: clean export withholds the stale causal account
    # and points at the authoritative successor; audit preserves the chain.
    clean1 = export(run1, "clean")
    assert "**Status:** superseded" in clean1
    assert "Superseded conclusion." in clean1
    assert "withheld from this clean export" in clean1
    assert "The deploy regressed connection handling." not in clean1
    audit1 = export(run1, "audit")
    assert "Superseding chain:" in audit1
    assert "Superseded by" in audit1

    # The successor run: clean export presents the new authoritative conclusion.
    clean2 = export(run2, "clean")
    assert "**Status:** finalized" in clean2
    assert "New evidence shows a different mechanism." in clean2
    assert "Supersedes an earlier disputed conclusion" in clean2


def test_disputed_conclusion_export_behavior(app, client: TestClient, auth_headers):
    incident_id, run_id = _seed_succeeded_run(app, client, auth_headers)
    _finalize(client, auth_headers, incident_id, run_id)
    client.post(
        _discrepancy_url(incident_id, run_id),
        json={"explanation": "The cited deploy postdates the spike."},
        headers=auth_headers,
    )

    def export(mode):
        return client.post(
            f"/api/incidents/{incident_id}/analysis-runs/{run_id}/postmortem/export",
            json={"mode": mode},
            headers=auth_headers,
        ).json()["markdown"]

    clean = export("clean")
    # A clean export must not present the disputed conclusion as current fact: the
    # causal account is withheld and the disputed state is prominent (PRD story 45).
    assert "**Status:** disputed" in clean
    assert "Disputed conclusion." in clean
    assert "withheld from this clean export" in clean
    assert "The deploy regressed connection handling." not in clean

    audit = export("audit")
    # An audit export preserves the conclusion and the discrepancy for the record.
    assert "## Root Cause Conclusion" in audit
    assert "The deploy regressed connection handling." in audit
    assert "Recorded discrepancies:" in audit
    assert "The cited deploy postdates the spike." in audit
