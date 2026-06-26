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
    SupersedingConclusionCreate,
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


class ConclusionSupersessionError(Exception):
    """Raised when a Superseding Conclusion violates the chain contract (ADR 0045).

    Covers the invalid-predecessor and chain-integrity states: superseding a
    conclusion that is not disputed, one that has already been superseded, or
    targeting a run that already carries its own conclusion. Distinct from
    ``ConclusionValidationError`` (the per-factor trust floor) so the API can answer a
    conflicting predecessor state with 409.
    """


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
        """The representative Root Cause Conclusion for a run, or raise if none.

        A run can carry more than one conclusion once a same-run reinterpretation
        appends a Superseding Conclusion (ADR 0045), so this returns the run's
        *representative* — the latest finalized against it — which is the original for
        a run that has not been reinterpreted and the successor after a same-run
        supersession.
        """
        self._get_run(incident_id, run_id)
        conclusion = self._run_representative(run_id)
        if conclusion is None:
            raise ConclusionNotFoundError(run_id)
        return conclusion

    def list_supersedable(self, incident_id: str) -> list[RootCauseConclusion]:
        """Disputed, not-yet-superseded conclusions across the incident (ADR 0045).

        These are the conclusions a reviewer may resolve by finalizing a Superseding
        Conclusion: each is a Disputed Conclusion (open discrepancy) at the tail of its
        chain (not already superseded). Surfaced incident-wide so a *new* Analysis Run
        can supersede a predecessor from an earlier run — the new-Evidence path, which
        a single run's conclusion view cannot offer (PRD #26 stories 47-49). Ordered
        oldest-first for stable presentation.
        """
        IncidentService(self._session).get(incident_id)
        conclusions = list(
            self._session.scalars(
                select(RootCauseConclusion)
                .join(AnalysisRun, RootCauseConclusion.run_id == AnalysisRun.id)
                .where(AnalysisRun.incident_id == incident_id)
                .order_by(RootCauseConclusion.created_at.asc())
            )
        )
        return [c for c in conclusions if c.discrepancies and c.superseded_by is None]

    def _run_representative(self, run_id: str) -> RootCauseConclusion | None:
        """The conclusion a run currently presents (ADR 0045).

        A run carries more than one conclusion only after a same-run reinterpretation,
        which appends a successor in the same run; the run then presents the tail of
        that same-run sub-chain. A successor in a *different* run (new Evidence) leaves
        the predecessor as this run's representative — now superseded cross-run.
        """
        conclusions = list(
            self._session.scalars(
                select(RootCauseConclusion).where(RootCauseConclusion.run_id == run_id)
            )
        )
        return representative_conclusion(conclusions, run_id)

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
        run, postmortem = self._require_ready_run(incident_id, run_id)

        existing = self._run_representative(run_id)
        if existing is not None:
            raise ConclusionAlreadyFinalizedError(run_id)

        qualifications, summary, assumptions = self._validate_payload(run_id, payload)
        conclusion = self._persist_conclusion(
            run_id,
            postmortem,
            payload,
            principal,
            qualifications,
            summary,
            assumptions,
            on_conflict=lambda: ConclusionAlreadyFinalizedError(run_id),
        )
        log_event(
            logger,
            logging.INFO,
            "root_cause_conclusion_finalized",
            run_id=run_id,
            incident_id=incident_id,
            conclusion_id=conclusion.id,
            factor_count=len(payload.factors),
            human_assumption_count=len(assumptions),
            finalized_by=principal.id,
        )
        return conclusion

    def supersede(
        self,
        incident_id: str,
        run_id: str,
        payload: SupersedingConclusionCreate,
        principal: Principal,
    ) -> RootCauseConclusion:
        """Finalize a Superseding Conclusion that resolves a dispute (ADR 0045).

        The dispute is resolved by *appending* a new immutable conclusion, never by
        editing the predecessor (CONTEXT "Superseding Conclusion vs Revision"). The
        predecessor must be a Disputed Conclusion in this incident that has not already
        been superseded (chain integrity), and the named discrepancy must belong to it.
        ``run_id`` is the run the successor is finalized against: the predecessor's own
        run for reinterpretation of unchanged Evidence, or a new Analysis Run when new
        Evidence is used — in which case that run must not already carry a conclusion of
        its own (PRD #26 stories 47-50). The successor clears the same evidence trust
        floor as ``finalize`` and authority moves to it.
        """
        run, postmortem = self._require_ready_run(incident_id, run_id)

        predecessor = self._session.get(
            RootCauseConclusion, payload.supersedes_conclusion_id
        )
        # The predecessor must exist and belong to this incident; a foreign or missing
        # id is "not found" so the endpoint cannot leak or invent state.
        if predecessor is None or predecessor.run.incident_id != incident_id:
            raise ConclusionNotFoundError(payload.supersedes_conclusion_id)

        # Only a Disputed Conclusion may be superseded (ADR 0045): superseding is the
        # resolution of a recorded dispute, not a free re-finalization.
        if not predecessor.discrepancies:
            raise ConclusionSupersessionError(
                "only a disputed conclusion can be superseded"
            )
        # The chain is linear: a predecessor may be superseded at most once. The
        # unique index on ``supersedes_id`` is the race backstop below.
        if predecessor.superseded_by is not None:
            raise ConclusionSupersessionError(
                "this conclusion has already been superseded"
            )

        # The named discrepancy must be one of the predecessor's own, so the successor
        # is linked to the dispute it actually answers (PRD #26 story 48).
        discrepancy = next(
            (d for d in predecessor.discrepancies if d.id == payload.discrepancy_id),
            None,
        )
        if discrepancy is None:
            raise ConclusionValidationError(
                "the discrepancy does not belong to the conclusion being superseded"
            )

        # Reinterpretation reuses the predecessor's run; new Evidence requires a new
        # run (PRD #26 stories 49-50). New Evidence can only enter through a new
        # Analysis Run (artifacts are immutable, ADR 0018), and the successor's factors
        # are validated against ``run_id`` below. Keep each run's conclusion story
        # unambiguous: a cross-run successor must target a run with no conclusion yet.
        same_run = run_id == predecessor.run_id
        if not same_run and self._run_representative(run_id) is not None:
            raise ConclusionSupersessionError(
                "the target analysis run already has its own conclusion"
            )

        qualifications, summary, assumptions = self._validate_payload(run_id, payload)
        conclusion = self._persist_conclusion(
            run_id,
            postmortem,
            payload,
            principal,
            qualifications,
            summary,
            assumptions,
            supersedes_id=predecessor.id,
            superseded_discrepancy_id=discrepancy.id,
            on_conflict=lambda: ConclusionSupersessionError(
                "this conclusion has already been superseded"
            ),
        )
        # The chain-integrity check above loaded ``predecessor.superseded_by`` while it
        # was still None; the successor was then linked by setting the FK column
        # directly, which does not back-populate the cached relationship. Expire it so
        # any subsequent read (representative selection, derived status) reloads the new
        # successor instead of the stale None (sessions use expire_on_commit=False).
        self._session.expire(predecessor, ["superseded_by"])
        log_event(
            logger,
            logging.INFO,
            "root_cause_conclusion_superseded",
            run_id=run_id,
            incident_id=incident_id,
            conclusion_id=conclusion.id,
            supersedes_id=predecessor.id,
            discrepancy_id=discrepancy.id,
            same_run=same_run,
            finalized_by=principal.id,
        )
        return conclusion

    def _require_ready_run(
        self, incident_id: str, run_id: str
    ) -> tuple[AnalysisRun, Postmortem]:
        """The run and its Postmortem, or raise if it is not ready to conclude.

        The Analysis Run must finish before human review begins (PRD #26 story 26). A
        drafted Postmortem alone is not enough: drafting (stage 5) runs before the
        final unsupported-claim audit (stage 6), so a later stage failure can leave a
        ``failed`` run with a Postmortem still present. Finalizing then would conclude
        a root cause before the run cleared its final trust checkpoint, so require the
        run to have succeeded.
        """
        run = self._get_run(incident_id, run_id)
        if run.status != "succeeded":
            raise ConclusionNotReadyError(run_id)
        postmortem = self._session.scalar(
            select(Postmortem).where(Postmortem.run_id == run_id)
        )
        if postmortem is None:
            raise ConclusionNotReadyError(run_id)
        return run, postmortem

    def _validate_payload(
        self, run_id: str, payload: RootCauseConclusionCreate
    ) -> tuple[dict[str, tuple[str | None, str | None]], str, list[str]]:
        """Validate the factor trust floor and normalize the conclusion text.

        Enforces exactly one Failure Mechanism, no hypothesis in two roles, and the
        per-factor evidence and qualification floors (PRD #26 stories 31-41). Returns
        the per-hypothesis ``(acknowledgment, override)`` qualifications, the trimmed
        ``summary``, and the normalized non-blank ``human_assumptions``.
        """
        factors = payload.factors
        failure_mechanisms = [f for f in factors if f.role == FAILURE_MECHANISM]
        if len(failure_mechanisms) != 1:
            raise ConclusionValidationError(
                "a Root Cause Conclusion requires exactly one failure mechanism"
            )

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
        return qualifications, summary, assumptions

    def _persist_conclusion(
        self,
        run_id: str,
        postmortem: Postmortem,
        payload: RootCauseConclusionCreate,
        principal: Principal,
        qualifications: dict[str, tuple[str | None, str | None]],
        summary: str,
        assumptions: list[str],
        *,
        supersedes_id: str | None = None,
        superseded_discrepancy_id: str | None = None,
        on_conflict,
    ) -> RootCauseConclusion:
        """Persist a validated conclusion, its factors, and assumptions (ADR 0039/0045).

        Shared by ``finalize`` and ``supersede``: the only difference is the optional
        superseding links and which conflict the unique indexes map to (a second
        original for the run, or a second successor for one predecessor). Records
        Conclusion Provenance and flips the run's Postmortem to ``finalized``.
        """
        conclusion = RootCauseConclusion(
            run_id=run_id,
            summary=summary,
            finalized_by_principal=principal.id,
            finalized_by_display=principal.display,
            supersedes_id=supersedes_id,
            superseded_discrepancy_id=superseded_discrepancy_id,
        )
        self._session.add(conclusion)
        try:
            self._session.flush()
        except IntegrityError as exc:
            # Race backstop for the partial unique indexes (ADR 0039/0045): a second
            # original conclusion for the run, or a second successor for one
            # predecessor, is rejected so the single-original and linear-chain
            # invariants hold even without the service pre-checks.
            self._session.rollback()
            raise on_conflict() from exc

        # Keep a stable per-role sequence so repeatable Triggers / Amplifying
        # Conditions render in the order the reviewer chose them.
        role_sequence: dict[str, int] = {}
        for factor in payload.factors:
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

        # An automated draft is provisional until this human finalization (ADR 0035);
        # a successor reasserts ``finalized`` for its run as authority moves to it.
        postmortem.conclusion_status = "finalized"
        self._session.flush()
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
        # Dispute the run's representative conclusion — the successor after a same-run
        # reinterpretation, the original otherwise (ADR 0045).
        conclusion = self._run_representative(run_id)
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


