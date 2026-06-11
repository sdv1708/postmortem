from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Callable, Protocol

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..logging import log_event
from ..models import AnalysisRun, RunStageEvent
from ..pipeline import RUN_STAGES


logger = logging.getLogger("postmortem.pipeline")


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class StageFailedError(RuntimeError):
    """Raised by an executor when a stage exhausts its single retry (ADR 0029)."""

    def __init__(self, stage: str, error: str) -> None:
        self.stage = stage
        self.error = error
        super().__init__(f"stage '{stage}' failed: {error}")


class StageRecorder:
    """Persists Run Stage Events for one run (ADR 0021).

    The recorder owns the session write for stage events so the executor stays
    free of transaction concerns while the AnalysisService keeps the session
    boundary (ADR 0004). Each event is flushed as it is created or updated so
    callers sharing the transaction can observe stage order. HTTP pollers see
    progress when execution runs outside the POST request and commits through
    its own session.
    """

    def __init__(
        self, session: Session, run: AnalysisRun, *, commit_on_change: bool = False
    ) -> None:
        self._session = session
        self._run = run
        self._commit_on_change = commit_on_change
        existing = session.scalar(
            select(func.count())
            .select_from(RunStageEvent)
            .where(RunStageEvent.run_id == run.id)
        )
        self._sequence = int(existing or 0)

    def begin(self, stage: str, attempt: int) -> RunStageEvent:
        self._sequence += 1
        log_event(
            logger,
            logging.INFO,
            "pipeline_stage_started",
            run_id=self._run.id,
            incident_id=self._run.incident_id,
            stage=stage,
            attempt=attempt,
            sequence=self._sequence,
        )
        event = RunStageEvent(
            run_id=self._run.id,
            sequence=self._sequence,
            stage=stage,
            status="running",
            attempt=attempt,
            started_at=_utcnow(),
            warning_codes=[],
        )
        self._session.add(event)
        self._persist()
        return event

    def succeed(
        self,
        event: RunStageEvent,
        warning_codes: list[str] | None = None,
        usage: dict | None = None,
    ) -> None:
        event.status = "succeeded"
        event.completed_at = _utcnow()
        event.duration_ms = _elapsed_ms(event.started_at, event.completed_at)
        event.warning_codes = warning_codes or []
        event.usage = usage
        self._persist()
        log_event(
            logger,
            logging.INFO,
            "pipeline_stage_succeeded",
            run_id=self._run.id,
            incident_id=self._run.incident_id,
            stage=event.stage,
            attempt=event.attempt,
            duration_ms=event.duration_ms,
            warning_codes=",".join(event.warning_codes) if event.warning_codes else None,
            usage_keys=",".join(sorted(usage.keys())) if usage else None,
        )

    def fail(self, event: RunStageEvent, error: str) -> None:
        event.status = "failed"
        event.completed_at = _utcnow()
        event.duration_ms = _elapsed_ms(event.started_at, event.completed_at)
        event.error = error
        self._persist()
        log_event(
            logger,
            logging.WARNING,
            "pipeline_stage_failed",
            run_id=self._run.id,
            incident_id=self._run.incident_id,
            stage=event.stage,
            attempt=event.attempt,
            duration_ms=event.duration_ms,
            error=error,
        )

    def _persist(self) -> None:
        self._session.flush()
        if self._commit_on_change:
            self._session.commit()


def _elapsed_ms(start: datetime | None, end: datetime | None) -> int | None:
    if start is None or end is None:
        return None
    return max(0, int((end - start).total_seconds() * 1000))


# A stage's work. Returns optional {"warning_codes": [...], "usage": {...}};
# raising signals stage failure. `attempt` lets a runner behave differently on
# the retry, which the tests use to exercise the single-retry path (ADR 0029).
StageRunner = Callable[[str, int, AnalysisRun], dict | None]


def _normalize_outcome(result: object) -> dict:
    """Coerce a stage runner's return into an outcome dict.

    ``None`` (the common "nothing to report" case) becomes an empty dict. A
    non-dict return is a programming error in the stage runner; treating it as a
    stage failure keeps the failure inside the per-stage retry/record path
    rather than escaping as an uncaught exception.
    """
    if result is None:
        return {}
    if not isinstance(result, dict):
        raise TypeError(f"stage runner returned {type(result).__name__}, expected dict or None")
    return result


def _noop_stage_runner(stage: str, attempt: int, run: AnalysisRun) -> dict | None:
    """Default stage work until the real pipeline lands (#5 placeholder body).

    No LLM is wired in yet (that arrives in #7), so each stage succeeds with no
    warnings or usage. The orchestration, persistence, retry, and observability
    contract around the stages is what this slice makes real.
    """
    return None


class RunExecutor(Protocol):
    """Executes the work of an Analysis Run (ADR 0009 kept interface).

    Implementations advance the run through its stages, recording a Run Stage
    Event per attempt through the injected recorder, and raise to signal that a
    stage has failed after its single retry.
    """

    def execute(self, run: AnalysisRun, recorder: StageRecorder) -> None: ...


class StagedRunExecutor:
    """Default executor: the six-stage DB-persisted pipeline (ADR 0026).

    Runs the six MVP stages in order. Each stage is attempted at most twice —
    the original try plus one retry (ADR 0029) — and every attempt is persisted
    as a Run Stage Event before the next stage starts. If a stage still fails
    after its retry, the executor raises `StageFailedError`; later stages never
    run, and the stage events already persisted remain inspectable.
    """

    def __init__(self, stage_runner: StageRunner | None = None) -> None:
        self._stage_runner = stage_runner or _noop_stage_runner

    def execute(self, run: AnalysisRun, recorder: StageRecorder) -> None:
        for stage in RUN_STAGES:
            self._run_stage(stage, run, recorder)

    def _run_stage(self, stage: str, run: AnalysisRun, recorder: StageRecorder) -> None:
        last_error = "unknown error"
        for attempt in (1, 2):  # original attempt + at most one retry (ADR 0029)
            event = recorder.begin(stage, attempt)
            try:
                result = self._stage_runner(stage, attempt, run)
                outcome = _normalize_outcome(result)
            except Exception as exc:
                last_error = str(exc) or exc.__class__.__name__
                recorder.fail(event, last_error)
                continue
            recorder.succeed(
                event,
                warning_codes=outcome.get("warning_codes"),
                usage=outcome.get("usage"),
            )
            return
        log_event(
            logger,
            logging.ERROR,
            "pipeline_stage_exhausted",
            run_id=run.id,
            incident_id=run.incident_id,
            stage=stage,
            error=last_error,
        )
        raise StageFailedError(stage, last_error)


class PlaceholderRunExecutor:
    """Minimal executor that records no stages and does no work.

    Retained for tests and trivial swappability demos (ADR 0009). The default
    product executor is `StagedRunExecutor`.
    """

    def execute(self, run: AnalysisRun, recorder: StageRecorder) -> None:
        return None
