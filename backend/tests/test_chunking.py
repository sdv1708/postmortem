from __future__ import annotations

from postmortem.chunking import (
    CHUNKING_STRATEGY_VERSION,
    SourceAwareLineWindowChunker,
)


def _chunker() -> SourceAwareLineWindowChunker:
    return SourceAwareLineWindowChunker()


def test_version_is_exposed():
    assert _chunker().version == CHUNKING_STRATEGY_VERSION == "source-aware-1"


def test_short_artifact_is_a_single_chunk_with_full_line_range():
    body = "line one\nline two\nline three"
    chunks = _chunker().chunk("logs", "api.log", body)
    assert len(chunks) == 1
    assert (chunks[0].line_start, chunks[0].line_end) == (1, 3)
    assert chunks[0].text == body


def test_log_windows_overlap_by_15_percent_and_preserve_line_numbers():
    # 100 lines, log window = 40, overlap = 6 -> step 34.
    body = "\n".join(f"line {i}" for i in range(1, 101))
    chunks = _chunker().chunk("logs", "api.log", body)

    assert len(chunks) > 1
    # First window is exactly the window size, 1-based.
    assert (chunks[0].line_start, chunks[0].line_end) == (1, 40)
    # 15% of 40 = 6 lines of overlap -> next window starts at 35.
    assert chunks[1].line_start == 35
    overlap = chunks[0].line_end - chunks[1].line_start + 1
    assert overlap == 6
    # Windows cover the whole artifact and never exceed it.
    assert chunks[-1].line_end == 100
    assert all(c.line_start >= 1 and c.line_end <= 100 for c in chunks)


def test_consecutive_windows_always_share_at_least_one_line():
    body = "\n".join(f"l{i}" for i in range(1, 250))
    chunks = _chunker().chunk("logs", "api.log", body)
    for earlier, later in zip(chunks, chunks[1:]):
        assert later.line_start <= earlier.line_end  # overlap, no gap


def test_stack_trace_stays_together_as_one_chunk():
    body = "\n".join(
        ["Traceback (most recent call last):"]
        + [f'  File "mod{i}.py", line {i}, in fn' for i in range(1, 30)]
        + ["ValueError: boom"]
    )
    chunks = _chunker().chunk("stack_trace", "trace.txt", body)
    assert len(chunks) == 1
    assert chunks[0].line_start == 1
    assert chunks[0].line_end == body.count("\n") + 1


def test_incident_notes_split_on_paragraph_boundaries():
    body = "First paragraph line a\nFirst paragraph line b\n\nSecond paragraph\n\nThird"
    chunks = _chunker().chunk("incident_notes", "notes.md", body)
    assert [c.text for c in chunks] == [
        "First paragraph line a\nFirst paragraph line b",
        "Second paragraph",
        "Third",
    ]
    # Line numbers stay accurate across the dropped blank separators.
    assert (chunks[0].line_start, chunks[0].line_end) == (1, 2)
    assert (chunks[1].line_start, chunks[1].line_end) == (4, 4)
    assert (chunks[2].line_start, chunks[2].line_end) == (6, 6)


def test_deploy_notes_are_small_release_entry_chunks():
    body = "release v184\nrolled out 14:28\n\nrelease v185\nrolled back 14:50"
    chunks = _chunker().chunk("deployment_notes", "deploys.txt", body)
    assert len(chunks) == 2
    assert chunks[0].text == "release v184\nrolled out 14:28"
    assert chunks[1].line_start == 4


def test_empty_block_artifact_yields_no_chunks():
    chunks = _chunker().chunk("incident_notes", "blank.md", "\n\n\n")
    assert chunks == []
