from __future__ import annotations

import json

from postmortem.llm import FakeLLMClient
from postmortem.models import EvidenceChunk, Hypothesis, RunStageEvent, TimelineEvent
from postmortem.schemas import AnalysisRunCreate, ArtifactCreate, IncidentCreate
from postmortem.services import AnalysisService, ArtifactService, IncidentService


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


def _hypotheses(session, run_id):
    return list(
        session.query(Hypothesis)
        .filter(Hypothesis.run_id == run_id)
        .order_by(Hypothesis.rank)
    )


def _rca_event(session, run_id):
    return (
        session.query(RunStageEvent)
        .filter(
            RunStageEvent.run_id == run_id,
            RunStageEvent.stage == "generating_rca_hypotheses",
        )
        .order_by(RunStageEvent.sequence.desc())
        .first()
    )


def _two_competing_hypotheses(artifact_id: str) -> str:
    return json.dumps(
        {
            "hypotheses": [
                {
                    "title": "Deploy v184 regressed connection handling",
                    "summary": "The v184 deploy preceded pool exhaustion and 500s.",
                    "supporting_evidence": [
                        {"artifact_id": artifact_id, "line_start": 1, "line_end": 2},
                        {"artifact_id": artifact_id, "line_start": 3, "line_end": 3,
                         "confidence_score": 0.8},
                    ],
                    "contradicting_evidence": [
                        {"artifact_id": artifact_id, "line_start": 4, "line_end": 4}
                    ],
                    "unknowns": ["Whether v184 touched the pool config"],
                    "validation_steps": ["Diff v183..v184 for pool settings"],
                    "impact_claims": [
                        {
                            "description": "API returned 500s to users",
                            "evidence": [
                                {"artifact_id": artifact_id, "line_start": 3, "line_end": 3}
                            ],
                        }
                    ],
                    "remediation_items": [
                        {"description": "Roll back v184", "evidence": []}
                    ],
                },
                {
                    "title": "Cache memory pressure cascaded",
                    "summary": "A cache eviction may have driven load onto the DB.",
                    "supporting_evidence": [
                        {"artifact_id": artifact_id, "line_start": 4, "line_end": 4}
                    ],
                    "contradicting_evidence": [],
                    "unknowns": ["Cache hit-rate before the incident"],
                    "validation_steps": ["Check cache memory metrics at 14:33"],
                    "impact_claims": [],
                    "remediation_items": [],
                },
            ]
        }
    )


def test_ambiguous_evidence_yields_multiple_ranked_hypotheses(fresh_session):
    incident = _incident(fresh_session)
    artifact = _add(fresh_session, incident.id)
    fresh_session.commit()

    fake = FakeLLMClient(
        [_two_competing_hypotheses(artifact.id)],
        label="fake-model",
        usage={"total_tokens": 321},
    )
    run = AnalysisService(fresh_session, llm_client=fake).start_run(
        incident.id, AnalysisRunCreate()
    )
    fresh_session.commit()

    assert run.status == "succeeded"
    hyps = _hypotheses(fresh_session, run.id)
    assert [h.rank for h in hyps] == [1, 2]
    assert [h.title for h in hyps][0].startswith("Deploy v184")

    top = hyps[0]
    # Supporting/contradicting evidence is split by role and resolved to exact
    # snippets from the stored artifact lines (ADR 0024), never the model's text.
    supporting = [r for r in top.evidence_refs if r.role == "supporting"]
    contradicting = [r for r in top.evidence_refs if r.role == "contradicting"]
    assert len(supporting) == 2
    assert len(contradicting) == 1
    # The first ref spans lines 1-2, so its snippet is those two stored lines
    # joined verbatim (citation source of truth, ADR 0024).
    assert supporting[0].snippet == (
        "2026-05-09T14:28:31Z deploy v184 rolled out\n"
        "2026-05-09T14:31:10Z db connection pool exhausted"
    )
    assert contradicting[0].line_start == 4
    assert top.assumption is False

    assert [c.description for c in top.impact_claims] == ["API returned 500s to users"]
    assert top.impact_claims[0].evidence_refs[0].line_start == 3
    assert [a.description for a in top.action_items] == ["Roll back v184"]

    # Usage from the provider is recorded on the stage event (ADR 0021).
    event = _rca_event(fresh_session, run.id)
    assert event.status == "succeeded"
    assert event.usage == {"total_tokens": 321}
    assert fake.calls, "the configured client was actually invoked"


def test_schema_invalid_output_fails_stage_without_corrupting_prior_outputs(fresh_session):
    incident = _incident(fresh_session)
    _add(fresh_session, incident.id)
    fresh_session.commit()

    # Malformed on every attempt (covers the single retry too): the stage must
    # fail rather than persist corrupt output (ADR 0028).
    fake = FakeLLMClient(lambda system, user: "{ not valid json")
    run = AnalysisService(fresh_session, llm_client=fake).start_run(
        incident.id, AnalysisRunCreate()
    )
    fresh_session.commit()

    assert run.status == "failed"
    # No hypotheses leaked into state.
    assert _hypotheses(fresh_session, run.id) == []
    # Prior stages' outputs remain intact and inspectable (ADR 0029): the
    # normalize and timeline stages already persisted before stage 3 failed.
    chunks = fresh_session.query(EvidenceChunk).filter_by(run_id=run.id).all()
    timeline = fresh_session.query(TimelineEvent).filter_by(run_id=run.id).all()
    assert len(chunks) >= 1
    assert len(timeline) == 4
    # The RCA stage event records the failure and a retry was attempted.
    event = _rca_event(fresh_session, run.id)
    assert event.status == "failed"
    assert event.attempt == 2


