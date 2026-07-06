from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import DEFAULT_WORKSPACE_NAME, DEFAULT_WORKSPACE_SLUG
from ..models import Workspace


def ensure_default_workspace(session: Session) -> Workspace:
    """Idempotently fetch or create the single default workspace stub.

    The default workspace is the shared "anonymous" bucket used when a request
    carries no session identity (direct API/CLI use, tests). Per-visitor sandboxes
    use ``ensure_workspace_for_session`` instead (ADR 0017).
    """
    workspace = session.scalar(select(Workspace).where(Workspace.slug == DEFAULT_WORKSPACE_SLUG))
    if workspace is None:
        workspace = Workspace(slug=DEFAULT_WORKSPACE_SLUG, name=DEFAULT_WORKSPACE_NAME)
        session.add(workspace)
        session.flush()
    return workspace


def ensure_workspace_for_session(session: Session, session_id: str | None) -> Workspace:
    """Fetch-or-create the private workspace for an anonymous visitor session.

    Each browser session (an opaque id minted by the frontend BFF proxy and sent
    as a header) gets its own Workspace, so incidents are isolated per visitor
    without login (ADR 0017 tenancy boundary). A missing/blank id falls back to the
    shared default workspace, so direct API use and tests never fail for lack of a
    session. Idempotent, mirroring ``ensure_default_workspace``.
    """
    session_id = (session_id or "").strip()
    if not session_id:
        return ensure_default_workspace(session)
    slug = f"sess-{session_id}"[:64]
    workspace = session.scalar(select(Workspace).where(Workspace.slug == slug))
    if workspace is None:
        workspace = Workspace(slug=slug, name=f"Session {session_id[:8]}")
        session.add(workspace)
        session.flush()
    return workspace
