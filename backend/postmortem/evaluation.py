from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Final, Protocol, runtime_checkable

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from .llm import LLMClient
from .provenance import output_token_cap_for

# Versioned identity for the deterministic check floor and the judge, recorded in
# Evaluation Run metadata (ADR 0025) so eval results stay comparable across runs.
EVAL_CHECK_SUITE_VERSION: Final[str] = "eval-checks-2"
LLM_JUDGE_VERSION: Final[str] = "llm-judge-1"


# --- ORM-free snapshot of one run's outputs --------------------------------
#
# The runner materializes a scenario run in an ephemeral database, then distills
# it into these plain views so the checks are pure and unit-testable without a
# session or fixtures (ADR 0010 deterministic floor).


@dataclass(frozen=True)
class TimelineView:
    sequence: int
    normalized_ts: datetime | None


@dataclass(frozen=True)
class HypothesisView:
    rank: int
    support_status: str
    citation_count: int
    # Post-challenge Advisory Hypothesis Ranking position (ADR 0037); None only
    # before the ranking substep ran or on an older run.
    advisory_rank: int | None = None
    # Whether the bounded Falsification Round persisted a Hypothesis Challenge for
    # this candidate (ADR 0034). False for every candidate in a Builder-Only
    # Baseline run, which is the comparison signal the challenge-coverage check reads.
    has_challenge: bool = False
    # Generation provenance: "initial" (builder) or "proposed" (falsifier
    # expansion). Used by the alternative-consideration check (PRD #38).
    origin: str = "initial"
    # Title + summary, scanned by the unacceptable-overclaims check (PRD #38).
    title: str = ""
    summary: str = ""


@dataclass(frozen=True)
class ExpectedFactorView:
    """ORM-free view of one expected causal factor family + role (PRD #38)."""

    family: str
    role: str


@dataclass(frozen=True)
class CitationRange:
    """An ORM-free citation address: source file + 1-based inclusive line range.

    Used to match declared known counterevidence against the evidence the run's
    challenges actually cited, by line-range overlap rather than wording (PRD #38).
    """

    source_name: str
    line_start: int
    line_end: int


@dataclass(frozen=True)
class CounterevidenceView:
    """A declared known-counterevidence item: its description + cited line range."""

    description: str
    source_name: str
    line_start: int
    line_end: int


@dataclass(frozen=True)
class CausalExpectationsView:
    """ORM-free distillation of a scenario's Causal Evaluation Expectations.

    Mirrors ``scenarios.CausalEvaluationExpectations`` but stays free of the
    scenario-loading imports so the deterministic checks remain pure and unit
    testable, exactly like ``RunOutputSnapshot`` (ADR 0010 / 0044).
    """

    expected_factors: tuple[ExpectedFactorView, ...]
    plausible_rejected_alternatives: tuple[str, ...]
    expected_refusal: bool
    unacceptable_overclaims: tuple[str, ...]
    # Known counterevidence the falsifier should surface, cited to real evidence
    # lines, and the critical Evidence Gaps a sound analysis should flag (PRD #38).
    # Counterevidence is checked deterministically by citation overlap; the prose
    # gaps inform the semantic judge (deterministic checks avoid exact wording).
    known_counterevidence: tuple[CounterevidenceView, ...] = ()
    critical_evidence_gaps: tuple[str, ...] = ()


@dataclass(frozen=True)
class RunOutputSnapshot:
    """Everything the deterministic checks and judge need from one run."""

    summary: str | None
    timeline: tuple[TimelineView, ...]
    hypotheses: tuple[HypothesisView, ...]
    # Every EvidenceRef's citation-integrity status across the whole run. This is
    # the deterministic citation-validity signal — never the judge's (ADR 0010).
    citation_statuses: tuple[str, ...]
    # Flattened Warning Codes across the run's stage events (ADR 0021).
    warning_codes: tuple[str, ...]
    # How many competing hypotheses the scenario expects (ambiguity behavior).
    expected_hypothesis_count: int
    # Refusal scenarios intentionally have sparse evidence and should not force
    # timeline/citation/hypothesis output just to satisfy the normal floor.
    insufficient_evidence_expected: bool = False
    # The product's own deterministic refusal verdict for the run (ADR 0032),
    # read back from the drafted Postmortem: 'sufficient' or 'insufficient'.
    evidence_sufficiency: str = "sufficient"
    # The configuration that produced the run: "multi_pass" or "builder_only"
    # (PRD #38). Recorded so the comparison is legible; the checks read the run's
    # actual outputs, not this label.
    analysis_mode: str = "multi_pass"
    # Structured Causal Evaluation Expectations for the scenario, or None when the
    # manifest declares no ``causal_evaluation`` block — in which case the
    # causal-specific checks degrade to trivial passes (PRD #38 / ADR 0044).
    causal_expectations: CausalExpectationsView | None = None
    # Every citation a Counterclaim raised across the run's Hypothesis Challenges
    # (source + line range). The counterevidence-coverage check matches declared
    # known counterevidence against these; a Builder-Only Baseline has none, so it
    # cannot surface the known counterevidence (PRD #38).
    counterclaim_citations: tuple[CitationRange, ...] = ()


