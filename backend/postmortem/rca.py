from __future__ import annotations

from typing import Final

from pydantic import BaseModel, ConfigDict, Field

# Versioned prompt identity recorded in Experiment Metadata (ADR 0025). Bump when
# the prompt or the expected output contract changes so runs stay comparable.
PROMPT_VERSION: Final[str] = "rca-1"

# Versioned identity of the builder's strict output schema (ADR 0028 / 0038),
# recorded on each builder Model Call Record. Bump when ``RcaGenerationOutput``
# changes so a run records which contract validated its hypotheses.
RCA_SCHEMA_VERSION: Final[str] = "rca-output-1"

# The bounded builder cardinality (ADR 0036, PRD #26 / #30 user story 65, Hypothesis
# Budget): the builder may generate at most this many initial RCA Hypotheses. More
# than this fails the Runtime Reasoning Gate rather than persisting an unbounded
# candidate set, keeping the review and token surface predictable. This is the
# initial-hypothesis sibling of ``MAX_PROPOSED_HYPOTHESES`` (at most two), which
# together cap the final advisory list at seven.
MAX_INITIAL_HYPOTHESES: Final[int] = 5


# --- Strict structured model-output contract (ADR 0028) ---------------------
#
# The model must return JSON matching these schemas. Parsing/validation happens
# before any of it becomes pipeline state; invalid JSON or a schema violation
# fails the stage (ADR 0029) rather than persisting corrupt output. The model
# cites Artifact line ranges (ADR 0024); the stage resolves the exact snippet
# from the stored lines, so the model is not trusted to reproduce snippet text.


class StrictRcaModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class RcaEvidenceRef(StrictRcaModel):
    artifact_id: str
    line_start: int = Field(ge=1)
    line_end: int = Field(ge=1)
    confidence_score: float = Field(default=1.0, ge=0.0, le=1.0)


class RcaRemediationItem(StrictRcaModel):
    description: str = Field(min_length=1)
    evidence: list[RcaEvidenceRef] = Field(default_factory=list)


class RcaHypothesis(StrictRcaModel):
    title: str = Field(min_length=1)
    summary: str = Field(min_length=1)
    supporting_evidence: list[RcaEvidenceRef] = Field(default_factory=list)
    contradicting_evidence: list[RcaEvidenceRef] = Field(default_factory=list)
    unknowns: list[str] = Field(default_factory=list)
    validation_steps: list[str] = Field(default_factory=list)
    remediation_items: list[RcaRemediationItem] = Field(default_factory=list)


class RcaGenerationOutput(StrictRcaModel):
    """Top-level RCA stage output: ranked hypotheses (highest support first).

    ``hypotheses`` defaults to empty so the offline/no-provider client (which
    returns ``{}``) validates as "no hypotheses generated" rather than failing
    the stage. Impact Claims are no longer part of this contract — they are
    run-level incident facts produced by the earlier stage (ADR 0033).
    """

    hypotheses: list[RcaHypothesis] = Field(default_factory=list)


_SYSTEM_PROMPT = """\
You are an incident root-cause analysis assistant for an evidence review system.
You do not write confident prose; you produce auditable, evidence-backed
hypotheses that a skeptical engineer can judge.

Rules:
- Output ONLY a single JSON object. No prose, no markdown fences.
- When the evidence is ambiguous, produce MULTIPLE competing hypotheses rather
  than committing to one. Rank them most-supported first.
- Cite evidence by Artifact id and exact 1-based inclusive line ranges from the
  EVIDENCE block. Never invent artifact ids or line numbers.
- Every hypothesis must include supporting evidence when the evidence exists. If
  you cannot cite it, state it as an unknown instead of asserting it.
- Include contradicting evidence, open unknowns, and concrete validation steps
  for each hypothesis. Tie remediation items to the hypothesis.
- Do NOT restate observed incident impact here; impact is extracted separately as
  a run-level incident fact. Focus on the suspected cause.

The JSON object must match this shape:
{
  "hypotheses": [
    {
      "title": "short hypothesis name",
      "summary": "1-3 sentence statement of the suspected root cause",
      "supporting_evidence": [{"artifact_id": "...", "line_start": 1, "line_end": 2, "confidence_score": 0.0-1.0}],
      "contradicting_evidence": [{"artifact_id": "...", "line_start": 1, "line_end": 1}],
      "unknowns": ["what we still cannot determine"],
      "validation_steps": ["how to confirm or refute this"],
      "remediation_items": [{"description": "concrete action", "evidence": []}]
    }
  ]
}
"""


def _render_artifact(artifact_id: str, source_type: str, source_name: str, body: str) -> str:
    lines = body.split("\n")
    numbered = "\n".join(f"{index}: {line}" for index, line in enumerate(lines, start=1))
    return (
        f"### Artifact {artifact_id} — {source_name} ({source_type})\n{numbered}"
    )


def build_rca_prompt(artifacts, timeline_events) -> tuple[str, str]:
    """Assemble the (system, user) prompt from a run's normalized evidence.

    Each artifact is rendered with its id and 1-based line numbers so the model
    can cite exact lines (ADR 0024). Already-extracted timeline candidates are
    included as chronological context so the RCA reasons over the same anchored
    events the timeline stage found.
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

    user = (
        "EVIDENCE (cite artifact_id + line numbers shown):\n"
        f"{evidence}\n\n"
        "TIMELINE CANDIDATES:\n"
        f"{timeline}\n\n"
        "Produce ranked RCA hypotheses as the JSON object described in the system "
        "message. Return multiple hypotheses if the cause is ambiguous."
    )
    return _SYSTEM_PROMPT, user
