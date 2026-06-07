from __future__ import annotations

import json

from fastapi.testclient import TestClient

from postmortem.llm import FakeLLMClient
from postmortem.schemas import AnalysisRunCreate
from postmortem.services import AnalysisService

from tests._fakes import FakeClaimSupportVerifier


def create_incident(client: TestClient, auth_headers) -> str:
    resp = client.post("/api/incidents", json={"title": "Hyp incident"}, headers=auth_headers)
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


def add_artifact(client: TestClient, auth_headers, incident_id: str) -> str:
    resp = client.post(
        f"/api/incidents/{incident_id}/artifacts",
        json={"source_type": "logs", "source_name": "api.log", "body": "alpha line\nbeta line"},
        headers=auth_headers,
    )
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


def _seed_run_with_hypotheses(app, client, auth_headers, claim_support_verifier=None):
    """Start a run via HTTP but execute it with a seeded provider.

    The scheduler is stubbed so the POST only queues the run; the run is then
    executed against the app's own DB with a FakeLLMClient (and a fake
    claim-support verifier so stage 6 does not need seeded LLM responses) so the
    HTTP read endpoints surface real persisted hypotheses.
    """
    captured: list[str] = []
    app.state.run_scheduler = lambda background_tasks, session_factory, run_id: captured.append(
        run_id
    )

    incident_id = create_incident(client, auth_headers)
    artifact_id = add_artifact(client, auth_headers, incident_id)
    start = client.post(
        f"/api/incidents/{incident_id}/analysis-runs", json={}, headers=auth_headers
    )
    assert start.status_code == 201, start.text
    run_id = start.json()["id"]

    payload = json.dumps(
        {
            "hypotheses": [
                {
                    "title": "Primary cause",
                    "summary": "Most-supported explanation.",
                    "supporting_evidence": [
                        {"artifact_id": artifact_id, "line_start": 1, "line_end": 1}
                    ],
                    "contradicting_evidence": [
                        {"artifact_id": artifact_id, "line_start": 2, "line_end": 2}
                    ],
                    "unknowns": ["one open question"],
                    "validation_steps": ["confirm via metrics"],
                    "impact_claims": [
                        {
                            "description": "Customers errored",
                            "evidence": [
                                {"artifact_id": artifact_id, "line_start": 2, "line_end": 2}
                            ],
                        }
                    ],
                    "remediation_items": [{"description": "Roll back", "evidence": []}],
                },
                {
                    "title": "Alternative cause",
                    "summary": "A competing explanation.",
                    "supporting_evidence": [
                        {"artifact_id": artifact_id, "line_start": 1, "line_end": 1}
                    ],
                },
            ]
        }
    )
    session = app.state.session_factory()
    try:
        run = AnalysisService(
            session,
            llm_client=FakeLLMClient([payload], label="fake-model"),
            claim_support_verifier=claim_support_verifier or FakeClaimSupportVerifier(),
        ).execute_run(run_id, commit_progress=True)
        assert run.status == "succeeded"
        session.commit()
    finally:
        session.close()

    return incident_id, run_id


def test_list_hypotheses_returns_ranked_with_split_evidence(app, client: TestClient, auth_headers):
    incident_id, run_id = _seed_run_with_hypotheses(app, client, auth_headers)

    resp = client.get(
        f"/api/incidents/{incident_id}/analysis-runs/{run_id}/hypotheses", headers=auth_headers
    )
    assert resp.status_code == 200, resp.text
    hyps = resp.json()
    assert [h["rank"] for h in hyps] == [1, 2]

    top = hyps[0]
    assert top["title"] == "Primary cause"
    assert top["review_status"] == "proposed"
    assert len(top["supporting_evidence"]) == 1
    assert len(top["contradicting_evidence"]) == 1
    # Snippets are resolved from the stored artifact lines (ADR 0024).
    assert top["supporting_evidence"][0]["snippet"] == "alpha line"
    assert top["contradicting_evidence"][0]["snippet"] == "beta line"
    # The deterministic citation-integrity pass ran (stage 4) and stamped each
    # citation verified, so the Review Surface can show citation trust (ADR 0014).
    assert top["supporting_evidence"][0]["verifier_status"] == "verified"
    assert top["contradicting_evidence"][0]["verifier_status"] == "verified"
    assert top["impact_claims"][0]["evidence_refs"][0]["verifier_status"] == "verified"
    assert top["impact_claims"][0]["description"] == "Customers errored"
    assert top["action_items"][0]["description"] == "Roll back"
    assert top["unknowns"] == ["one open question"]
    assert top["validation_steps"] == ["confirm via metrics"]
    # Stage 6 classified each Major Claim's support and exposes it for the Review
    # Surface to separate authoritative from auditable-only (ADR 0014).
    assert top["support_status"] == "supported"
    assert top["support_rationale"]
    assert top["impact_claims"][0]["support_status"] == "supported"