@dataclass(frozen=True)
class CheckResult:
    name: str
    passed: bool
    detail: str


# --- Deterministic checks (the trust floor, ADR 0010) -----------------------

# The verifier status that counts as a valid citation (mirrors
# verification.CitationIntegrityStatus.VERIFIED without importing the enum).
_VERIFIED: Final[str] = "verified"


def check_citation_integrity(snapshot: RunOutputSnapshot) -> CheckResult:
    """Every EvidenceRef must deterministically resolve to its exact lines.

    This is the mechanical citation-validity floor (ADR 0002 / 0010): the LLM
    judge is never consulted for it.
    """
    total = len(snapshot.citation_statuses)
    verified = sum(1 for status in snapshot.citation_statuses if status == _VERIFIED)
    passed = verified == total and (snapshot.insufficient_evidence_expected or total > 0)
    return CheckResult(
        name="citation_integrity",
        passed=passed,
        detail=f"{verified}/{total} citations verified",
    )


def check_required_outputs(snapshot: RunOutputSnapshot) -> CheckResult:
    """The postmortem must carry its required sections (PRD MVP outputs)."""
    missing: list[str] = []
    if not (snapshot.summary and snapshot.summary.strip()):
        missing.append("summary")
    if not snapshot.timeline and not snapshot.insufficient_evidence_expected:
        missing.append("timeline")
    if not snapshot.hypotheses and not snapshot.insufficient_evidence_expected:
        missing.append("hypotheses")
    passed = not missing
    detail = "all required sections present" if passed else f"missing: {', '.join(missing)}"
    return CheckResult(name="required_outputs", passed=passed, detail=detail)


def check_timeline_ordering(snapshot: RunOutputSnapshot) -> CheckResult:
    """Normalized timeline events must be chronological by sequence (ADR 0019)."""
    dated = [
        event
        for event in sorted(snapshot.timeline, key=lambda e: e.sequence)
        if event.normalized_ts is not None
    ]
    out_of_order = sum(
        1 for i in range(len(dated) - 1) if dated[i].normalized_ts > dated[i + 1].normalized_ts
    )
    passed = out_of_order == 0
    detail = (
        f"{len(dated)} dated events in chronological order"
        if passed
        else f"{out_of_order} dated events out of chronological order"
    )
    return CheckResult(name="timeline_ordering", passed=passed, detail=detail)


def check_hypothesis_multiplicity(snapshot: RunOutputSnapshot) -> CheckResult:
    """Ambiguous evidence must yield multiple competing hypotheses (ADR 0006)."""
    observed = len(snapshot.hypotheses)
    if snapshot.insufficient_evidence_expected:
        evidence_backed = sum(1 for hypothesis in snapshot.hypotheses if hypothesis.citation_count > 0)
        passed = evidence_backed == 0
        return CheckResult(
            name="hypothesis_multiplicity",
            passed=passed,
            detail=(
                f"{observed} hypotheses, {evidence_backed} evidence-backed "
                "hypotheses (expected refusal)"
            ),
        )
    expected = max(2, snapshot.expected_hypothesis_count)
    passed = observed >= expected
    return CheckResult(
        name="hypothesis_multiplicity",
        passed=passed,
        detail=f"{observed} hypotheses (expected at least {expected})",
    )


def check_insufficient_evidence_refusal(snapshot: RunOutputSnapshot) -> CheckResult:
    """The product must refuse exactly when evidence is insufficient (ADR 0032).

    For a refusal scenario, the run must mark itself ``insufficient`` and produce
    no evidence-backed hypotheses; for any other scenario, the run must *not*
    spuriously refuse. This is the positive check that an insufficient-evidence
    run does not become a confident postmortem — and that good evidence is not
    wrongly rejected.
    """
    refused = snapshot.evidence_sufficiency == "insufficient"
    if snapshot.insufficient_evidence_expected:
        evidence_backed = sum(1 for hypothesis in snapshot.hypotheses if hypothesis.citation_count > 0)
        passed = refused and evidence_backed == 0
        detail = (
            "refused as insufficient (no evidence-backed hypotheses)"
            if passed
            else f"expected refusal but sufficiency={snapshot.evidence_sufficiency!r} "
            f"with {evidence_backed} evidence-backed hypotheses"
        )
    else:
        passed = not refused
        detail = (
            "sufficient evidence, no spurious refusal"
            if passed
            else "spuriously refused despite sufficient evidence"
        )
    return CheckResult(name="insufficient_evidence_refusal", passed=passed, detail=detail)


