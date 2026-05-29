from __future__ import annotations

from typing import Protocol

from ..models import AnalysisRun


class RunExecutor(Protocol):
    """Executes the work of an Analysis Run (ADR 0009 kept interface).

    The six-stage, DB-persisted pipeline (ADR 0026) and Run Stage Events arrive
    in slice #5. For this slice the executor only has to advance a started run
    to a terminal state so the async lifecycle is real and pollable. Tests swap
    in fakes to prove swappability and to exercise the failure path (ADR 0029).
    """

    def execute(self, run: AnalysisRun) -> None:
        """Run the pipeline for `run`. Raise to signal stage/run failure."""
        ...


class PlaceholderRunExecutor:
    """Default executor used until the real pipeline lands in slice #5.

    It performs no analysis work. The run still moves through the durable
    queued -> running -> succeeded lifecycle via the AnalysisService, which is
    enough for the status-polling product experience (ADR 0003).
    """

    def execute(self, run: AnalysisRun) -> None:  # noqa: D401 - placeholder no-op
        return None
