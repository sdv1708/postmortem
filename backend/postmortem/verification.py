from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Final, Mapping, Protocol

# Versioned verifier identity recorded in Experiment Metadata (ADR 0025). Bump
# when the integrity contract or its outcomes change so runs stay comparable.
CITATION_VERIFIER_VERSION: Final[str] = "citation-integrity-1"


class CitationIntegrityStatus(str, Enum):
    """Deterministic citation-integrity outcomes (ADR 0014).

    Citation integrity is the mechanical trust floor for the core differentiator
    (ADR 0002 / 0010): a citation must address existing immutable Artifact lines
    and its stored snippet must equal those exact lines, character for character.
    This is distinct from semantic Claim Support (SUPPORTED/PARTIAL/UNSUPPORTED),
    which is a later, LLM-assisted concern (ADR 0014).
    """

    VERIFIED = "verified"
    ARTIFACT_MISSING = "artifact_missing"
    LINE_RANGE_INVALID = "line_range_invalid"
    SNIPPET_MISMATCH = "snippet_mismatch"

    @property
    def ok(self) -> bool:
        return self is CitationIntegrityStatus.VERIFIED


@dataclass(frozen=True)
class CitationTarget:
    """The minimal, immutable evidence address a verifier checks.

    Decoupled from the ORM so the deterministic check is trivially unit-testable
    and the verifier boundary stays swappable (ADR 0009 / 0014). Line numbers are
    1-based and inclusive, matching how EvidenceRefs cite Artifact lines.
    """

    artifact_id: str
    line_start: int
    line_end: int
    snippet: str


class CitationVerifier(Protocol):
    """Swappable citation verifier boundary (ADR 0014, client brief).

    The MVP ships only the deterministic integrity pass; a semantic
    ClaimSupportVerifier is a separate, later implementation behind this same
    boundary. ``artifact_bodies`` maps artifact id to canonical body text for the
    evidence in scope — the verifier never reads the database itself.
    """

    @property
    def version(self) -> str: ...

    def verify(
        self, target: CitationTarget, artifact_bodies: Mapping[str, str]
    ) -> CitationIntegrityStatus: ...


class DeterministicCitationIntegrityVerifier:
    """Checks Artifact existence, line-range existence, and exact snippet match.

    Each check is deterministic and order-sensitive: an absent artifact short-
    circuits before line math, and an out-of-range range short-circuits before
    the snippet compare. The snippet is rebuilt from the cited lines exactly as
    the timeline and RCA stages resolve it (``"\\n".join`` of the 1-based
    inclusive range), so a verified citation is provably the source of truth.
    """

    version: Final[str] = CITATION_VERIFIER_VERSION

    def verify(
        self, target: CitationTarget, artifact_bodies: Mapping[str, str]
    ) -> CitationIntegrityStatus:
        body = artifact_bodies.get(target.artifact_id)
        if body is None:
            return CitationIntegrityStatus.ARTIFACT_MISSING
        lines = body.split("\n")
        if (
            target.line_start < 1
            or target.line_end < target.line_start
            or target.line_end > len(lines)
        ):
            return CitationIntegrityStatus.LINE_RANGE_INVALID
        expected = "\n".join(lines[target.line_start - 1 : target.line_end])
        if expected != target.snippet:
            return CitationIntegrityStatus.SNIPPET_MISMATCH
        return CitationIntegrityStatus.VERIFIED