def check_advisory_ranking_coverage(snapshot: RunOutputSnapshot) -> CheckResult:
    """Every hypothesis must hold a distinct advisory rank forming 1..N (ADR 0037).

    The post-challenge Advisory Hypothesis Ranking must place each initial and
    proposed hypothesis exactly once (PRD user stories 17 / 60). A refusal scenario
    has no hypotheses and so nothing to rank, which passes trivially.
    """
    observed = len(snapshot.hypotheses)
    if observed == 0:
        return CheckResult(
            name="advisory_ranking_coverage",
            passed=True,
            detail="no hypotheses to rank",
        )
    ranks = sorted(
        h.advisory_rank for h in snapshot.hypotheses if h.advisory_rank is not None
    )
    passed = ranks == list(range(1, observed + 1))
    detail = (
        f"{observed} hypotheses ranked 1..{observed}"
        if passed
        else f"advisory ranks {ranks} do not cover 1..{observed} exactly once"
    )
    return CheckResult(name="advisory_ranking_coverage", passed=passed, detail=detail)


# --- Causal-analysis deterministic checks (PRD #38 / ADR 0044) --------------
#
# These measure whether bounded multi-pass causal analysis actually does the work
# the PRD promises, and they are what makes the Builder-Only Baseline measurably
# weaker (it fails challenge coverage). They use the scenario's structured Causal
# Evaluation Expectations where present, and never consult the judge for citation
# validity (AC #4). A scenario with no expectations declared degrades to a trivial
# pass for the expectation-driven checks rather than failing.

# Semantic support statuses that could back a finalizable Causal Factor (CONTEXT
# "Causal Factor vs Human Assumption"): only supported or partial, never an
# uncited assumption or an unsupported claim.
_FINALIZABLE_SUPPORT: Final[frozenset[str]] = frozenset({"supported", "partial"})


def check_causal_challenge_coverage(snapshot: RunOutputSnapshot) -> CheckResult:
    """Every RCA Hypothesis must carry a persisted Hypothesis Challenge (ADR 0034).

    This is the headline multi-pass-vs-baseline signal: the Builder-Only Baseline
    skips the Falsification Round, so none of its hypotheses are challenged and this
    check fails for the baseline while passing for the multi-pass run.
    """
    total = len(snapshot.hypotheses)
    if total == 0:
        return CheckResult(
            name="causal_challenge_coverage",
            passed=True,
            detail="no hypotheses to challenge",
        )
    challenged = sum(1 for h in snapshot.hypotheses if h.has_challenge)
    passed = challenged == total
    return CheckResult(
        name="causal_challenge_coverage",
        passed=passed,
        detail=f"{challenged}/{total} hypotheses challenged",
    )


def _family_represented_by_non_leader(family: str, snapshot: RunOutputSnapshot) -> bool:
    """Was a hypothesis family considered but not chosen as the advisory leader?

    A causal factor family is "represented" by a hypothesis when every meaningful
    token of its slug (``connection-pool-capacity`` → pool/capacity/connection)
    appears in the hypothesis title — a concept match, not exact-wording matching of
    generated prose. "Considered but rejected" means represented by a hypothesis the
    Advisory Hypothesis Ranking did *not* place first.
    """
    tokens = [token for token in family.lower().split("-") if len(token) >= 3]
    if not tokens:
        return False
    for hypothesis in snapshot.hypotheses:
        title = hypothesis.title.lower()
        if all(token in title for token in tokens) and hypothesis.advisory_rank != 1:
            return True
    return False


def check_alternative_consideration(snapshot: RunOutputSnapshot) -> CheckResult:
    """Each declared plausible alternative must be weighed and not chosen as lead.

    The PRD's structured expectations let this be tested without exact wording: a
    sound run must represent every declared ``plausible_rejected_alternative`` family
    as a generated hypothesis that the Advisory Hypothesis Ranking did not place
    first — i.e. it was genuinely considered and then ranked below the leading
    candidate, rather than ignored or mistaken for the answer (PRD #38 story 83).
    With no expectations (or none declared) the check passes with the observed count.
    """
    exp = snapshot.causal_expectations
    observed = len(snapshot.hypotheses)
    if exp is None or exp.expected_refusal or not exp.plausible_rejected_alternatives:
        return CheckResult(
            name="alternative_consideration",
            passed=True,
            detail=f"{observed} hypotheses considered (no alternatives required)",
        )
    missing = [
        family
        for family in exp.plausible_rejected_alternatives
        if not _family_represented_by_non_leader(family, snapshot)
    ]
    passed = not missing
    detail = (
        f"all {len(exp.plausible_rejected_alternatives)} declared alternative(s) "
        "considered and ranked below the lead"
        if passed
        else f"declared alternative(s) not considered as a non-leading candidate: {missing}"
    )
    return CheckResult(name="alternative_consideration", passed=passed, detail=detail)


