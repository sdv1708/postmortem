from __future__ import annotations

import json

import pytest

from postmortem.llm import FakeLLMClient
from postmortem.verification import (
    CLAIM_SUPPORT_VERIFIER_VERSION,
    ClaimSupportStatus,
    ClaimToVerify,
    LLMClaimSupportVerifier,
    build_claim_support_prompt,
)


def _verifier(response: str) -> LLMClaimSupportVerifier:
    return LLMClaimSupportVerifier(FakeLLMClient([response]))


def _claim() -> ClaimToVerify:
    return ClaimToVerify(
        claim_text="The 14:28 deploy caused the 500 spike",
        evidence=("14:28 deploy v184 rolled out", "14:32 api 500 rate climbing"),
    )


def test_supported_judgment_is_parsed():
    judgment = _verifier(
        json.dumps({"status": "supported", "rationale": "Deploy precedes the spike."})
    ).verify(_claim())
    assert judgment.status is ClaimSupportStatus.SUPPORTED
    assert judgment.rationale == "Deploy precedes the spike."


def test_partial_judgment_is_parsed():
    judgment = _verifier(
        json.dumps({"status": "partial", "rationale": "Correlation only, no causation."})
    ).verify(_claim())
    assert judgment.status is ClaimSupportStatus.PARTIAL


def test_unsupported_judgment_is_parsed():
    judgment = _verifier(
        json.dumps({"status": "unsupported", "rationale": "Snippets do not mention the deploy."})
    ).verify(_claim())
    assert judgment.status is ClaimSupportStatus.UNSUPPORTED


def test_schema_invalid_output_raises():
    # A status outside the allowed set must not become a verdict (ADR 0028).
    with pytest.raises(ValueError):
        _verifier(json.dumps({"status": "maybe", "rationale": "unsure"})).verify(_claim())


def test_non_json_output_raises():
    with pytest.raises(ValueError):
        _verifier("not json at all").verify(_claim())


def test_extra_fields_are_rejected():
    with pytest.raises(ValueError):
        _verifier(
            json.dumps({"status": "supported", "rationale": "ok", "confidence": 0.9})
        ).verify(_claim())


def test_prompt_includes_claim_and_numbered_evidence():
    system, user = build_claim_support_prompt(_claim())
    assert "single JSON object" in system
    assert "The 14:28 deploy caused the 500 spike" in user
    # Snippets are presented to the model as the cited evidence to judge.
    assert "[1] 14:28 deploy v184 rolled out" in user
    assert "[2] 14:32 api 500 rate climbing" in user


def test_verifier_reports_its_version():
    assert LLMClaimSupportVerifier(FakeLLMClient([])).version == CLAIM_SUPPORT_VERIFIER_VERSION
