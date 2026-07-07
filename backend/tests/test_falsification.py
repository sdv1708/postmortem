"""Unit tests for the falsifier contract (ADR 0034 / 0036).

These cover the strict structured-output schema and the prompt toggle directly,
without the deep stage, so the Reasoning Role's contract is pinned independently.
"""

from __future__ import annotations

from postmortem.falsification import (
    HypothesisChallengeOutput,
    HypothesisToChallenge,
    LLMFalsifier,
    build_falsification_prompt,
)
from postmortem.llm import FakeLLMClient
from postmortem.rca import RcaHypothesis, RcaRemediationItem


class _Artifact:
    def __init__(self, id: str, body: str) -> None:
        self.id = id
        self.source_type = "logs"
        self.source_name = "api.log"
        self.body = body


def _hypothesis() -> HypothesisToChallenge:
    return HypothesisToChallenge(
        title="Deploy regressed the pool",
        summary="v184 preceded the pool exhaustion.",
        supporting_snippets=("deploy v184 rolled out",),
        contradicting_snippets=(),
    )


def test_output_schema_round_trips_proposed_hypotheses():
    output = HypothesisChallengeOutput.model_validate(
        {
            "challenged_claim": "x",
            "severity": "material",
            "proposed_hypotheses": [
                {
                    "title": "Cache eviction shifted load",
                    "summary": "A cache eviction pushed reads onto the DB.",
                    "supporting_evidence": [
                        {"artifact_id": "a1", "line_start": 1, "line_end": 1}
                    ],
                }
            ],
        }
    )
    assert len(output.proposed_hypotheses) == 1
    assert isinstance(output.proposed_hypotheses[0], RcaHypothesis)
    # Defaults to empty so the offline/no-proposal path validates unchanged.
    assert HypothesisChallengeOutput(challenged_claim="x", severity="minor").proposed_hypotheses == []


def test_remediation_item_accepts_item_alias_for_description():
    # The GPT-5 family sometimes emits remediation text under "item"; accept it as
    # an alias so a proposed hypothesis does not fail strict validation, while
    # keeping "description" canonical on output.
    aliased = RcaRemediationItem.model_validate({"item": "index the facet field"})
    assert aliased.description == "index the facet field"
    assert aliased.model_dump()["description"] == "index the facet field"
    assert "item" not in aliased.model_dump()

    canonical = RcaRemediationItem.model_validate({"description": "same key"})
    assert canonical.description == "same key"


def test_proposed_hypothesis_with_item_keyed_remediation_validates():
    output = HypothesisChallengeOutput.model_validate(
        {
            "challenged_claim": "x",
            "severity": "material",
            "proposed_hypotheses": [
                {
                    "title": "Retry storm amplified the exhaustion",
                    "summary": "Amplifying condition: clients retried without backoff.",
                    "remediation_items": [{"item": "add exponential backoff"}],
                }
            ],
        }
    )
    assert output.proposed_hypotheses[0].remediation_items[0].description == (
        "add exponential backoff"
    )


def test_prompt_permits_or_forbids_proposals_by_round():
    artifacts = [_Artifact("a1", "deploy v184 rolled out\npool exhausted")]
    allowed_system, _ = build_falsification_prompt(
        _hypothesis(), artifacts, [], allow_proposals=True
    )
    forbidden_system, _ = build_falsification_prompt(
        _hypothesis(), artifacts, [], allow_proposals=False
    )
    assert "MAY surface a missed alternative" in allowed_system
    assert "Do NOT propose new hypotheses" in forbidden_system
    # Both still document the JSON shape with the proposed_hypotheses field.
    assert '"proposed_hypotheses"' in allowed_system
    assert '"proposed_hypotheses"' in forbidden_system


def test_llm_falsifier_passes_allow_proposals_into_its_prompt():
    captured: dict[str, str] = {}

    class _Client(FakeLLMClient):
        def complete(self, *, system: str, user: str, max_output_tokens: int | None = None):
            captured["system"] = system
            return super().complete(
                system=system, user=user, max_output_tokens=max_output_tokens
            )

    client = _Client(['{"challenged_claim": "x", "severity": "minor"}'])
    LLMFalsifier(client).challenge(
        hypothesis=_hypothesis(),
        artifacts=[_Artifact("a1", "deploy v184 rolled out")],
        timeline_events=[],
        allow_proposals=False,
    )
    assert "Do NOT propose new hypotheses" in captured["system"]