def _ranges_overlap(item: CounterevidenceView, citation: CitationRange) -> bool:
    """Do a counterevidence item and a counterclaim citation cover shared lines?"""
    return (
        item.source_name == citation.source_name
        and item.line_start <= citation.line_end
        and citation.line_start <= item.line_end
    )


def check_counterevidence_coverage(snapshot: RunOutputSnapshot) -> CheckResult:
    """The falsifier must surface every declared known counterevidence item (PRD #38).

    Falsification quality is testable, not assumed: each declared counterevidence is
    cited to exact evidence lines, and a sound multi-pass run must raise a
    Counterclaim citing those lines. Matching is by line-range overlap, so it does
    not depend on generated wording (PRD story 83 / AC #4). A Builder-Only Baseline
    raises no Counterclaims, so it cannot surface any known counterevidence — the
    second signal, beside challenge coverage, that distinguishes the configurations.
    A scenario that declares no counterevidence (or expects refusal) passes trivially.
    """
    exp = snapshot.causal_expectations
    if exp is None or exp.expected_refusal or not exp.known_counterevidence:
        return CheckResult(
            name="counterevidence_coverage",
            passed=True,
            detail="no known counterevidence declared",
        )
    missing: list[str] = []
    for item in exp.known_counterevidence:
        if not any(
            _ranges_overlap(item, citation) for citation in snapshot.counterclaim_citations
        ):
            missing.append(f"{item.source_name}:{item.line_start}-{item.line_end}")
    surfaced = len(exp.known_counterevidence) - len(missing)
    passed = not missing
    detail = (
        f"{surfaced}/{len(exp.known_counterevidence)} known counterevidence items "
        "surfaced by challenges"
        + ("" if passed else f"; missing {missing}")
    )
    return CheckResult(name="counterevidence_coverage", passed=passed, detail=detail)


def check_unsupported_causal_claims(snapshot: RunOutputSnapshot) -> CheckResult:
    """The advisory leader must not rest on unsupported evidence (PRD story 23).

    A valid citation that does not semantically support its claim cannot be allowed
    to top the ranking. Any hypothesis judged ``unsupported`` is counted for
    visibility, but only an unsupported *advisory leader* fails the check.
    """
    if not snapshot.hypotheses:
        return CheckResult(
            name="unsupported_causal_claims",
            passed=True,
            detail="no causal claims",
        )
    unsupported = sum(1 for h in snapshot.hypotheses if h.support_status == "unsupported")
    leader = next((h for h in snapshot.hypotheses if h.advisory_rank == 1), None)
    leader_unsupported = leader is not None and leader.support_status == "unsupported"
    passed = not leader_unsupported
    detail = (
        f"{unsupported} unsupported hypotheses; advisory leader "
        + ("unsupported" if leader_unsupported else "supported/partial/assumption")
    )
    return CheckResult(name="unsupported_causal_claims", passed=passed, detail=detail)


def check_causal_refusal(snapshot: RunOutputSnapshot) -> CheckResult:
    """The run must refuse exactly when the expectations say it should (PRD #38).

    Driven by the scenario's structured ``expected_refusal`` rather than the tag
    heuristic. A refusal scenario must mark itself ``insufficient`` and produce no
    evidence-backed hypotheses; any other scenario must not spuriously refuse.
    """
    exp = snapshot.causal_expectations
    if exp is None:
        return CheckResult(
            name="causal_refusal",
            passed=True,
            detail="no causal expectations declared",
        )
    refused = snapshot.evidence_sufficiency == "insufficient"
    if exp.expected_refusal:
        evidence_backed = sum(1 for h in snapshot.hypotheses if h.citation_count > 0)
        passed = refused and evidence_backed == 0
        detail = (
            "refused as expected (no evidence-backed hypotheses)"
            if passed
            else f"expected refusal but sufficiency={snapshot.evidence_sufficiency!r} "
            f"with {evidence_backed} evidence-backed hypotheses"
        )
    else:
        passed = not refused
        detail = (
            "did not spuriously refuse"
            if passed
            else "spuriously refused despite sufficient evidence"
        )
    return CheckResult(name="causal_refusal", passed=passed, detail=detail)


def check_causal_role_constraints(snapshot: RunOutputSnapshot) -> CheckResult:
    """A non-refusal scenario must yield a finalizable Failure Mechanism candidate.

    A Root Cause Conclusion needs exactly one Failure Mechanism backed by verified,
    semantically supported (or partial) evidence (ADR 0039 / 0042). At eval time —
    before any human finalization — that means a non-refusal run must produce at
    least one ``supported``/``partial`` hypothesis a reviewer could finalize as the
    mechanism; a refusal run must produce no evidence-backed candidates at all.
    """
    exp = snapshot.causal_expectations
    if exp is None:
        return CheckResult(
            name="causal_role_constraints",
            passed=True,
            detail="no causal expectations declared",
        )
    if exp.expected_refusal:
        evidence_backed = sum(1 for h in snapshot.hypotheses if h.citation_count > 0)
        passed = evidence_backed == 0
        return CheckResult(
            name="causal_role_constraints",
            passed=passed,
            detail=(
                "no finalizable factors (refusal)"
                if passed
                else f"{evidence_backed} evidence-backed hypotheses in a refusal scenario"
            ),
        )
    finalizable = sum(
        1 for h in snapshot.hypotheses if h.support_status in _FINALIZABLE_SUPPORT
    )
    passed = finalizable >= 1
    return CheckResult(
        name="causal_role_constraints",
        passed=passed,
        detail=f"{finalizable} finalizable (supported/partial) Failure Mechanism candidate(s)",
    )


