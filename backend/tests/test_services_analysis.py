from __future__ import annotations

import pytest

from postmortem.models import Artifact
from postmortem.schemas import AnalysisRunCreate, ArtifactCreate, IncidentCreate
from postmortem.services import (
    AnalysisService,
    ArtifactLockedError,
    ArtifactService,
    IncidentService,
    NoArtifactsError,
    run_artifact_ids,
)
from postmortem.services.artifacts import ArtifactNotFoundError


def _incident_with_artifact(session, body: str = "14:28 deploy\n14:32 500s spike"):
    incident = IncidentService(session).create(IncidentCreate(title="Deploy ambiguity"))
    artifact = ArtifactService(session).create(
        incident.id, ArtifactCreate(source_type="logs", source_name="api.log", body=body)
    )
    session.commit()
    return incident, artifact


def test_start_run_locks_included_artifacts(fresh_session):
    incident, artifact = _incident_with_artifact(fresh_session)

    run = AnalysisService(fresh_session).start_run(incident.id, AnalysisRunCreate())
    fresh_session.commit()

    assert run.status == "succeeded"
    assert run_artifact_ids(run) == [artifact.id]
    assert fresh_session.get(Artifact, artifact.id).included_in_analysis_run is True


def test_start_run_persists_experiment_metadata_defaults(fresh_session):
    incident, _ = _incident_with_artifact(fresh_session)

    run = AnalysisService(fresh_session).start_run(incident.id, AnalysisRunCreate())
    fresh_session.commit()

    assert run.pipeline_version == "mvp-0"
    assert run.retrieval_strategy == "deterministic-0"
    # Slice 5 wired a real Chunking Strategy; the run records its version.
    assert run.chunking_strategy == "source-aware-1"


def test_locked_artifact_cannot_be_deleted_or_replaced(fresh_session):
    incident, artifact = _incident_with_artifact(fresh_session)
    AnalysisService(fresh_session).start_run(incident.id, AnalysisRunCreate())
    fresh_session.commit()

    artifacts = ArtifactService(fresh_session)
    with pytest.raises(ArtifactLockedError):
        artifacts.delete(incident.id, artifact.id)
    from postmortem.schemas import ArtifactReplace

    with pytest.raises(ArtifactLockedError):
        artifacts.replace(incident.id, artifact.id, ArtifactReplace(body="tampered"))


def test_locked_artifact_body_is_unchanged_source_of_truth(fresh_session):
    original = "14:28 deploy\n14:32 500s spike"
    incident, artifact = _incident_with_artifact(fresh_session, body=original)
    AnalysisService(fresh_session).start_run(incident.id, AnalysisRunCreate())
    fresh_session.commit()

    # Correction requires a new Artifact + new run, not mutation (ADR 0018).
    correction = ArtifactService(fresh_session).create(
        incident.id,
        ArtifactCreate(source_type="logs", source_name="api.log", body="corrected line"),
    )
    fresh_session.commit()

    assert fresh_session.get(Artifact, artifact.id).body == original
    assert correction.id != artifact.id
    assert correction.included_in_analysis_run is False


def test_start_run_with_explicit_subset(fresh_session):
    incident = IncidentService(fresh_session).create(IncidentCreate(title="Subset"))
    a = ArtifactService(fresh_session).create(
        incident.id, ArtifactCreate(source_type="logs", source_name="a.log", body="a")
    )
    b = ArtifactService(fresh_session).create(
        incident.id, ArtifactCreate(source_type="logs", source_name="b.log", body="b")
    )
    fresh_session.commit()

    run = AnalysisService(fresh_session).start_run(
        incident.id, AnalysisRunCreate(artifact_ids=[a.id])
    )
    fresh_session.commit()

    assert run_artifact_ids(run) == [a.id]
    assert fresh_session.get(Artifact, a.id).included_in_analysis_run is True
    assert fresh_session.get(Artifact, b.id).included_in_analysis_run is False


def test_start_run_without_artifacts_raises(fresh_session):
    incident = IncidentService(fresh_session).create(IncidentCreate(title="No evidence"))
    fresh_session.commit()

    with pytest.raises(NoArtifactsError):
        AnalysisService(fresh_session).start_run(incident.id, AnalysisRunCreate())


def test_start_run_with_foreign_artifact_raises(fresh_session):
    incident, _ = _incident_with_artifact(fresh_session)
    other = IncidentService(fresh_session).create(IncidentCreate(title="Other"))
    foreign = ArtifactService(fresh_session).create(
        other.id, ArtifactCreate(source_type="logs", source_name="x.log", body="x")
    )
    fresh_session.commit()

    with pytest.raises(ArtifactNotFoundError):
        AnalysisService(fresh_session).start_run(
            incident.id, AnalysisRunCreate(artifact_ids=[foreign.id])
        )


def test_failed_executor_marks_run_failed_but_keeps_lock(fresh_session):
    incident, artifact = _incident_with_artifact(fresh_session)

    class BoomExecutor:
        def execute(self, run, recorder):
            raise RuntimeError("stage exploded")

    run = AnalysisService(fresh_session, executor=BoomExecutor()).start_run(
        incident.id, AnalysisRunCreate()
    )
    fresh_session.commit()

    assert run.status == "failed"
    assert run.error == "stage exploded"
    assert run.completed_at is not None
    # Prior state preserved: the artifact stays locked (ADR 0029 + 0018).
    assert fresh_session.get(Artifact, artifact.id).included_in_analysis_run is True
    assert run_artifact_ids(run) == [artifact.id]


def test_fake_executor_runs_and_can_inspect_locked_run(fresh_session):
    incident, _ = _incident_with_artifact(fresh_session)
    seen = {}

    class RecordingExecutor:
        def execute(self, run, recorder):
            seen["status_during"] = run.status
            seen["artifact_count"] = len(run.run_artifacts)

    run = AnalysisService(fresh_session, executor=RecordingExecutor()).start_run(
        incident.id, AnalysisRunCreate()
    )
    fresh_session.commit()

    assert seen == {"status_during": "running", "artifact_count": 1}
    assert run.status == "succeeded"


def test_list_runs_orders_newest_first(fresh_session):
    incident, _ = _incident_with_artifact(fresh_session)
    service = AnalysisService(fresh_session)
    first = service.start_run(incident.id, AnalysisRunCreate())
    second = service.start_run(incident.id, AnalysisRunCreate())
    fresh_session.commit()

    runs = service.list_runs(incident.id)
    assert [r.id for r in runs][:2] == [second.id, first.id]
