from __future__ import annotations

import io
import json
import urllib.error

import pytest

from postmortem.llm import LLMError, OpenAICompatibleLLMClient


def _client() -> OpenAICompatibleLLMClient:
    return OpenAICompatibleLLMClient(
        base_url="https://provider.test/v1",
        api_key="secret",
        model="model-name",
    )


def test_http_error_omits_provider_response_body(monkeypatch):
    def fail(request, timeout):
        raise urllib.error.HTTPError(
            request.full_url,
            429,
            "Too Many Requests",
            {},
            io.BytesIO(b"sensitive provider detail"),
        )

    monkeypatch.setattr("urllib.request.urlopen", fail)

    with pytest.raises(LLMError) as excinfo:
        _client().complete(system="system", user="user")

    assert str(excinfo.value) == "provider returned HTTP 429"
    assert "sensitive" not in str(excinfo.value)


def test_invalid_provider_envelope_omits_response_body(monkeypatch):
    class Response:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, traceback):
            return False

        def read(self):
            return json.dumps({"choices": [], "sensitive": "provider detail"}).encode("utf-8")

    monkeypatch.setattr("urllib.request.urlopen", lambda request, timeout: Response())

    with pytest.raises(LLMError) as excinfo:
        _client().complete(system="system", user="user")

    assert str(excinfo.value) == "provider envelope missing completion text"
    assert "sensitive" not in str(excinfo.value)

