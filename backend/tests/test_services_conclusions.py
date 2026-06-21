from __future__ import annotations

import json

import pytest

from postmortem.auth import Principal
from postmortem.incident_facts import FactsImpactClaim
from postmortem.llm import FakeLLMClient
from postmortem.rca import RcaEvidenceRef
from postmortem.schemas import (
    AnalysisRunCreate,
    ArtifactCreate,
    CausalFactorCreate,
    ConclusionDiscrepancyCreate,
    IncidentCreate,
    RootCauseConclusionCreate,
)
from postmortem.services import (
    AnalysisRunNotFoundError,
    AnalysisService,
    ConclusionAlreadyFinalizedError,
    ConclusionNotFoundError,
    ConclusionNotReadyError,
    ConclusionService,
    HypothesisNotFoundError,
    IncidentService,
    ArtifactService,
    conclusion_read,
)
from postmortem.services.conclusions import ConclusionValidationError
from postmortem.verification import ClaimSupportJudgment, ClaimSupportStatus

from tests._fakes import (
    FakeClaimSupportVerifier,
    FakeFalsifier,
    FakeIncidentFactExtractor,
)


PRINCIPAL = Principal(id="reviewer-1", display="Reviewer One")


def _succeeded_run(
    session, *, titles=("Primary cause", "Alternative cause"), verifier=None, falsifier=None
):
    """Seed a succeeded run with the given hypotheses (each line-cited)."""
    incident = IncidentService(session).create(IncidentCreate(title="Ambiguous"))
    artifact = ArtifactService(session).create(
        incident.id,
        ArtifactCreate(
            source_type="logs",
            source_name="api.log",
            body="line one\nline two\nline three\nline four\nline five",
        ),
    )
    session.commit()
    hypotheses_payload = [
        {
            "title": title,
            "summary": f"{title} explanation.",
            "supporting_evidence": [
                {"artifact_id": artifact.id, "line_start": index + 1, "line_end": index + 1}
            ],
        }
        for index, title in enumerate(titles)
    ]
    payload = json.dumps({"hypotheses": hypotheses_payload})
    impact = [
        FactsImpactClaim(
            description="Customers saw errors",
            evidence=[RcaEvidenceRef(artifact_id=artifact.id, line_start=1, line_end=1)],
        )
    ]
    service = AnalysisService(
        session,
        llm_client=FakeLLMClient([payload], label="fake-model"),
        claim_support_verifier=verifier or FakeClaimSupportVerifier(),
        incident_fact_extractor=FakeIncidentFactExtractor(impact),
        falsifier=falsifier or FakeFalsifier(),
    )
    run = service.start_run(incident.id, AnalysisRunCreate())
    session.commit()
    assert run.status == "succeeded"
    return service, incident, run


def _by_title(service, incident, run):
    return {h.title: h for h in service.list_hypotheses(incident.id, run.id)}


def _accept(service, incident, run, *hypotheses):
    for hypothesis in hypotheses:
        service.review_hypothesis(incident.id, run.id, hypothesis.id, "accepted")


def test_finalize_records_conclusion_with_provenance(fresh_session):
    service, incident, run = _succeeded_run(fresh_session)
    hyps = _by_title(service, incident, run)
    _accept(service, incident, run, hyps["Primary cause"])
    fresh_session.commit()

    conclusion = ConclusionService(fresh_session).finalize(
        incident.id,
        run.id,
        RootCauseConclusionCreate(
            summary="The deploy regressed connection handling.",
            factors=[
                CausalFactorCreate(
                    hypothesis_id=hyps["Primary cause"].id, role="failure_mechanism"
                )
            ],
        ),
        PRINCIPAL,
    )
    fresh_session.commit()

    assert conclusion.finalized_by_principal == "reviewer-1"
    assert conclusion.finalized_by_display == "Reviewer One"
    assert conclusion.finalized_at is not None

    shaped = conclusion_read(conclusion)
    assert shaped["incident_id"] == incident.id
    assert shaped["failure_mechanism"]["title"] == "Primary cause"
    assert shaped["failure_mechanism"]["support_status"] == "supported"
    assert shaped["failure_mechanism"]["supporting_evidence"]  # navigable to evidence
    assert shaped["triggers"] == []
    assert shaped["amplifying_conditions"] == []

    # The automated provisional draft becomes finalized once the human concludes.
    document = service.get_postmortem_document(incident.id, run.id)
    assert document["conclusion_status"] == "finalized"
    assert document["conclusion"]["id"] == conclusion.id


