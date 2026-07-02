from __future__ import annotations

import logging
from typing import Final, Protocol

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from .llm import LLMClient
from .provenance import ROLE_INCIDENT_FACTS, output_token_cap_for
from .rca import RcaEvidenceRef

logger = logging.getLogger("postmortem.incident_facts")

# Versioned prompt identity for the incident-facts extractor (ADR 0025 / 0033).
# Bump when the prompt or the expected output contract changes so runs stay
# comparable. Distinct from the RCA prompt: incident facts are a separate
# Reasoning Role with its own prompt and schema (PRD #26).
INCIDENT_FACTS_PROMPT_VERSION: Final[str] = "incident-facts-1"
INCIDENT_FACT_EXTRACTOR_VERSION: Final[str] = "llm-incident-facts-1"
# Versioned identity of the extractor's strict output schema (ADR 0028 / 0038),
# recorded on its Model Call Record. Bump when ``IncidentFactsOutput`` changes.
INCIDENT_FACTS_SCHEMA_VERSION: Final[str] = "incident-facts-output-1"


# --- Strict structured model-output contract (ADR 0028) ---------------------
#
# Stage 2 ("extracting incident facts") produces run-level Impact Claims before
# any causal interpretation (ADR 0033). The model cites Artifact line ranges
# (ADR 0024); the stage resolves the exact snippet from the stored lines, so the
# model is never trusted to reproduce snippet text. Invalid JSON or a schema
# violation fails the stage (ADR 0029) rather than persisting corrupt output.


class StrictFactsModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class FactsImpactClaim(StrictFactsModel):
    description: str = Field(min_length=1)
    # Reuse the shared cite shape (artifact_id + 1-based inclusive line range +
    # confidence) so the stage's existing ref-resolution path applies unchanged.
    evidence: list[RcaEvidenceRef] = Field(default_factory=list)


class IncidentFactsOutput(StrictFactsModel):
    """Top-level incident-facts stage output: run-level Impact Claims.

    ``impact_claims`` defaults to empty so the offline/no-provider client (which
    returns ``{}``) validates as "no impact extracted" rather than failing the
    stage.
    """

    impact_claims: list[FactsImpactClaim] = Field(default_factory=list)


_SYSTEM_PROMPT = """\
You are an incident-impact extraction assistant for an evidence review system.
You extract OBSERVED incident impact — user-facing or system consequences that
actually happened — separately from any explanation of why they happened.

Rules:
- Output ONLY a single JSON object. No prose, no markdown fences.
- Extract IMPACT only: observed consequences (error rates, failed requests,
  customer-facing degradation, data effects). Do NOT propose root causes; that is
  a later stage.
- Produce each distinct impact ONCE for the whole incident. Do not duplicate the
  same impact under different wordings.
- Cite evidence by Artifact id and exact 1-based inclusive line ranges from the
  EVIDENCE block. Never invent artifact ids or line numbers.
- Every impact claim must include supporting evidence when the evidence exists.
  If you cannot cite it, omit it rather than asserting it.

The JSON object must match this shape:
{
  "impact_claims": [
    {"description": "evidence-backed observed impact", "evidence": [{"artifact_id": "...", "line_start": 1, "line_end": 1, "confidence_score": 0.0-1.0}]}
  ]
}
"""


def _render_artifact(artifact_id: str, source_type: str, source_name: str, body: str) -> str:
    lines = body.split("\n")
    numbered = "\n".join(f"{index}: {line}" for index, line in enumerate(lines, start=1))
    return f"### Artifact {artifact_id} — {source_name} ({source_type})\n{numbered}"


def build_incident_facts_prompt(artifacts, timeline_events) -> tuple[str, str]:
    """Assemble the (system, user) prompt for run-level impact extraction.

    Each artifact is rendered with its id and 1-based line numbers so the model
    can cite exact lines (ADR 0024). Already-extracted timeline candidates are
    included as chronological context.
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
        "Extract the observed incident impact as the JSON object described in the "
        "system message. Extract impact only, not root causes."
    )
    return _SYSTEM_PROMPT, user


class IncidentFactExtractor(Protocol):
    """Swappable boundary that produces run-level incident facts (ADR 0009 / 0033).

    A separate Reasoning Role from RCA generation (PRD #26): it has its own
    prompt, schema, and version. ``version`` feeds Experiment Metadata.
    """

    @property
    def version(self) -> str: ...

    def extract(self, *, artifacts, timeline_events) -> IncidentFactsOutput: ...


class LLMIncidentFactExtractor:
    """Default extractor: one configured-model call validated against the schema.

    Uses the run's configured LLMClient (ADR 0011). With no provider configured
    the offline client returns ``{}``, which validates as "no impact extracted"
    so a run still completes its six stages.
    """

    version: Final[str] = INCIDENT_FACT_EXTRACTOR_VERSION

    def __init__(self, llm_client: LLMClient) -> None:
        self._llm = llm_client

    def extract(self, *, artifacts, timeline_events) -> IncidentFactsOutput:
        system, user = build_incident_facts_prompt(artifacts, timeline_events)
        response = self._llm.complete(
            system=system, user=user, max_output_tokens=output_token_cap_for(ROLE_INCIDENT_FACTS)
        )
        try:
            output = IncidentFactsOutput.model_validate_json(response.text)
        except ValidationError as exc:
            # Schema-invalid (or non-JSON) model output fails the stage rather
            # than becoming pipeline state (ADR 0028).
            raise ValueError(f"incident-facts output failed schema validation: {exc}") from exc
        logger.debug(
            "incident_facts_extracted impact_claim_count=%s", len(output.impact_claims)
        )
        return output
