from __future__ import annotations

import pytest

from postmortem.db import make_session_factory
from postmortem.models import AnalysisRun, Artifact, RunStageEvent
from postmortem.pipeline import RUN_STAGES
from postmortem.schemas import AnalysisRunCreate, ArtifactCreate, IncidentCreate
from postmortem.services import (
    AnalysisService,
    ArtifactService,
    IncidentService,
    StageFailedError,
    StagedRunExecutor,
    StageRecorder,
)


def _incident_with_artifact(session):
    incident = IncidentService(session).create(IncidentCreate(title="Deploy ambiguity"))
    ArtifactService(session).create(
        incident.id, ArtifactCreate(source_type="logs", source_name="api.log", body="a\nb")
    )
    session.commit()
    return incident


def _events(session, run_id):
    return list(
        session.query(RunStageEvent)
        .filter(RunStageEvent.run_id == run_id)
        .order_by(RunStageEvent.sequence)
    )


def test_default_run_records_six_stages_in_order(fresh_session):
    incident = _incident_with_artifact(fresh_session)
    run = AnalysisService(fresh_session).start_run(incident.id, AnalysisRunCreate())
    fresh_session.commit()

    events = _events(fresh_session, run.id)
    assert [e.stage for e in events] == list(RUN_STAGES)
    assert all(e.status == "succeeded" for e in events)
    assert [e.sequence for e in events] == [1, 2, 3, 4, 5, 6]
    assert all(e.attempt == 1 for e in events)
    assert run.status == "succeeded"


def test_each_stage_persisted_before_the_next_starts(fresh_session):
    incident = _incident_with_artifact(fresh_session)
    snapshots: list[list[str]] = []

    def runner(stage, attempt, run):
        # Observe what is already durable when this stage begins. Each prior
        # stage must already be a succeeded event (ADR 0026).
        prior = _events(fresh_session, run.id)
        snapshots.append([f"{e.stage}:{e.status}" for e in prior])
        return None

    executor = StagedRunExecutor(stage_runner=runner)
    run = AnalysisService(fresh_session, executor=executor).start_run(
        incident.id, AnalysisRunCreate()
    )
    fresh_session.commit()

    # When stage N begins, stages 1..N-1 are persisted as succeeded and stage N
    # is persisted as running.
    assert snapshots[0] == ["normalizing_evidence:running"]
    assert snapshots[1] == [
        "normalizing_evidence:succeeded",
        "extracting_incident_facts:running",
    ]
    assert snapshots[5][0] == "normalizing_evidence:succeeded"
    assert snapshots[5][-1] == "flagging_unsupported_claims:running"
    assert run.status == "succeeded"


def test_commit_progress_makes_stage_transitions_visible_to_other_sessions(fresh_session):
    incident = _incident_with_artifact(fresh_session)
    run = AnalysisService(fresh_session).start_run(
        incident.id, AnalysisRunCreate(), execute_inline=False
    )
    fresh_session.commit()
    observer_factory = make_session_factory(fresh_session.get_bind())
    snapshots: list[tuple[str, list[str]]] = []

    def runner(stage, attempt, run):
        observer = observer_factory()
        try:
            observed_run = observer.get(AnalysisRun, run.id)
            events = _events(observer, run.id)
            snapshots.append(
                (
                    observed_run.status,
                    [f"{event.stage}:{event.status}" for event in events],
                )
            )
        finally:
            observer.close()
        return None

    executor = StagedRunExecutor(stage_runner=runner)
    AnalysisService(fresh_session, executor=executor).execute_run(
        run.id, commit_progress=True
    )
    fresh_session.commit()

    assert snapshots[0] == ("running", ["normalizing_evidence:running"])
    assert snapshots[1] == (
        "running",
        [
            "normalizing_evidence:succeeded",
            "extracting_incident_facts:running",
        ],
    )
    assert snapshots[-1][1][-1] == "flagging_unsupported_claims:running"


def test_stage_retried_once_then_succeeds(fresh_session):
    incident = _incident_with_artifact(fresh_session)

    def runner(stage, attempt, run):
        if stage == "verifying_citations" and attempt == 1:
            raise RuntimeError("flaky verifier")
        return None

    executor = StagedRunExecutor(stage_runner=runner)
    run = AnalysisService(fresh_session, executor=executor).start_run(
        incident.id, AnalysisRunCreate()
    )
    fresh_session.commit()

    events = _events(fresh_session, run.id)
    verifying = [e for e in events if e.stage == "verifying_citations"]
    assert [e.status for e in verifying] == ["failed", "succeeded"]
    assert [e.attempt for e in verifying] == [1, 2]
    # The run completes all six stages despite the one retry.
    assert run.status == "succeeded"
    assert [e.stage for e in events if e.status == "succeeded"] == list(RUN_STAGES)


