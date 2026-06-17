from __future__ import annotations

from datetime import datetime, timezone

from postmortem.drafting import (
    DeterministicPostmortemComposer,
    HypothesisDigest,
    PostmortemComposerContext,
)
from postmortem.markdown_export import ExportMode, render_markdown
from postmortem.schemas import (
    EvidenceRefRead,
    HypothesisRead,
    ImpactClaimRead,
    ActionItemRead,
    PostmortemRead,
    TimelineEventRead,
)


# --- Deterministic composer ------------------------------------------------


def _context(**overrides) -> PostmortemComposerContext:
    base = dict(
        incident_title="Checkout API outage",
        incident_severity="sev1",
        artifact_count=2,
        timeline_event_count=3,
        earliest_ts_text="14:28",
        latest_ts_text="14:45",
        hypotheses=(
            HypothesisDigest(rank=1, title="Deploy v184 regressed the pool", assumption=False,
                             unknowns=("Was the pool size changed in v184?",)),
            HypothesisDigest(rank=2, title="Cache pressure cascaded", assumption=True,
                             unknowns=("Was the pool size changed in v184?", "Did cache evict early?")),
        ),
    )
    base.update(overrides)
    return PostmortemComposerContext(**base)


def test_composer_summary_restates_structured_facts_only():
    draft = DeterministicPostmortemComposer().compose(_context())
    # Every clause is grounded in a count or an anchor that an earlier verified
    # stage already produced. Hypothesis titles are intentionally omitted because
    # drafting runs before support filtering and clean exports include this
    # summary as authoritative narrative.
    assert "Checkout API outage" in draft.summary
    assert "2 evidence artifacts" in draft.summary
    assert "3 events from 14:28 to 14:45" in draft.summary
    assert "2 root-cause hypotheses were generated for evidence review" in draft.summary
    assert "Deploy v184 regressed the pool" not in draft.summary
    assert "Cache pressure cascaded" not in draft.summary


def test_composer_lessons_are_deduped_unknowns_in_rank_order():
    draft = DeterministicPostmortemComposer().compose(_context())
    assert draft.lessons_learned == (
        "Was the pool size changed in v184?",
        "Did cache evict early?",
    )


def test_composer_is_deterministic():
    composer = DeterministicPostmortemComposer()
    assert composer.compose(_context()) == composer.compose(_context())


def test_composer_handles_no_hypotheses_and_no_timeline():
    draft = DeterministicPostmortemComposer().compose(
        _context(timeline_event_count=0, earliest_ts_text=None, latest_ts_text=None, hypotheses=())
    )
    assert "No timeline events were extracted" in draft.summary
    assert "no root-cause hypotheses" in draft.summary
    assert draft.lessons_learned == ()


def test_composer_flags_all_assumptions():
    draft = DeterministicPostmortemComposer().compose(
        _context(
            hypotheses=(
                HypothesisDigest(rank=1, title="Guess one", assumption=True, unknowns=()),
                HypothesisDigest(rank=2, title="Guess two", assumption=True, unknowns=()),
            )
        )
    )
    assert "Every hypothesis is currently an assumption" in draft.summary


# --- Refusal on insufficient evidence (ADR 0032 / 0015) --------------------


def test_composer_marks_sufficient_when_a_hypothesis_is_evidence_backed():
    # The default context has one non-assumption (cited) hypothesis.
    draft = DeterministicPostmortemComposer().compose(_context())
    assert draft.evidence_sufficiency == "sufficient"
    assert draft.evidence_gaps == ()
    assert draft.next_validation_steps == ()
    assert "not enough evidence" not in draft.summary


def test_composer_refuses_when_no_hypothesis_is_evidence_backed():
    draft = DeterministicPostmortemComposer().compose(
        _context(
            timeline_event_count=0,
            earliest_ts_text=None,
            latest_ts_text=None,
            hypotheses=(),
            present_source_types=("incident_notes",),
        )
    )
    assert draft.evidence_sufficiency == "insufficient"
    # The summary is an explicit refusal, not a confident narrative.
    assert "not enough evidence to write a confident postmortem" in draft.summary
    # Gaps and next steps are populated and name concrete missing categories.
    assert any("no timestamps" in gap for gap in draft.evidence_gaps)
    assert any("logs" in gap for gap in draft.evidence_gaps)
    assert any("timestamped logs" in step for step in draft.next_validation_steps)
    # Refusal guidance is procedural — it invents no incident facts (ADR 0026):
    # nothing references the (absent) hypotheses or a fabricated cause.
    assert "root cause is" not in " ".join(draft.evidence_gaps).lower()


