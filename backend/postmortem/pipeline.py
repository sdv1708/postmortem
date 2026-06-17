from __future__ import annotations

from typing import Final

# The six MVP Analysis Run stages, in execution order (ADR 0026, amended by
# ADR 0033). Six is the status-page ceiling. Stage 2 ("extracting incident
# facts") produces cited Timeline Events and run-level Impact Claims before any
# causal interpretation; stage 3 ("analyzing causal hypotheses") generates and
# ranks RCA Hypotheses. Remediation generation still lives inside the causal
# stage rather than becoming a separate visible stage.
#
# Stages 1-3 may introduce factual incident claims; stages 4-6 may only verify,
# annotate, or compose existing claims. This module is the single source of
# truth for stage identity and ordering, shared by the executor, the API
# schema, and the evaluation harness so they cannot drift.
RUN_STAGES: Final[tuple[str, ...]] = (
    "normalizing_evidence",
    "extracting_incident_facts",
    "analyzing_causal_hypotheses",
    "verifying_citations",
    "drafting_postmortem",
    "flagging_unsupported_claims",
)