def representative_conclusion(
    conclusions: list[RootCauseConclusion], run_id: str
) -> RootCauseConclusion | None:
    """The conclusion a run presents, from its own conclusions (ADR 0045).

    The tail of the run's same-run chain: the conclusion not superseded by another
    conclusion *in the same run*. A predecessor superseded cross-run (new Evidence)
    stays its run's representative — now rendered ``superseded`` with a pointer to the
    successor's run. Shared by the conclusion service and the postmortem read so both
    agree on which conclusion a run currently shows.
    """
    for conclusion in conclusions:
        successor = conclusion.superseded_by
        if successor is None or successor.run_id != run_id:
            return conclusion
    return conclusions[-1] if conclusions else None


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
    disputed = bool(discrepancies)
    # Superseding-chain links (ADR 0045): the disputed predecessor this conclusion
    # replaced, the successor that replaced it, and the full predecessor history for
    # audit. A conclusion is authoritative only at the undisputed tail of its chain.
    superseded_by = conclusion.superseded_by
    authoritative = not disputed and superseded_by is None
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
        "disputed": disputed,
        "discrepancies": [discrepancy_read(d) for d in discrepancies],
        "supersedes": superseded_link_read(conclusion.supersedes)
        if conclusion.supersedes is not None
        else None,
        "superseded_by": superseded_link_read(superseded_by)
        if superseded_by is not None
        else None,
        "history": [superseded_link_read(c) for c in _predecessor_chain(conclusion)],
        "authoritative": authoritative,
        "created_at": _aware(conclusion.created_at),
    }