def test_finalize_supports_optional_repeatable_roles(fresh_session):
    service, incident, run = _succeeded_run(
        fresh_session, titles=("Mechanism", "Trigger one", "Amp one", "Amp two")
    )
    hyps = _by_title(service, incident, run)
    _accept(service, incident, run, *hyps.values())
    fresh_session.commit()

    conclusion = ConclusionService(fresh_session).finalize(
        incident.id,
        run.id,
        RootCauseConclusionCreate(
            summary="Multi-factor incident.",
            factors=[
                CausalFactorCreate(hypothesis_id=hyps["Mechanism"].id, role="failure_mechanism"),
                CausalFactorCreate(hypothesis_id=hyps["Trigger one"].id, role="trigger"),
                CausalFactorCreate(hypothesis_id=hyps["Amp one"].id, role="amplifying_condition"),
                CausalFactorCreate(hypothesis_id=hyps["Amp two"].id, role="amplifying_condition"),
            ],
        ),
        PRINCIPAL,
    )
    fresh_session.commit()

    shaped = conclusion_read(conclusion)
    assert shaped["failure_mechanism"]["title"] == "Mechanism"
    assert [t["title"] for t in shaped["triggers"]] == ["Trigger one"]
    assert {a["title"] for a in shaped["amplifying_conditions"]} == {"Amp one", "Amp two"}


def test_finalize_requires_exactly_one_failure_mechanism(fresh_session):
    service, incident, run = _succeeded_run(fresh_session)
    hyps = _by_title(service, incident, run)
    _accept(service, incident, run, *hyps.values())
    fresh_session.commit()
    svc = ConclusionService(fresh_session)

    # Zero failure mechanisms.
    with pytest.raises(ConclusionValidationError):
        svc.finalize(
            incident.id,
            run.id,
            RootCauseConclusionCreate(
                summary="x",
                factors=[
                    CausalFactorCreate(hypothesis_id=hyps["Primary cause"].id, role="trigger")
                ],
            ),
            PRINCIPAL,
        )
    fresh_session.rollback()

    # Two failure mechanisms.
    with pytest.raises(ConclusionValidationError):
        svc.finalize(
            incident.id,
            run.id,
            RootCauseConclusionCreate(
                summary="x",
                factors=[
                    CausalFactorCreate(
                        hypothesis_id=hyps["Primary cause"].id, role="failure_mechanism"
                    ),
                    CausalFactorCreate(
                        hypothesis_id=hyps["Alternative cause"].id, role="failure_mechanism"
                    ),
                ],
            ),
            PRINCIPAL,
        )


def test_finalize_rejects_unaccepted_hypothesis(fresh_session):
    service, incident, run = _succeeded_run(fresh_session)
    hyps = _by_title(service, incident, run)  # left "proposed"
    fresh_session.commit()
    with pytest.raises(ConclusionValidationError, match="accepted"):
        ConclusionService(fresh_session).finalize(
            incident.id,
            run.id,
            RootCauseConclusionCreate(
                summary="x",
                factors=[
                    CausalFactorCreate(
                        hypothesis_id=hyps["Primary cause"].id, role="failure_mechanism"
                    )
                ],
            ),
            PRINCIPAL,
        )


def test_finalize_rejects_unsupported_hypothesis(fresh_session):
    def judge(claim):
        if claim.claim_text.startswith("Primary cause"):
            return ClaimSupportJudgment(ClaimSupportStatus.UNSUPPORTED, "Not established.")
        return ClaimSupportJudgment(ClaimSupportStatus.SUPPORTED, "ok")

    service, incident, run = _succeeded_run(
        fresh_session, verifier=FakeClaimSupportVerifier(judge)
    )
    hyps = _by_title(service, incident, run)
    _accept(service, incident, run, hyps["Primary cause"])
    fresh_session.commit()
    with pytest.raises(ConclusionValidationError, match="not supported"):
        ConclusionService(fresh_session).finalize(
            incident.id,
            run.id,
            RootCauseConclusionCreate(
                summary="x",
                factors=[
                    CausalFactorCreate(
                        hypothesis_id=hyps["Primary cause"].id, role="failure_mechanism"
                    )
                ],
            ),
            PRINCIPAL,
        )


