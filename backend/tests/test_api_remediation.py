from __future__ import annotations

import json

from fastapi.testclient import TestClient

from postmortem.incident_facts import FactsImpactClaim
from postmortem.llm import FakeLLMClient
from postmortem.rca import RcaEvidenceRef
from postmortem.services import AnalysisService

from tests._fakes import (
    FakeClaimSupportVerifier,
    FakeFalsifier,
    FakeIncidentFactExtractor,
)


# Evidence Gaps the fake falsifier stamps on every Hypothesis Challenge so the
# evidence-gap link target exists (ADR 0034 / 0041).
_EVIDENCE_GAPS = ["No DB pool saturation metrics were collected", "Deploy diff is missing"]


def _seed_succeeded_run(
    app, client, auth_headers, *, titles=("Primary cause", "Alternative cause")
):
    """Queue a run via HTTP, then execute it with seeded fakes.

    Each hypothesis carries one generated Remediation Proposal, and every challenge
    carries Evidence Gaps, so both accepted-link targets are available.
    """
    app.state.run_scheduler = lambda background_tasks, session_factory, run_id: None

    incident_resp = client.post("/api/incidents", json={"title": "Rem"}, headers=auth_headers)
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
                    "remediation_items": [{"description": f"Remediate {title}"}],
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
            claim_support_verifier=FakeClaimSupportVerifier(),
            incident_fact_extractor=FakeIncidentFactExtractor(impact),
            falsifier=FakeFalsifier(evidence_gaps=_EVIDENCE_GAPS),
        ).execute_run(run_id, commit_progress=True)
        assert run.status == "succeeded"
        session.commit()
    finally:
        session.close()
    return incident_id, run_id, artifact_id


def _remediation(client, auth_headers, incident_id, run_id):
    resp = client.get(
        f"/api/incidents/{incident_id}/analysis-runs/{run_id}/remediation", headers=auth_headers
    )
    assert resp.status_code == 200, resp.text
    return resp.json()


def _decision_url(incident_id, run_id, action_item_id):
    return (
        f"/api/incidents/{incident_id}/analysis-runs/{run_id}"
        f"/remediation/{action_item_id}/decision"
    )


def _hypotheses(client, auth_headers, incident_id, run_id):
    resp = client.get(
        f"/api/incidents/{incident_id}/analysis-runs/{run_id}/hypotheses", headers=auth_headers
    )
    return {h["title"]: h for h in resp.json()}


