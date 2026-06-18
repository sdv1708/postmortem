from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import Final

from .llm import LLMClient, LLMResponse

# The Reasoning Roles whose invocations are recorded as Model Call Records
# (ADR 0038, PRD #26 user stories 57, 74). Stage 2's incident-fact extractor is
# recorded too so the provenance trail is complete and the recording buffer is
# drained at a clean boundary, but the four causal roles below are the ones the
# diagnostics view centers on.
ROLE_INCIDENT_FACTS: Final[str] = "incident_facts"
ROLE_BUILDER: Final[str] = "builder"
ROLE_FALSIFIER: Final[str] = "falsifier"
ROLE_SUPPORT_VERIFIER: Final[str] = "support_verifier"
ROLE_RANKER: Final[str] = "ranker"

# The falsifier performs Falsification Retrieval across ALL immutable run
# artifacts rather than the builder's retrieval subset (ADR 0034, PRD user story
# 13), so its Retrieval Trace records this strategy label instead of the builder's
# RetrievalStrategy version.
FALSIFICATION_RETRIEVAL_STRATEGY: Final[str] = "falsification-all-artifacts-1"

# The support verifier does not retrieve; it judges the verified supporting
# citations handed to it (a Role Handoff, ADR 0037). Its input trace records the
# chunks those citations resolve to so a support judgment with no evidence in
# front of it (an input omission) is distinguishable from one that saw evidence
# and judged it unsupported (a reasoning outcome) — PRD user story 69.
SUPPORT_INPUT_STRATEGY: Final[str] = "support-verified-citations-1"

# Roles recorded by each claim-generating stage, so a stage retry can clear only
# its own provenance before regenerating (idempotency, ADR 0029).
STAGE2_ROLES: Final[frozenset[str]] = frozenset({ROLE_INCIDENT_FACTS})
STAGE3_ROLES: Final[frozenset[str]] = frozenset(
    {ROLE_BUILDER, ROLE_FALSIFIER, ROLE_SUPPORT_VERIFIER, ROLE_RANKER}
)


def content_hash(*parts: str) -> str:
    """A stable digest of prompt/response text for reproducibility (ADR 0038).

    Product provenance records store only this digest, never the prompt or raw
    response text itself, so Sensitive Evidence is not duplicated into the
    provenance tables (PRD user stories 71, 73). Two runs over identical input and
    output therefore produce identical hashes without exposing the content.
    """
    digest = hashlib.sha256()
    for index, part in enumerate(parts):
        if index:
            digest.update(b"\x00")
        digest.update(part.encode("utf-8"))
    return digest.hexdigest()


@dataclass(frozen=True)
class CapturedModelCall:
    """One model completion's reproducibility metadata, captured in flight.

    Holds hashes and token usage only — never the prompt or completion text — so
    a Model Call Record can be written without copying Sensitive Evidence
    (ADR 0038, PRD user story 71/73). ``model_identity`` is the client label that
    produced the completion.
    """

    model_identity: str
    input_hash: str
    output_hash: str
    usage: dict | None


class RecordingLLMClient:
    """An LLMClient decorator that buffers each completion's provenance (ADR 0038).

    Wraps the configured generation client so every Reasoning Role that talks to a
    model funnels through it transparently. After each ``complete`` it appends a
    ``CapturedModelCall`` — prompt/response *hashes* and token usage, never their
    text — which the stage drains at the role boundary to write a Model Call
    Record. Because it stores no prompt or raw response, Sensitive Evidence is
    never duplicated into product provenance (PRD user stories 71, 73). The
    pipeline keeps depending only on the ``LLMClient`` surface (ADR 0011); this is
    a swappable wrapper, not a new boundary.
    """

    def __init__(self, inner: LLMClient) -> None:
        self._inner = inner
        self._buffer: list[CapturedModelCall] = []

    @property
    def label(self) -> str:
        return self._inner.label

    def complete(self, *, system: str, user: str) -> LLMResponse:
        response = self._inner.complete(system=system, user=user)
        self._buffer.append(
            CapturedModelCall(
                model_identity=self._inner.label,
                input_hash=content_hash(system, user),
                output_hash=content_hash(response.text),
                usage=response.usage,
            )
        )
        return response

    def drain(self) -> list[CapturedModelCall]:
        """Return the captures since the last drain and clear the buffer.

        Called at each role boundary so captures are attributed to the role that
        produced them. A deterministic role (e.g. the default advisory ranker)
        makes no model call, so its drain is empty and the stage records a Model
        Call Record with the role's own version as model identity instead.
        """
        captures = self._buffer
        self._buffer = []
        return captures
