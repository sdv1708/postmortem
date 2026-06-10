from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Final, Protocol, runtime_checkable

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from .llm import LLMClient

# Versioned identity for the deterministic check floor and the judge, recorded in
# Evaluation Run metadata (ADR 0025) so eval results stay comparable across runs.
EVAL_CHECK_SUITE_VERSION: Final[str] = "eval-checks-1"
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


DETERMINISTIC_CHECKS = (
    check_citation_integrity,
    check_required_outputs,
    check_timeline_ordering,
    check_hypothesis_multiplicity,
    check_insufficient_evidence_refusal,
)


def run_deterministic_checks(snapshot: RunOutputSnapshot) -> list[CheckResult]:
    return [check(snapshot) for check in DETERMINISTIC_CHECKS]


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
    """The four rubric dimensions, each scored 1-5 (ADR 0010 Judge Rubric)."""

    model_config = ConfigDict(extra="forbid")

    timeline_accuracy: int = Field(ge=1, le=5)
    root_cause_quality: int = Field(ge=1, le=5)
    evidence_grounding: int = Field(ge=1, le=5)
    uncertainty_honesty: int = Field(ge=1, le=5)


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
- Do NOT judge whether citations resolve to real lines; citation integrity is
  checked deterministically elsewhere and is not your responsibility.
- Always include a one-to-two sentence rationale.

The JSON object must match this shape:
{"scores": {"timeline_accuracy": 1-5, "root_cause_quality": 1-5,
"evidence_grounding": 1-5, "uncertainty_honesty": 1-5}, "rationale": "..."}
"""


def build_judge_prompt(payload: JudgeInput) -> tuple[str, str]:
    """Assemble the (system, user) prompt scoring one generated postmortem."""
    if payload.generated_hypotheses:
        hypotheses = "\n".join(
            f"{index}. [{h.support_status}] {h.title} — {h.summary}"
            for index, h in enumerate(payload.generated_hypotheses, start=1)
        )
    else:
        hypotheses = "(no hypotheses were generated)"
    user = (
        f"GENERATED POSTMORTEM SUMMARY:\n{payload.generated_summary}\n\n"
        f"GENERATED HYPOTHESES:\n{hypotheses}\n\n"
        f"GROUND-TRUTH POSTMORTEM:\n{payload.ground_truth_postmortem}\n\n"
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
        response = self._llm.complete(system=system, user=user)
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
