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
    # The persisted Falsification Round output for this hypothesis (ADR 0034):
    # Evidence Gaps the falsifier could not close and the Falsification Tests it
    # proposed. Both are procedural, already-persisted content — not new incident
    # facts — so the composer may surface them (ADR 0026-safe). Empty when the
    # hypothesis was not challenged.
    challenge_evidence_gaps: tuple[str, ...] = ()
    challenge_falsification_tests: tuple[str, ...] = ()


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
    # Distinct Artifact source types included in the run (e.g. "logs",
    # "deployment_notes"), used to name which evidence categories are missing when
    # the analysis must refuse. Empty tuple is treated as "unknown".
    present_source_types: tuple[str, ...] = ()


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
    # Deterministic refusal assessment (ADR 0032 / 0015). ``evidence_sufficiency``
    # is "sufficient" or "insufficient". The gaps and validation steps are
    # procedural guidance about evidence completeness: on refusal they name the
    # structural evidence shortfall; on a sufficient run they carry forward the
    # Falsification Round's open Evidence Gaps and Falsification Tests so the
    # honest limits of a completed analysis stay visible, not just on refusal.
    evidence_sufficiency: str = "sufficient"
    evidence_gaps: tuple[str, ...] = ()
    next_validation_steps: tuple[str, ...] = ()


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
        sufficiency = self._sufficiency(context)
        insufficient = sufficiency == "insufficient"
        # On refusal, name the structural evidence shortfall. On a sufficient run,
        # carry forward the Falsification Round's open Evidence Gaps and proposed
        # Falsification Tests so a completed postmortem still states what it could
        # not close instead of implying nothing is missing.
        if insufficient:
            evidence_gaps = self._evidence_gaps(context)
            next_validation_steps = self._validation_steps(context)
        else:
            evidence_gaps = self._challenge_evidence_gaps(context)
            next_validation_steps = self._challenge_validation_steps(context)
        return PostmortemDraft(
            summary=self._summary(context, insufficient),
            lessons_learned=self._lessons(context),
            evidence_sufficiency=sufficiency,
            evidence_gaps=evidence_gaps,
            next_validation_steps=next_validation_steps,
        )

    def _sufficiency(self, context: PostmortemComposerContext) -> str:
        """Refuse unless at least one hypothesis is backed by cited evidence.

        ``assumption`` is False only when a hypothesis carried supporting
        EvidenceRefs (set in the RCA stage). If nothing the analysis proposes is
        evidence-backed — zero hypotheses, or every hypothesis an uncited
        assumption — there is no honest authoritative narrative, so the system
        refuses a confident postmortem (ADR 0032 / 0015) rather than presenting an
        unsupported one.
        """
        supported_basis = any(not h.assumption for h in context.hypotheses)
        return "sufficient" if supported_basis else "insufficient"

    def _summary(self, context: PostmortemComposerContext, insufficient: bool) -> str:
        artifacts = _count(context.artifact_count, "evidence artifact")
        parts = [f'Incident "{context.incident_title}" was analyzed from {artifacts}.']

        if insufficient:
            parts.append(
                "There is not enough evidence to write a confident postmortem; the "
                "system is withholding a root-cause conclusion rather than asserting "
                "an unsupported one."
            )

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

    def _evidence_gaps(self, context: PostmortemComposerContext) -> tuple[str, ...]:
        """Name what is missing, from structural signals only (ADR 0026-safe).

        These are statements about evidence *completeness*, not new factual
        claims about the incident, so a deterministic composer may emit them.
        """
        gaps: list[str] = []
        if context.timeline_event_count == 0:
            gaps.append("No time-anchored events could be extracted; the evidence has no timestamps.")
        if not context.hypotheses:
            gaps.append("No root-cause hypothesis could be formed from the available evidence.")
        elif all(h.assumption for h in context.hypotheses):
            gaps.append("Every proposed hypothesis is an unsupported assumption with no cited evidence.")
        present = set(context.present_source_types)
        if present and "logs" not in present:
            gaps.append("No application, gateway, or database logs were provided.")
        if present and "deployment_notes" not in present:
            gaps.append("No deployment or configuration-change history was provided.")
        return tuple(gaps)

    def _validation_steps(self, context: PostmortemComposerContext) -> tuple[str, ...]:
        """Concrete next evidence to collect so the analysis could proceed."""
        present = set(context.present_source_types)
        steps: list[str] = []
        if context.timeline_event_count == 0:
            steps.append("Collect timestamped logs spanning the incident window to anchor a timeline.")
        if present and "logs" not in present:
            steps.append("Attach application, gateway, or database logs from the affected service.")
        if present and "deployment_notes" not in present:
            steps.append("Attach the deploy and configuration-change history around the incident time.")
        steps.append(
            "Confirm the incident's start, detection, and resolution times with corroborating evidence."
        )
        return tuple(steps)

    def _challenge_evidence_gaps(
        self, context: PostmortemComposerContext
    ) -> tuple[str, ...]:
        """Open Evidence Gaps the Falsification Round could not close.

        Aggregated across hypotheses in rank order and deduplicated. These are the
        falsifier's already-persisted, procedural gap statements (ADR 0034), not
        new incident claims, so a deterministic composer may surface them on a
        completed analysis (ADR 0026-safe).
        """
        return _dedupe_in_order(
            gap for h in context.hypotheses for gap in h.challenge_evidence_gaps
        )

    def _challenge_validation_steps(
        self, context: PostmortemComposerContext
    ) -> tuple[str, ...]:
        """Falsification Tests proposed for the ranked hypotheses, deduplicated."""
        return _dedupe_in_order(
            test for h in context.hypotheses for test in h.challenge_falsification_tests
        )

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


def _dedupe_in_order(values) -> tuple[str, ...]:
    seen: set[str] = set()
    ordered: list[str] = []
    for value in values:
        if value not in seen:
            seen.add(value)
            ordered.append(value)
    return tuple(ordered)


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
