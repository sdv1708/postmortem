from __future__ import annotations

import pytest

from postmortem.schemas import IncidentCreate
from postmortem.services import IncidentNotFoundError, IncidentService, ensure_default_workspace


def test_default_workspace_is_idempotent(fresh_session):
    a = ensure_default_workspace(fresh_session)
    b = ensure_default_workspace(fresh_session)
    fresh_session.commit()
    assert a.id == b.id
    assert a.slug == "default"


def test_create_incident_attaches_default_workspace(fresh_session):
    service = IncidentService(fresh_session)
    incident = service.create(IncidentCreate(title="API 500s spiking", severity="sev2"))
    fresh_session.commit()

    workspace = ensure_default_workspace(fresh_session)
    assert incident.workspace_id == workspace.id
    assert incident.title == "API 500s spiking"
    assert incident.status == "open"
    assert incident.id is not None


def test_get_incident_round_trip(fresh_session):
    service = IncidentService(fresh_session)
    created = service.create(IncidentCreate(title="Deploy ambiguity"))
    fresh_session.commit()

    fetched = service.get(created.id)
    assert fetched.id == created.id
    assert fetched.title == "Deploy ambiguity"


def test_get_unknown_incident_raises(fresh_session):
    service = IncidentService(fresh_session)
    with pytest.raises(IncidentNotFoundError):
        service.get("does-not-exist")


def test_list_incidents_orders_newest_first(fresh_session):
    service = IncidentService(fresh_session)
    a = service.create(IncidentCreate(title="first"))
    b = service.create(IncidentCreate(title="second"))
    fresh_session.commit()

    listed = service.list()
    ids = [i.id for i in listed]
    assert ids[0] == b.id
    assert ids[1] == a.id
