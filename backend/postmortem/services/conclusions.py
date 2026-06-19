from __future__ import annotations

import logging

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ..auth import Principal
from ..logging import log_event
from ..models import (
    AnalysisRun,
    CausalFactor,
    Hypothesis,
    Postmortem,
    RootCauseConclusion,
)
from ..schemas import RootCauseConclusionCreate
from .analysis import AnalysisRunNotFoundError, HypothesisNotFoundError
from .incidents import IncidentService


logger = logging.getLogger("postmortem.conclusions")

# The single required causal role and the support verdicts a Causal Factor may
# carry (ADR 0039 / 0014): finalization cannot bypass the evidence trust floor.
FAILURE_MECHANISM = "failure_mechanism"
_SUFFICIENT_SUPPORT: frozenset[str] = frozenset({"supported", "partial"})


class ConclusionValidationError(ValueError):
    """Raised when a finalization request violates the causal-factor contract."""


class ConclusionNotReadyError(LookupError):
    """Raised when a run has not produced a Postmortem to finalize against."""


class ConclusionAlreadyFinalizedError(Exception):
    """Raised when a run already has an immutable Root Cause Conclusion (ADR 0039)."""


class ConclusionNotFoundError(LookupError):
    """Raised when a run has no finalized Root Cause Conclusion yet."""


class ConclusionService:
    """Owns the human Root Cause Conclusion finalization path (ADR 0039).

    Finalization is a deliberate human action, separate from accepting a
    hypothesis (CONTEXT "Hypothesis Review Decision vs Root Cause Conclusion"). The
    Analysis Run completes and produces a Provisional Postmortem; a reviewer later
    finalizes exactly one Failure Mechanism plus optional Triggers and Amplifying
    Conditions, each drawn from an accepted hypothesis that clears the evidence
    trust floor. The result is immutable.
    """

    def __init__(self, session: Session) -> None:
        self._session = session

    def _get_run(self, incident_id: str, run_id: str) -> AnalysisRun:
        IncidentService(self._session).get(incident_id)
        run = self._session.get(AnalysisRun, run_id)
        if run is None or run.incident_id != incident_id:
            raise AnalysisRunNotFoundError(run_id)
        return run

    def get_conclusion(self, incident_id: str, run_id: str) -> RootCauseConclusion:
        """The finalized Root Cause Conclusion for a run, or raise if none (ADR 0039)."""
        self._get_run(incident_id, run_id)
        conclusion = self._session.scalar(
            select(RootCauseConclusion).where(RootCauseConclusion.run_id == run_id)
        )
        if conclusion is None:
            raise ConclusionNotFoundError(run_id)
        return conclusion

    def finalize(
        self,
        incident_id: str,
        run_id: str,
        payload: RootCauseConclusionCreate,
        principal: Principal,
    ) -> RootCauseConclusion:
        """Finalize an evidence-governed Root Cause Conclusion (ADR 0039).

        Validates the trust floor before persisting: the run has a Postmortem and
        no existing conclusion (immutability), exactly one Failure Mechanism, and
        every Causal Factor references a hypothesis from this run that is accepted,
        has supported/partial claim support, and carries at least one verified
        supporting citation (PRD #26 stories 30-37). Records Conclusion Provenance
        and flips the run's Postmortem to ``finalized`` (story 42).
        """
        run = self._get_run(incident_id, run_id)

        # The Analysis Run must finish before human review begins (PRD #26 story 26).
        # A drafted Postmortem alone is not enough: drafting (stage 5) runs before
        # the final unsupported-claim audit (stage 6), so a later stage failure can
        # leave a ``failed`` run with a Postmortem still present. Finalizing then
        # would conclude a root cause before the run cleared its final trust
        # checkpoint, so require the run to have succeeded.
        if run.status != "succeeded":
            raise ConclusionNotReadyError(run_id)

        postmortem = self._session.scalar(
            select(Postmortem).where(Postmortem.run_id == run_id)
        )
        if postmortem is None:
            raise ConclusionNotReadyError(run_id)

        existing = self._session.scalar(
            select(RootCauseConclusion).where(RootCauseConclusion.run_id == run_id)
        )
        if existing is not None:
            raise ConclusionAlreadyFinalizedError(run_id)

        factors = payload.factors
        failure_mechanisms = [f for f in factors if f.role == FAILURE_MECHANISM]
        if len(failure_mechanisms) != 1:
            raise ConclusionValidationError(
                "a Root Cause Conclusion requires exactly one failure mechanism"
            )

        seen: set[str] = set()
        for factor in factors:
            if factor.hypothesis_id in seen:
                raise ConclusionValidationError(
                    "a hypothesis cannot play more than one causal role"
                )
            seen.add(factor.hypothesis_id)
            self._validate_hypothesis(run_id, factor.hypothesis_id)

        summary = payload.summary.strip()
        if not summary:
            raise ConclusionValidationError("conclusion summary cannot be blank")

        conclusion = RootCauseConclusion(
            run_id=run_id,
            summary=summary,
            finalized_by_principal=principal.id,
            finalized_by_display=principal.display,
        )
        self._session.add(conclusion)
        try:
            self._session.flush()
        except IntegrityError as exc:
            # The pre-check above handles the common sequential case; this is the
            # race backstop. The unique index on ``run_id`` rejects a second
            # concurrent finalization, so two immutable conclusions can never exist
            # for one run (ADR 0039).
            self._session.rollback()
            raise ConclusionAlreadyFinalizedError(run_id) from exc

        # Keep a stable per-role sequence so repeatable Triggers / Amplifying
        # Conditions render in the order the reviewer chose them.
        role_sequence: dict[str, int] = {}
        for factor in factors:
            sequence = role_sequence.get(factor.role, 0)
            role_sequence[factor.role] = sequence + 1
            self._session.add(
                CausalFactor(
                    conclusion_id=conclusion.id,
                    hypothesis_id=factor.hypothesis_id,
                    role=factor.role,
                    sequence=sequence,
                )
            )

        # An automated draft is provisional until this human finalization (ADR 0035).
        postmortem.conclusion_status = "finalized"
        self._session.flush()

        log_event(
            logger,
            logging.INFO,
            "root_cause_conclusion_finalized",
            run_id=run_id,
            incident_id=incident_id,
            conclusion_id=conclusion.id,
            factor_count=len(factors),
            finalized_by=principal.id,
        )
        return conclusion

    def _validate_hypothesis(self, run_id: str, hypothesis_id: str) -> None:
        hypothesis = self._session.get(Hypothesis, hypothesis_id)
        # Cross-run ownership rejection: a conclusion may only reference its own
        # run's hypotheses (PRD #26 / AC). A foreign or missing id is "not found".
        if hypothesis is None or hypothesis.run_id != run_id:
            raise HypothesisNotFoundError(hypothesis_id)
        # Accepting a hypothesis is a prerequisite, not the conclusion itself
        # (CONTEXT "Hypothesis Review Decision vs Root Cause Conclusion").
        if hypothesis.review_status != "accepted":
            raise ConclusionValidationError(
                f"hypothesis {hypothesis_id} must be accepted before it can be a causal factor"
            )
        # The semantic trust floor: an unsupported (or not-yet-evaluated) hypothesis
        # cannot be finalized as a Causal Factor (PRD #26 story 37, ADR 0014).
        if hypothesis.support_status not in _SUFFICIENT_SUPPORT:
            raise ConclusionValidationError(
                f"hypothesis {hypothesis_id} is not supported by evidence "
                f"(support: {hypothesis.support_status})"
            )
        # The citation trust floor: human finalization cannot bypass verified
        # citations (PRD #26 story 37, ADR 0013/0014). A contradicting ref does not
        # count — the factor must rest on verified supporting evidence.
        verified_supporting = any(
            ref.role != "contradicting" and ref.verifier_status == "verified"
            for ref in hypothesis.evidence_refs
        )
        if not verified_supporting:
            raise ConclusionValidationError(
                f"hypothesis {hypothesis_id} has no verified supporting citation"
            )


