from __future__ import annotations

from postmortem.verification import (
    CITATION_VERIFIER_VERSION,
    CitationIntegrityStatus,
    CitationTarget,
    DeterministicCitationIntegrityVerifier,
)


BODY = "first line\nsecond line\nthird line"
BODIES = {"art-1": BODY}


def _verify(target: CitationTarget) -> CitationIntegrityStatus:
    return DeterministicCitationIntegrityVerifier().verify(target, BODIES)


def test_exact_single_line_citation_is_verified():
    status = _verify(CitationTarget("art-1", 2, 2, "second line"))
    assert status is CitationIntegrityStatus.VERIFIED
    assert status.ok is True


def test_multi_line_citation_matches_joined_lines():
    # Snippet must equal the 1-based inclusive range joined with newlines, the
    # same way the timeline and RCA stages resolve it (ADR 0024).
    status = _verify(CitationTarget("art-1", 1, 2, "first line\nsecond line"))
    assert status is CitationIntegrityStatus.VERIFIED


def test_missing_artifact_is_flagged():
    status = _verify(CitationTarget("nope", 1, 1, "first line"))
    assert status is CitationIntegrityStatus.ARTIFACT_MISSING
    assert status.ok is False


def test_line_range_past_the_end_is_flagged():
    status = _verify(CitationTarget("art-1", 3, 9, "third line"))
    assert status is CitationIntegrityStatus.LINE_RANGE_INVALID


def test_zero_and_inverted_line_ranges_are_flagged():
    assert _verify(CitationTarget("art-1", 0, 1, "first line")) is (
        CitationIntegrityStatus.LINE_RANGE_INVALID
    )
    assert _verify(CitationTarget("art-1", 2, 1, "")) is (
        CitationIntegrityStatus.LINE_RANGE_INVALID
    )


def test_snippet_that_does_not_match_stored_lines_is_flagged():
    # The line range exists, but the stored snippet has drifted from the cited
    # text — exactly the tampering the integrity pass must catch (ADR 0002).
    status = _verify(CitationTarget("art-1", 2, 2, "SECOND line"))
    assert status is CitationIntegrityStatus.SNIPPET_MISMATCH


def test_artifact_existence_short_circuits_before_line_math():
    # An unknown artifact is reported as missing even when the line numbers are
    # nonsense, because existence is checked first.
    status = _verify(CitationTarget("nope", 999, 999, "anything"))
    assert status is CitationIntegrityStatus.ARTIFACT_MISSING


def test_status_values_are_stable_strings_for_persistence():
    # The enum doubles as the persisted column value (EvidenceRef.verifier_status).
    assert CitationIntegrityStatus.VERIFIED.value == "verified"
    assert CitationIntegrityStatus.SNIPPET_MISMATCH.value == "snippet_mismatch"
    assert DeterministicCitationIntegrityVerifier().version == CITATION_VERIFIER_VERSION