def check_unacceptable_overclaims(snapshot: RunOutputSnapshot) -> CheckResult:
    """The generated narrative must not contain a declared unacceptable overclaim.

    Penalizes confident-but-shallow output (PRD story 84): each declared overclaim
    phrase is matched case-insensitively against the postmortem summary and every
    hypothesis title/summary. With none declared the check passes trivially.
    """
    exp = snapshot.causal_expectations
    if exp is None or not exp.unacceptable_overclaims:
        return CheckResult(
            name="unacceptable_overclaims",
            passed=True,
            detail="no overclaims declared",
        )
    parts = [snapshot.summary or ""]
    parts.extend(f"{h.title} {h.summary}" for h in snapshot.hypotheses)
    haystack = "\n".join(parts).lower()
    found = [phrase for phrase in exp.unacceptable_overclaims if phrase.lower() in haystack]
    passed = not found
    detail = (
        "no unacceptable overclaims present"
        if passed
        else f"found overclaim(s): {found}"
    )
    return CheckResult(name="unacceptable_overclaims", passed=passed, detail=detail)


DETERMINISTIC_CHECKS = (
    check_citation_integrity,
    check_required_outputs,
    check_timeline_ordering,
    check_hypothesis_multiplicity,
    check_insufficient_evidence_refusal,
    check_advisory_ranking_coverage,
    check_causal_challenge_coverage,
    check_counterevidence_coverage,
    check_alternative_consideration,
    check_unsupported_causal_claims,
    check_causal_refusal,
    check_causal_role_constraints,
    check_unacceptable_overclaims,
)


def run_deterministic_checks(snapshot: RunOutputSnapshot) -> list[CheckResult]:
    return [check(snapshot) for check in DETERMINISTIC_CHECKS]


# The deterministic checks that are meaningful *without* a ground-truth reference,
# used to evaluate a real product incident's Analysis Run (which ships no scenario
# fixture). These need only the run's own outputs — exact citations, required
# sections, chronological timeline, competing hypotheses, a complete advisory
# ranking, every hypothesis challenged, and a supported advisory leader. The
# expectation-driven checks (alternative_consideration, counterevidence_coverage,
# causal_refusal, causal_role_constraints, unacceptable_overclaims) and the
# refusal-correctness check are deliberately excluded: with no declared
# expectations they degrade to a trivial pass, which would be a misleading green.
GROUND_TRUTH_FREE_CHECKS: tuple[str, ...] = (
    "citation_integrity",
    "required_outputs",
    "timeline_ordering",
    "hypothesis_multiplicity",
    "advisory_ranking_coverage",
    "causal_challenge_coverage",
    "unsupported_causal_claims",
)


def run_floor_checks(snapshot: RunOutputSnapshot) -> list[CheckResult]:
    """The ground-truth-free deterministic floor for a real-incident evaluation.

    A subset of ``run_deterministic_checks`` restricted to checks that grade a run
    against its own outputs rather than a scenario's declared expectations (ADR
    0010). No judge runs for an incident evaluation: there is no reference
    postmortem to score semantic quality against.
    """
    by_name = {check.name: check for check in run_deterministic_checks(snapshot)}
    return [by_name[name] for name in GROUND_TRUTH_FREE_CHECKS if name in by_name]


def aggregate_warning_codes(snapshot: RunOutputSnapshot) -> dict[str, int]:
    """Count Warning Codes across the run for experiment tracking (ADR 0025)."""
    counts: dict[str, int] = {}
    for code in snapshot.warning_codes:
        counts[code] = counts.get(code, 0) + 1
    return counts


def citation_tally(snapshot: RunOutputSnapshot) -> tuple[int, int]:
    """(total, verified) citation counts surfaced as dashboard summary columns."""
    total = len(snapshot.citation_statuses)
    verified = sum(1 for status in snapshot.citation_statuses if status == _VERIFIED)
    return total, verified


# --- LLM-as-judge framework (semantic quality only, ADR 0010) ---------------


