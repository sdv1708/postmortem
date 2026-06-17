from __future__ import annotations

import json

from postmortem.falsification import FalsificationCounterclaim, HypothesisChallengeOutput
from postmortem.llm import FakeLLMClient
from postmortem.models import (
    Counterclaim,
    EvidenceChunk,
    Hypothesis,
    HypothesisChallenge,
    ImpactClaim,
    Postmortem,
    RunStageEvent,
    TimelineEvent,
)
from postmortem.rca import RcaEvidenceRef
from postmortem.schemas import AnalysisRunCreate, ArtifactCreate, IncidentCreate
from postmortem.services import AnalysisService, ArtifactService, IncidentService

from tests._fakes import (
    FakeClaimSupportVerifier,
    FakeFalsifier,
    FakeIncidentFactExtractor,
)


AMBIGUOUS_BODY = (
    "2026-05-09T14:28:31Z deploy v184 rolled out\n"
    "2026-05-09T14:31:10Z db connection pool exhausted\n"
    "2026-05-09T14:32:02Z api 500 rate climbing\n"
    "2026-05-09T14:33:40Z cache node evicted under memory pressure"
)


def _incident(session):
    return IncidentService(session).create(IncidentCreate(title="Ambiguous outage"))


def _add(session, incident_id, body=AMBIGUOUS_BODY, source_name="api.log"):
    return ArtifactService(session).create(
        incident_id,
        ArtifactCreate(source_type="logs", source_name=source_name, body=body),
    )


def _two_hypotheses(artifact_id: str) -> str:
    return json.dumps(
        {
            "hypotheses": [
                {
                    "title": "Deploy v184 regressed connection handling",
                    "summary": "The v184 deploy preceded pool exhaustion and 500s.",
                    "supporting_evidence": [
                        {"artifact_id": artifact_id, "line_start": 1, "line_end": 2}
                    ],
                },
                {
                    "title": "Cache memory pressure cascaded",
                    "summary": "A cache eviction may have driven load onto the DB.",
                    "supporting_evidence": [
                        {"artifact_id": artifact_id, "line_start": 4, "line_end": 4}
                    ],
                },
            ]
        }
    )


def _hypotheses(session, run_id):
    return list(
        session.query(Hypothesis).filter(Hypothesis.run_id == run_id).order_by(Hypothesis.rank)
    )


def _rca_event(session, run_id):
    return (
        session.query(RunStageEvent)
        .filter(
            RunStageEvent.run_id == run_id,
            RunStageEvent.stage == "analyzing_causal_hypotheses",
        )
        .order_by(RunStageEvent.sequence.desc())
        .first()
    )


def test_every_hypothesis_gets_exactly_one_persisted_challenge(fresh_session):
    incident = _incident(fresh_session)
    artifact = _add(fresh_session, incident.id)
    fresh_session.commit()

    # A falsifier that cites a real line so the counterclaim is a verified Major
    # Claim, plus an evidence gap and a falsification test.
    falsifier = FakeFalsifier(
        severity="critical",
        counterclaims=[
            FalsificationCounterclaim(
                statement="The pool was already exhausted before the deploy settled.",
                evidence=[RcaEvidenceRef(artifact_id=artifact.id, line_start=2, line_end=2)],
            )
        ],
        evidence_gaps=["The v183..v184 diff is not in evidence."],
        falsification_tests=["Replay v184 under staging load."],
    )
    run = AnalysisService(
        fresh_session,
        llm_client=FakeLLMClient([_two_hypotheses(artifact.id)]),
        claim_support_verifier=FakeClaimSupportVerifier(),
        incident_fact_extractor=FakeIncidentFactExtractor(),
        falsifier=falsifier,
    ).start_run(incident.id, AnalysisRunCreate())
    fresh_session.commit()

    assert run.status == "succeeded"
    hyps = _hypotheses(fresh_session, run.id)
    assert len(hyps) == 2
    # The falsifier was invoked once per hypothesis (complete coverage).
    assert len(falsifier.calls) == 2

    for hypothesis in hyps:
        challenge = hypothesis.challenge
        assert challenge is not None, "every hypothesis carries exactly one challenge"
        assert challenge.severity == "critical"
        assert challenge.challenged_claim
        assert challenge.evidence_gaps == ["The v183..v184 diff is not in evidence."]
        assert challenge.falsification_tests == ["Replay v184 under staging load."]
        # The counterclaim is a Major Claim with a citation resolved from the
        # stored artifact line (ADR 0024), not the model's text.
        assert len(challenge.counterclaims) == 1
        counter = challenge.counterclaims[0]
        assert counter.assumption is False
        assert len(counter.evidence_refs) == 1
        assert counter.evidence_refs[0].snippet == "2026-05-09T14:31:10Z db connection pool exhausted"
        # Stage 4 audited the counterclaim citation like any other EvidenceRef.
        assert counter.evidence_refs[0].verifier_status == "verified"


