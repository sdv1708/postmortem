from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Final, Literal, Protocol

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from .llm import LLMClient
from .provenance import ROLE_FALSIFIER, output_token_cap_for
from .rca import RcaEvidenceRef, RcaHypothesis
from .reasoning import append_repair_feedback

logger = logging.getLogger("postmortem.falsification")

# The bounded alternative-expansion cap (ADR 0036, PRD #26 / #30): across one
# Falsification Round the falsifier may introduce at most this many Proposed RCA
# Hypotheses total. More than this fails the Runtime Reasoning Gate rather than
# silently truncating, so the bound is auditable.
MAX_PROPOSED_HYPOTHESES: Final[int] = 2

# Versioned prompt/role identity for the falsifier (ADR 0025 / 0034). Bump when
# the prompt or the expected output contract changes so runs stay comparable.
# The falsifier is a separate Reasoning Role from RCA generation and incident-
# facts extraction (PRD #26 / #28): it has its own prompt, schema, and version,
# even when it is backed by the same configured model.
FALSIFICATION_PROMPT_VERSION: Final[str] = "falsification-2"
FALSIFIER_VERSION: Final[str] = "llm-falsifier-1"
# Versioned identity of the falsifier's strict output schema (ADR 0028 / 0038),
# recorded on each falsifier Model Call Record. Bump when
# ``HypothesisChallengeOutput`` changes.
FALSIFICATION_SCHEMA_VERSION: Final[str] = "falsification-output-1"


# --- Strict structured model-output contract (ADR 0028) ---------------------
#
# The falsifier challenges one RCA Hypothesis per call and must return JSON
# matching this schema. Parsing/validation happens before any of it becomes
# pipeline state; invalid JSON or a schema violation raises, which the stage
# turns into a stage failure with one retry (ADR 0029). A Counterclaim cites
# Artifact line ranges (ADR 0024); the stage resolves the exact snippet from the
# stored lines, so the model is never trusted to reproduce snippet text.


class StrictFalsificationModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class FalsificationCounterclaim(StrictFalsificationModel):
    """A factual statement that weakens the hypothesis (a Major Claim).

    Reuses the shared cite shape so the stage's existing ref-resolution path
    applies unchanged. A Counterclaim with no resolvable citation is normalized
    to an assumption and flagged, exactly like an uncited hypothesis (ADR 0013).
    """

    statement: str = Field(min_length=1)
    evidence: list[RcaEvidenceRef] = Field(default_factory=list)


class HypothesisChallengeOutput(StrictFalsificationModel):
    """One falsifier pass over a single RCA Hypothesis.

    ``challenged_claim`` and ``severity`` are required so an empty object (the
    offline client's ``{}``) does NOT validate: a hypothesis cannot be honestly
    challenged without a configured model, so the offline path produces no
    hypotheses to challenge in the first place. ``counterclaims``,
    ``evidence_gaps``, and ``falsification_tests`` default to empty.
    """

    challenged_claim: str = Field(min_length=1)
    # Causal-role impact of the challenge (ADR 0034, domain glossary):
    # - critical: if valid, the hypothesis cannot serve as the Failure Mechanism.
    # - material: reduces plausibility or limits it to Trigger / Amplifying Condition.
    # - minor: adds qualification without changing causal-role suitability.
    severity: Literal["critical", "material", "minor"]
    counterclaims: list[FalsificationCounterclaim] = Field(default_factory=list)
    # Procedural guidance only — not new factual incident claims, so no citations
    # (CONTEXT "Counterclaim vs Evidence Gap vs Falsification Test").
    evidence_gaps: list[str] = Field(default_factory=list)
    falsification_tests: list[str] = Field(default_factory=list)
    # Optional Proposed RCA Hypotheses the falsifier surfaced while reviewing this
    # hypothesis (ADR 0036, PRD #26 / #30). A proposed alternative reuses the exact
    # RCA hypothesis shape so it can enter the normal citation, support, challenge,
    # and review path. It is NOT trusted output here: the stage persists it as an
    # ``origin='proposed'`` hypothesis and runs it through that path once. The
    # falsifier may only propose while challenging an initial hypothesis; a
    # second-round challenge of a proposed hypothesis must leave this empty (no
    # recursive expansion), which the stage enforces.
    proposed_hypotheses: list[RcaHypothesis] = Field(default_factory=list)


@dataclass(frozen=True)
class HypothesisToChallenge:
    """The persisted, structured handoff a falsifier receives for one hypothesis.

    A Role Handoff (ADR 0034): downstream roles consume persisted hypotheses,
    citations, and evidence rather than another role's hidden chain-of-thought or
    chat history. ORM-free so the falsifier boundary stays swappable and
    unit-testable.
    """

    title: str
    summary: str
    supporting_snippets: tuple[str, ...]
    contradicting_snippets: tuple[str, ...]