def test_finalize_rejects_unverified_citation(fresh_session):
    service, incident, run = _succeeded_run(fresh_session)
    hyps = _by_title(service, incident, run)
    target = hyps["Primary cause"]
    _accept(service, incident, run, target)
    # Simulate a citation that did not pass deterministic integrity.
    for ref in target.evidence_refs:
        ref.verifier_status = "snippet_mismatch"
    fresh_session.flush()
    fresh_session.commit()
    with pytest.raises(ConclusionValidationError, match="verified"):
        ConclusionService(fresh_session).finalize(
            incident.id,
            run.id,
            RootCauseConclusionCreate(
                summary="x",
                factors=[CausalFactorCreate(hypothesis_id=target.id, role="failure_mechanism")],
            ),
            PRINCIPAL,
        )


def test_finalize_rejects_cross_run_hypothesis(fresh_session):
    service, incident, run = _succeeded_run(fresh_session)
    _other_service, other_incident, other_run = _succeeded_run(fresh_session)
    other = _by_title(_other_service, other_incident, other_run)["Primary cause"]
    fresh_session.commit()
    with pytest.raises(HypothesisNotFoundError):
        ConclusionService(fresh_session).finalize(
            incident.id,
            run.id,
            RootCauseConclusionCreate(
                summary="x",
                factors=[CausalFactorCreate(hypothesis_id=other.id, role="failure_mechanism")],
            ),
            PRINCIPAL,
        )


def test_finalize_rejects_duplicate_hypothesis_roles(fresh_session):
    service, incident, run = _succeeded_run(fresh_session)
    hyps = _by_title(service, incident, run)
    target = hyps["Primary cause"]
    _accept(service, incident, run, target)
    fresh_session.commit()
    with pytest.raises(ConclusionValidationError, match="more than one causal role"):
        ConclusionService(fresh_session).finalize(
            incident.id,
            run.id,
            RootCauseConclusionCreate(
                summary="x",
                factors=[
                    CausalFactorCreate(hypothesis_id=target.id, role="failure_mechanism"),
                    CausalFactorCreate(hypothesis_id=target.id, role="trigger"),
                ],
            ),
            PRINCIPAL,
        )


def test_finalize_is_immutable_second_attempt_conflicts(fresh_session):
    service, incident, run = _succeeded_run(fresh_session)
    hyps = _by_title(service, incident, run)
    target = hyps["Primary cause"]
    _accept(service, incident, run, target)
    fresh_session.commit()
    create = RootCauseConclusionCreate(
        summary="first",
        factors=[CausalFactorCreate(hypothesis_id=target.id, role="failure_mechanism")],
    )
    ConclusionService(fresh_session).finalize(incident.id, run.id, create, PRINCIPAL)
    fresh_session.commit()
    with pytest.raises(ConclusionAlreadyFinalizedError):
        ConclusionService(fresh_session).finalize(incident.id, run.id, create, PRINCIPAL)


def test_finalize_rejects_failed_run_even_with_postmortem(fresh_session):
    # Drafting (stage 5) runs before the final audit (stage 6), so a later stage
    # failure can leave a failed run with a Postmortem present. Finalization must
    # still refuse it: the run has not cleared its final trust checkpoint (#26/#33).
    service, incident, run = _succeeded_run(fresh_session)
    hyps = _by_title(service, incident, run)
    target = hyps["Primary cause"]
    _accept(service, incident, run, target)
    run.status = "failed"
    fresh_session.flush()
    fresh_session.commit()
    with pytest.raises(ConclusionNotReadyError):
        ConclusionService(fresh_session).finalize(
            incident.id,
            run.id,
            RootCauseConclusionCreate(
                summary="x",
                factors=[CausalFactorCreate(hypothesis_id=target.id, role="failure_mechanism")],
            ),
            PRINCIPAL,
        )


