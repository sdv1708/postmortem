from __future__ import annotations

import logging

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..auth import Principal
from ..logging import log_event
from ..models import (
    ActionItem,
    AnalysisRun,
    CausalFactor,
    Hypothesis,
    HypothesisChallenge,
    _utcnow,
)
from ..schemas import RemediationDecisionCreate
from .analysis import AnalysisRunNotFoundError, _action_item_read
from .incidents import IncidentService


logger = logging.getLogger("postmortem.remediation")

# The four Remediation Proposal review states (ADR 0041). 'proposed' is the
# generated default; the rest are human dispositions.
_REMEDIATION_STATUSES: frozenset[str] = frozenset(
    {"proposed", "accepted", "rejected", "deferred"}
)


class RemediationProposalNotFoundError(LookupError):
    """Raised when a run has no Remediation Proposal with the given id."""


class RemediationValidationError(ValueError):
    """Raised when a remediation decision violates the proposal contract (ADR 0041)."""


class RemediationLinkNotFoundError(LookupError):
    """Raised when an accepted proposal's link target is missing or cross-incident."""


class RemediationService:
    """Owns the human Remediation Proposal review path (ADR 0041).

    Generated remediation is a candidate, not committed work: a reviewer accepts,
    rejects, or defers each proposal after the Analysis Run completes. The decision
    never edits the generated text (ADR 0016). An accepted proposal must link to a
    Causal Factor or documented Evidence Gap from the reviewed incident (PRD #26
    story 53). This review is entirely separate from the bounded Falsification
    Round, which never touches remediation (CONTEXT "Causal Falsification vs
    Remediation Review").
    """

    def __init__(self, session: Session) -> None:
        self._session = session

    def _get_run(self, incident_id: str, run_id: str) -> AnalysisRun:
        IncidentService(self._session).get(incident_id)
        run = self._session.get(AnalysisRun, run_id)
        if run is None or run.incident_id != incident_id:
            raise AnalysisRunNotFoundError(run_id)
        return run

    def list_proposals(self, incident_id: str, run_id: str) -> list[ActionItem]:
        """Every Remediation Proposal for a run, in hypothesis/sequence order."""
        self._get_run(incident_id, run_id)
        return list(
            self._session.scalars(
                select(ActionItem)
                .join(Hypothesis, ActionItem.hypothesis_id == Hypothesis.id)
                .where(Hypothesis.run_id == run_id)
                .order_by(Hypothesis.rank.asc(), ActionItem.sequence.asc())
            )
        )

    def decide(
        self,
        incident_id: str,
        run_id: str,
        action_item_id: str,
        payload: RemediationDecisionCreate,
        principal: Principal,
    ) -> ActionItem:
        """Record an accept/reject/defer decision on a Remediation Proposal (ADR 0041).

        Validates the proposal belongs to this run (cross-run/incident proposals are
        rejected as not-found), the decision is a known state, and — when accepting —
        that exactly one valid link to a Causal Factor or Evidence Gap from this
        incident is supplied. The generated ``description`` is never modified.
        """
        self._get_run(incident_id, run_id)

        proposal = self._session.get(ActionItem, action_item_id)
        if proposal is None or proposal.hypothesis.run_id != run_id:
            raise RemediationProposalNotFoundError(action_item_id)

        decision = payload.decision
        if decision not in _REMEDIATION_STATUSES:
            raise RemediationValidationError(f"invalid remediation decision: {decision}")

        rationale = (payload.rationale or "").strip() or None

        if decision == "accepted":
            self._apply_link(incident_id, run_id, proposal, payload)
        else:
            if payload.link is not None:
                raise RemediationValidationError(
                    f"a '{decision}' remediation proposal cannot carry a link"
                )
            # Clear any link from a prior acceptance so a re-decision stays consistent
            # with the accepted-link contract (ADR 0041).
            proposal.causal_factor_id = None
            proposal.evidence_gap_challenge_id = None
            proposal.evidence_gap_index = None

        proposal.review_status = decision
        proposal.decision_rationale = rationale
        proposal.decided_by_principal = principal.id
        proposal.decided_by_display = principal.display
        proposal.decided_at = _utcnow()
        self._session.flush()

        log_event(
            logger,
            logging.INFO,
            "remediation_proposal_decided",
            run_id=run_id,
            incident_id=incident_id,
            action_item_id=action_item_id,
            decision=decision,
            decided_by=principal.id,
        )
        return proposal

    def _apply_link(
        self,
        incident_id: str,
        run_id: str,
        proposal: ActionItem,
        payload: RemediationDecisionCreate,
    ) -> None:
        """Validate and set the link target of an accepted proposal (ADR 0041)."""
        link = payload.link
        if link is None:
            raise RemediationValidationError(
                "an accepted remediation proposal requires a link to a "
                "causal factor or evidence gap"
            )

        if link.kind == "causal_factor":
            if not link.causal_factor_id:
                raise RemediationValidationError(
                    "a causal_factor link requires a causal_factor_id"
                )
            factor = self._session.get(CausalFactor, link.causal_factor_id)
            # Cross-incident links are rejected: the factor's conclusion must belong
            # to a run in the reviewed incident (PRD story 53).
            if factor is None or factor.conclusion.run.incident_id != incident_id:
                raise RemediationLinkNotFoundError(link.causal_factor_id or "")
            proposal.causal_factor_id = factor.id
            proposal.evidence_gap_challenge_id = None
            proposal.evidence_gap_index = None
        elif link.kind == "evidence_gap":
            if not link.evidence_gap_challenge_id or link.evidence_gap_index is None:
                raise RemediationValidationError(
                    "an evidence_gap link requires an evidence_gap_challenge_id "
                    "and evidence_gap_index"
                )
            challenge = self._session.get(HypothesisChallenge, link.evidence_gap_challenge_id)
            # The challenge must belong to this run (and therefore this incident).
            if challenge is None or challenge.run_id != run_id:
                raise RemediationLinkNotFoundError(link.evidence_gap_challenge_id)
            gaps = list(challenge.evidence_gaps or [])
            if not (0 <= link.evidence_gap_index < len(gaps)):
                raise RemediationValidationError(
                    f"evidence_gap_index {link.evidence_gap_index} is out of range "
                    f"for challenge {challenge.id}"
                )
            proposal.evidence_gap_challenge_id = challenge.id
            proposal.evidence_gap_index = link.evidence_gap_index
            proposal.causal_factor_id = None
        else:  # pragma: no cover - schema Literal already constrains kind
            raise RemediationValidationError(f"invalid remediation link kind: {link.kind}")


def remediation_proposal_read(item: ActionItem) -> dict:
    """Shape an ActionItem as a Remediation Proposal for ActionItemRead (ADR 0041)."""
    return _action_item_read(item)