_SYSTEM_PROMPT_HEAD = """\
You are a skeptical incident reviewer whose only job is to FALSIFY a candidate
root-cause hypothesis. You are not writing prose and you are not confirming the
hypothesis; you are surfacing what would make a careful engineer doubt it.

Rules:
- Output ONLY a single JSON object. No prose, no markdown fences.
- Challenge exactly the ONE hypothesis provided.
- Search ALL of the evidence below, including lines the hypothesis did not cite,
  for counterevidence the original analysis may have overlooked.
- A "counterclaim" is a FACTUAL statement that weakens the hypothesis. Cite it by
  Artifact id and exact 1-based inclusive line ranges from the EVIDENCE block.
  Never invent artifact ids or line numbers. If you cannot cite a counterclaim,
  still state it — it will be recorded as an explicit assumption, not a fact.
- "evidence_gaps" name information that is MISSING and would help judge the
  hypothesis. "falsification_tests" are concrete investigations that could
  confirm or refute it. Neither asserts a new incident fact, so neither is cited.
- Before asserting any TEMPORAL counterclaim (that one event preceded, followed,
  or coincided with another), VERIFY the ordering against the actual timestamps
  on the cited evidence lines. Only claim "X happened before Y" if the cited
  timestamps genuinely show it. Do not manufacture a challenge by misreading event
  order — a temporal counterclaim whose own citations contradict it is worse than
  no counterclaim.
- Distinguish "a RIVAL cause" from "a different LAYER of the same cause." A
  co-occurring amplifying condition (a retry storm, a traffic surge) does not
  refute the failure mechanism it accompanies — they are parts of one chain, not
  competitors. Attack the hypothesis's CAUSAL ROLE (is it really the mechanism, or
  only a trigger/amplifier?), not the mere existence of another contributor.
- Pick ONE severity for the overall challenge:
  - "critical": if valid, this hypothesis cannot be the failure mechanism.
  - "material": reduces plausibility or limits it to a contributing role.
  - "minor": a qualification that does not change its causal role.
"""

# Appended when the falsifier is reviewing an INITIAL hypothesis and is therefore
# permitted to surface a missed alternative (ADR 0036, PRD #30 user stories 14-16).
_SYSTEM_PROMPT_PROPOSALS_ALLOWED = """\
- You MAY surface a missed alternative explanation the original analysis
  overlooked, in "proposed_hypotheses", using the SAME shape as an RCA hypothesis
  (title, summary, supporting_evidence, contradicting_evidence, unknowns,
  validation_steps, remediation_items). Propose one only if the evidence genuinely
  points to a cause the builder ignored; leave it empty otherwise. Across the whole
  review at most two alternatives total are accepted, and each is then verified and
  challenged like an initial hypothesis — so propose sparingly and cite it.
"""

# Appended when challenging a PROPOSED hypothesis: the single expansion round is
# already spent, so no further alternatives may be introduced (no recursion).
_SYSTEM_PROMPT_PROPOSALS_FORBIDDEN = """\
- Do NOT propose new hypotheses. "proposed_hypotheses" must be empty: this
  hypothesis is itself a proposed alternative and the expansion round is closed.
"""

_SYSTEM_PROMPT_SHAPE = """\

The JSON object must match this shape:
{
  "challenged_claim": "the specific hypothesis claim being challenged",
  "severity": "critical|material|minor",
  "counterclaims": [
    {"statement": "factual weakness", "evidence": [{"artifact_id": "...", "line_start": 1, "line_end": 2, "confidence_score": 0.0-1.0}]}
  ],
  "evidence_gaps": ["what is missing"],
  "falsification_tests": ["how to confirm or refute"],
  "proposed_hypotheses": []
}
"""


def _system_prompt(allow_proposals: bool) -> str:
    proposals = (
        _SYSTEM_PROMPT_PROPOSALS_ALLOWED if allow_proposals else _SYSTEM_PROMPT_PROPOSALS_FORBIDDEN
    )
    return _SYSTEM_PROMPT_HEAD + proposals + _SYSTEM_PROMPT_SHAPE


def _render_artifact(artifact_id: str, source_type: str, source_name: str, body: str) -> str:
    lines = body.split("\n")
    numbered = "\n".join(f"{index}: {line}" for index, line in enumerate(lines, start=1))
    return f"### Artifact {artifact_id} — {source_name} ({source_type})\n{numbered}"