@dataclass(frozen=True)
class JudgeHypothesis:
    title: str
    summary: str
    support_status: str
    # Falsification context (PRD #38): whether the bounded Falsification Round
    # challenged this hypothesis, the Challenge Severity, and how many cited
    # Counterclaims it raised. A Builder-Only Baseline hypothesis carries
    # ``has_challenge=False`` so the judge can score its falsification quality low.
    has_challenge: bool = False
    challenge_severity: str | None = None
    counterclaim_count: int = 0


@dataclass(frozen=True)
class JudgeInput:
    """The generated postmortem and its Ground-Truth reference for scoring.

    ORM-free so the judge boundary stays swappable and testable (ADR 0009). The
    judge scores semantic quality against the ground truth; it is explicitly not
    given citation-integrity authority (ADR 0010).
    """

    scenario_id: str
    generated_summary: str
    generated_hypotheses: tuple[JudgeHypothesis, ...]
    ground_truth_postmortem: str
    # The scenario's known counterevidence and critical Evidence Gaps (PRD #38).
    # Surfaced to the judge so it can score falsification quality and explanatory
    # coverage against what a sound analysis should have weighed — the prose Gaps
    # in particular live here rather than in a brittle exact-match deterministic
    # check (deterministic checks avoid generated wording, AC #4 / #6).
    known_counterevidence: tuple[str, ...] = ()
    critical_evidence_gaps: tuple[str, ...] = ()


@dataclass(frozen=True)
class JudgeResult:
    scores: dict[str, int]
    overall: float
    rationale: str
    version: str


@runtime_checkable
class PostmortemJudge(Protocol):
    """Swappable LLM-as-judge boundary (ADR 0009 / 0010, client brief).

    The MVP implementation is LLM-backed; tests inject a fake so rubric scoring is
    exercised without a live model. A judge is never the source of truth for
    citation validity — that is the deterministic check floor.
    """

    @property
    def version(self) -> str: ...

    def judge(self, payload: JudgeInput) -> JudgeResult: ...


class JudgeScores(BaseModel):
    """The six rubric dimensions, each scored 1-5 (ADR 0010 / 0044 Judge Rubric).

    The first four measure postmortem quality against the ground truth; the last
    two — added for the multi-pass-vs-baseline comparison (PRD #38, stories 86) —
    measure the depth the bounded causal analysis is supposed to add: explanatory
    coverage and falsification quality. The judge scores semantic quality only; it
    never decides citation validity (ADR 0010).
    """

    model_config = ConfigDict(extra="forbid")

    timeline_accuracy: int = Field(ge=1, le=5)
    root_cause_quality: int = Field(ge=1, le=5)
    evidence_grounding: int = Field(ge=1, le=5)
    uncertainty_honesty: int = Field(ge=1, le=5)
    explanatory_coverage: int = Field(ge=1, le=5)
    falsification_quality: int = Field(ge=1, le=5)


class JudgeOutput(BaseModel):
    """Strict structured judge output (ADR 0028): free-form prose is not a score."""

    model_config = ConfigDict(extra="forbid")

    scores: JudgeScores
    rationale: str = Field(min_length=1)


_JUDGE_SYSTEM_PROMPT = """\
You are a senior incident reviewer grading a generated postmortem against a
human-written ground-truth postmortem. You are not rewriting it; you are scoring
its semantic quality.

Rules:
- Output ONLY a single JSON object. No prose, no markdown fences.
- Score each dimension as an integer from 1 (poor) to 5 (excellent):
  - timeline_accuracy: does the timeline match the ground-truth sequence?
  - root_cause_quality: are the ranked hypotheses sound and well reasoned?
  - evidence_grounding: are claims tied to evidence rather than asserted?
  - uncertainty_honesty: does it admit ambiguity instead of overclaiming?
  - explanatory_coverage: do the hypotheses explain the observed impact and the
    competing causal factors, rather than collapsing to one apparent winner?
  - falsification_quality: were the hypotheses meaningfully challenged — real
    counterevidence, evidence gaps, and falsification tests? Score this LOW when
    the hypotheses carry no challenges at all.
- Do NOT judge whether citations resolve to real lines; citation integrity is
  checked deterministically elsewhere and is not your responsibility.
- Always include a one-to-two sentence rationale.

The JSON object must match this shape:
{"scores": {"timeline_accuracy": 1-5, "root_cause_quality": 1-5,
"evidence_grounding": 1-5, "uncertainty_honesty": 1-5,
"explanatory_coverage": 1-5, "falsification_quality": 1-5}, "rationale": "..."}
"""


def _challenge_phrase(hypothesis: JudgeHypothesis) -> str:
    """Describe a hypothesis's falsification status for the judge prompt (PRD #38)."""
    if not hypothesis.has_challenge:
        return "not challenged"
    severity = hypothesis.challenge_severity or "unknown"
    return f"{severity} severity, {hypothesis.counterclaim_count} counterclaim(s)"