def causal_factor_read(factor: CausalFactor) -> dict:
    """Shape a CausalFactor (with its hypothesis provenance) for CausalFactorRead."""
    hypothesis = factor.hypothesis
    supporting = [
        ref for ref in hypothesis.evidence_refs if ref.role != "contradicting"
    ]
    return {
        "id": factor.id,
        "role": factor.role,
        "hypothesis_id": factor.hypothesis_id,
        "title": hypothesis.title,
        "summary": hypothesis.summary,
        "support_status": hypothesis.support_status,
        "advisory_rank": hypothesis.advisory_rank,
        "supporting_evidence": supporting,
    }


def conclusion_read(conclusion: RootCauseConclusion) -> dict:
    """Shape a RootCauseConclusion for RootCauseConclusionRead (ADR 0039).

    Splits the Causal Factors by role so the Review Surface and exports render the
    single Failure Mechanism distinctly from the optional repeatable Triggers and
    Amplifying Conditions, and surfaces Conclusion Provenance.
    """
    factors = list(conclusion.factors)
    failure_mechanism = next(f for f in factors if f.role == FAILURE_MECHANISM)
    triggers = [f for f in factors if f.role == "trigger"]
    amplifying = [f for f in factors if f.role == "amplifying_condition"]
    return {
        "id": conclusion.id,
        "run_id": conclusion.run_id,
        "incident_id": conclusion.run.incident_id,
        "summary": conclusion.summary,
        "finalized_by": conclusion.finalized_by_principal,
        "finalized_by_display": conclusion.finalized_by_display,
        "finalized_at": _aware(conclusion.finalized_at),
        "failure_mechanism": causal_factor_read(failure_mechanism),
        "triggers": [causal_factor_read(f) for f in triggers],
        "amplifying_conditions": [causal_factor_read(f) for f in amplifying],
        "created_at": _aware(conclusion.created_at),
    }


def _aware(value):
    """Re-attach UTC tz to naive stored timestamps so the API emits a `...Z` instant."""
    from datetime import timezone

    if value is not None and value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value