def test_composer_refuses_when_every_hypothesis_is_an_uncited_assumption():
    draft = DeterministicPostmortemComposer().compose(
        _context(
            hypotheses=(
                HypothesisDigest(rank=1, title="Guess one", assumption=True, unknowns=()),
                HypothesisDigest(rank=2, title="Guess two", assumption=True, unknowns=()),
            )
        )
    )
    assert draft.evidence_sufficiency == "insufficient"
    assert any("unsupported assumption" in gap for gap in draft.evidence_gaps)


# --- Markdown renderer -----------------------------------------------------


def _ref(snippet: str, line: int = 1) -> EvidenceRefRead:
    return EvidenceRefRead(
        id=f"ref-{line}",
        artifact_id="art-1",
        source_name="api.log",
        line_start=line,
        line_end=line,
        snippet=snippet,
        confidence_score=1.0,
        verifier_status="verified",
    )


def _hypothesis(*, rank, title, summary, support_status, assumption=False, rationale=None,
                actions=None) -> HypothesisRead:
    return HypothesisRead(
        id=f"hyp-{rank}",
        run_id="run-1",
        rank=rank,
        title=title,
        summary=summary,
        assumption=assumption,
        review_status="proposed",
        support_status=support_status,
        support_rationale=rationale,
        unknowns=[],
        validation_steps=[],
        supporting_evidence=[_ref("deploy v184 rolled out")],
        contradicting_evidence=[],
        action_items=actions or [],
    )


def _postmortem() -> PostmortemRead:
    supported = _hypothesis(
        rank=1,
        title="Deploy v184 regressed the pool",
        summary="The v184 deploy preceded the error spike.",
        support_status="supported",
        actions=[
            ActionItemRead(
                id="act-1", sequence=1, description="Add pool-size regression alert",
                evidence_refs=[],
            )
        ],
    )
    # Impact is run-level now (ADR 0033): one impact claim owned by the run.
    impact_claims = [
        ImpactClaimRead(
            id="imp-1", sequence=1, description="Users saw elevated 500s",
            assumption=False, support_status="partial",
            support_rationale="Correlated, not proven causal.",
            evidence_refs=[_ref("api 500 rate climbing", 2)],
        )
    ]
    unsupported = _hypothesis(
        rank=2,
        title="Sunspot interference theory",
        summary="An unfalsifiable guess with no cited support.",
        support_status="unsupported",
        assumption=True,
        rationale="No supporting evidence was cited.",
    )
    return PostmortemRead(
        id="pm-1",
        run_id="run-1",
        incident_title="Checkout API outage",
        incident_severity="sev1",
        summary="Incident summary text.",
        lessons_learned=["Add pre-deploy pool-size checks."],
        evidence_sufficiency="sufficient",
        evidence_gaps=[],
        next_validation_steps=[],
        composer_version="postmortem-template-1",
        created_at=datetime.now(timezone.utc),
        timeline=[
            TimelineEventRead(
                id="tl-1", sequence=1, normalized_ts=None, original_ts_text="14:28",
                uncertain=False, description="deploy v184 rolled out",
                evidence_refs=[_ref("deploy v184 rolled out")],
            )
        ],
        impact_claims=impact_claims,
        hypotheses=[supported, unsupported],
    )


def test_clean_export_omits_unsupported_claims():
    markdown = render_markdown(_postmortem(), ExportMode.CLEAN)
    assert "**Export mode:** clean" in markdown
    assert "## Open questions" in markdown
    assert "## Lessons learned" not in markdown
    assert "Deploy v184 regressed the pool" in markdown
    # The unsupported claim must not appear as fact in a clean export (ADR 0015).
    assert "Sunspot interference theory" not in markdown
    assert "Review findings" not in markdown
    # Supported + partial impact and remediation are part of the clean narrative.
    assert "Users saw elevated 500s" in markdown
    assert "Add pool-size regression alert" in markdown


def test_audit_export_includes_unsupported_claims_labeled():
    markdown = render_markdown(_postmortem(), ExportMode.AUDIT)
    assert "**Export mode:** audit" in markdown
    assert "Audit export" in markdown
    # The unsupported claim is retained, in a clearly marked review section, with
    # its rationale (ADR 0015).
    assert "Review findings (unsupported & assumptions)" in markdown
    assert "Sunspot interference theory" in markdown
    assert "No supporting evidence was cited." in markdown
    assert "_(support: unsupported)_" in markdown


def test_markdown_is_derived_only_from_structured_data():
    postmortem = _postmortem()
    markdown = render_markdown(postmortem, ExportMode.AUDIT)
    # Every rendered claim/snippet traces to a structured field; the renderer adds
    # only static section labels, never new incident facts (ADR 0012).
    assert postmortem.summary in markdown
    assert postmortem.hypotheses[0].summary in markdown
    assert "api.log:2" in markdown  # impact citation, from the EvidenceRef
    for question in postmortem.lessons_learned:
        assert question in markdown
