"""Bounded Causal Analysis Stage: budgets, gates, and Targeted Repair (ADR 0043).

These drive the deep stage through the real ``AnalysisService`` with deterministic
fake Reasoning Roles to exercise issue #37's acceptance criteria end to end:

* a failed role is repaired exactly once and a successful repair lets the run
  succeed, without rerunning the roles that already succeeded;
* an unrepairable role or an exhausted Reasoning Budget fails stage 3 with a
  controlled code and a named substep;
* a failed stage preserves the inspectable prior substep outputs, produces no
  Provisional Postmortem, and never degrades to a successful builder-only run.
"""

from __future__ import annotations

import json

from postmortem.falsification import LLMFalsifier
from postmortem.models import Hypothesis, Postmortem, EvidenceChunk, TimelineEvent
from postmortem.ranking import (
    AdvisoryRankingOutput,
    DeterministicAdvisoryRanker,
    RankedCandidate,
    RankingCandidate,
    RankingRationale,
)
from postmortem.llm import FakeLLMClient
from postmortem.reasoning import ReasoningBudget
from postmortem.schemas import AnalysisRunCreate, ArtifactCreate, IncidentCreate
from postmortem.services import AnalysisService, ArtifactService, IncidentService

from tests._fakes import FakeClaimSupportVerifier, FakeFalsifier, FakeIncidentFactExtractor


def _one_hypothesis(artifact_id: str) -> str:
    return json.dumps(
        {
            "hypotheses": [
                {
                    "title": "Solo",
                    "summary": "The single suspected cause.",
                    "supporting_evidence": [
                        {"artifact_id": artifact_id, "line_start": 1, "line_end": 2}
                    ],
                }
            ]
        }
    )


def _challenge_json() -> str:
    return json.dumps(
        {
            "challenged_claim": "The deploy is not clearly the cause.",
            "severity": "material",
            "counterclaims": [],
            "evidence_gaps": [],
            "falsification_tests": [],
            "proposed_hypotheses": [],
        }
    )


def _support_json() -> str:
    return json.dumps({"status": "supported", "rationale": "The cited lines support it."})


BODY = (
    "2026-05-09T14:28:31Z deploy v184 rolled out\n"
    "2026-05-09T14:31:10Z db connection pool exhausted\n"
    "2026-05-09T14:32:02Z api 500 rate climbing\n"
    "2026-05-09T14:33:40Z cache node evicted under memory pressure"
)


def _incident(session):
    return IncidentService(session).create(IncidentCreate(title="Ambiguous outage"))


def _add(session, incident_id):
    return ArtifactService(session).create(
        incident_id,
        ArtifactCreate(source_type="logs", source_name="api.log", body=BODY),
    )