def build_judge_prompt(payload: JudgeInput) -> tuple[str, str]:
    """Assemble the (system, user) prompt scoring one generated postmortem."""
    if payload.generated_hypotheses:
        hypotheses = "\n".join(
            f"{index}. [{h.support_status}] {h.title} — {h.summary} "
            f"(challenge: {_challenge_phrase(h)})"
            for index, h in enumerate(payload.generated_hypotheses, start=1)
        )
    else:
        hypotheses = "(no hypotheses were generated)"
    counterevidence = (
        "\n".join(f"- {item}" for item in payload.known_counterevidence)
        if payload.known_counterevidence
        else "(none recorded)"
    )
    gaps = (
        "\n".join(f"- {item}" for item in payload.critical_evidence_gaps)
        if payload.critical_evidence_gaps
        else "(none recorded)"
    )
    user = (
        f"GENERATED POSTMORTEM SUMMARY:\n{payload.generated_summary}\n\n"
        f"GENERATED HYPOTHESES:\n{hypotheses}\n\n"
        f"GROUND-TRUTH POSTMORTEM:\n{payload.ground_truth_postmortem}\n\n"
        # Reference signals for the falsification_quality / explanatory_coverage
        # dimensions: what a sound analysis should have weighed (PRD #38).
        f"KNOWN COUNTEREVIDENCE THE ANALYSIS SHOULD ADDRESS:\n{counterevidence}\n\n"
        f"CRITICAL EVIDENCE GAPS THE ANALYSIS SHOULD FLAG:\n{gaps}\n\n"
        "Score the generated postmortem and return the JSON object described in "
        "the system message."
    )
    return _JUDGE_SYSTEM_PROMPT, user


def _overall(scores: JudgeScores) -> float:
    values = list(scores.model_dump().values())
    return round(sum(values) / len(values), 2)


class LLMPostmortemJudge:
    """Default judge: one configured LLM behind the swappable interface (ADR 0011).

    Builds a rubric prompt, calls the LLMClient, and validates the verdict against
    ``JudgeOutput`` (ADR 0028). Schema-invalid or non-JSON output raises so an
    unscoreable verdict never becomes an Evaluation Run score.
    """

    version: Final[str] = LLM_JUDGE_VERSION

    def __init__(self, llm: LLMClient) -> None:
        self._llm = llm

    def judge(self, payload: JudgeInput) -> JudgeResult:
        system, user = build_judge_prompt(payload)
        response = self._llm.complete(
            system=system, user=user, max_output_tokens=output_token_cap_for("judge")
        )
        try:
            output = JudgeOutput.model_validate_json(response.text)
        except ValidationError as exc:
            raise ValueError(f"judge output failed schema validation: {exc}") from exc
        return JudgeResult(
            scores=output.scores.model_dump(),
            overall=_overall(output.scores),
            rationale=output.rationale,
            version=self.version,
        )


# --- Reference-free judge for real incidents (no ground truth) ----------------
#
# A real product incident ships no human-written reference postmortem, so the
# ground-truth dimensions (timeline_accuracy, root_cause_quality) cannot be scored
# — judging against a gold answer would require hand-labelling every incident,
# which does not scale. Instead this judge grades the output against *criteria*
# using the incident's own cited evidence as grounding. It measures whether the
# reasoning is well-supported, self-consistent, and honest — NOT whether the root
# cause is objectively correct, which only a human or post-incident reality can
# establish (so it never replaces the human conclusion, only flags weak drafts).

REFERENCE_FREE_JUDGE_VERSION: Final[str] = "incident-judge-1"


class ReferenceFreeJudgeScores(BaseModel):
    """The four reference-free rubric dimensions, each scored 1-5.

    All four are answerable from the generated postmortem plus its cited evidence
    alone — none needs a ground-truth reference (ADR 0010).
    """

    model_config = ConfigDict(extra="forbid")

    evidence_grounding: int = Field(ge=1, le=5)
    internal_consistency: int = Field(ge=1, le=5)
    uncertainty_honesty: int = Field(ge=1, le=5)
    explanatory_coverage: int = Field(ge=1, le=5)


class ReferenceFreeJudgeOutput(BaseModel):
    """Strict structured output for the reference-free incident judge (ADR 0028)."""

    model_config = ConfigDict(extra="forbid")

    scores: ReferenceFreeJudgeScores
    rationale: str = Field(min_length=1)


@dataclass(frozen=True)
class IncidentJudgeInput:
    """A real incident's generated postmortem and its own evidence, for scoring.

    ORM-free (ADR 0009). There is no ground-truth reference: ``cited_evidence`` is
    the exact text of the lines the analysis cited, used to judge groundedness;
    ``evidence_sufficiency`` and ``evidence_gaps`` are the run's own honesty signals.
    """

    incident_id: str
    generated_summary: str
    generated_hypotheses: tuple[JudgeHypothesis, ...]
    cited_evidence: tuple[str, ...]
    evidence_sufficiency: str
    evidence_gaps: tuple[str, ...]


