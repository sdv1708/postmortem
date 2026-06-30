from __future__ import annotations

import json
import logging
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from typing import Callable, Protocol, runtime_checkable

logger = logging.getLogger("postmortem.llm")


class LLMError(RuntimeError):
    """A transport/protocol failure talking to the model provider.

    Raised for network errors, non-2xx responses, or unparseable provider
    envelopes. The RCA stage lets this propagate so the executor's single-retry
    path (ADR 0029) can retry once before failing the run. It is distinct from a
    schema-invalid *model output*, which the stage validates separately.
    """


@dataclass(frozen=True)
class LLMResponse:
    """The text a model returned plus optional usage for observability.

    ``text`` is the raw completion the RCA stage parses and validates against a
    strict JSON schema (ADR 0028); the client never interprets it. ``usage`` is
    recorded on the Run Stage Event when the provider reports it (ADR 0021).
    """

    text: str
    usage: dict | None = None


@runtime_checkable
class LLMClient(Protocol):
    """One configured generation provider behind an interface (ADR 0011).

    A kept MVP boundary (ADR 0009): the pipeline depends only on this surface,
    and tests swap in fakes/replays instead of calling a live model. ``label``
    feeds Experiment Metadata (ADR 0025) so a run records which model produced
    its hypotheses.
    """

    @property
    def label(self) -> str: ...

    def complete(
        self, *, system: str, user: str, max_output_tokens: int | None = None
    ) -> LLMResponse: ...


class FakeLLMClient:
    """Deterministic replay client for tests (ADR 0011 fakes/replay).

    Seeded with the exact completions a real provider would return — a list of
    strings popped per call, or a callable computing one from the prompt. This is
    how the pipeline is tested without live model calls, including the
    schema-invalid path: seed it with malformed JSON and the RCA stage must fail.
    """

    def __init__(
        self,
        responses: list[str] | Callable[[str, str], str],
        *,
        label: str = "fake",
        usage: dict | None = None,
    ) -> None:
        self._responses = responses
        self._label = label
        self._usage = usage
        self._cursor = 0
        self.calls: list[tuple[str, str]] = []

    @property
    def label(self) -> str:
        return self._label

    def complete(
        self, *, system: str, user: str, max_output_tokens: int | None = None
    ) -> LLMResponse:
        # The fake records prompts for assertions; the output cap is a live-provider
        # concern only, so it is accepted for interface parity and ignored here.
        self.calls.append((system, user))
        logger.debug("fake_llm_completion label=%s call=%s", self._label, len(self.calls))
        if callable(self._responses):
            return LLMResponse(text=self._responses(system, user), usage=self._usage)
        if self._cursor >= len(self._responses):
            raise LLMError("FakeLLMClient exhausted its seeded responses")
        text = self._responses[self._cursor]
        self._cursor += 1
        return LLMResponse(text=text, usage=self._usage)


class OfflineLLMClient:
    """Safe default when no provider is configured (no API key).

    Returns an empty JSON object so a run still completes its six stages rather
    than failing for lack of a model. ``{}`` validates as empty against every
    strict stage contract whose collections default to empty (RCA hypotheses,
    incident-facts impact claims), so neither the incident-facts stage nor the
    RCA stage produces output. Real runs configure a provider and never hit this;
    tests inject seeded fakes. It exists so local dev and the deterministic
    timeline tests do not depend on a live model.
    """

    @property
    def label(self) -> str:
        return "offline"

    def complete(
        self, *, system: str, user: str, max_output_tokens: int | None = None
    ) -> LLMResponse:
        logger.info("offline_llm_completion")
        return LLMResponse(text=json.dumps({}))


class OpenAICompatibleLLMClient:
    """Provider-agnostic client for any OpenAI-compatible chat endpoint.

    Switch providers/models by changing base URL, API key, and model name only
    (OpenAI, OpenRouter, Together, a local gateway, an Anthropic-compatible
    proxy, ...) — the wire contract is the shared ``/chat/completions`` shape, so
    nothing in the pipeline is model-specific (ADR 0011). Uses the standard
    library so the backend takes no new hard dependency.
    """

    def __init__(
        self,
        *,
        base_url: str,
        api_key: str,
        model: str,
        timeout: float = 60.0,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        parsed_url = urllib.parse.urlsplit(self._base_url)
        if parsed_url.scheme not in {"http", "https"}:
            raise ValueError(
                f"unsupported LLM base URL scheme {parsed_url.scheme!r} for {base_url!r}"
            )
        self._provider = parsed_url.netloc or self._base_url
        self._api_key = api_key
        self._model = model
        self._timeout = timeout

    @property
    def label(self) -> str:
        return f"openai-compatible:{self._provider}:{self._model}"

    def complete(
        self, *, system: str, user: str, max_output_tokens: int | None = None
    ) -> LLMResponse:
        logger.info(
            "llm_request_started provider=%s model=%s",
            self._provider,
            self._model,
        )
        payload: dict = {
            "model": self._model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            # Ask compatible providers to constrain output to a JSON object so the
            # strict schema parse (ADR 0028) has the best chance of succeeding;
            # providers that ignore this still return text we validate ourselves.
            "response_format": {"type": "json_object"},
            "temperature": 0.2,
        }
        # Bound the completion length per role to cut output tokens (the role caps
        # are sized above observed output with headroom so a valid JSON answer is
        # never truncated into a schema-invalid result, which would cost a repair
        # retry). A provider that ignores max_tokens still returns text we validate.
        if max_output_tokens and max_output_tokens > 0:
            payload["max_tokens"] = max_output_tokens
        request = urllib.request.Request(
            f"{self._base_url}/chat/completions",
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {self._api_key}",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=self._timeout) as response:
                body = json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:  # non-2xx
            raise LLMError(f"provider returned HTTP {exc.code}") from exc
        except (urllib.error.URLError, TimeoutError) as exc:
            raise LLMError(f"provider request failed: {exc}") from exc
        except json.JSONDecodeError as exc:
            raise LLMError(f"provider returned non-JSON envelope: {exc}") from exc

        try:
            text = body["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as exc:
            raise LLMError("provider envelope missing completion text") from exc
        logger.info(
            "llm_request_completed provider=%s model=%s usage_keys=%s",
            self._provider,
            self._model,
            ",".join(sorted(body.get("usage", {}).keys())) if body.get("usage") else "none",
        )
        return LLMResponse(text=text, usage=body.get("usage"))


def build_llm_client(settings) -> LLMClient:
    """Resolve the configured generation provider for real runs (ADR 0011).

    With an API key set, returns the provider-agnostic OpenAI-compatible client
    driven entirely by config. Without one, returns the offline client and logs a
    warning so runs still complete without silently looking configured.
    """
    if settings.llm_api_key:
        return OpenAICompatibleLLMClient(
            base_url=settings.llm_base_url,
            api_key=settings.llm_api_key,
            model=settings.llm_model,
        )
    logger.warning(
        "No POSTMORTEM_LLM_API_KEY configured; RCA generation will produce no "
        "hypotheses. Set base url, key, and model to enable a real provider."
    )
    return OfflineLLMClient()
