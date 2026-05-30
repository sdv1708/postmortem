from __future__ import annotations

from datetime import datetime, timezone

from postmortem.models import TimelineEvent
from postmortem.schemas import AnalysisRunCreate, ArtifactCreate, IncidentCreate
from postmortem.services import AnalysisService, ArtifactService, IncidentService


def _incident(session):
    return IncidentService(session).create(IncidentCreate(title="Deploy ambiguity"))


def _add(session, incident_id, source_type, source_name, body):
    return ArtifactService(session).create(
        incident_id, ArtifactCreate(source_type=source_type, source_name=source_name, body=body)
    )


def _timeline(session, run_id):
    return list(
        session.query(TimelineEvent)
        .filter(TimelineEvent.run_id == run_id)
        .order_by(TimelineEvent.sequence)
    )


def _utc(value: datetime | None) -> datetime | None:
    # normalized_ts is stored naive UTC and may load naive (SQLite) or aware
    # (Postgres); compare as UTC instants regardless of backend.
    if value is None or value.tzinfo is not None:
        return value
    return value.replace(tzinfo=timezone.utc)


def test_timeline_events_built_from_timestamped_lines_with_citations(fresh_session):
    incident = _incident(fresh_session)
    artifact = _add(
        fresh_session,
        incident.id,
        "logs",
        "api.log",
        "2026-05-09T14:28:31Z deploy v184 rolled out\n"
        "noise line without a time\n"
        "2026-05-09T14:32:02Z api 500 rate climbing",
    )
    fresh_session.commit()

    run = AnalysisService(fresh_session).start_run(incident.id, AnalysisRunCreate())
    fresh_session.commit()

    events = _timeline(fresh_session, run.id)
    assert len(events) == 2
    # Chronological order, normalized to UTC and stored naive (backend-uniform).
    assert _utc(events[0].normalized_ts) == datetime(2026, 5, 9, 14, 28, 31, tzinfo=timezone.utc)
    assert _utc(events[1].normalized_ts) == datetime(2026, 5, 9, 14, 32, 2, tzinfo=timezone.utc)
    assert events[0].uncertain is False

    # Each event cites the exact artifact line, and the snippet matches the
    # stored line (citation source of truth, ADR 0024).
    ref = events[0].evidence_refs[0]
    assert ref.artifact_id == artifact.id
    assert ref.source_name == "api.log"
    assert ref.line_start == ref.line_end == 1
    assert ref.snippet == "2026-05-09T14:28:31Z deploy v184 rolled out"
    # The noise line (line 2) is never cited.
    assert events[1].evidence_refs[0].line_start == 3


def test_normalized_events_sort_before_inferred_ones(fresh_session):
    incident = _incident(fresh_session)
    _add(
        fresh_session,
        incident.id,
        "incident_notes",
        "notes.md",
        "14:40 noticed the dashboards were red\n"
        "2026-05-09T14:28:31Z deploy v184 rolled out",
    )
    fresh_session.commit()

    run = AnalysisService(fresh_session).start_run(incident.id, AnalysisRunCreate())
    fresh_session.commit()

    events = _timeline(fresh_session, run.id)
    assert len(events) == 2
    # The dated line sorts first even though it appears second in the source.
    assert events[0].normalized_ts is not None
    assert events[0].uncertain is False
    # The time-only line is inferred/uncertain and sorts after dated events.
    assert events[1].normalized_ts is None
    assert events[1].uncertain is True
    assert events[1].original_ts_text == "14:40"


def test_timeline_extraction_is_idempotent_across_retry(fresh_session):
    # Regression: a timeline stage that fails after writing events, then
    # succeeds on its one retry (ADR 0029), must not duplicate events.
    from postmortem.services import StagedRunExecutor
    from postmortem.services.stages import PipelineStageRunner

    incident = _incident(fresh_session)
    _add(
        fresh_session,
        incident.id,
        "logs",
        "api.log",
        "2026-05-09T14:28:31Z one\n2026-05-09T14:32:02Z two",
    )
    fresh_session.commit()

    real = PipelineStageRunner(fresh_session)

    def flaky(stage, attempt, run):
        if stage == "extracting_timeline_candidates":
            outcome = real(stage, attempt, run)  # writes the events
            if attempt == 1:
                raise RuntimeError("boom after partial write")
            return outcome
        return real(stage, attempt, run)

    run = AnalysisService(fresh_session, executor=StagedRunExecutor(stage_runner=flaky)).start_run(
        incident.id, AnalysisRunCreate()
    )
    fresh_session.commit()

    events = _timeline(fresh_session, run.id)
    assert run.status == "succeeded"
    assert [e.sequence for e in events] == [1, 2]  # no duplicates from the retry


def test_run_without_timestamped_evidence_has_empty_timeline_but_succeeds(fresh_session):
    incident = _incident(fresh_session)
    _add(fresh_session, incident.id, "incident_notes", "notes.md", "no times here\njust prose")
    fresh_session.commit()

    run = AnalysisService(fresh_session).start_run(incident.id, AnalysisRunCreate())
    fresh_session.commit()

    assert run.status == "succeeded"
    assert _timeline(fresh_session, run.id) == []


def test_evidence_ref_snippet_matches_artifact_line_exactly(fresh_session):
    incident = _incident(fresh_session)
    artifact = _add(
        fresh_session,
        incident.id,
        "logs",
        "api.log",
        "prelude\n2026-05-09T14:32:02Z   spike with trailing spaces   ",
    )
    fresh_session.commit()

    run = AnalysisService(fresh_session).start_run(incident.id, AnalysisRunCreate())
    fresh_session.commit()

    event = _timeline(fresh_session, run.id)[0]
    ref = event.evidence_refs[0]
    artifact_lines = artifact.body.split("\n")
    # The snippet is byte-for-byte the cited artifact line.
    assert ref.snippet == artifact_lines[ref.line_start - 1]


def test_list_timeline_service_orders_by_sequence(fresh_session):
    incident = _incident(fresh_session)
    _add(
        fresh_session,
        incident.id,
        "logs",
        "api.log",
        "2026-05-09T14:32:02Z later\n2026-05-09T14:28:31Z earlier",
    )
    fresh_session.commit()

    service = AnalysisService(fresh_session)
    run = service.start_run(incident.id, AnalysisRunCreate())
    fresh_session.commit()

    events = service.list_timeline(incident.id, run.id)
    assert [e.sequence for e in events] == [1, 2]
    assert events[0].normalized_ts < events[1].normalized_ts