def build_falsification_prompt(
    hypothesis: HypothesisToChallenge,
    artifacts,
    timeline_events,
    *,
    allow_proposals: bool = True,
    repair_feedback: tuple[str, ...] = (),
) -> tuple[str, str]:
    """Assemble the (system, user) prompt to challenge one hypothesis.

    Every run Artifact is rendered with its id and 1-based line numbers so the
    falsifier can cite counterevidence from lines the builder never selected
    (Falsification Retrieval across all artifacts, PRD user story 13).
    ``allow_proposals`` controls whether the falsifier may surface a missed
    alternative: True while challenging an initial hypothesis, False during the
    second-round challenge of a proposed alternative (ADR 0036).

    ``repair_feedback`` carries the deterministic Runtime Reasoning Gate errors from
    a rejected first attempt so the single Targeted Repair re-invocation is informed
    rather than a blind replay of the same prompt (ADR 0043, issue #37).
    """
    evidence = "\n\n".join(
        _render_artifact(a.id, a.source_type, a.source_name, a.body) for a in artifacts
    )
    if timeline_events:
        timeline = "\n".join(
            f"- {event.original_ts_text or event.normalized_ts or '?'}: {event.description}"
            for event in timeline_events
        )
    else:
        timeline = "(no time-anchored events were extracted)"

    cited = "\n".join(f"- {snippet}" for snippet in hypothesis.supporting_snippets) or "(none)"
    against = "\n".join(f"- {snippet}" for snippet in hypothesis.contradicting_snippets) or "(none)"

    # Stable evidence first, the per-hypothesis challenge and instruction last. The
    # falsifier challenges each hypothesis with the *same* system prompt and the same
    # full evidence, so leading with that shared block lets a prefix-caching provider
    # reuse it across the per-hypothesis calls (ADR 0021 usage). Only the hypothesis
    # and the closing instruction vary, so they trail; this matches the builder and
    # incident-facts prompts, which are already evidence-first.
    user = (
        "ALL EVIDENCE (cite artifact_id + line numbers shown):\n"
        f"{evidence}\n\n"
        "TIMELINE CANDIDATES:\n"
        f"{timeline}\n\n"
        "HYPOTHESIS TO CHALLENGE:\n"
        f"Title: {hypothesis.title}\n"
        f"Summary: {hypothesis.summary}\n\n"
        "EVIDENCE THE HYPOTHESIS CITED IN SUPPORT:\n"
        f"{cited}\n\n"
        "EVIDENCE ALREADY NOTED AGAINST IT:\n"
        f"{against}\n\n"
        "Falsify the hypothesis as the JSON object described in the system "
        "message. Look beyond the cited lines for overlooked counterevidence."
    )
    return _system_prompt(allow_proposals), append_repair_feedback(user, repair_feedback)


class Falsifier(Protocol):
    """Swappable boundary that challenges one RCA Hypothesis (ADR 0009 / 0034).

    A separate Reasoning Role from RCA generation and incident-facts extraction
    (PRD #26): its own prompt, schema, and version. ``version`` feeds Experiment
    Metadata so a challenged run is never mistaken for a builder-only run.
    """

    @property
    def version(self) -> str: ...

    def challenge(
        self,
        *,
        hypothesis: HypothesisToChallenge,
        artifacts,
        timeline_events,
        allow_proposals: bool = True,
        repair_feedback: tuple[str, ...] = (),
    ) -> HypothesisChallengeOutput: ...


class LLMFalsifier:
    """Default falsifier: one configured-model call per hypothesis (ADR 0011).

    Builds a strict prompt, calls the LLMClient, and validates the completion
    against ``HypothesisChallengeOutput`` (ADR 0028). Schema-invalid or non-JSON
    output raises, which the Causal Analysis Stage turns into a stage failure
    with one retry (ADR 0029) rather than persisting an unchallengeable verdict.

    There is no offline shortcut: a hypothesis cannot be honestly challenged
    without a model. In the offline configuration the builder produces no
    hypotheses, so the falsifier is never invoked and the run still completes.
    """

    version: Final[str] = FALSIFIER_VERSION

    def __init__(self, llm_client: LLMClient) -> None:
        self._llm = llm_client

    def challenge(
        self,
        *,
        hypothesis: HypothesisToChallenge,
        artifacts,
        timeline_events,
        allow_proposals: bool = True,
        repair_feedback: tuple[str, ...] = (),
    ) -> HypothesisChallengeOutput:
        system, user = build_falsification_prompt(
            hypothesis,
            artifacts,
            timeline_events,
            allow_proposals=allow_proposals,
            repair_feedback=repair_feedback,
        )
        response = self._llm.complete(
            system=system, user=user, max_output_tokens=output_token_cap_for(ROLE_FALSIFIER)
        )
        try:
            output = HypothesisChallengeOutput.model_validate_json(response.text)
        except ValidationError as exc:
            # Schema-invalid (or non-JSON) model output fails the stage rather
            # than persisting an incomplete challenge (ADR 0028 / 0034).
            raise ValueError(
                f"falsification output failed schema validation: {exc}"
            ) from exc
        logger.debug(
            "hypothesis_challenged severity=%s counterclaim_count=%s proposed=%s",
            output.severity,
            len(output.counterclaims),
            len(output.proposed_hypotheses),
        )
        return output
