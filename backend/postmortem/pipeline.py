from __future__ import annotations

from typing import Final

# The six MVP Analysis Run stages, in execution order (ADR 0026). Six is the
# status-page ceiling: impact analysis and remediation generation live inside
# the RCA hypothesis stage rather than becoming separate visible stages.
#
# Stages 1-3 may introduce factual incident claims; stages 4-6 may only verify,
# annotate, or compose existing claims. This module is the single source of
# truth for stage identity and ordering, shared by the executor, the API
# schema, and the evaluation harness so they cannot drift.
RUN_STAGES: Final[tuple[str, ...]] = (
    "normalizing_evidence",
    "extracting_timeline_candidates",
    "generating_rca_hypotheses",
    "verifying_citations",
    "drafting_postmortem",
    "flagging_unsupported_claims",
)
