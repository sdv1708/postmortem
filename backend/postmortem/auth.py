from __future__ import annotations

from dataclasses import dataclass

from fastapi import Depends, Header, HTTPException, status

from .config import Settings


@dataclass(frozen=True)
class Principal:
    """The authenticated actor behind a request (ADR 0017 / 0039).

    The MVP single-user gate authorizes one principal; ``id`` is the stable
    authenticated identifier recorded as Conclusion Provenance, and ``display`` is
    the human-readable name when configured (PRD #26 story 42).
    """

    id: str
    display: str | None = None


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


def require_principal(
    _: None = Depends(require_user),
    settings: Settings = Depends(get_settings),
) -> Principal:
    """Resolve the authenticated Principal after the single-user gate passes.

    Reuses ``require_user`` for the auth check, then returns the configured
    single-user identity so command endpoints (e.g. Root Cause Conclusion
    finalization, ADR 0039) can record Conclusion Provenance without introducing
    roles or multi-user authorization (PRD #26 story 42, out-of-scope RBAC).
    """
    return Principal(id=settings.principal_id, display=settings.principal_display)
