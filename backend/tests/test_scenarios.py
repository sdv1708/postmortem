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
    # Every replay hypothesis has a bundled Hypothesis Challenge so the demo's
    # mandatory stage-3 challenge coverage is complete (ADR 0034). The falsifier
    # also surfaces a missed alternative; that proposed hypothesis is itself
    # challenged once (ADR 0036), so the challenge keys are the builder titles plus
    # the proposed alternative's title.
    titles = {h["title"] for h in scenario.rca_replay["hypotheses"]}
    proposed_titles = {
        p["title"]
        for challenge in scenario.falsification_replay.values()
        for p in challenge.get("proposed_hypotheses", [])
    }
    assert proposed_titles, "the canonical demo should exercise the expansion round"
    assert set(scenario.falsification_replay.keys()) == titles | proposed_titles
    one = next(iter(scenario.falsification_replay.values()))
    assert one["severity"] in {"critical", "material", "minor"}


@pytest.mark.parametrize(
    "scenario_id,expected_families",
    [
        ("dependency-failure", {"provider-degradation", "missing-resilience", "local-regression"}),
        ("config-drift", {"config-drift", "traffic-surge", "code-regression"}),
    ],
)
def test_additional_scenario_families_load_and_validate(scenario_id, expected_families):
    # ADR 0006: deploy, dependency failure, and configuration drift families with
    # evidence files and Ground-Truth Postmortems.
    scenario = load_scenario(scenario_id)
    assert scenario.id == scenario_id
    assert len(scenario.evidence) == 4
    assert all(e.body.strip() for e in scenario.evidence)
    assert "ground truth" in scenario.ground_truth_postmortem.lower()
    assert set(scenario.expected_hypothesis_families) == expected_families
    # Each ships a multi-hypothesis replay that passes strict RCA + ref validation.
    assert len(scenario.rca_replay["hypotheses"]) == 3
    # And a falsifier replay that challenges every replay hypothesis (ADR 0034).
    titles = {h["title"] for h in scenario.rca_replay["hypotheses"]}
    assert set(scenario.falsification_replay.keys()) == titles


def test_insufficient_evidence_scenario_loads_as_refusal_stub():
    scenario = load_scenario("insufficient-evidence")

    assert scenario.id == "insufficient-evidence"
    assert "insufficient-evidence" in scenario.evaluation_tags
    assert "refusal" in scenario.evaluation_tags
    assert len(scenario.evidence) == 1
    assert scenario.expected_hypothesis_families == ()
    assert scenario.rca_replay == {"hypotheses": []}
    assert "not enough" in scenario.ground_truth_postmortem.lower()


def test_list_scenarios_includes_the_canonical_demo():
    ids = [s.id for s in list_scenarios()]
    assert CANONICAL in ids
    assert "insufficient-evidence" in ids


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


def test_incomplete_falsification_coverage_fails_validation(tmp_path):
    """A scenario with hypotheses must challenge each one or fail fast (ADR 0034)."""
    base = _clone_canonical(tmp_path)
    falsification_path = base / CANONICAL / "replay" / "falsification.json"
    replay = json.loads(falsification_path.read_text(encoding="utf-8"))
    # Drop one hypothesis's challenge: coverage is now incomplete.
    replay.pop(next(iter(replay)))
    falsification_path.write_text(json.dumps(replay), encoding="utf-8")
    with pytest.raises(ScenarioValidationError, match="challenge exactly the replay hypotheses"):
        load_scenario(CANONICAL, base)


def test_falsification_schema_violation_fails_validation(tmp_path):
    base = _clone_canonical(tmp_path)
    falsification_path = base / CANONICAL / "replay" / "falsification.json"
    replay = json.loads(falsification_path.read_text(encoding="utf-8"))
    # An invalid severity violates the strict falsifier contract (ADR 0028).
    title = next(iter(replay))
    replay[title]["severity"] = "catastrophic"
    falsification_path.write_text(json.dumps(replay), encoding="utf-8")
    with pytest.raises(ScenarioValidationError, match="strict schema"):
        load_scenario(CANONICAL, base)


def test_more_than_two_proposed_alternatives_fails_validation(tmp_path):
    """The bounded expansion round caps proposals at two (ADR 0036, AC #4)."""
    base = _clone_canonical(tmp_path)
    falsification_path = base / CANONICAL / "replay" / "falsification.json"
    replay = json.loads(falsification_path.read_text(encoding="utf-8"))
    title = next(iter(replay))
    replay[title]["proposed_hypotheses"] = [
        {"title": "Alt one"},
        {"title": "Alt two"},
        {"title": "Alt three"},
    ]
    falsification_path.write_text(json.dumps(replay), encoding="utf-8")
    with pytest.raises(ScenarioValidationError, match="exceeding the bounded maximum"):
        load_scenario(CANONICAL, base)


def test_recursive_proposed_alternative_fails_validation(tmp_path):
    """A proposed alternative may not itself propose further hypotheses (AC #1)."""
    base = _clone_canonical(tmp_path)
    falsification_path = base / CANONICAL / "replay" / "falsification.json"
    replay = json.loads(falsification_path.read_text(encoding="utf-8"))
    title = next(iter(replay))
    replay[title]["proposed_hypotheses"] = [{"title": "Recursive alt"}]
    # The proposed alternative's own challenge tries to expand again.
    replay["Recursive alt"] = {
        "challenged_claim": "x",
        "severity": "minor",
        "proposed_hypotheses": [{"title": "Even deeper alt"}],
    }
    falsification_path.write_text(json.dumps(replay), encoding="utf-8")
    with pytest.raises(ScenarioValidationError, match="no recursive expansion"):
        load_scenario(CANONICAL, base)