def test_run_id_is_unique_so_concurrent_finalization_cannot_double(fresh_session):
    # Backstop for the check-then-insert race: even bypassing the service's
    # existence pre-check, the DB rejects a second conclusion for the same run, so
    # two immutable conclusions can never exist for one run (ADR 0039).
    from sqlalchemy.exc import IntegrityError

    from postmortem.models import RootCauseConclusion

    service, incident, run = _succeeded_run(fresh_session)
    hyps = _by_title(service, incident, run)
    target = hyps["Primary cause"]
    _accept(service, incident, run, target)
    fresh_session.commit()
    ConclusionService(fresh_session).finalize(
        incident.id,
        run.id,
        RootCauseConclusionCreate(
            summary="first",
            factors=[CausalFactorCreate(hypothesis_id=target.id, role="failure_mechanism")],
        ),
        PRINCIPAL,
    )
    fresh_session.commit()

    fresh_session.add(
        RootCauseConclusion(
            run_id=run.id,
            summary="racing duplicate",
            finalized_by_principal="reviewer-2",
        )
    )
    with pytest.raises(IntegrityError):
        fresh_session.flush()
    fresh_session.rollback()


def test_finalize_requires_a_drafted_postmortem(fresh_session):
    incident = IncidentService(fresh_session).create(IncidentCreate(title="Bare"))
    ArtifactService(fresh_session).create(
        incident.id, ArtifactCreate(source_type="logs", source_name="a.log", body="x")
    )
    fresh_session.commit()
    # A queued run that never executed has no Postmortem to finalize against.
    from postmortem.models import AnalysisRun

    run = AnalysisRun(
        incident_id=incident.id,
        status="queued",
        pipeline_version="mvp-0",
        prompt_version="none-0",
        model_provider="none",
        retrieval_strategy="d-0",
        chunking_strategy="c-0",
        verifier_version="v-0",
    )
    fresh_session.add(run)
    fresh_session.commit()
    with pytest.raises(ConclusionNotReadyError):
        ConclusionService(fresh_session).finalize(
            incident.id,
            run.id,
            RootCauseConclusionCreate(
                summary="x",
                factors=[CausalFactorCreate(hypothesis_id="nope", role="failure_mechanism")],
            ),
            PRINCIPAL,
        )


def test_get_conclusion_raises_before_finalization(fresh_session):
    service, incident, run = _succeeded_run(fresh_session)
    fresh_session.commit()
    with pytest.raises(ConclusionNotFoundError):
        ConclusionService(fresh_session).get_conclusion(incident.id, run.id)


def _finalize(session, incident, run, hypothesis):
    """Finalize a single-factor conclusion against an accepted, supported hypothesis."""
    return ConclusionService(session).finalize(
        incident.id,
        run.id,
        RootCauseConclusionCreate(
            summary="The deploy regressed connection handling.",
            factors=[CausalFactorCreate(hypothesis_id=hypothesis.id, role="failure_mechanism")],
        ),
        PRINCIPAL,
    )


def _finalized_conclusion(session):
    """Seed a run with one finalized, immutable Root Cause Conclusion."""
    service, incident, run = _succeeded_run(session)
    hyps = _by_title(service, incident, run)
    target = hyps["Primary cause"]
    _accept(service, incident, run, target)
    session.commit()
    conclusion = _finalize(session, incident, run, target)
    session.commit()
    return service, incident, run, conclusion


def test_raise_discrepancy_disputes_without_editing_conclusion(fresh_session):
    # Flagging appends an immutable discrepancy and never edits the conclusion: the
    # conclusion's own fields are untouched and it becomes disputed by derivation
    # (ADR 0040, PRD #26 stories 44-45).
    service, incident, run, conclusion = _finalized_conclusion(fresh_session)
    original_summary = conclusion.summary

    discrepancy = ConclusionService(fresh_session).raise_discrepancy(
        incident.id,
        run.id,
        ConclusionDiscrepancyCreate(explanation="The cited deploy postdates the spike."),
        Principal(id="reviewer-2", display="Reviewer Two"),
    )
    fresh_session.commit()

    assert discrepancy.explanation == "The cited deploy postdates the spike."
    assert discrepancy.raised_by_principal == "reviewer-2"
    assert discrepancy.raised_by_display == "Reviewer Two"

    # The conclusion row is unchanged; disputed state is derived, not stored on it.
    fresh_session.refresh(conclusion)
    assert conclusion.summary == original_summary
    shaped = conclusion_read(conclusion)
    assert shaped["disputed"] is True
    assert shaped["discrepancies"][0]["explanation"] == discrepancy.explanation


