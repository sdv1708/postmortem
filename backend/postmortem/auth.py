from __future__ import annotations

from fastapi import Depends, Header, HTTPException, status

from .config import Settings


class _SettingsHolder:
    settings: Settings | None = None


def configure_auth(settings: Settings) -> None:
    _SettingsHolder.settings = settings


def get_settings() -> Settings:
    if _SettingsHolder.settings is None:
        _SettingsHolder.settings = Settings.from_env()
    return _SettingsHolder.settings


def require_user(
    authorization: str | None = Header(default=None),
    settings: Settings = Depends(get_settings),
) -> None:
    """MVP single-user gate (ADR 0017, 0030).

    - If `POSTMORTEM_DEV_BYPASS=1`, requests pass without a token. This is the
      explicit local-development bypass — never set it in hosted/demo deploys.
    - Otherwise `POSTMORTEM_API_TOKEN` must be configured and the request must
      send `Authorization: Bearer <token>` with a matching value.
    """
    if settings.dev_bypass:
        return

    if not settings.api_token:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="single-user gate not configured: set POSTMORTEM_API_TOKEN",
        )

    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="missing bearer token",
            headers={"WWW-Authenticate": "Bearer"},
        )

    presented = authorization.split(" ", 1)[1].strip()
    if presented != settings.api_token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="invalid bearer token",
            headers={"WWW-Authenticate": "Bearer"},
        )
