from __future__ import annotations

import contextvars
import logging as py_logging
import sys
from collections.abc import Iterator
from contextlib import contextmanager


_request_id: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "postmortem_request_id",
    default=None,
)

_CONFIGURED = False


def configure_logging(level: str) -> None:
    """Configure application logging once for local/server runs.

    Keep the format plain text and key-value friendly so local terminals,
    uvicorn, and simple log collectors can read the same output. Payload bodies,
    prompts, evidence text, and secrets are intentionally left out by callers.
    """
    global _CONFIGURED
    numeric_level = getattr(py_logging, level.upper(), py_logging.INFO)
    root = py_logging.getLogger()
    if not _CONFIGURED:
        handler = py_logging.StreamHandler(sys.stdout)
        handler.setFormatter(
            py_logging.Formatter(
                "%(asctime)s %(levelname)s %(name)s %(message)s",
                datefmt="%Y-%m-%dT%H:%M:%S%z",
            )
        )
        root.addHandler(handler)
        _CONFIGURED = True
    py_logging.getLogger("postmortem").setLevel(numeric_level)


@contextmanager
def request_context(request_id: str) -> Iterator[None]:
    token = _request_id.set(request_id)
    try:
        yield
    finally:
        _request_id.reset(token)


def current_request_id() -> str | None:
    return _request_id.get()


def log_event(
    logger: py_logging.Logger,
    level: int,
    event: str,
    **fields: object,
) -> None:
    """Write one safe structured-ish event as a key-value log line."""
    if not logger.isEnabledFor(level):
        return
    request_id = current_request_id()
    if request_id and "request_id" not in fields:
        fields["request_id"] = request_id
    details = " ".join(f"{key}={_format_value(value)}" for key, value in fields.items())
    logger.log(level, "%s%s", event, f" {details}" if details else "")


def _format_value(value: object) -> str:
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return str(value)
    text = str(value)
    if not text:
        return '""'
    safe = text.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n")
    if any(ch.isspace() for ch in safe) or "=" in safe:
        return f'"{safe}"'
    return safe