def test_uncited_counterclaim_is_normalized_to_an_assumption(fresh_session):
    incident = _incident(fresh_session)
    artifact = _add(fresh_session, incident.id)
    fresh_session.commit()

    falsifier = FakeFalsifier(
        severity="minor",
        counterclaims=[
            FalsificationCounterclaim(statement="A hunch with nothing to cite.", evidence=[])
        ],
    )
    run = AnalysisService(
        fresh_session,
        llm_client=FakeLLMClient([_two_hypotheses(artifact.id)]),
        claim_support_verifier=FakeClaimSupportVerifier(),
        incident_fact_extractor=FakeIncidentFactExtractor(),
        falsifier=falsifier,
    ).start_run(incident.id, AnalysisRunCreate())
    fresh_session.commit()

    assert run.status == "succeeded"
    counter = _hypotheses(fresh_session, run.id)[0].challenge.counterclaims[0]
    # An uncited Counterclaim is an explicit assumption, not an asserted fact
    # (ADR 0013), and is flagged as an uncited claim — but never fails the run.
    assert counter.assumption is True
    assert counter.evidence_refs == []
    assert "uncited_claim" in _rca_event(fresh_session, run.id).warning_codes


def test_falsifier_sees_all_run_artifacts_not_just_the_cited_subset(fresh_session):
    incident = _incident(fresh_session)
    cited = _add(fresh_session, incident.id, body="deploy v184 rolled out", source_name="deploy.log")
    other = _add(
        fresh_session,
        incident.id,
        body="2026-05-09T14:31:10Z unrelated upstream timeout",
        source_name="upstream.log",
    )
    fresh_session.commit()

    builder = json.dumps(
        {
            "hypotheses": [
                {
                    "title": "Deploy regressed handling",
                    "summary": "The deploy did it.",
                    "supporting_evidence": [
                        {"artifact_id": cited.id, "line_start": 1, "line_end": 1}
                    ],
                }
            ]
        }
    )

    seen_artifact_ids: set[str] = set()

    def challenge(hypothesis):
        return HypothesisChallengeOutput(challenged_claim="x", severity="minor")

    class RecordingFalsifier(FakeFalsifier):
        def challenge(self, *, hypothesis, artifacts, timeline_events):
            seen_artifact_ids.update(a.id for a in artifacts)
            return super().challenge(
                hypothesis=hypothesis, artifacts=artifacts, timeline_events=timeline_events
            )

    run = AnalysisService(
        fresh_session,
        llm_client=FakeLLMClient([builder]),
        claim_support_verifier=FakeClaimSupportVerifier(),
        incident_fact_extractor=FakeIncidentFactExtractor(),
        falsifier=RecordingFalsifier(),
    ).start_run(incident.id, AnalysisRunCreate())
    fresh_session.commit()

    assert run.status == "succeeded"
    # The falsifier received every run artifact, including the one the builder
    # never cited, so it can find overlooked counterevidence (PRD user story 13).
    assert seen_artifact_ids == {cited.id, other.id}