def test_support_status_separates_unsupported_and_partial_claims(
    app, client: TestClient, auth_headers
):
    from postmortem.verification import ClaimSupportJudgment, ClaimSupportStatus

    def judge(claim):
        # The top hypothesis statement is unsupported; everything else partial.
        if claim.claim_text.startswith("Primary cause"):
            return ClaimSupportJudgment(ClaimSupportStatus.UNSUPPORTED, "Evidence does not establish this.")
        return ClaimSupportJudgment(ClaimSupportStatus.PARTIAL, "Only partially established.")

    incident_id, run_id = _seed_run_with_hypotheses(
        app, client, auth_headers, claim_support_verifier=FakeClaimSupportVerifier(judge)
    )
    resp = client.get(
        f"/api/incidents/{incident_id}/analysis-runs/{run_id}/hypotheses", headers=auth_headers
    )
    assert resp.status_code == 200, resp.text
    hyps = {h["title"]: h for h in resp.json()}
    # Unsupported claims stay visible (auditable) but carry the unsupported status
    # and a rationale so the UI can route them to Review Findings (ADR 0015).
    assert hyps["Primary cause"]["support_status"] == "unsupported"
    assert hyps["Primary cause"]["support_rationale"] == "Evidence does not establish this."
    # The impact claim under the primary hypothesis was judged partial.
    assert hyps["Primary cause"]["impact_claims"][0]["support_status"] == "partial"
    assert hyps["Alternative cause"]["support_status"] == "partial"


def test_review_hypothesis_sets_status_without_altering_claims(
    app, client: TestClient, auth_headers
):
    incident_id, run_id = _seed_run_with_hypotheses(app, client, auth_headers)
    base = f"/api/incidents/{incident_id}/analysis-runs/{run_id}/hypotheses"
    before = client.get(base, headers=auth_headers).json()[0]

    resp = client.post(
        f"{base}/{before['id']}/review", json={"decision": "accepted"}, headers=auth_headers
    )
    assert resp.status_code == 200, resp.text
    updated = resp.json()
    assert updated["review_status"] == "accepted"
    # The accept decision flips status only; claims and citations are unchanged.
    assert updated["title"] == before["title"]
    assert updated["summary"] == before["summary"]
    assert [r["id"] for r in updated["supporting_evidence"]] == [
        r["id"] for r in before["supporting_evidence"]
    ]
    assert updated["impact_claims"] == before["impact_claims"]

    # The new status is durable on the next read.
    after = client.get(base, headers=auth_headers).json()[0]
    assert after["review_status"] == "accepted"


def test_review_unknown_hypothesis_returns_404(app, client: TestClient, auth_headers):
    incident_id, run_id = _seed_run_with_hypotheses(app, client, auth_headers)
    resp = client.post(
        f"/api/incidents/{incident_id}/analysis-runs/{run_id}/hypotheses/nope/review",
        json={"decision": "accepted"},
        headers=auth_headers,
    )
    assert resp.status_code == 404
    assert resp.json()["detail"] == "hypothesis not found"


def test_list_hypotheses_for_unknown_run_returns_404(client: TestClient, auth_headers):
    incident_id = create_incident(client, auth_headers)
    resp = client.get(
        f"/api/incidents/{incident_id}/analysis-runs/nope/hypotheses", headers=auth_headers
    )
    assert resp.status_code == 404
    assert resp.json()["detail"] == "analysis run not found"


def test_hypotheses_require_auth(client: TestClient):
    resp = client.get("/api/incidents/whatever/analysis-runs/whatever/hypotheses")
    assert resp.status_code == 401
