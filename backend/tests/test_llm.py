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


@pytest.mark.parametrize("base_url", ["ftp://provider.test/v1", "provider.test/v1"])
def test_client_rejects_unsupported_base_url_scheme(base_url):
    with pytest.raises(ValueError) as excinfo:
        OpenAICompatibleLLMClient(
            base_url=base_url,
            api_key="secret",
            model="model-name",
        )

    assert repr(base_url) in str(excinfo.value)


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


def _capture_payload(monkeypatch, model, **complete_kwargs):
    """Run a completion with a captured request and return the JSON payload sent."""
    captured: dict = {}

    class Response:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, traceback):
            return False

        def read(self):
            return json.dumps(
                {"choices": [{"message": {"content": "{}"}}]}
            ).encode("utf-8")

    def urlopen(request, timeout):
        captured["payload"] = json.loads(request.data.decode("utf-8"))
        return Response()

    monkeypatch.setattr("urllib.request.urlopen", urlopen)
    client = OpenAICompatibleLLMClient(
        base_url="https://provider.test/v1", api_key="secret", model=model
    )
    client.complete(system="system", user="user", **complete_kwargs)
    return captured["payload"]


def test_chat_model_sends_temperature_and_max_tokens(monkeypatch):
    payload = _capture_payload(monkeypatch, "gpt-4o-mini", max_output_tokens=512)

    assert payload["temperature"] == 0.2
    assert payload["max_tokens"] == 512
    assert "max_completion_tokens" not in payload


@pytest.mark.parametrize("model", ["gpt-5.4-mini", "gpt-5", "o1-mini", "o3", "vendor/gpt-5"])
def test_reasoning_model_drops_temperature_and_renames_token_cap(monkeypatch, model):
    payload = _capture_payload(monkeypatch, model, max_output_tokens=512)

    # GPT-5/o-series 400 on any non-default temperature and on max_tokens.
    assert "temperature" not in payload
    assert "max_tokens" not in payload
    assert payload["max_completion_tokens"] == 512


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
