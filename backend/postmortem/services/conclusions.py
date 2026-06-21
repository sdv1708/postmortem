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
    ConclusionDiscrepancy,
    HumanAssumption,
    Hypothesis,
    Postmortem,
    RootCauseConclusion,
)
from ..schemas import (
    ConclusionDiscrepancyCreate,
    CausalFactorCreate,
    RootCauseConclusionCreate,
)
from .analysis import AnalysisRunNotFoundError, HypothesisNotFoundError, challenge_read
from .incidents import IncidentService


logger = logging.getLogger("postmortem.conclusions")

# The single required causal role and the support verdicts a Causal Factor may
# carry (ADR 0039 / 0014): finalization cannot bypass the evidence trust floor.
FAILURE_MECHANISM = "failure_mechanism"
_SUFFICIENT_SUPPORT: frozenset[str] = frozenset({"supported", "partial"})
# A partially supported factor must be qualified; a critically challenged Failure
# Mechanism must be explicitly overridden (ADR 0042, PRD #26 stories 38-41).
PARTIAL_SUPPORT = "partial"
CRITICAL_SEVERITY = "critical"


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

        # Validate every factor and stash its normalized qualification text so the
        # persistence loop below stores exactly what the trust floor required.
        seen: set[str] = set()
        qualifications: dict[str, tuple[str | None, str | None]] = {}
        for factor in factors:
            if factor.hypothesis_id in seen:
                raise ConclusionValidationError(
                    "a hypothesis cannot play more than one causal role"
                )
            seen.add(factor.hypothesis_id)
            hypothesis = self._validate_hypothesis(run_id, factor.hypothesis_id)
            qualifications[factor.hypothesis_id] = self._validate_qualifications(
                factor, hypothesis
            )

        summary = payload.summary.strip()
        if not summary:
            raise ConclusionValidationError("conclusion summary cannot be blank")

        # Human Assumptions are unevidenced reviewer beliefs (PRD #26 story 38):
        # normalize, drop blanks, and persist them separately from the factors so
        # they can never render as established fact.
        assumptions = [a.strip() for a in payload.human_assumptions if a.strip()]

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
            acknowledgment, override = qualifications[factor.hypothesis_id]
            self._session.add(
                CausalFactor(
                    conclusion_id=conclusion.id,
                    hypothesis_id=factor.hypothesis_id,
                    role=factor.role,
                    sequence=sequence,
                    partial_support_acknowledgment=acknowledgment,
                    critical_challenge_override=override,
                )
            )

        for sequence, statement in enumerate(assumptions):
            self._session.add(
                HumanAssumption(
                    conclusion_id=conclusion.id,
                    sequence=sequence,
                    statement=statement,
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
            human_assumption_count=len(assumptions),
            finalized_by=principal.id,
        )
        return conclusion

    def _validate_hypothesis(self, run_id: str, hypothesis_id: str) -> Hypothesis:
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
        return hypothesis

    def _validate_qualifications(
        self, factor: CausalFactorCreate, hypothesis: Hypothesis
    ) -> tuple[str | None, str | None]:
        """Enforce the qualification trust floor and return persisted text (ADR 0042).

        A partially supported Causal Factor cannot be finalized without a
        Partial-Support Acknowledgment describing what is supported and what remains
        uncertain (PRD #26 stories 38-39). A critically challenged hypothesis cannot
        serve as the Failure Mechanism without a Critical-Challenge Override that
        addresses the unresolved critical challenge (stories 40-41); the challenge is
        preserved either way. Returns the normalized ``(acknowledgment, override)``
        to persist — ``None`` for a qualification that does not apply, so a fully
        supported, uncontested factor stores neither and the conclusion never carries
        misleading qualification text.
        """
        acknowledgment: str | None = None
        if hypothesis.support_status == PARTIAL_SUPPORT:
            acknowledgment = (factor.partial_support_acknowledgment or "").strip()
            if not acknowledgment:
                raise ConclusionValidationError(
                    f"hypothesis {hypothesis.id} has partial support and requires a "
                    "partial-support acknowledgment describing what is supported and "
                    "what remains uncertain"
                )

        override: str | None = None
        challenge = hypothesis.challenge
        is_critically_challenged = (
            challenge is not None and challenge.severity == CRITICAL_SEVERITY
        )
        if factor.role == FAILURE_MECHANISM and is_critically_challenged:
            override = (factor.critical_challenge_override or "").strip()
            if not override:
                raise ConclusionValidationError(
                    f"hypothesis {hypothesis.id} has an unresolved critical challenge "
                    "and cannot be the failure mechanism without a critical-challenge "
                    "override addressing it"
                )
        return acknowledgment, override

    def raise_discrepancy(
        self,
        incident_id: str,
        run_id: str,
        payload: ConclusionDiscrepancyCreate,
        principal: Principal,
    ) -> ConclusionDiscrepancy:
        """Flag a finalized Root Cause Conclusion as disputed (ADR 0040).

        Appends an immutable Conclusion Discrepancy without editing, replacing, or
        deleting the conclusion (PRD #26 stories 44-46). An open discrepancy makes
        the conclusion a Disputed Conclusion: it is preserved for audit but is no
        longer authoritative, and the incident returns to unresolved Postmortem
        Review. The disputed state is derived from the discrepancy's existence, so no
        mutation touches the immutable conclusion row.

        Requires a finalized conclusion to dispute (cross-incident/cross-run requests
        are rejected as not-found by ``_get_run``). Discrepancies are append-only:
        flagging an already-disputed conclusion appends another, building the audit
        trail rather than replacing earlier disagreement.
        """
        self._get_run(incident_id, run_id)
        conclusion = self._session.scalar(
            select(RootCauseConclusion).where(RootCauseConclusion.run_id == run_id)
        )
        if conclusion is None:
            raise ConclusionNotFoundError(run_id)

        explanation = payload.explanation.strip()
        if not explanation:
            raise ConclusionValidationError("discrepancy explanation cannot be blank")

        # Retry-safety for an append-only, DB-irreversible record. A discrepancy can
        # never be edited or deleted (ADR 0040), so a lost-response retry that
        # re-POSTs the identical explanation must not append a permanent duplicate
        # that overstates how many independent concerns were raised. An exact-text
        # match on this conclusion is treated as the same dispute and returned
        # unchanged (idempotent create); a genuinely different explanation still
        # appends, preserving the append-only audit trail for distinct concerns.
        # This guards the realistic single-user sequential-retry case (ADR 0017); it
        # is not a cross-request lock, which the MVP single-user gate does not need.
        existing = next(
            (d for d in conclusion.discrepancies if d.explanation == explanation),
            None,
        )
        if existing is not None:
            log_event(
                logger,
                logging.INFO,
                "conclusion_discrepancy_retry_ignored",
                run_id=run_id,
                incident_id=incident_id,
                conclusion_id=conclusion.id,
                discrepancy_id=existing.id,
            )
            return existing

        # Attach via the relationship (not a bare FK) so the conclusion's in-memory
        # ``discrepancies`` collection stays consistent within the session and the
        # derived disputed state is correct even before the next request reloads it.
        discrepancy = ConclusionDiscrepancy(
            conclusion=conclusion,
            run_id=run_id,
            explanation=explanation,
            raised_by_principal=principal.id,
            raised_by_display=principal.display,
        )
        self._session.add(discrepancy)
        self._session.flush()

        log_event(
            logger,
            logging.INFO,
            "conclusion_discrepancy_raised",
            run_id=run_id,
            incident_id=incident_id,
            conclusion_id=conclusion.id,
            discrepancy_id=discrepancy.id,
            raised_by=principal.id,
        )
        return discrepancy


def causal_factor_read(factor: CausalFactor) -> dict:
    """Shape a CausalFactor (with its hypothesis provenance) for CausalFactorRead.

    Surfaces the reviewer's Partial-Support Acknowledgment and Critical-Challenge
    Override, and the factor hypothesis's full persisted Hypothesis Challenge, so the
    qualifications and the actual critical challenge (challenged claim, counterclaims,
    evidence gaps, falsification tests) stay visible wherever the conclusion is
    rendered — finalization never erases the concern, and an override can be audited
    against it (ADR 0042, PRD #26 stories 38-41).
    """
    hypothesis = factor.hypothesis
    supporting = [
        ref for ref in hypothesis.evidence_refs if ref.role != "contradicting"
    ]
    challenge = hypothesis.challenge
    return {
        "id": factor.id,
        "role": factor.role,
        "hypothesis_id": factor.hypothesis_id,
        "title": hypothesis.title,
        "summary": hypothesis.summary,
        "support_status": hypothesis.support_status,
        "advisory_rank": hypothesis.advisory_rank,
        "supporting_evidence": supporting,
        "partial_support_acknowledgment": factor.partial_support_acknowledgment,
        "critical_challenge_override": factor.critical_challenge_override,
        "challenge": challenge_read(challenge) if challenge is not None else None,
    }


def human_assumption_read(assumption: HumanAssumption) -> dict:
    """Shape a HumanAssumption for HumanAssumptionRead (ADR 0042)."""
    return {
        "id": assumption.id,
        "statement": assumption.statement,
        "created_at": _aware(assumption.created_at),
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
    # A Disputed Conclusion is derived from the existence of an open Conclusion
    # Discrepancy, never from mutating the immutable conclusion row (ADR 0040).
    discrepancies = list(conclusion.discrepancies)
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
        "human_assumptions": [
            human_assumption_read(a) for a in conclusion.human_assumptions
        ],
        "disputed": bool(discrepancies),
        "discrepancies": [discrepancy_read(d) for d in discrepancies],
        "created_at": _aware(conclusion.created_at),
    }


def discrepancy_read(discrepancy: ConclusionDiscrepancy) -> dict:
    """Shape a ConclusionDiscrepancy for ConclusionDiscrepancyRead (ADR 0040)."""
    return {
        "id": discrepancy.id,
        "conclusion_id": discrepancy.conclusion_id,
        "run_id": discrepancy.run_id,
        "explanation": discrepancy.explanation,
        "raised_by": discrepancy.raised_by_principal,
        "raised_by_display": discrepancy.raised_by_display,
        "created_at": _aware(discrepancy.created_at),
    }


def _aware(value):
    """Re-attach UTC tz to naive stored timestamps so the API emits a `...Z` instant."""
    from datetime import timezone

    if value is not None and value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value
