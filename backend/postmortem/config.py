from __future__ import annotations

import os
from dataclasses import dataclass


DEFAULT_WORKSPACE_SLUG = "default"
DEFAULT_WORKSPACE_NAME = "Default Workspace"


@dataclass(frozen=True)
class Settings:
    database_url: str
    api_token: str | None
    dev_bypass: bool

    @classmethod
    def from_env(cls) -> "Settings":
        return cls(
            database_url=os.environ.get("POSTMORTEM_DATABASE_URL", "sqlite:///./postmortem.db"),
            api_token=os.environ.get("POSTMORTEM_API_TOKEN") or None,
            dev_bypass=os.environ.get("POSTMORTEM_DEV_BYPASS", "").lower() in {"1", "true", "yes"},
        )