def test_stage_failing_twice_fails_run_and_preserves_prior_outputs(fresh_session):
    incident = _incident_with_artifact(fresh_session)

    def runner(stage, attempt, run):
        if stage == "analyzing_causal_hypotheses":
            raise RuntimeError("model unavailable")
        return None

    executor = StagedRunExecutor(stage_runner=runner)
    service = AnalysisService(fresh_session, executor=executor)
    run = service.start_run(incident.id, AnalysisRunCreate())
    fresh_session.commit()

    events = _events(fresh_session, run.id)
    stages_seen = [e.stage for e in events]

    # Stages 1-2 succeeded and remain inspectable.
    assert events[0].stage == "normalizing_evidence" and events[0].status == "succeeded"
    assert events[1].stage == "extracting_incident_facts" and events[1].status == "succeeded"
    # The failing stage produced exactly two failed attempts (original + retry).
    rca = [e for e in events if e.stage == "analyzing_causal_hypotheses"]
    assert [e.status for e in rca] == ["failed", "failed"]
    assert [e.attempt for e in rca] == [1, 2]
    # Later stages never ran (ADR 0029).
    assert "verifying_citations" not in stages_seen
    assert "drafting_postmortem" not in stages_seen
    assert "flagging_unsupported_claims" not in stages_seen

    assert run.status == "failed"
    assert "analyzing_causal_hypotheses" in run.error
    # The Artifact lock is preserved through failure (ADR 0018 + 0029).
    artifact = fresh_session.query(Artifact).filter_by(incident_id=incident.id).first()
    assert artifact.included_in_analysis_run is True


def test_stage_warning_codes_and_duration_are_recorded(fresh_session):
    incident = _incident_with_artifact(fresh_session)

    def runner(stage, attempt, run):
        if stage == "flagging_unsupported_claims":
            return {"warning_codes": ["uncited_claim"]}
        return None

    executor = StagedRunExecutor(stage_runner=runner)
    run = AnalysisService(fresh_session, executor=executor).start_run(
        incident.id, AnalysisRunCreate()
    )
    fresh_session.commit()

    events = _events(fresh_session, run.id)
    flagging = next(e for e in events if e.stage == "flagging_unsupported_claims")
    assert flagging.warning_codes == ["uncited_claim"]
    assert all(e.duration_ms is not None and e.duration_ms >= 0 for e in events)
    # Warnings do not fail the run (ADR 0029).
    assert run.status == "succeeded"


def test_stage_recorder_continues_sequence_from_existing_events(fresh_session):
    incident = _incident_with_artifact(fresh_session)
    service = AnalysisService(fresh_session)
    run = service.start_run(incident.id, AnalysisRunCreate())
    fresh_session.commit()

    # A fresh recorder for the same run must not restart numbering at 1.
    recorder = StageRecorder(fresh_session, run)
    event = recorder.begin("normalizing_evidence", attempt=1)
    fresh_session.commit()
    assert event.sequence == len(RUN_STAGES) + 1


def test_stage_runner_returning_non_dict_fails_the_stage(fresh_session):
    # A misbehaving stage runner that returns a non-dict is treated as a stage
    # failure (recorded + retried), not an uncaught crash.
    incident = _incident_with_artifact(fresh_session)

    def runner(stage, attempt, run):
        if stage == "verifying_citations":
            return "not a dict"
        return None

    executor = StagedRunExecutor(stage_runner=runner)
    run = AnalysisService(fresh_session, executor=executor).start_run(
        incident.id, AnalysisRunCreate()
    )
    fresh_session.commit()

    events = _events(fresh_session, run.id)
    verifying = [e for e in events if e.stage == "verifying_citations"]
    assert [e.status for e in verifying] == ["failed", "failed"]
    assert run.status == "failed"
    assert "verifying_citations" in run.error


def test_placeholder_executor_records_no_stages(fresh_session):
    from postmortem.services import PlaceholderRunExecutor

    incident = _incident_with_artifact(fresh_session)
    run = AnalysisService(fresh_session, executor=PlaceholderRunExecutor()).start_run(
        incident.id, AnalysisRunCreate()
    )
    fresh_session.commit()

    assert _events(fresh_session, run.id) == []
    assert run.status == "succeeded"


def test_staged_executor_raises_typed_stage_failed_error(fresh_session):
    incident = _incident_with_artifact(fresh_session)
    run = AnalysisService(fresh_session).start_run(incident.id, AnalysisRunCreate())
    fresh_session.commit()

    def runner(stage, attempt, run):
        raise RuntimeError("always down")

    # Drive the executor directly to assert the typed error contract the
    # service relies on (ADR 0029).
    recorder = StageRecorder(fresh_session, run)
    with pytest.raises(StageFailedError) as excinfo:
        StagedRunExecutor(stage_runner=runner).execute(run, recorder)
    assert excinfo.value.stage == "normalizing_evidence"
    assert "always down" in excinfo.value.error
