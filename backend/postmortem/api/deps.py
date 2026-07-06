from __future__ import annotations

from collections.abc import Iterator

from fastapi import Depends, Header, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import Incident
from ..services.workspaces import ensure_workspace_for_session


# Header the frontend BFF proxy sets from its per-visitor session cookie. The
# backend maps it to a private Workspace so incidents are isolated per visitor
# (ADR 0017 tenancy). Absent → the shared default workspace (anonymous bucket).
SESSION_HEADER = "X-Postmortem-Session"


def get_db(request: Request) -> Iterator[Session]:
    session_factory = request.app.state.session_factory
    session = session_factory()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def get_workspace_id(
    x_postmortem_session: str | None = Header(default=None),
    db: Session = Depends(get_db),
) -> str:
    """Resolve the calling visitor's Workspace id from the session header.

    FastAPI caches ``get_db`` within a request, so the workspace this creates and
    the handler's queries share one session and commit together. No header falls
    back to the shared default workspace.
    """
    return ensure_workspace_for_session(db, x_postmortem_session).id


def require_owned_incident(
    incident_id: str,
    db: Session = Depends(get_db),
    workspace_id: str = Depends(get_workspace_id),
) -> None:
    """Router-level guard: 404 unless the path's incident is in the caller's workspace.

    Attached to the incident-nested routers (artifacts, analysis-runs), it enforces
    tenancy once for every nested resource — runs, artifacts, hypotheses,
    diagnostics, conclusions, remediation — since those are all reached through this
    ``incident_id`` and resolved against it downstream. A cross-workspace or unknown
    incident is indistinguishable from not-found by design (no existence leak).
    """
    owner = db.scalar(select(Incident.workspace_id).where(Incident.id == incident_id))
    if owner != workspace_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="incident not found")