def test_disputed_conclusion_returns_review_to_unresolved(fresh_session):
    # A disputed conclusion returns the run to unresolved review: the postmortem
    # read model reports "disputed", no longer "finalized" (PRD #26 story 46).
    service, incident, run, _conclusion = _finalized_conclusion(fresh_session)
    assert service.get_postmortem_document(incident.id, run.id)["conclusion_status"] == "finalized"

    ConclusionService(fresh_session).raise_discrepancy(
        incident.id,
        run.id,
        ConclusionDiscrepancyCreate(explanation="Evidence contradicts the mechanism."),
        PRINCIPAL,
    )
    fresh_session.commit()

    document = service.get_postmortem_document(incident.id, run.id)
    assert document["conclusion_status"] == "disputed"
    assert document["conclusion"]["disputed"] is True


def test_discrepancies_are_append_only_and_accumulate(fresh_session):
    # Append-only history: flagging an already-disputed conclusion adds another
    # discrepancy rather than replacing the first (ADR 0040).
    service, incident, run, conclusion = _finalized_conclusion(fresh_session)
    svc = ConclusionService(fresh_session)
    svc.raise_discrepancy(
        incident.id, run.id, ConclusionDiscrepancyCreate(explanation="First problem."), PRINCIPAL
    )
    fresh_session.commit()
    svc.raise_discrepancy(
        incident.id, run.id, ConclusionDiscrepancyCreate(explanation="Second problem."), PRINCIPAL
    )
    fresh_session.commit()

    fresh_session.refresh(conclusion)
    explanations = [d["explanation"] for d in conclusion_read(conclusion)["discrepancies"]]
    assert explanations == ["First problem.", "Second problem."]


def test_raise_discrepancy_is_idempotent_for_identical_explanation(fresh_session):
    # Append-only + DB-irreversible: a lost-response retry that re-sends the same
    # explanation must not append a permanent duplicate (ADR 0040 retry-safety).
    service, incident, run, conclusion = _finalized_conclusion(fresh_session)
    svc = ConclusionService(fresh_session)
    payload = ConclusionDiscrepancyCreate(explanation="The cited deploy postdates the spike.")

    first = svc.raise_discrepancy(incident.id, run.id, payload, PRINCIPAL)
    fresh_session.commit()
    # A normal retry of the identical command (trailing whitespace differences are
    # normalized away) returns the same row rather than recording a second dispute.
    retry = svc.raise_discrepancy(
        incident.id,
        run.id,
        ConclusionDiscrepancyCreate(explanation="The cited deploy postdates the spike.  "),
        PRINCIPAL,
    )
    fresh_session.commit()

    assert retry.id == first.id
    fresh_session.refresh(conclusion)
    assert len(conclusion_read(conclusion)["discrepancies"]) == 1


def test_raise_discrepancy_requires_a_finalized_conclusion(fresh_session):
    service, incident, run = _succeeded_run(fresh_session)
    fresh_session.commit()
    with pytest.raises(ConclusionNotFoundError):
        ConclusionService(fresh_session).raise_discrepancy(
            incident.id,
            run.id,
            ConclusionDiscrepancyCreate(explanation="Nothing to dispute yet."),
            PRINCIPAL,
        )


def _partial_verifier(*titles):
    """A claim-support verifier that judges the named hypotheses PARTIAL."""
    wanted = set(titles)

    def judge(claim):
        for title in wanted:
            if claim.claim_text.startswith(title):
                return ClaimSupportJudgment(ClaimSupportStatus.PARTIAL, "Partly shown.")
        return ClaimSupportJudgment(ClaimSupportStatus.SUPPORTED, "ok")

    return FakeClaimSupportVerifier(judge)


