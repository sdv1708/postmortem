from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timezone


@dataclass(frozen=True)
class ParsedTimestamp:
    """A timestamp extracted from a line of evidence (ADR 0019).

    ``normalized`` is UTC when a real datetime could be parsed, else None. The
    ``original_text`` always preserves exactly what appeared in the evidence so
    timeline claims stay auditable. ``inferred`` marks timestamps that are
    relative/partial (e.g. "14:32" with no date, or "~5 min later"), which the
    UI must label as uncertain rather than present as equally precise.
    """

    original_text: str
    normalized: datetime | None
    inferred: bool


# Absolute formats, tried most-specific first. Each entry is (regex, strptime
# format). Patterns are anchored to the start of the line because log/deploy
# lines lead with their timestamp. The date/time separator (space or "T") is
# normalized to a space before strptime, so the formats use a space.
_ABSOLUTE_PATTERNS: list[tuple[re.Pattern[str], str]] = [
    # 2026-05-09T14:28:31Z / 2026-05-09 14:28:31 (optional fractional seconds)
    (re.compile(r"^(\d{4}-\d{2}-\d{2}[ T]\d{2}:\d{2}:\d{2})(?:\.\d+)?Z?"), "%Y-%m-%d %H:%M:%S"),
    # 2026-05-09 14:28 (no seconds)
    (re.compile(r"^(\d{4}-\d{2}-\d{2}[ T]\d{2}:\d{2})(?!:)"), "%Y-%m-%d %H:%M"),
]

# A numeric tz offset, optionally after fractional seconds. The fractional part
# is matched (so the offset still anchors) but dropped before parsing.
_OFFSET_PATTERN = re.compile(
    r"^(\d{4}-\d{2}-\d{2}[ T]\d{2}:\d{2}:\d{2})(?:\.\d+)?([+-]\d{2}:?\d{2})"
)

# Time-only, no date: real clock time but missing the day, so it is anchored
# only relative to other evidence. Inferred/uncertain (ADR 0019). The full
# match (incl. any surrounding brackets) is the original text so it can be
# stripped verbatim from the cited line; group(1) is the bare clock time.
_TIME_ONLY_PATTERN = re.compile(r"^\[?\d{2}:\d{2}(?::\d{2})?\]?(?=\s|$)")

# Relative/vague human phrasing: explicitly uncertain.
_RELATIVE_PATTERN = re.compile(
    r"\b(?:~|about |around |roughly )?\d+\s*(?:s|sec|secs|seconds|m|min|mins|minutes|h|hr|hrs|hours)\s+(?:later|after|before|ago)\b",
    re.IGNORECASE,
)


def parse_timestamp(line: str) -> ParsedTimestamp | None:
    """Best-effort deterministic timestamp parse for a single evidence line.

    Returns None when the line carries no recognizable time anchor.
    """
    stripped = line.strip()
    if not stripped:
        return None

    offset = _OFFSET_PATTERN.match(stripped)
    if offset:
        base = offset.group(1).replace("T", " ")
        tz = offset.group(2).replace(":", "")
        try:
            dt = datetime.strptime(f"{base}{tz}", "%Y-%m-%d %H:%M:%S%z")
        except ValueError:
            dt = None
        if dt is not None:
            return ParsedTimestamp(
                original_text=offset.group(0),
                normalized=dt.astimezone(timezone.utc),
                inferred=False,
            )

    for pattern, fmt in _ABSOLUTE_PATTERNS:
        match = pattern.match(stripped)
        if not match:
            continue
        raw = match.group(1).replace("T", " ")
        try:
            dt = datetime.strptime(raw, fmt)
        except ValueError:
            continue
        return ParsedTimestamp(
            original_text=match.group(0),
            normalized=dt.replace(tzinfo=timezone.utc),
            inferred=False,
        )

    time_only = _TIME_ONLY_PATTERN.match(stripped)
    if time_only:
        return ParsedTimestamp(
            original_text=time_only.group(0),
            normalized=None,
            inferred=True,
        )

    relative = _RELATIVE_PATTERN.search(stripped)
    if relative:
        return ParsedTimestamp(
            original_text=relative.group(0),
            normalized=None,
            inferred=True,
        )

    return None
