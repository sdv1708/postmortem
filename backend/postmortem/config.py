from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


DEFAULT_WORKSPACE_SLUG = "default"
DEFAULT_WORKSPACE_NAME = "Default Workspace"

# Experiment Metadata defaults recorded on each Analysis Run (ADR 0025). These
# are intentionally MVP placeholders; later slices wire real prompt/model and
# strategy versions as those components enter the pipeline (ADR 0009).
DEFAULT_EXPERIMENT_METADATA: dict[str, str] = {
    "pipeline_version": "mvp-0",
    "prompt_version": "none-0",
    "model_provider": "none",
    "retrieval_strategy": "deterministic-0",
    "chunking_strategy": "source-aware-0",
    "verifier_version": "none-0",
}


@dataclass(frozen=True)
class Settings:
    database_url: str
    api_token: str | None
    dev_bypass: bool
    cors_origins: tuple[str, ...]
    # Generation provider config behind the LLMClient boundary (ADR 0011). The
    # provider is model-agnostic: switch models/providers by changing these three
    # values only. An empty api_key means "no provider configured" — the pipeline
    # falls back to the offline client.
    llm_base_url: str = "https://api.openai.com/v1"
    llm_api_key: str | None = None
    llm_model: str = "gpt-4o-mini"

    @classmethod
    def from_env(cls) -> "Settings":
        load_env_files()
        return cls(
            database_url=os.environ.get("POSTMORTEM_DATABASE_URL", "sqlite:///./postmortem.db"),
            api_token=os.environ.get("POSTMORTEM_API_TOKEN") or None,
            dev_bypass=os.environ.get("POSTMORTEM_DEV_BYPASS", "").lower() in {"1", "true", "yes"},
            cors_origins=tuple(
                origin.strip()
                for origin in os.environ.get(
                    "POSTMORTEM_CORS_ORIGINS",
                    "http://localhost:3000,http://127.0.0.1:3000",
                ).split(",")
                if origin.strip()
            ),
            llm_base_url=os.environ.get("POSTMORTEM_LLM_BASE_URL", "https://api.openai.com/v1"),
            llm_api_key=os.environ.get("POSTMORTEM_LLM_API_KEY") or None,
            llm_model=os.environ.get("POSTMORTEM_LLM_MODEL", "gpt-4o-mini"),
        )


def load_env_files(paths: tuple[Path, ...] | None = None) -> None:
    """Load local .env files without overriding real environment variables.

    The backend has no settings framework yet, so keep this intentionally small:
    KEY=VALUE lines, optional ``export KEY=VALUE``, quotes, blank lines, and
    comments are supported. Existing process env values always win so deploy
    environments and one-off shell overrides remain authoritative.
    """
    for path in _env_paths(paths):
        if not path.is_file():
            continue
        for line in path.read_text(encoding="utf-8").splitlines():
            parsed = _parse_env_line(line)
            if parsed is None:
                continue
            key, value = parsed
            os.environ.setdefault(key, value)


def _env_paths(paths: tuple[Path, ...] | None) -> tuple[Path, ...]:
    if paths is not None:
        return paths
    repo_root = Path(__file__).resolve().parents[2]
    backend_root = Path(__file__).resolve().parents[1]
    candidates = (repo_root / ".env", backend_root / ".env", Path.cwd() / ".env")
    seen: set[Path] = set()
    ordered: list[Path] = []
    for candidate in candidates:
        resolved = candidate.resolve()
        if resolved not in seen:
            seen.add(resolved)
            ordered.append(resolved)
    return tuple(ordered)


def _parse_env_line(line: str) -> tuple[str, str] | None:
    text = line.strip()
    if not text or text.startswith("#"):
        return None
    if text.startswith("export "):
        text = text[len("export ") :].strip()
    key, separator, value = text.partition("=")
    if not separator:
        return None
    key = key.strip()
    if not key:
        return None
    value = value.strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
        value = value[1:-1]
    elif " #" in value:
        value = value.split(" #", 1)[0].rstrip()
    return key, value
