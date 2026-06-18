"""Unit tests for the reasoning-provenance recording layer (ADR 0038).

The RecordingLLMClient is the transparent decorator that captures each model
completion's reproducibility metadata for Model Call Records. These tests assert
its core discipline: it returns the inner completion unchanged, captures hashes
and usage, never retains prompt or response text, and drains per role boundary.
"""

from __future__ import annotations

from postmortem.llm import FakeLLMClient, LLMResponse
from postmortem.provenance import RecordingLLMClient, content_hash


def test_content_hash_is_stable_and_order_sensitive():
    assert content_hash("a", "b") == content_hash("a", "b")
    # The separator prevents ("ab","") from colliding with ("a","b").
    assert content_hash("a", "b") != content_hash("ab", "")
    assert content_hash("system", "user") != content_hash("user", "system")


def test_recording_client_passes_completion_through():
    inner = FakeLLMClient(["{}"], label="fake-model", usage={"total_tokens": 7})
    recorder = RecordingLLMClient(inner)

    assert recorder.label == "fake-model"
    response = recorder.complete(system="sys", user="usr")
    assert isinstance(response, LLMResponse)
    assert response.text == "{}"
    assert response.usage == {"total_tokens": 7}


def test_recording_client_captures_hashes_and_usage_not_text():
    inner = FakeLLMClient(["the-completion-text"], label="m", usage={"total_tokens": 3})
    recorder = RecordingLLMClient(inner)
    recorder.complete(system="secret-system-prompt", user="secret-user-prompt")

    captures = recorder.drain()
    assert len(captures) == 1
    capture = captures[0]
    assert capture.model_identity == "m"
    assert capture.usage == {"total_tokens": 3}
    # Hashes match the content_hash of the same inputs/outputs...
    assert capture.input_hash == content_hash("secret-system-prompt", "secret-user-prompt")
    assert capture.output_hash == content_hash("the-completion-text")
    # ...but the prompt and response text themselves are never retained.
    serialized = repr(capture)
    assert "secret-system-prompt" not in serialized
    assert "secret-user-prompt" not in serialized
    assert "the-completion-text" not in serialized


def test_drain_returns_buffered_calls_in_order_then_clears():
    inner = FakeLLMClient(["one", "two"], label="m")
    recorder = RecordingLLMClient(inner)

    recorder.complete(system="s1", user="u1")
    recorder.complete(system="s2", user="u2")
    captures = recorder.drain()
    assert [c.output_hash for c in captures] == [content_hash("one"), content_hash("two")]
    # A second drain with no intervening calls is empty (a deterministic role makes
    # no model call, so its drain is empty and the stage records its own version).
    assert recorder.drain() == []


def test_usage_is_none_when_provider_reports_none():
    recorder = RecordingLLMClient(FakeLLMClient(["{}"], label="m"))
    recorder.complete(system="s", user="u")
    assert recorder.drain()[0].usage is None