def _finalize_conclusion(client, auth_headers, incident_id, run_id):
    """Accept the primary hypothesis and finalize it as the failure mechanism."""
    hyps = _hypotheses(client, auth_headers, incident_id, run_id)
    primary = hyps["Primary cause"]
    client.post(
        f"/api/incidents/{incident_id}/analysis-runs/{run_id}/hypotheses/{primary['id']}/review",
        json={"decision": "accepted"},
        headers=auth_headers,
    )
    resp = client.post(
        f"/api/incidents/{incident_id}/analysis-runs/{run_id}/conclusion",
        json={
            "summary": "The deploy regressed connection handling.",
            "factors": [{"hypothesis_id": primary["id"], "role": "failure_mechanism"}],
        },
        headers=auth_headers,
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


def test_generated_remediation_is_proposed(app, client: TestClient, auth_headers):
    incident_id, run_id, _ = _seed_succeeded_run(app, client, auth_headers)
    proposals = _remediation(client, auth_headers, incident_id, run_id)
    assert len(proposals) == 2
    # Generated remediation starts as a candidate, not committed work (ADR 0041).
    for proposal in proposals:
        assert proposal["review_status"] == "proposed"
        assert proposal["link"] is None
        assert proposal["decided_by"] is None


def test_accept_links_to_causal_factor(app, client: TestClient, auth_headers):
    incident_id, run_id, _ = _seed_succeeded_run(app, client, auth_headers)
    conclusion = _finalize_conclusion(client, auth_headers, incident_id, run_id)
    factor_id = conclusion["failure_mechanism"]["id"]
    proposal = _remediation(client, auth_headers, incident_id, run_id)[0]

    resp = client.post(
        _decision_url(incident_id, run_id, proposal["id"]),
        json={
            "decision": "accepted",
            "rationale": "Closes the failure mechanism.",
            "link": {"kind": "causal_factor", "causal_factor_id": factor_id},
        },
        headers=auth_headers,
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["review_status"] == "accepted"
    assert body["decided_by"] == "single-user"
    assert body["decision_rationale"] == "Closes the failure mechanism."
    assert body["link"]["kind"] == "causal_factor"
    assert body["link"]["causal_factor_id"] == factor_id
    assert body["link"]["hypothesis_title"] == "Primary cause"
    # The generated text is never edited by a decision (ADR 0016).
    assert body["description"] == proposal["description"]


def test_accept_links_to_evidence_gap(app, client: TestClient, auth_headers):
    incident_id, run_id, _ = _seed_succeeded_run(app, client, auth_headers)
    hyps = _hypotheses(client, auth_headers, incident_id, run_id)
    challenge_id = hyps["Primary cause"]["challenge"]["id"]
    proposal = _remediation(client, auth_headers, incident_id, run_id)[0]

    resp = client.post(
        _decision_url(incident_id, run_id, proposal["id"]),
        json={
            "decision": "accepted",
            "link": {
                "kind": "evidence_gap",
                "evidence_gap_challenge_id": challenge_id,
                "evidence_gap_index": 1,
            },
        },
        headers=auth_headers,
    )
    assert resp.status_code == 200, resp.text
    link = resp.json()["link"]
    assert link["kind"] == "evidence_gap"
    assert link["evidence_gap_index"] == 1
    assert link["evidence_gap_text"] == _EVIDENCE_GAPS[1]


def test_reject_and_defer_carry_no_link(app, client: TestClient, auth_headers):
    incident_id, run_id, _ = _seed_succeeded_run(app, client, auth_headers)
    proposals = _remediation(client, auth_headers, incident_id, run_id)

    rejected = client.post(
        _decision_url(incident_id, run_id, proposals[0]["id"]),
        json={"decision": "rejected", "rationale": "Out of scope."},
        headers=auth_headers,
    )
    assert rejected.status_code == 200, rejected.text
    assert rejected.json()["review_status"] == "rejected"
    assert rejected.json()["link"] is None

    deferred = client.post(
        _decision_url(incident_id, run_id, proposals[1]["id"]),
        json={"decision": "deferred"},
        headers=auth_headers,
    )
    assert deferred.status_code == 200, deferred.text
    assert deferred.json()["review_status"] == "deferred"


def test_decision_transitions_clear_prior_link(app, client: TestClient, auth_headers):
    incident_id, run_id, _ = _seed_succeeded_run(app, client, auth_headers)
    conclusion = _finalize_conclusion(client, auth_headers, incident_id, run_id)
    factor_id = conclusion["failure_mechanism"]["id"]
    proposal = _remediation(client, auth_headers, incident_id, run_id)[0]

    # accept (with a link), then defer: the link must be cleared.
    client.post(
        _decision_url(incident_id, run_id, proposal["id"]),
        json={"decision": "accepted", "link": {"kind": "causal_factor", "causal_factor_id": factor_id}},
        headers=auth_headers,
    )
    deferred = client.post(
        _decision_url(incident_id, run_id, proposal["id"]),
        json={"decision": "deferred"},
        headers=auth_headers,
    )
    assert deferred.status_code == 200, deferred.text
    assert deferred.json()["review_status"] == "deferred"
    assert deferred.json()["link"] is None


def test_accept_requires_a_link(app, client: TestClient, auth_headers):
    incident_id, run_id, _ = _seed_succeeded_run(app, client, auth_headers)
    proposal = _remediation(client, auth_headers, incident_id, run_id)[0]
    resp = client.post(
        _decision_url(incident_id, run_id, proposal["id"]),
        json={"decision": "accepted"},
        headers=auth_headers,
    )
    assert resp.status_code == 422, resp.text
    assert "link" in resp.json()["detail"]


def test_non_accepted_decision_rejects_a_link(app, client: TestClient, auth_headers):
    incident_id, run_id, _ = _seed_succeeded_run(app, client, auth_headers)
    hyps = _hypotheses(client, auth_headers, incident_id, run_id)
    challenge_id = hyps["Primary cause"]["challenge"]["id"]
    proposal = _remediation(client, auth_headers, incident_id, run_id)[0]
    resp = client.post(
        _decision_url(incident_id, run_id, proposal["id"]),
        json={
            "decision": "deferred",
            "link": {
                "kind": "evidence_gap",
                "evidence_gap_challenge_id": challenge_id,
                "evidence_gap_index": 0,
            },
        },
        headers=auth_headers,
    )
    assert resp.status_code == 422, resp.text


def test_accept_rejects_cross_incident_causal_factor(app, client: TestClient, auth_headers):
    incident_id, run_id, _ = _seed_succeeded_run(app, client, auth_headers)
    other_incident_id, other_run_id, _ = _seed_succeeded_run(app, client, auth_headers)
    # A finalized causal factor that belongs to a different incident.
    other_conclusion = _finalize_conclusion(client, auth_headers, other_incident_id, other_run_id)
    foreign_factor_id = other_conclusion["failure_mechanism"]["id"]

    proposal = _remediation(client, auth_headers, incident_id, run_id)[0]
    resp = client.post(
        _decision_url(incident_id, run_id, proposal["id"]),
        json={
            "decision": "accepted",
            "link": {"kind": "causal_factor", "causal_factor_id": foreign_factor_id},
        },
        headers=auth_headers,
    )
    assert resp.status_code == 404, resp.text


def test_accept_rejects_cross_incident_evidence_gap(app, client: TestClient, auth_headers):
    incident_id, run_id, _ = _seed_succeeded_run(app, client, auth_headers)
    other_incident_id, other_run_id, _ = _seed_succeeded_run(app, client, auth_headers)
    other_hyps = _hypotheses(client, auth_headers, other_incident_id, other_run_id)
    foreign_challenge_id = other_hyps["Primary cause"]["challenge"]["id"]

    proposal = _remediation(client, auth_headers, incident_id, run_id)[0]
    resp = client.post(
        _decision_url(incident_id, run_id, proposal["id"]),
        json={
            "decision": "accepted",
            "link": {
                "kind": "evidence_gap",
                "evidence_gap_challenge_id": foreign_challenge_id,
                "evidence_gap_index": 0,
            },
        },
        headers=auth_headers,
    )
    assert resp.status_code == 404, resp.text


def test_evidence_gap_index_out_of_range(app, client: TestClient, auth_headers):
    incident_id, run_id, _ = _seed_succeeded_run(app, client, auth_headers)
    hyps = _hypotheses(client, auth_headers, incident_id, run_id)
    challenge_id = hyps["Primary cause"]["challenge"]["id"]
    proposal = _remediation(client, auth_headers, incident_id, run_id)[0]
    resp = client.post(
        _decision_url(incident_id, run_id, proposal["id"]),
        json={
            "decision": "accepted",
            "link": {
                "kind": "evidence_gap",
                "evidence_gap_challenge_id": challenge_id,
                "evidence_gap_index": 99,
            },
        },
        headers=auth_headers,
    )
    assert resp.status_code == 422, resp.text


def test_decision_on_unknown_proposal_is_404(app, client: TestClient, auth_headers):
    incident_id, run_id, _ = _seed_succeeded_run(app, client, auth_headers)
    resp = client.post(
        _decision_url(incident_id, run_id, "missing-id"),
        json={"decision": "deferred"},
        headers=auth_headers,
    )
    assert resp.status_code == 404, resp.text


def test_decision_rejects_cross_run_proposal(app, client: TestClient, auth_headers):
    incident_id, run_id, _ = _seed_succeeded_run(app, client, auth_headers)
    other_incident_id, other_run_id, _ = _seed_succeeded_run(app, client, auth_headers)
    foreign_proposal = _remediation(client, auth_headers, other_incident_id, other_run_id)[0]

    # The proposal id is real but belongs to another run/incident.
    resp = client.post(
        _decision_url(incident_id, run_id, foreign_proposal["id"]),
        json={"decision": "deferred"},
        headers=auth_headers,
    )
    assert resp.status_code == 404, resp.text


def test_accepted_remediation_surfaces_in_exports(app, client: TestClient, auth_headers):
    incident_id, run_id, _ = _seed_succeeded_run(app, client, auth_headers)
    conclusion = _finalize_conclusion(client, auth_headers, incident_id, run_id)
    factor_id = conclusion["failure_mechanism"]["id"]
    proposals = _remediation(client, auth_headers, incident_id, run_id)

    client.post(
        _decision_url(incident_id, run_id, proposals[0]["id"]),
        json={"decision": "accepted", "link": {"kind": "causal_factor", "causal_factor_id": factor_id}},
        headers=auth_headers,
    )
    client.post(
        _decision_url(incident_id, run_id, proposals[1]["id"]),
        json={"decision": "rejected"},
        headers=auth_headers,
    )

    def export(mode):
        resp = client.post(
            f"/api/incidents/{incident_id}/analysis-runs/{run_id}/postmortem/export",
            json={"mode": mode},
            headers=auth_headers,
        )
        assert resp.status_code == 200, resp.text
        return resp.json()["markdown"]

    clean = export("clean")
    # Clean export shows only accepted remediation, with its link.
    assert "Remediate Primary cause" in clean
    assert "Remediate Alternative cause" not in clean

    audit = export("audit")
    # Audit export groups every proposal by state.
    assert "Accepted" in audit
    assert "Rejected" in audit
    assert "Remediate Alternative cause" in audit
