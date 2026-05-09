from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import DEFAULT_WORKSPACE_NAME, DEFAULT_WORKSPACE_SLUG
from ..models import Workspace


def ensure_default_workspace(session: Session) -> Workspace:
    """Idempotently fetch or create the single default workspace stub.

    The MVP has no workspace UX; this exists so future tenancy has a foreign
    key boundary already in place (ADR 0017).
    """
    workspace = session.scalar(select(Workspace).where(Workspace.slug == DEFAULT_WORKSPACE_SLUG))
    if workspace is None:
        workspace = Workspace(slug=DEFAULT_WORKSPACE_SLUG, name=DEFAULT_WORKSPACE_NAME)
        session.add(workspace)
        session.flush()
    return workspace
