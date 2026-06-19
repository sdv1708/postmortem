from __future__ import annotations

from enum import Enum

from .schemas import (
    CausalFactorRead,
    EvidenceRefRead,
    HypothesisRead,
    ImpactClaimRead,
    PostmortemRead,
    RootCauseConclusionRead,
    TimelineEventRead,
)


class ExportMode(str, Enum):
    """How a Markdown export treats unsupported and assumption claims (ADR 0015).

    ``CLEAN`` is the shareable final postmortem: it presents only evidence-backed
    (supported/partial) claims and omits unsupported claims and assumptions so
    nothing unverified reads as incident truth. ``AUDIT`` is the review export:
    it additionally surfaces unsupported claims and assumptions, clearly labeled,
    so a reviewer can audit what the system was unsure about.
    """

    CLEAN = "clean"
    AUDIT = "audit"


# Support verdicts that may appear in the authoritative narrative (ADR 0014 /
# 0015). Unsupported, assumption, and not-yet-evaluated claims are excluded from
# clean exports and moved to the audit-only Review Findings section.
_AUTHORITATIVE_SUPPORT = frozenset({"supported", "partial"})

# The mandatory provisional label (ADR 0035, PRD #26 stories 27-28). Every export
# of a provisional draft — clean or audit — carries this so a shared draft can
# never be mistaken for a human-finalized Root Cause Conclusion.
DRAFT_NOT_FINALIZED = "Draft: Root cause not finalized"


def render_markdown(postmortem: PostmortemRead, mode: ExportMode) -> str:
    """Render a structured Postmortem to Markdown (ADR 0012 / 0022).

    The Markdown is derived entirely from the structured Postmortem read model —
    every claim, timestamp, and snippet comes from persisted rows, and the
    function never parses Markdown back into truth (ADR 0012). ``mode`` controls
    only which already-classified claims are shown, not their content.
    """
    authoritative = [h for h in postmortem.hypotheses if _is_authoritative(h.support_status)]
    review_findings = [h for h in postmortem.hypotheses if not _is_authoritative(h.support_status)]

    insufficient = postmortem.evidence_sufficiency == "insufficient"
    provisional = postmortem.conclusion_status == "provisional"
    # A Disputed Conclusion is no longer authoritative (ADR 0040): the incident has
    # returned to unresolved review. Distinct from provisional (a conclusion *was*
    # finalized, then disputed), so it carries its own prominent banner.
    disputed = postmortem.conclusion_status == "disputed"

    title = f"# Postmortem — {postmortem.incident_title}"
    if provisional:
        # Stamp the provisional status into the heading itself so it survives
        # copy/paste of a fragment, not just the metadata block (ADR 0035).
        title = f"{title} [{DRAFT_NOT_FINALIZED}]"
    lines: list[str] = [title, ""]
    if provisional:
        lines.append(
            f"> **{DRAFT_NOT_FINALIZED}.** This is an automated provisional "
            "postmortem. It presents hypotheses and uncertainty for review; no "
            "root cause has been established. Only a human reviewer finalizes a "
            "Root Cause Conclusion."
        )
        lines.append("")
    if disputed:
        # Prominent, audit-safe: the conclusion is preserved but not authoritative.
        lines.append(
            "> **Disputed conclusion.** A reviewer has raised an open discrepancy "
            "against the finalized Root Cause Conclusion. It is no longer "
            "authoritative and the incident has returned to unresolved review. The "
            "conclusion and the discrepancies are retained for audit below."
        )
        lines.append("")
    lines.append(f"- **Severity:** {postmortem.incident_severity or '—'}")
    lines.append(f"- **Export mode:** {mode.value}")
    lines.append(f"- **Status:** {postmortem.conclusion_status}")
    lines.append(f"- **Evidence sufficiency:** {postmortem.evidence_sufficiency}")
    if insufficient:
        lines.append(
            "- **Refusal:** The evidence is insufficient for a confident postmortem. "
            "No root cause is asserted; see what is missing below."
        )
    if mode is ExportMode.AUDIT:
        lines.append(
            "- **Note:** Audit export — includes unsupported claims and assumptions "
            "flagged for review. These are not verified incident facts."
        )
    lines.append("")

    _section(lines, "Summary", [postmortem.summary] if postmortem.summary else [])

    if insufficient:
        _section(
            lines,
            "What's missing",
            [f"- {gap}" for gap in postmortem.evidence_gaps] or ["_No specific gaps recorded._"],
        )
        _section(
            lines,
            "Suggested next evidence",
            [f"- {step}" for step in postmortem.next_validation_steps]
            or ["_No next steps recorded._"],
        )

    lines.append("## Timeline")
    lines.append("")
    if postmortem.timeline:
        lines.extend(_timeline_line(event) for event in postmortem.timeline)
    else:
        lines.append("_No timeline events were extracted from the evidence._")
    lines.append("")

    _impact_section(lines, postmortem.impact_claims, mode)
    if postmortem.conclusion is not None:
        _conclusion_section(lines, postmortem.conclusion, mode, disputed=disputed)
    _hypotheses_section(lines, authoritative, mode)
    if mode is ExportMode.AUDIT and review_findings:
        _review_findings_section(lines, review_findings)
    _remediation_section(lines, authoritative)

    lines.append("## Open questions")
    lines.append("")
    if postmortem.lessons_learned:
        lines.extend(f"- {lesson}" for lesson in postmortem.lessons_learned)
    else:
        lines.append("_No open questions were recorded._")
    lines.append("")

    return "\n".join(lines).rstrip() + "\n"


