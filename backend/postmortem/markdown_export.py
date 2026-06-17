from __future__ import annotations

from enum import Enum

from .schemas import EvidenceRefRead, HypothesisRead, ImpactClaimRead, PostmortemRead, TimelineEventRead


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

    lines: list[str] = [f"# Postmortem — {postmortem.incident_title}", ""]
    lines.append(f"- **Severity:** {postmortem.incident_severity or '—'}")
    lines.append(f"- **Export mode:** {mode.value}")
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
        _hypothesis_body(lines, hypothesis, mode, heading_prefix=f"{hypothesis.rank}. ")


def _review_findings_section(lines: list[str], findings: list[HypothesisRead]) -> None:
    lines.append("## Review findings (unsupported & assumptions)")
    lines.append("")
    lines.append(
        "_The cited evidence does not support these claims; they are retained for "
        "audit but are not part of the verified narrative._"
    )
    lines.append("")
    for hypothesis in findings:
        _hypothesis_body(lines, hypothesis, ExportMode.AUDIT, heading_prefix=f"{hypothesis.rank}. ")


def _hypothesis_body(
    lines: list[str], hypothesis: HypothesisRead, mode: ExportMode, *, heading_prefix: str
) -> None:
    annotation = _support_annotation(hypothesis.support_status) if mode is ExportMode.AUDIT else ""
    label = " _(assumption)_" if hypothesis.assumption and mode is ExportMode.AUDIT else ""
    lines.append(f"### {heading_prefix}{hypothesis.title}{annotation}{label}")
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