def test_missing_challenge_coverage_fails_stage_after_retry(fresh_session):
    incident = _incident(fresh_session)
    artifact = _add(fresh_session, incident.id)
    fresh_session.commit()

    # The falsifier cannot challenge the second hypothesis on any attempt, so the
    # mandatory coverage gate fails stage 3 after its single retry (ADR 0034).
    # Seed the builder twice because stage 3 runs the original attempt + one retry.
    run = AnalysisService(
        fresh_session,
        llm_client=FakeLLMClient([_two_hypotheses(artifact.id), _two_hypotheses(artifact.id)]),
        claim_support_verifier=FakeClaimSupportVerifier(),
        incident_fact_extractor=FakeIncidentFactExtractor(),
        falsifier=FakeFalsifier(raise_for={"Cache memory pressure cascaded"}),
    ).start_run(incident.id, AnalysisRunCreate())
    fresh_session.commit()

    # The run fails and never looks successful (PRD user stories 61-62 / 64).
    assert run.status == "failed"
    event = _rca_event(fresh_session, run.id)
    assert event.status == "failed"
    assert event.attempt == 2
    # No Provisional Postmortem is produced after causal-analysis failure.
    assert fresh_session.query(Postmortem).filter_by(run_id=run.id).count() == 0
    # Prior stage outputs remain intact and inspectable (ADR 0029): the normalize
    # and incident-facts stages persisted before stage 3 failed.
    assert fresh_session.query(EvidenceChunk).filter_by(run_id=run.id).count() >= 1
    assert fresh_session.query(TimelineEvent).filter_by(run_id=run.id).count() == 4


def test_offline_run_with_no_hypotheses_produces_no_challenges(fresh_session):
    incident = _incident(fresh_session)
    _add(fresh_session, incident.id)
    fresh_session.commit()

    # No provider configured: the builder returns no hypotheses, so the falsifier
    # is never invoked and the run still completes (ADR 0034).
    falsifier = FakeFalsifier()
    run = AnalysisService(fresh_session, falsifier=falsifier).start_run(
        incident.id, AnalysisRunCreate()
    )
    fresh_session.commit()

    assert run.status == "succeeded"
    assert _hypotheses(fresh_session, run.id) == []
    assert fresh_session.query(HypothesisChallenge).filter_by(run_id=run.id).count() == 0
    assert fresh_session.query(Counterclaim).count() == 0
    assert falsifier.calls == []


def test_challenges_are_idempotent_across_stage_retry(fresh_session):
    from postmortem.services import StagedRunExecutor
    from postmortem.services.stages import PipelineStageRunner

    incident = _incident(fresh_session)
    artifact = _add(fresh_session, incident.id)
    fresh_session.commit()

    real = PipelineStageRunner(
        fresh_session,
        llm_client=FakeLLMClient([_two_hypotheses(artifact.id), _two_hypotheses(artifact.id)]),
        claim_support_verifier=FakeClaimSupportVerifier(),
        incident_fact_extractor=FakeIncidentFactExtractor(),
        falsifier=FakeFalsifier(
            counterclaims=[
                FalsificationCounterclaim(
                    statement="Pool was already saturated.",
                    evidence=[RcaEvidenceRef(artifact_id=artifact.id, line_start=2, line_end=2)],
                )
            ],
        ),
    )

    def flaky(stage, attempt, run):
        if stage == "analyzing_causal_hypotheses":
            outcome = real(stage, attempt, run)  # persists hypotheses + challenges
            if attempt == 1:
                raise RuntimeError("boom after persisting challenges")
            return outcome
        return real(stage, attempt, run)

    run = AnalysisService(
        fresh_session, executor=StagedRunExecutor(stage_runner=flaky)
    ).start_run(incident.id, AnalysisRunCreate())
    fresh_session.commit()

    assert run.status == "succeeded"
    # The retry cleared the first attempt's hypotheses (cascading their challenges
    # and counterclaims away), so no duplicates remain (ADR 0029 / 0034).
    assert len(_hypotheses(fresh_session, run.id)) == 2
    assert fresh_session.query(HypothesisChallenge).filter_by(run_id=run.id).count() == 2
    assert fresh_session.query(Counterclaim).count() == 2