def _is_authoritative(support_status: str) -> bool:
    return support_status in _AUTHORITATIVE_SUPPORT


def _section(lines: list[str], heading: str, body: list[str]) -> None:
    lines.append(f"## {heading}")
    lines.append("")
    lines.extend(body)
    lines.append("")


def _timeline_line(event: TimelineEventRead) -> str:
    when = (
        event.normalized_ts.isoformat().replace("+00:00", "Z")
        if event.normalized_ts is not None
        else (event.original_ts_text or "—")
    )
    inferred = " _(inferred)_" if event.uncertain else ""
    refs = _refs(event.evidence_refs)
    suffix = f" ({refs})" if refs else ""
    return f"- `{when}`{inferred} — {event.description}{suffix}"


def _impact_section(
    lines: list[str],
    impact_claims: list[ImpactClaimRead],
    mode: ExportMode,
) -> None:
    """Render run-level Impact Claims once (ADR 0033).

    Impact is an incident fact owned by the run, not by any hypothesis, so it is
    rendered a single time regardless of how many hypotheses the run produced. A
    clean export shows only evidence-backed (supported/partial) impact; an audit
    export additionally retains unsupported/assumption impact, labeled.
    """
    lines.append("## Impact analysis")
    lines.append("")
    rendered = [
        _impact_line(claim, mode)
        for claim in impact_claims
        if mode is ExportMode.AUDIT or _is_authoritative(claim.support_status)
    ]
    if rendered:
        lines.extend(rendered)
    elif mode is ExportMode.CLEAN:
        lines.append("_No evidence-backed impact claims were recorded._")
    else:
        lines.append("_No impact claims were recorded._")
    lines.append("")


def _impact_line(claim: ImpactClaimRead, mode: ExportMode) -> str:
    refs = _refs(claim.evidence_refs)
    suffix = f" ({refs})" if refs else ""
    annotation = _support_annotation(claim.support_status) if mode is ExportMode.AUDIT else ""
    return f"- {claim.description}{annotation}{suffix}"


def _conclusion_section(
    lines: list[str],
    conclusion: RootCauseConclusionRead,
    mode: ExportMode,
    *,
    disputed: bool,
) -> None:
    """Render the finalized human Root Cause Conclusion (ADR 0039 / 0040).

    Distinct from the Advisory Hypothesis Ranking below: a ranking recommends
    plausible candidates, this is the human's decision (PRD #26 stories 30, 90).
    Shows the single Failure Mechanism, optional repeatable Triggers and Amplifying
    Conditions, and Conclusion Provenance.

    A Disputed Conclusion is not authoritative (ADR 0040, PRD #26 stories 44-46): a
    **clean** export withholds the disputed causal account so it cannot read as
    current fact, while an **audit** export preserves the full conclusion and the
    recorded discrepancies for the historical record.
    """
    lines.append("## Root Cause Conclusion")
    lines.append("")
    if disputed and mode is ExportMode.CLEAN:
        lines.append(
            "_This conclusion has an open discrepancy and has returned to unresolved "
            "review, so it is withheld from this clean export. See the audit export "
            "for the disputed conclusion and the recorded discrepancies._"
        )
        lines.append("")
        return
    who = conclusion.finalized_by_display or conclusion.finalized_by
    when = conclusion.finalized_at.isoformat().replace("+00:00", "Z")
    finalized_note = (
        f"_Finalized by {who} on {when}. This is the human reviewer's conclusion, "
        "not an automated ranking; the hypotheses below are the advisory candidates "
        "it was drawn from._"
    )
    if disputed:
        finalized_note = (
            f"_Disputed — retained for audit, not authoritative. {finalized_note[1:]}"
        )
    lines.append(finalized_note)
    lines.append("")
    lines.append(conclusion.summary)
    lines.append("")
    lines.append("**Failure mechanism:**")
    lines.append(_causal_factor_line(conclusion.failure_mechanism))
    if conclusion.triggers:
        lines.append("")
        lines.append("**Triggers:**")
        lines.extend(_causal_factor_line(factor) for factor in conclusion.triggers)
    if conclusion.amplifying_conditions:
        lines.append("")
        lines.append("**Amplifying conditions:**")
        lines.extend(
            _causal_factor_line(factor) for factor in conclusion.amplifying_conditions
        )
    if conclusion.discrepancies:
        # Audit-only: preserve the recorded disagreement alongside the conclusion.
        lines.append("")
        lines.append("**Recorded discrepancies:**")
        for discrepancy in conclusion.discrepancies:
            raised_by = discrepancy.raised_by_display or discrepancy.raised_by
            raised_at = discrepancy.created_at.isoformat().replace("+00:00", "Z")
            lines.append(
                f"- {discrepancy.explanation} _(raised by {raised_by} on {raised_at})_"
            )
    lines.append("")


