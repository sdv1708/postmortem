from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Final, Literal, Mapping, Protocol

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from .llm import LLMClient
from .provenance import ROLE_SUPPORT_VERIFIER, output_token_cap_for

# Versioned verifier identity recorded in Experiment Metadata (ADR 0025). Bump
# when the integrity contract or its outcomes change so runs stay comparable.
CITATION_VERIFIER_VERSION: Final[str] = "citation-integrity-1"
# Versioned identity for the semantic claim-support pass (ADR 0014 / 0025). Bump
# when its prompt or output contract changes so runs stay comparable.
CLAIM_SUPPORT_VERIFIER_VERSION: Final[str] = "claim-support-1"
# Versioned prompt/schema identity of the semantic claim-support pass (ADR 0028 /
# 0038), recorded on each support-verifier Model Call Record. Bump when the prompt
# or ``ClaimSupportOutput`` changes so judgments stay comparable.
CLAIM_SUPPORT_PROMPT_VERSION: Final[str] = "claim-support-prompt-1"
CLAIM_SUPPORT_SCHEMA_VERSION: Final[str] = "claim-support-output-1"


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


# --- Semantic claim-support verification (ADR 0014) -------------------------
#
# The second verification pass. Where citation integrity is a deterministic
# address check, claim support is an LLM judgment about whether the cited
# evidence actually backs a Major Claim. It is honest by construction: it judges
# the stored citation snippets (already the source of truth) and is allowed to
# say PARTIAL or UNSUPPORTED rather than overstate. Unsupported claims are
# flagged, never deleted, and never fail the run (ADR 0015).


class ClaimSupportStatus(str, Enum):
    """How well the cited evidence supports a Major Claim (ADR 0014)."""

    SUPPORTED = "supported"
    PARTIAL = "partial"
    UNSUPPORTED = "unsupported"


@dataclass(frozen=True)
class ClaimToVerify:
    """A Major Claim and the exact cited snippets that should back it.

    ORM-free so the verifier boundary stays swappable and unit-testable
    (ADR 0009 / 0014); ``evidence`` holds the stored citation snippets, which are
    the citation source of truth (ADR 0024), never model-invented text.
    """

    claim_text: str
    evidence: tuple[str, ...]


@dataclass(frozen=True)
class ClaimSupportJudgment:
    status: ClaimSupportStatus
    rationale: str


class ClaimSupportVerifier(Protocol):
    """Swappable semantic claim-support boundary (ADR 0014 / 0009, client brief).

    The MVP implementation is LLM-backed; tests inject fakes/replays so support
    classification is exercised without a live model.
    """

    @property
    def version(self) -> str: ...

    def verify(self, claim: ClaimToVerify) -> ClaimSupportJudgment: ...


class ClaimSupportOutput(BaseModel):
    """Strict structured output contract for the claim-support pass (ADR 0028).

    Free-form prose is not pipeline truth; the model must return exactly this
    JSON, which is validated before becoming claim state.
    """

    model_config = ConfigDict(extra="forbid")

    status: Literal["supported", "partial", "unsupported"]
    rationale: str = Field(min_length=1)


_CLAIM_SUPPORT_SYSTEM_PROMPT = """\
You are a skeptical incident reviewer judging whether cited evidence supports a
claim. You are not writing prose; you are auditing support.

Rules:
- Output ONLY a single JSON object. No prose, no markdown fences.
- Judge ONLY the evidence snippets provided. Do not use outside knowledge and do
  not invent facts beyond the snippets.
- "supported": the snippets clearly and directly establish the claim.
- "partial": the snippets are related and consistent but do not fully establish
  the claim (e.g. correlation without causation, or only part of the claim).
- "unsupported": the snippets do not establish the claim, or contradict it.
- Always include a one-sentence rationale grounded in the snippets.

The JSON object must match this shape:
{"status": "supported|partial|unsupported", "rationale": "one sentence"}
"""


def build_claim_support_prompt(claim: ClaimToVerify) -> tuple[str, str]:
    """Assemble the (system, user) prompt judging one claim against its evidence."""
    if claim.evidence:
        evidence = "\n".join(
            f"[{index}] {snippet}" for index, snippet in enumerate(claim.evidence, start=1)
        )
    else:
        evidence = "(no evidence was cited)"
    user = (
        f"CLAIM:\n{claim.claim_text}\n\n"
        f"CITED EVIDENCE:\n{evidence}\n\n"
        "Judge how well the cited evidence supports the claim and return the JSON "
        "object described in the system message."
    )
    return _CLAIM_SUPPORT_SYSTEM_PROMPT, user


class LLMClaimSupportVerifier:
    """Default claim-support verifier: one configured LLM behind the interface.

    Builds a strict prompt, calls the LLMClient (ADR 0011), and validates the
    completion against ``ClaimSupportOutput`` (ADR 0028). Schema-invalid or
    non-JSON output raises, which the flagging stage turns into a stage failure
    with one retry (ADR 0029) rather than persisting an unverifiable verdict.
    """

    version: Final[str] = CLAIM_SUPPORT_VERIFIER_VERSION

    def __init__(self, llm: LLMClient) -> None:
        self._llm = llm

    def verify(self, claim: ClaimToVerify) -> ClaimSupportJudgment:
        system, user = build_claim_support_prompt(claim)
        response = self._llm.complete(
            system=system, user=user, max_output_tokens=output_token_cap_for(ROLE_SUPPORT_VERIFIER)
        )
        try:
            output = ClaimSupportOutput.model_validate_json(response.text)
        except ValidationError as exc:
            raise ValueError(f"claim support output failed schema validation: {exc}") from exc
        return ClaimSupportJudgment(
            status=ClaimSupportStatus(output.status),
            rationale=output.rationale,
        )