def test_finalize_requires_partial_support_acknowledgment(fresh_session):
    # A partially supported Causal Factor cannot be finalized without an
    # acknowledgment describing supported and uncertain portions (PRD #26 stories
    # 38-39).
    service, incident, run = _succeeded_run(
        fresh_session, verifier=_partial_verifier("Primary cause")
    )
    hyps = _by_title(service, incident, run)
    target = hyps["Primary cause"]
    assert target.support_status == "partial"
    _accept(service, incident, run, target)
    fresh_session.commit()
    svc = ConclusionService(fresh_session)

    # Missing acknowledgment is rejected.
    with pytest.raises(ConclusionValidationError, match="partial-support acknowledgment"):
        svc.finalize(
            incident.id,
            run.id,
            RootCauseConclusionCreate(
                summary="x",
                factors=[CausalFactorCreate(hypothesis_id=target.id, role="failure_mechanism")],
            ),
            PRINCIPAL,
        )
    fresh_session.rollback()

    # A blank-only acknowledgment is treated as missing.
    _accept(service, incident, run, target)
    with pytest.raises(ConclusionValidationError, match="partial-support acknowledgment"):
        svc.finalize(
            incident.id,
            run.id,
            RootCauseConclusionCreate(
                summary="x",
                factors=[
                    CausalFactorCreate(
                        hypothesis_id=target.id,
                        role="failure_mechanism",
                        partial_support_acknowledgment="   ",
                    )
                ],
            ),
            PRINCIPAL,
        )


def test_finalize_persists_partial_support_acknowledgment(fresh_session):
    service, incident, run = _succeeded_run(
        fresh_session, verifier=_partial_verifier("Primary cause")
    )
    hyps = _by_title(service, incident, run)
    target = hyps["Primary cause"]
    _accept(service, incident, run, target)
    fresh_session.commit()

    conclusion = ConclusionService(fresh_session).finalize(
        incident.id,
        run.id,
        RootCauseConclusionCreate(
            summary="Partly evidenced mechanism.",
            factors=[
                CausalFactorCreate(
                    hypothesis_id=target.id,
                    role="failure_mechanism",
                    partial_support_acknowledgment=(
                        "Logs confirm the pool exhausted; the deploy link is unconfirmed."
                    ),
                )
            ],
        ),
        PRINCIPAL,
    )
    fresh_session.commit()

    shaped = conclusion_read(conclusion)["failure_mechanism"]
    assert shaped["support_status"] == "partial"
    assert "unconfirmed" in shaped["partial_support_acknowledgment"]


def test_supported_factor_does_not_store_acknowledgment(fresh_session):
    # A fully supported factor needs no acknowledgment; any stray text is dropped so
    # the conclusion carries no misleading qualification.
    service, incident, run = _succeeded_run(fresh_session)
    hyps = _by_title(service, incident, run)
    target = hyps["Primary cause"]
    _accept(service, incident, run, target)
    fresh_session.commit()

    conclusion = ConclusionService(fresh_session).finalize(
        incident.id,
        run.id,
        RootCauseConclusionCreate(
            summary="Fully evidenced.",
            factors=[
                CausalFactorCreate(
                    hypothesis_id=target.id,
                    role="failure_mechanism",
                    partial_support_acknowledgment="ignored because support is full",
                )
            ],
        ),
        PRINCIPAL,
    )
    fresh_session.commit()
    assert conclusion_read(conclusion)["failure_mechanism"][
        "partial_support_acknowledgment"
    ] is None


def test_finalize_requires_critical_challenge_override_for_failure_mechanism(fresh_session):
    # A critically challenged hypothesis cannot be the Failure Mechanism without an
    # override addressing the unresolved critical challenge (PRD #26 stories 40-41).
    service, incident, run = _succeeded_run(
        fresh_session, falsifier=FakeFalsifier(severity="critical")
    )
    hyps = _by_title(service, incident, run)
    target = hyps["Primary cause"]
    assert target.challenge.severity == "critical"
    _accept(service, incident, run, target)
    fresh_session.commit()

    with pytest.raises(ConclusionValidationError, match="critical-challenge override"):
        ConclusionService(fresh_session).finalize(
            incident.id,
            run.id,
            RootCauseConclusionCreate(
                summary="x",
                factors=[CausalFactorCreate(hypothesis_id=target.id, role="failure_mechanism")],
            ),
            PRINCIPAL,
        )