def _causal_factor_line(factor: CausalFactorRead) -> str:
    refs = _refs(factor.supporting_evidence)
    suffix = f" ({refs})" if refs else ""
    return f"- {factor.title}{suffix}"


def _hypotheses_section(
    lines: list[str], authoritative: list[HypothesisRead], mode: ExportMode
) -> None:
    lines.append("## Root cause hypotheses")
    lines.append("")
    if not authoritative:
        lines.append("_No evidence-backed root-cause hypotheses were recorded._")
        lines.append("")
        return
    for hypothesis in authoritative:
        _hypothesis_body(lines, hypothesis, mode, heading_prefix=f"{_rank_label(hypothesis)}. ")


def _review_findings_section(lines: list[str], findings: list[HypothesisRead]) -> None:
    lines.append("## Review findings (unsupported & assumptions)")
    lines.append("")
    lines.append(
        "_The cited evidence does not support these claims; they are retained for "
        "audit but are not part of the verified narrative._"
    )
    lines.append("")
    for hypothesis in findings:
        _hypothesis_body(
            lines, hypothesis, ExportMode.AUDIT, heading_prefix=f"{_rank_label(hypothesis)}. "
        )


def _hypothesis_body(
    lines: list[str], hypothesis: HypothesisRead, mode: ExportMode, *, heading_prefix: str
) -> None:
    annotation = _support_annotation(hypothesis.support_status) if mode is ExportMode.AUDIT else ""
    label = " _(assumption)_" if hypothesis.assumption and mode is ExportMode.AUDIT else ""
    # A critically challenged advisory leader is labeled wherever it is rendered so
    # its rank is never read as confidence (ADR 0037, PRD user stories 21-22).
    leading = (
        " _(Leading but critically challenged)_"
        if hypothesis.leading_but_critically_challenged
        else ""
    )
    lines.append(f"### {heading_prefix}{hypothesis.title}{annotation}{label}{leading}")
    lines.append("")
    lines.append(hypothesis.summary)
    lines.append("")
    if mode is ExportMode.AUDIT and hypothesis.support_rationale and not _is_authoritative(
        hypothesis.support_status
    ):
        lines.append(f"> {hypothesis.support_rationale}")
        lines.append("")
    supporting = _refs(hypothesis.supporting_evidence)
    lines.append(f"**Supporting evidence:** {supporting or 'none cited'}")
    contradicting = _refs(hypothesis.contradicting_evidence)
    if contradicting:
        lines.append(f"**Contradicting evidence:** {contradicting}")
    lines.append("")


def _remediation_section(lines: list[str], authoritative: list[HypothesisRead]) -> None:
    lines.append("## Remediation")
    lines.append("")
    items = [
        f"- {item.description}{f' ({refs})' if (refs := _refs(item.evidence_refs)) else ''}"
        for hypothesis in authoritative
        for item in hypothesis.action_items
    ]
    if items:
        lines.extend(items)
    else:
        lines.append("_No remediation items were recorded._")
    lines.append("")


def _rank_label(hypothesis: HypothesisRead) -> str:
    """Display number for a hypothesis heading (ADR 0037).

    Uses the post-challenge advisory rank when present so the export presents
    hypotheses in plausibility order; falls back to the builder ``rank`` for an
    older run that predates the advisory ranking substep.
    """
    return str(hypothesis.advisory_rank if hypothesis.advisory_rank is not None else hypothesis.rank)


def _support_annotation(support_status: str) -> str:
    if support_status == "unevaluated":
        return ""
    return f" _(support: {support_status})_"


def _refs(refs: list[EvidenceRefRead]) -> str:
    return ", ".join(_ref(ref) for ref in refs)


def _ref(ref: EvidenceRefRead) -> str:
    span = (
        f"{ref.line_start}"
        if ref.line_end == ref.line_start
        else f"{ref.line_start}-{ref.line_end}"
    )
    return f"{ref.source_name}:{span}"