def test_uncited_hypothesis_normalized_to_assumption_with_warning(fresh_session):
    incident = _incident(fresh_session)
    artifact = _add(fresh_session, incident.id)
    fresh_session.commit()

    uncited = json.dumps(
        {
            "hypotheses": [
                {
                    "title": "Vague suspicion with no citation",
                    "summary": "Something in the deploy caused it, but we cannot cite a line.",
                    "supporting_evidence": [],
                    "impact_claims": [
                        {"description": "Users were affected", "evidence": []}
                    ],
                }
            ]
        }
    )
    fake = FakeLLMClient([uncited])
    run = AnalysisService(fresh_session, llm_client=fake).start_run(
        incident.id, AnalysisRunCreate()
    )
    fresh_session.commit()

    assert run.status == "succeeded"
    hyp = _hypotheses(fresh_session, run.id)[0]
    # An uncited Major Claim is normalized to an assumption rather than asserted
    # as fact (ADR 0013); it does not fail the run.
    assert hyp.assumption is True
    assert hyp.impact_claims[0].assumption is True

    event = _rca_event(fresh_session, run.id)
    assert "uncited_claim" in event.warning_codes
    # Warning codes are deduped even though both the hypothesis and its impact
    # claim were uncited.
    assert event.warning_codes.count("uncited_claim") == 1
    # artifact remains untouched as the citation source of truth.
    assert artifact.body == AMBIGUOUS_BODY


def test_out_of_range_citation_is_dropped(fresh_session):
    incident = _incident(fresh_session)
    artifact = _add(fresh_session, incident.id)
    fresh_session.commit()

    bad_ref = json.dumps(
        {
            "hypotheses": [
                {
                    "title": "Cites a line that does not exist",
                    "summary": "Model hallucinated a citation past the artifact end.",
                    "supporting_evidence": [
                        {"artifact_id": artifact.id, "line_start": 1, "line_end": 1},
                        {"artifact_id": artifact.id, "line_start": 99, "line_end": 99},
                        {"artifact_id": "nonexistent", "line_start": 1, "line_end": 1},
                    ],
                }
            ]
        }
    )
    fake = FakeLLMClient([bad_ref])
    run = AnalysisService(fresh_session, llm_client=fake).start_run(
        incident.id, AnalysisRunCreate()
    )
    fresh_session.commit()

    hyp = _hypotheses(fresh_session, run.id)[0]
    refs = [r for r in hyp.evidence_refs if r.role == "supporting"]
    # Only the in-range, in-run citation survives; the others are dropped so a
    # citation never points outside the locked evidence.
    assert len(refs) == 1
    assert refs[0].line_start == 1
    # It still has one valid citation, so it is not an assumption.
    assert hyp.assumption is False


def test_offline_default_produces_no_hypotheses_but_run_succeeds(fresh_session):
    incident = _incident(fresh_session)
    _add(fresh_session, incident.id)
    fresh_session.commit()

    # No llm_client injected → OfflineLLMClient default returns empty hypotheses.
    run = AnalysisService(fresh_session).start_run(incident.id, AnalysisRunCreate())
    fresh_session.commit()

    assert run.status == "succeeded"
    assert _hypotheses(fresh_session, run.id) == []


def test_rca_generation_is_idempotent_across_retry(fresh_session):
    from postmortem.services import StagedRunExecutor
    from postmortem.services.stages import PipelineStageRunner

    incident = _incident(fresh_session)
    artifact = _add(fresh_session, incident.id)
    fresh_session.commit()

    fake = FakeLLMClient(
        [
            _two_competing_hypotheses(artifact.id),
            _two_competing_hypotheses(artifact.id),
        ]
    )
    real = PipelineStageRunner(fresh_session, llm_client=fake)

    def flaky(stage, attempt, run):
        if stage == "generating_rca_hypotheses":
            outcome = real(stage, attempt, run)  # persists hypotheses
            if attempt == 1:
                raise RuntimeError("boom after persisting hypotheses")
            return outcome
        return real(stage, attempt, run)

    run = AnalysisService(
        fresh_session, executor=StagedRunExecutor(stage_runner=flaky)
    ).start_run(incident.id, AnalysisRunCreate())
    fresh_session.commit()

    assert run.status == "succeeded"
    # The retry cleared the first attempt's hypotheses; no duplicates or rank
    # collisions remain (ADR 0029).
    assert [h.rank for h in _hypotheses(fresh_session, run.id)] == [1, 2]
