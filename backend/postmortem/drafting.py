from __future__ import annotations

from dataclasses import dataclass
from typing import Final, Protocol

# Versioned identity for the drafting composer, recorded on each Postmortem so
# template choices stay comparable (ADR 0025, client brief "Postmortem
# template"). Bump when the composition logic changes.
POSTMORTEM_COMPOSER_VERSION: Final[str] = "postmortem-template-1"


@dataclass(frozen=True)
class HypothesisDigest:
    """The minimal hypothesis facts the composer reads.

    ORM-free so the composer boundary stays swappable and unit-testable
    (ADR 0009). Only already-persisted, already-verified fields are carried — the
    composer must not introduce new factual incident claims (ADR 0026).
    """

    rank: int
    title: str
    assumption: bool
    unknowns: tuple[str, ...]


@dataclass(frozen=True)
class PostmortemComposerContext:
    """The structured outputs a Postmortem is composed from (ADR 0012 / 0026).

    Everything here is derived from prior stages' persisted state: incident
    metadata, timeline counts/anchors, and ranked hypotheses. The composer turns
    this into connective narrative (summary, lessons) without asserting any new
    incident fact.
    """

    incident_title: str
    incident_severity: str | None
    artifact_count: int
    timeline_event_count: int
    earliest_ts_text: str | None
    latest_ts_text: str | None
    hypotheses: tuple[HypothesisDigest, ...]


@dataclass(frozen=True)
class PostmortemDraft:
    """The composed sections that are not already structured claims.

    ``summary`` is connective overview prose and ``lessons_learned`` are
    reflective follow-ups (CONTEXT "Major Claim vs Generic Text"): neither is a
    Major Claim, so they carry no citations. The factual sections (timeline,
    hypotheses, impact, remediation) are the existing structured rows and are not
    regenerated here.
    """

    summary: str
    lessons_learned: tuple[str, ...]


class PostmortemComposer(Protocol):
    """Swappable Postmortem template boundary (client brief, ADR 0009 / 0012).

    The MVP ships one deterministic composer; alternates (e.g. an LLM-assisted
    template) can be injected behind this same surface. ``version`` is recorded
    in experiment metadata on the Postmortem row.
    """

    @property
    def version(self) -> str: ...

    def compose(self, context: PostmortemComposerContext) -> PostmortemDraft: ...


class DeterministicPostmortemComposer:
    """Composes the Postmortem narrative from structured outputs, no LLM.

    Drafting is a stage-5 audit/compose step: it runs after citation
    verification, so it must introduce no new factual incident claims (ADR 0026).
    A deterministic composer guarantees that by construction — every sentence it
    emits restates a count or a timestamp anchor that an earlier verified stage
    already produced. It deliberately does not name a leading hypothesis because
    support filtering runs after drafting, and clean exports include this summary
    as authoritative narrative. It also makes no model call, so it neither needs
    a provider nor disturbs pipeline tests that seed LLM responses for the RCA
    stage.
    """

    version: Final[str] = POSTMORTEM_COMPOSER_VERSION

    def compose(self, context: PostmortemComposerContext) -> PostmortemDraft:
        return PostmortemDraft(
            summary=self._summary(context),
            lessons_learned=self._lessons(context),
        )

    def _summary(self, context: PostmortemComposerContext) -> str:
        artifacts = _count(context.artifact_count, "evidence artifact")
        parts = [f'Incident "{context.incident_title}" was analyzed from {artifacts}.']

        if context.timeline_event_count == 0:
            parts.append("No timeline events were extracted from the available evidence.")
        else:
            events = _count(context.timeline_event_count, "event")
            parts.append(f"The reconstructed timeline contains {events}{_span(context)}.")

        if not context.hypotheses:
            parts.append("The analysis produced no root-cause hypotheses for this evidence.")
        else:
            hyps = _count(len(context.hypotheses), "root-cause hypothesis", "root-cause hypotheses")
            verb = "was" if len(context.hypotheses) == 1 else "were"
            parts.append(f"{hyps} {verb} generated for evidence review.")
            if all(h.assumption for h in context.hypotheses):
                parts.append(
                    "Every hypothesis is currently an assumption pending supporting evidence."
                )

        return " ".join(parts)

    def _lessons(self, context: PostmortemComposerContext) -> tuple[str, ...]:
        # The honest "lessons" for an unresolved, ambiguous incident are the open
        # questions the hypotheses still carry. Deduplicated in rank order; never
        # invented.
        seen: set[str] = set()
        lessons: list[str] = []
        for hypothesis in context.hypotheses:
            for unknown in hypothesis.unknowns:
                if unknown not in seen:
                    seen.add(unknown)
                    lessons.append(unknown)
        return tuple(lessons)


def _span(context: PostmortemComposerContext) -> str:
    earliest, latest = context.earliest_ts_text, context.latest_ts_text
    if not earliest or not latest:
        return ""
    if earliest == latest:
        return f" at {earliest}"
    return f" from {earliest} to {latest}"


def _count(value: int, singular: str, plural: str | None = None) -> str:
    noun = singular if value == 1 else (plural or f"{singular}s")
    return f"{value} {noun}"