_INCIDENT_JUDGE_SYSTEM_PROMPT = """\
You are a senior incident reviewer grading a generated postmortem WITHOUT a
ground-truth reference. You only have the postmortem and the exact evidence it
cited. You are scoring the quality of its reasoning, not rewriting it.

Critically: you cannot and must not judge whether the root cause is objectively
correct — you do not know the true cause. Judge only what the evidence in front
of you supports.

Rules:
- Output ONLY a single JSON object. No prose, no markdown fences.
- Score each dimension as an integer from 1 (poor) to 5 (excellent):
  - evidence_grounding: does every substantive claim trace to the cited evidence,
    rather than being asserted or going beyond what the evidence says?
  - internal_consistency: are the summary, hypotheses, and stated uncertainty
    mutually consistent, with no contradictions?
  - uncertainty_honesty: does it hedge and flag gaps when the evidence is thin,
    instead of overclaiming? A confident conclusion on sparse evidence scores LOW;
    an honest "insufficient evidence" on sparse evidence scores HIGH.
  - explanatory_coverage: do the hypotheses actually explain the cited evidence and
    weigh competing factors, rather than ignoring evidence or collapsing to one
    apparent winner?
- Do NOT judge whether citations resolve to real lines; citation integrity is
  checked deterministically elsewhere and is not your responsibility.
- Always include a one-to-two sentence rationale.

The JSON object must match this shape:
{"scores": {"evidence_grounding": 1-5, "internal_consistency": 1-5,
"uncertainty_honesty": 1-5, "explanatory_coverage": 1-5}, "rationale": "..."}
"""


def build_incident_judge_prompt(payload: IncidentJudgeInput) -> tuple[str, str]:
    """Assemble the (system, user) prompt for the reference-free incident judge."""
    if payload.generated_hypotheses:
        hypotheses = "\n".join(
            f"{index}. [{h.support_status}] {h.title} — {h.summary} "
            f"(challenge: {_challenge_phrase(h)})"
            for index, h in enumerate(payload.generated_hypotheses, start=1)
        )
    else:
        hypotheses = "(no hypotheses were generated)"
    evidence = (
        "\n".join(f"- {snippet}" for snippet in payload.cited_evidence)
        if payload.cited_evidence
        else "(no evidence was cited)"
    )
    gaps = (
        "\n".join(f"- {item}" for item in payload.evidence_gaps)
        if payload.evidence_gaps
        else "(none flagged)"
    )
    user = (
        f"GENERATED POSTMORTEM SUMMARY:\n{payload.generated_summary}\n\n"
        f"GENERATED HYPOTHESES:\n{hypotheses}\n\n"
        f"EVIDENCE THE ANALYSIS CITED (the only grounding you have):\n{evidence}\n\n"
        f"THE RUN'S OWN EVIDENCE SUFFICIENCY: {payload.evidence_sufficiency}\n"
        f"EVIDENCE GAPS THE RUN FLAGGED:\n{gaps}\n\n"
        "Score the generated postmortem and return the JSON object described in "
        "the system message."
    )
    return _INCIDENT_JUDGE_SYSTEM_PROMPT, user


def _reference_free_overall(scores: ReferenceFreeJudgeScores) -> float:
    values = list(scores.model_dump().values())
    return round(sum(values) / len(values), 2)


@runtime_checkable
class IncidentPostmortemJudge(Protocol):
    """Swappable reference-free judge boundary for real-incident evaluation.

    Distinct from ``PostmortemJudge`` because it grades without a ground-truth
    reference. Tests inject a fake; an offline environment configures none and the
    incident evaluation stands on its deterministic floor alone (ADR 0010).
    """

    version: str

    def judge_incident(self, payload: IncidentJudgeInput) -> JudgeResult: ...


class LLMIncidentJudge:
    """Default reference-free incident judge: one configured LLM (ADR 0011).

    Mirrors ``LLMPostmortemJudge`` but with the reference-free rubric/prompt and
    schema. Schema-invalid or non-JSON output raises so an unscoreable verdict
    never becomes an Evaluation Run score.
    """

    version: Final[str] = REFERENCE_FREE_JUDGE_VERSION

    def __init__(self, llm: LLMClient) -> None:
        self._llm = llm

    def judge_incident(self, payload: IncidentJudgeInput) -> JudgeResult:
        system, user = build_incident_judge_prompt(payload)
        response = self._llm.complete(
            system=system, user=user, max_output_tokens=output_token_cap_for("incident_judge")
        )
        try:
            output = ReferenceFreeJudgeOutput.model_validate_json(response.text)
        except ValidationError as exc:
            raise ValueError(f"incident judge output failed schema validation: {exc}") from exc
        return JudgeResult(
            scores=output.scores.model_dump(),
            overall=_reference_free_overall(output.scores),
            rationale=output.rationale,
            version=self.version,
        )
