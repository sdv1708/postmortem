from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Final, Protocol

from .timestamps import parse_timestamp

# Versioned Chunking Strategy identity recorded in Experiment Metadata (ADR
# 0025). Bump this string whenever the chunking rules change so runs produced by
# different rule sets stay comparable.
CHUNKING_STRATEGY_VERSION: Final[str] = "source-aware-1"

# Line-window sizing for the source types that use fixed windows. Windows are
# in *lines* (ADR 0027: line-window chunking), and overlap is 15% of the window
# rounded down, with a floor of one line so consecutive windows always share a
# boundary line and no event is lost between chunks.
_LOG_WINDOW_LINES: Final[int] = 40
_DEFAULT_WINDOW_LINES: Final[int] = 60
_OVERLAP_RATIO: Final[float] = 0.15


@dataclass(frozen=True)
class Chunk:
    """A retrieval-aid chunk of an Artifact.

    Chunks are NOT durable citation targets (ADR 0027): EvidenceRefs point to
    Artifact line ranges, because chunk boundaries can change across strategy
    versions. ``line_start``/``line_end`` are 1-based and inclusive, matching the
    Artifact line addressing used everywhere else.
    """

    source_type: str
    source_name: str
    line_start: int
    line_end: int
    text: str

    @property
    def line_count(self) -> int:
        return self.line_end - self.line_start + 1


class ChunkingStrategy(Protocol):
    """Splits Artifact bodies into retrieval chunks (ADR 0009 kept interface)."""

    @property
    def version(self) -> str: ...

    def chunk(self, source_type: str, source_name: str, body: str) -> list[Chunk]: ...


def _overlap_for(window: int) -> int:
    return max(1, int(window * _OVERLAP_RATIO))


def _lines(body: str) -> list[str]:
    return body.split("\n")


def _window_chunks(
    source_type: str,
    source_name: str,
    lines: list[str],
    window: int,
    *,
    base_line: int = 1,
) -> list[Chunk]:
    """Fixed line-window chunking with 15% overlap (ADR 0027).

    ``base_line`` is the 1-based Artifact line number of ``lines[0]`` so callers
    that pre-split a body (e.g. paragraph blocks) still emit Artifact-accurate
    line ranges.
    """
    total = len(lines)
    if total == 0:
        return []
    if total <= window:
        return [
            Chunk(
                source_type=source_type,
                source_name=source_name,
                line_start=base_line,
                line_end=base_line + total - 1,
                text="\n".join(lines),
            )
        ]

    overlap = _overlap_for(window)
    step = window - overlap  # > 0 because overlap < window for any sane window
    chunks: list[Chunk] = []
    start = 0
    while start < total:
        end = min(start + window, total)
        chunks.append(
            Chunk(
                source_type=source_type,
                source_name=source_name,
                line_start=base_line + start,
                line_end=base_line + end - 1,
                text="\n".join(lines[start:end]),
            )
        )
        if end == total:
            break
        start += step
    return chunks


# A blank line (or run of blank lines) separates human-note paragraphs and
# deploy-note release entries.
_BLANK_LINE = re.compile(r"^\s*$")
_HEADING_LINE = re.compile(r"^\s{0,3}#{1,6}\s+\S")


def _blocks_by_blank_lines(lines: list[str]) -> list[tuple[int, list[str]]]:
    """Group lines into blocks separated by blank lines or note headings.

    Returns (base_line, block_lines) where base_line is the 1-based Artifact
    line of the block's first line. Blank separator lines are dropped from the
    blocks but still counted so line numbers stay accurate. Markdown headings
    begin a new block so human-note section boundaries survive chunking.
    """
    blocks: list[tuple[int, list[str]]] = []
    current: list[str] = []
    current_base = 1
    for index, line in enumerate(lines, start=1):
        if _BLANK_LINE.match(line):
            if current:
                blocks.append((current_base, current))
                current = []
            continue

        if _HEADING_LINE.match(line) and current:
            blocks.append((current_base, current))
            current = []

        if not current:
            current_base = index
        current.append(line)
    if current:
        blocks.append((current_base, current))
    return blocks


def _has_time_anchor(line: str) -> bool:
    parsed = parse_timestamp(line)
    return parsed is not None and line.strip().startswith(parsed.original_text)


def _timestamp_aware_window_chunks(
    source_name: str,
    lines: list[str],
    window: int,
) -> list[Chunk]:
    total = len(lines)
    if total == 0:
        return []
    if total <= window:
        return _window_chunks("logs", source_name, lines, window)

    overlap = _overlap_for(window)
    step = window - overlap
    chunks: list[Chunk] = []
    start = 0
    while start < total:
        end = min(start + window, total)
        chunks.append(
            Chunk(
                source_type="logs",
                source_name=source_name,
                line_start=start + 1,
                line_end=end,
                text="\n".join(lines[start:end]),
            )
        )
        if end == total:
            break

        nominal = start + step
        next_start = nominal
        for candidate in range(nominal, start, -1):
            if _has_time_anchor(lines[candidate]):
                next_start = candidate
                break
        start = next_start
    return chunks


class SourceAwareLineWindowChunker:
    """Source-type-aware line-window chunking with 15% overlap (ADR 0027).

    Rules, per the PRD:
    - logs: timestamp-aware fixed line windows (smaller windows; overlap keeps
      boundary events from being lost).
    - stack_trace: kept together as a single chunk when possible so a frame
      sequence is never split.
    - incident_notes: preserve paragraph/heading boundaries (blank-line blocks);
      a very long paragraph still falls back to windowing.
    - deployment_notes: small release-entry chunks (one block per release entry).
    - other / unknown: default fixed line windows.
    """

    @property
    def version(self) -> str:
        return CHUNKING_STRATEGY_VERSION

    def chunk(self, source_type: str, source_name: str, body: str) -> list[Chunk]:
        lines = _lines(body)
        if source_type == "stack_trace":
            return self._stack_trace(source_name, lines)
        if source_type in {"incident_notes", "deployment_notes"}:
            return self._block_oriented(source_type, source_name, lines)
        if source_type == "logs":
            return _timestamp_aware_window_chunks(source_name, lines, _LOG_WINDOW_LINES)
        window = _DEFAULT_WINDOW_LINES
        return _window_chunks(source_type, source_name, lines, window)

    def _stack_trace(self, source_name: str, lines: list[str]) -> list[Chunk]:
        # Keep the trace together when possible; only fall back to windowing for
        # pathologically long traces so a single chunk does not grow unbounded.
        if len(lines) <= _DEFAULT_WINDOW_LINES * 2:
            return [
                Chunk(
                    source_type="stack_trace",
                    source_name=source_name,
                    line_start=1,
                    line_end=len(lines),
                    text="\n".join(lines),
                )
            ]
        return _window_chunks("stack_trace", source_name, lines, _DEFAULT_WINDOW_LINES)

    def _block_oriented(
        self, source_type: str, source_name: str, lines: list[str]
    ) -> list[Chunk]:
        blocks = _blocks_by_blank_lines(lines)
        if not blocks:
            return []
        chunks: list[Chunk] = []
        for base_line, block in blocks:
            # A normal paragraph / release entry is one chunk; an unusually long
            # block still windows so chunks stay bounded.
            chunks.extend(
                _window_chunks(
                    source_type,
                    source_name,
                    block,
                    _DEFAULT_WINDOW_LINES,
                    base_line=base_line,
                )
            )
        return chunks