def _predecessor_chain(conclusion: RootCauseConclusion) -> list[RootCauseConclusion]:
    """Walk a conclusion's predecessors oldest-first for audit (ADR 0045).

    Follows ``supersedes`` back to the original so an audit view shows the complete
    chain (PRD #26 story 48). The ``seen`` guard is defensive against a malformed
    cycle; the unique ``supersedes_id`` index keeps the chain linear in practice.
    """
    chain: list[RootCauseConclusion] = []
    seen: set[str] = set()
    current = conclusion.supersedes
    while current is not None and current.id not in seen:
        seen.add(current.id)
        chain.append(current)
        current = current.supersedes
    chain.reverse()
    return chain


def superseded_link_read(conclusion: RootCauseConclusion) -> dict:
    """Shape a summary-level link to another conclusion in a chain (ADR 0045)."""
    discrepancies = list(conclusion.discrepancies)
    return {
        "id": conclusion.id,
        "run_id": conclusion.run_id,
        "incident_id": conclusion.run.incident_id,
        "summary": conclusion.summary,
        "finalized_by": conclusion.finalized_by_principal,
        "finalized_by_display": conclusion.finalized_by_display,
        "finalized_at": _aware(conclusion.finalized_at),
        "disputed": bool(discrepancies),
        "discrepancies": [discrepancy_read(d) for d in discrepancies],
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
