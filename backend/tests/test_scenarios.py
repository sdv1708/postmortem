from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from postmortem.scenarios import (
    SCENARIOS_DIR,
    ScenarioNotFoundError,
    ScenarioValidationError,
    load_scenario,
    list_scenarios,
    resolve_replay_rca,
)


CANONICAL = "deploy-ambiguity"


def test_canonical_scenario_loads_and_validates():
    scenario = load_scenario(CANONICAL)

    assert scenario.id == CANONICAL
    assert scenario.severity == "sev2"
    # All four evidence files are present with real, line-addressable bodies.
    names = [e.source_name for e in scenario.evidence]
    assert names == ["deploy-notes.md", "api-gateway.log", "db-pool.log", "oncall-notes.md"]
    assert all(e.body.strip() for e in scenario.evidence)
    # No evidence body carries a trailing blank line, so 1-based citations land
    # on real content.
    assert all(not e.body.endswith("\n") for e in scenario.evidence)
    # Ground-Truth Postmortem content is loaded (ADR 0006 / 0010).
    assert "ground truth" in scenario.ground_truth_postmortem.lower()
    # The replay shows the ambiguity: multiple competing hypotheses.
    assert len(scenario.rca_replay["hypotheses"]) >= 2


def test_list_scenarios_includes_the_canonical_demo():
    ids = [s.id for s in list_scenarios()]
    assert CANONICAL in ids


def test_unknown_scenario_raises_not_found():
    with pytest.raises(ScenarioNotFoundError):
        load_scenario("does-not-exist")


def test_resolve_replay_rewrites_source_name_to_artifact_id():
    replay = {
        "hypotheses": [
            {
                "title": "t",
                "supporting_evidence": [
                    {"source_name": "api-gateway.log", "line_start": 1, "line_end": 2}
                ],
            }
        ]
    }
    resolved = resolve_replay_rca(replay, {"api-gateway.log": "artifact-123"})
    ref = resolved["hypotheses"][0]["supporting_evidence"][0]
    assert ref == {"artifact_id": "artifact-123", "line_start": 1, "line_end": 2}
    # The original structure is not mutated.
    assert "source_name" in replay["hypotheses"][0]["supporting_evidence"][0]


def _clone_canonical(tmp_path: Path) -> Path:
    base = tmp_path / "scenarios"
    shutil.copytree(SCENARIOS_DIR / CANONICAL, base / CANONICAL)
    return base


def test_missing_evidence_file_fails_validation(tmp_path):
    base = _clone_canonical(tmp_path)
    (base / CANONICAL / "evidence" / "api-gateway.log").unlink()
    with pytest.raises(ScenarioValidationError, match="missing file"):
        load_scenario(CANONICAL, base)


def test_empty_ground_truth_fails_validation(tmp_path):
    base = _clone_canonical(tmp_path)
    (base / CANONICAL / "ground_truth_postmortem.md").write_text("\n  \n", encoding="utf-8")
    with pytest.raises(ScenarioValidationError, match="empty"):
        load_scenario(CANONICAL, base)


def test_replay_citation_to_unknown_source_fails_validation(tmp_path):
    base = _clone_canonical(tmp_path)
    rca_path = base / CANONICAL / "replay" / "rca.json"
    replay = json.loads(rca_path.read_text(encoding="utf-8"))
    replay["hypotheses"][0]["supporting_evidence"][0]["source_name"] = "ghost.log"
    rca_path.write_text(json.dumps(replay), encoding="utf-8")
    with pytest.raises(ScenarioValidationError, match="unknown evidence source"):
        load_scenario(CANONICAL, base)


def test_replay_citation_out_of_range_fails_validation(tmp_path):
    base = _clone_canonical(tmp_path)
    rca_path = base / CANONICAL / "replay" / "rca.json"
    replay = json.loads(rca_path.read_text(encoding="utf-8"))
    replay["hypotheses"][0]["supporting_evidence"][0]["line_end"] = 999
    rca_path.write_text(json.dumps(replay), encoding="utf-8")
    with pytest.raises(ScenarioValidationError, match="outside its"):
        load_scenario(CANONICAL, base)


def test_replay_schema_violation_fails_validation(tmp_path):
    base = _clone_canonical(tmp_path)
    rca_path = base / CANONICAL / "replay" / "rca.json"
    replay = json.loads(rca_path.read_text(encoding="utf-8"))
    del replay["hypotheses"][0]["title"]
    replay["hypotheses"][1]["supporting_evidence"][0]["confidence_score"] = 1.5
    rca_path.write_text(json.dumps(replay), encoding="utf-8")
    with pytest.raises(ScenarioValidationError, match="strict RCA schema"):
        load_scenario(CANONICAL, base)