def test_finalize_persists_critical_challenge_override_and_preserves_challenge(fresh_session):
    service, incident, run = _succeeded_run(
        fresh_session, falsifier=FakeFalsifier(severity="critical")
    )
    hyps = _by_title(service, incident, run)
    target = hyps["Primary cause"]
    _accept(service, incident, run, target)
    fresh_session.commit()

    conclusion = ConclusionService(fresh_session).finalize(
        incident.id,
        run.id,
        RootCauseConclusionCreate(
            summary="Concluded despite the open critical challenge.",
            factors=[
                CausalFactorCreate(
                    hypothesis_id=target.id,
                    role="failure_mechanism",
                    critical_challenge_override=(
                        "The timing concern is addressed by the rollback log at 14:55."
                    ),
                )
            ],
        ),
        PRINCIPAL,
    )
    fresh_session.commit()

    shaped = conclusion_read(conclusion)["failure_mechanism"]
    # The override is recorded and the actual critical challenge is preserved, never
    # erased: the read model carries the full challenge, not just a severity label, so
    # the override can be audited against the concern it addresses (story 41).
    assert "rollback log" in shaped["critical_challenge_override"]
    assert shaped["challenge"]["severity"] == "critical"
    assert shaped["challenge"]["challenged_claim"] == "Challenge of: Primary cause"


def test_critically_challenged_hypothesis_allowed_as_trigger_without_override(fresh_session):
    # Challenge Severity 'critical' blocks the Failure Mechanism role only; a
    # critically challenged hypothesis may still be a Trigger without an override.
    service, incident, run = _succeeded_run(
        fresh_session,
        titles=("Mechanism", "Initiating event"),
        falsifier=FakeFalsifier(severity="critical"),
    )
    hyps = _by_title(service, incident, run)
    _accept(service, incident, run, *hyps.values())
    fresh_session.commit()

    conclusion = ConclusionService(fresh_session).finalize(
        incident.id,
        run.id,
        RootCauseConclusionCreate(
            summary="Mechanism with a critically challenged trigger.",
            factors=[
                CausalFactorCreate(
                    hypothesis_id=hyps["Mechanism"].id,
                    role="failure_mechanism",
                    critical_challenge_override="Addressed by the rollback log.",
                ),
                CausalFactorCreate(
                    hypothesis_id=hyps["Initiating event"].id, role="trigger"
                ),
            ],
        ),
        PRINCIPAL,
    )
    fresh_session.commit()
    trigger = conclusion_read(conclusion)["triggers"][0]
    assert trigger["critical_challenge_override"] is None
    assert trigger["challenge"]["severity"] == "critical"


def test_finalize_records_human_assumptions_separately(fresh_session):
    # Unevidenced beliefs are stored separately from factors and never become
    # Causal Factors (PRD #26 story 38).
    service, incident, run = _succeeded_run(fresh_session)
    hyps = _by_title(service, incident, run)
    target = hyps["Primary cause"]
    _accept(service, incident, run, target)
    fresh_session.commit()

    conclusion = ConclusionService(fresh_session).finalize(
        incident.id,
        run.id,
        RootCauseConclusionCreate(
            summary="Concluded with one labeled assumption.",
            factors=[CausalFactorCreate(hypothesis_id=target.id, role="failure_mechanism")],
            human_assumptions=[
                "The on-call likely restarted the service manually.",
                "   ",  # blanks are dropped
            ],
        ),
        PRINCIPAL,
    )
    fresh_session.commit()

    shaped = conclusion_read(conclusion)
    assert len(shaped["human_assumptions"]) == 1
    assert shaped["human_assumptions"][0]["statement"].startswith("The on-call")
    # The assumption is not among the evidence-backed factors.
    factor_titles = {shaped["failure_mechanism"]["title"]}
    assert shaped["human_assumptions"][0]["statement"] not in factor_titles


def test_raise_discrepancy_rejects_cross_incident_run(fresh_session):
    # The conclusion belongs to its own run/incident; another incident cannot flag
    # it (cross-incident rejection, AC).
    _service, _incident, _run, _conclusion = _finalized_conclusion(fresh_session)
    other_incident = IncidentService(fresh_session).create(IncidentCreate(title="Other"))
    fresh_session.commit()
    with pytest.raises(AnalysisRunNotFoundError):
        ConclusionService(fresh_session).raise_discrepancy(
            other_incident.id,
            _run.id,
            ConclusionDiscrepancyCreate(explanation="Wrong incident."),
            PRINCIPAL,
        )
