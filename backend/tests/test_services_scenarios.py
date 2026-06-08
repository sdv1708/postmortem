from __future__ import annotations

import json
import shutil

import pytest

from postmortem.models import AnalysisRun, Artifact, Hypothesis, Incident, Postmortem
from postmortem.scenarios import SCENARIOS_DIR, ScenarioValidationError
from postmortem.services import ScenarioSeedService


def _hypotheses(session, run_id):
    return list(
        session.query(Hypothesis).filter(Hypothesis.run_id == run_id).order_by(Hypothesis.rank)
    )


def test_seed_and_run_drives_the_founder_demo_trust_path(fresh_session):
    incident, run = ScenarioSeedService(fresh_session).seed_and_run("deploy-ambiguity")
    fresh_session.commit()

    # The scenario became real product data: an Incident plus its four Artifacts.
    assert incident.title.startswith("Ambiguous deploy")
    artifacts = list(
        fresh_session.query(Artifact).filter(Artifact.incident_id == incident.id)
    )
    assert len(artifacts) == 4
    # Each included artifact is locked once the run started (ADR 0018).
    assert all(a.included_in_analysis_run for a in artifacts)

    # The run completed end to end on the bundled replay (no live model).
    assert run.status == "succeeded"
    # The replay is recorded honestly in Experiment Metadata (ADR 0025).
    assert run.model_provider == "scenario-replay:deploy-ambiguity"
    assert "scenario-replay-claim-support-1" in run.verifier_version

    hyps = _hypotheses(fresh_session, run.id)
    # Ambiguity is demonstrated: multiple ranked hypotheses.
    assert [h.rank for h in hyps] == [1, 2, 3]

    top = hyps[0]
    supporting = [r for r in top.evidence_refs if r.role == "supporting"]
    contradicting = [r for r in top.evidence_refs if r.role == "contradicting"]
    # Supporting and contradicting evidence and unknowns all populated (PRD stage 3).
    assert len(supporting) >= 2
    assert len(contradicting) >= 1
    assert top.unknowns
    # Citations resolve to the exact stored artifact lines (ADR 0024), and the
    # citation-integrity pass verified them.
    assert all(r.verifier_status == "verified" for r in top.evidence_refs)
    assert top.support_status == "supported"

    # The middle hypothesis is judged PARTIAL via the scenario's replay override.
    assert hyps[1].support_status == "partial"

    # The third hypothesis is an honest, unevidenced suspicion: normalized to an
    # assumption and surfaced as an unsupported Review Finding, not authoritative.
    assert hyps[2].assumption is True
    assert hyps[2].support_status == "unsupported"

    # A structured Postmortem was drafted for the Review Surface (ADR 0012).
    postmortem = fresh_session.query(Postmortem).filter(Postmortem.run_id == run.id).one()
    assert postmortem.summary


def test_seed_and_run_is_offline_and_deterministic(fresh_session):
    # Two independent seeds of the same scenario produce the same hypothesis
    # titles and ranking, proving the demo path needs no live model.
    _, run_a = ScenarioSeedService(fresh_session).seed_and_run("deploy-ambiguity")
    _, run_b = ScenarioSeedService(fresh_session).seed_and_run("deploy-ambiguity")
    fresh_session.commit()

    titles_a = [h.title for h in _hypotheses(fresh_session, run_a.id)]
    titles_b = [h.title for h in _hypotheses(fresh_session, run_b.id)]
    assert titles_a == titles_b
    assert run_a.status == run_b.status == "succeeded"


def test_invalid_replay_schema_does_not_seed_product_rows(fresh_session, tmp_path):
    base = tmp_path / "scenarios"
    shutil.copytree(SCENARIOS_DIR / "deploy-ambiguity", base / "deploy-ambiguity")
    rca_path = base / "deploy-ambiguity" / "replay" / "rca.json"
    replay = json.loads(rca_path.read_text(encoding="utf-8"))
    del replay["hypotheses"][0]["title"]
    rca_path.write_text(json.dumps(replay), encoding="utf-8")

    with pytest.raises(ScenarioValidationError, match="strict RCA schema"):
        ScenarioSeedService(fresh_session, base).seed_and_run("deploy-ambiguity")

    assert fresh_session.query(Incident).count() == 0
    assert fresh_session.query(Artifact).count() == 0
    assert fresh_session.query(AnalysisRun).count() == 0