def _two_hypotheses(artifact_id: str) -> str:
    return json.dumps(
        {
            "hypotheses": [
                {
                    "title": "Alpha",
                    "summary": "Cause alpha.",
                    "supporting_evidence": [
                        {"artifact_id": artifact_id, "line_start": 1, "line_end": 2}
                    ],
                },
                {
                    "title": "Beta",
                    "summary": "Cause beta.",
                    "supporting_evidence": [
                        {"artifact_id": artifact_id, "line_start": 3, "line_end": 4}
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
    from postmortem.models import RunStageEvent

    return (
        session.query(RunStageEvent)
        .filter(
            RunStageEvent.run_id == run_id,
            RunStageEvent.stage == "analyzing_causal_hypotheses",
        )
        .order_by(RunStageEvent.sequence.desc())
        .first()
    )


def _service(session, *, llm, falsifier=None, ranker=None, budget=None):
    return AnalysisService(
        session,
        llm_client=llm,
        claim_support_verifier=FakeClaimSupportVerifier(),
        incident_fact_extractor=FakeIncidentFactExtractor(),
        falsifier=falsifier or FakeFalsifier(),
        advisory_ranker=ranker,
        reasoning_budget=budget,
    )


class _RepairOnceRanker:
    """A ranker that drops a candidate on its first call, then ranks fully.

    Models a mechanically invalid ranking that a single Targeted Repair fixes: the
    first output fails the ranking-coverage gate, the repair output covers every
    candidate (ADR 0043).
    """

    version = "repair-once-ranker-0"

    def __init__(self) -> None:
        self.calls = 0

    def rank(
        self,
        candidates: list[RankingCandidate],
        *,
        repair_feedback: tuple[str, ...] = (),
    ) -> AdvisoryRankingOutput:
        self.calls += 1
        self.last_repair_feedback = repair_feedback
        kept = list(candidates)
        if self.calls == 1:
            kept = kept[:-1]  # drop the last candidate → coverage gate fails
        ranked = DeterministicAdvisoryRanker().rank(kept)
        by_id = {c.hypothesis_id: c for c in kept}
        return AdvisoryRankingOutput(
            rankings=[
                RankedCandidate(
                    hypothesis_id=entry.hypothesis_id,
                    rationale=_rationale(by_id[entry.hypothesis_id]),
                )
                for entry in ranked.rankings
            ]
        )


def _rationale(candidate: RankingCandidate) -> RankingRationale:
    return RankingRationale(
        support_strength="s",
        counterevidence_severity="c",
        explanatory_coverage="e",
        evidence_gaps="g",
        assumption_dependence="a",
        summary=f"Ranked {candidate.title}.",
    )


# --- Successful repair ------------------------------------------------------


def test_builder_schema_failure_is_repaired_once_and_run_succeeds(fresh_session):
    incident = _incident(fresh_session)
    artifact = _add(fresh_session, incident.id)
    fresh_session.commit()

    # The builder returns malformed JSON first (schema gate fails), then valid output
    # on its single Targeted Repair — so the run succeeds without rerunning any other
    # role (AC #3 / #6).
    run = _service(
        fresh_session,
        llm=FakeLLMClient(["{ not valid json", _two_hypotheses(artifact.id)]),
    ).start_run(incident.id, AnalysisRunCreate())
    fresh_session.commit()

    assert run.status == "succeeded"
    assert run.failure_code is None
    assert [h.title for h in _hypotheses(fresh_session, run.id)] == ["Alpha", "Beta"]
    # The recorded budget shows exactly one builder repair was spent.
    snapshot = _rca_event(fresh_session, run.id).usage["reasoning_budget"]
    assert snapshot["roles"]["builder"]["calls"] == 1
    assert snapshot["roles"]["builder"]["repair_calls"] == 1


def test_ranking_coverage_failure_is_repaired_once_and_run_succeeds(fresh_session):
    incident = _incident(fresh_session)
    artifact = _add(fresh_session, incident.id)
    fresh_session.commit()

    ranker = _RepairOnceRanker()
    run = _service(
        fresh_session,
        llm=FakeLLMClient([_two_hypotheses(artifact.id)]),
        ranker=ranker,
    ).start_run(incident.id, AnalysisRunCreate())
    fresh_session.commit()

    assert run.status == "succeeded"
    # The ranker was invoked twice (original + one repair); the builder and falsifier
    # were not re-run, so their single outputs stand.
    assert ranker.calls == 2
    ranks = [h.advisory_rank for h in _hypotheses(fresh_session, run.id)]
    assert sorted(ranks) == [1, 2]
    snapshot = _rca_event(fresh_session, run.id).usage["reasoning_budget"]
    assert snapshot["roles"]["ranker"]["repair_calls"] == 1


def test_falsifier_repair_is_informed_by_the_gate_errors(fresh_session):
    incident = _incident(fresh_session)
    artifact = _add(fresh_session, incident.id)
    fresh_session.commit()

    # A real LLMFalsifier (sharing the recorded client) returns malformed output on
    # its first challenge, then valid output on its single Targeted Repair. The
    # repair must be *informed* — the second falsifier prompt carries the gate's
    # deterministic validation errors, not a blind replay of the first (issue #37 /
    # ADR 0043). Responses: builder, falsifier-attempt-1 (bad), falsifier-repair (good).
    client = FakeLLMClient(
        [_one_hypothesis(artifact.id), "{ not valid json", _challenge_json()]
    )
    run = AnalysisService(
        fresh_session,
        llm_client=client,
        claim_support_verifier=FakeClaimSupportVerifier(),
        incident_fact_extractor=FakeIncidentFactExtractor(),
        falsifier=LLMFalsifier(client),
        reasoning_budget=None,
    ).start_run(incident.id, AnalysisRunCreate())
    fresh_session.commit()

    assert run.status == "succeeded"
    # calls: 0 = builder, 1 = falsifier first attempt, 2 = falsifier informed repair.
    assert len(client.calls) >= 3
    first_challenge_prompt = client.calls[1][1]
    repair_prompt = client.calls[2][1]
    assert "rejected by a deterministic validation gate" not in first_challenge_prompt
    assert "rejected by a deterministic validation gate" in repair_prompt
    # The specific gate error that caused the repair is fed back to the role.
    assert "could not challenge hypothesis" in repair_prompt


# --- Failed repair ----------------------------------------------------------


def test_unrepairable_falsifier_fails_stage_and_preserves_outputs(fresh_session):
    incident = _incident(fresh_session)
    artifact = _add(fresh_session, incident.id)
    fresh_session.commit()

    # The falsifier can never challenge Beta, so its one Targeted Repair cannot
    # complete coverage: the stage fails with a controlled code (AC #4).
    run = _service(
        fresh_session,
        llm=FakeLLMClient([_two_hypotheses(artifact.id)]),
        falsifier=FakeFalsifier(raise_for={"Beta"}),
    ).start_run(incident.id, AnalysisRunCreate())
    fresh_session.commit()

    assert run.status == "failed"
    assert run.failure_code == "repair_exhausted"
    assert run.failed_substep.startswith("challenge:initial:")
    # No Provisional Postmortem after a causal-analysis failure (AC #4).
    assert fresh_session.query(Postmortem).filter_by(run_id=run.id).count() == 0
    # Prior substep outputs remain inspectable: chunks, timeline, and the builder's
    # hypotheses persisted before the falsifier failed.
    assert fresh_session.query(EvidenceChunk).filter_by(run_id=run.id).count() >= 1
    assert fresh_session.query(TimelineEvent).filter_by(run_id=run.id).count() == 4
    assert len(_hypotheses(fresh_session, run.id)) == 2
    # Terminal failure: the stage is not re-attempted (ADR 0043).
    assert _rca_event(fresh_session, run.id).attempt == 1


# --- Budget exhaustion ------------------------------------------------------


def test_total_call_budget_exhaustion_fails_stage_without_builder_only_success(
    fresh_session,
):
    incident = _incident(fresh_session)
    artifact = _add(fresh_session, incident.id)
    fresh_session.commit()

    # A total-call budget of one lets the builder run, then the first falsifier
    # challenge exceeds the stage budget. The run must fail — it must never present a
    # successful builder-only result with the falsification round skipped (AC #4/#6).
    run = _service(
        fresh_session,
        llm=FakeLLMClient([_two_hypotheses(artifact.id)]),
        budget=ReasoningBudget(max_total_calls=1),
    ).start_run(incident.id, AnalysisRunCreate())
    fresh_session.commit()

    assert run.status == "failed"
    assert run.failure_code == "budget_exhausted"
    assert run.failed_substep.startswith("challenge:initial:")
    assert fresh_session.query(Postmortem).filter_by(run_id=run.id).count() == 0
    # The builder's hypotheses persisted before the budget ran out, but no challenge
    # did, so the run is not a degraded builder-only success.
    assert len(_hypotheses(fresh_session, run.id)) == 2


def test_support_verifier_token_budget_is_enforced(fresh_session):
    incident = _incident(fresh_session)
    artifact = _add(fresh_session, incident.id)
    fresh_session.commit()

    # The default (recorded) support verifier makes a real model call per hypothesis.
    # With two hypotheses at 100 input tokens each and a per-role input budget of 150,
    # the builder (1 call) stays under budget but the support verifier's second call
    # crosses it — proving token budgets are enforced across support verification, not
    # just the builder (issue #37 / ADR 0043). Responses: builder, then one support
    # judgment per hypothesis.
    client = FakeLLMClient(
        [_two_hypotheses(artifact.id), _support_json(), _support_json()],
        usage={"prompt_tokens": 100},
    )
    run = AnalysisService(
        fresh_session,
        llm_client=client,
        # Do NOT inject a fake support verifier: the default LLMClaimSupportVerifier
        # funnels through the recorded client so its token usage is observed.
        incident_fact_extractor=FakeIncidentFactExtractor(),
        falsifier=FakeFalsifier(),
        reasoning_budget=ReasoningBudget(max_input_tokens_per_role=150),
    ).start_run(incident.id, AnalysisRunCreate())
    fresh_session.commit()

    assert run.status == "failed"
    assert run.failure_code == "budget_exhausted"
    assert run.failed_substep.startswith("support:")
    assert fresh_session.query(Postmortem).filter_by(run_id=run.id).count() == 0


def test_zero_builder_call_budget_fails_at_builder_substep(fresh_session):
    incident = _incident(fresh_session)
    artifact = _add(fresh_session, incident.id)
    fresh_session.commit()

    run = _service(
        fresh_session,
        llm=FakeLLMClient([_two_hypotheses(artifact.id)]),
        budget=ReasoningBudget(max_calls_per_role=0),
    ).start_run(incident.id, AnalysisRunCreate())
    fresh_session.commit()

    assert run.status == "failed"
    assert run.failure_code == "budget_exhausted"
    assert run.failed_substep == "builder:generate"
    # The gate fired before the builder persisted anything.
    assert _hypotheses(fresh_session, run.id) == []


# --- Recorded budget on success ---------------------------------------------


def test_recorded_budget_is_exposed_in_experiment_metadata(fresh_session):
    incident = _incident(fresh_session)
    artifact = _add(fresh_session, incident.id)
    fresh_session.commit()

    budget = ReasoningBudget(max_calls_per_role=9)
    run = _service(
        fresh_session,
        llm=FakeLLMClient([_two_hypotheses(artifact.id)]),
        budget=budget,
    ).start_run(incident.id, AnalysisRunCreate())
    fresh_session.commit()

    assert run.status == "succeeded"
    # The budget the stage ran under is recorded as comparable Experiment Metadata.
    assert run.reasoning_budget["max_calls_per_role"] == 9
    assert run.reasoning_budget["repair_calls_per_role"] == 1
