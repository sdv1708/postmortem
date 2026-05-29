from __future__ import annotations

import os
from dataclasses import dataclass


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

    @classmethod
    def from_env(cls) -> "Settings":
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
        )
