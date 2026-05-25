from __future__ import annotations

from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from postmortem.app import create_app
from postmortem.config import Settings
from postmortem.db import Base, make_engine, make_session_factory


@pytest.fixture
def settings(tmp_path) -> Settings:
    return Settings(
        database_url=f"sqlite:///{tmp_path}/test.db",
        api_token="test-token",
        dev_bypass=False,
        cors_origins=("http://localhost:3000",),
    )


@pytest.fixture
def app(settings):
    return create_app(settings)


@pytest.fixture
def session_factory(app):
    return app.state.session_factory


@pytest.fixture
def session(session_factory) -> Iterator[Session]:
    session = session_factory()
    try:
        yield session
    finally:
        session.close()


@pytest.fixture
def client(app) -> Iterator[TestClient]:
    with TestClient(app) as c:
        yield c


@pytest.fixture
def auth_headers() -> dict[str, str]:
    return {"Authorization": "Bearer test-token"}


@pytest.fixture
def dev_bypass_app(tmp_path):
    settings = Settings(
        database_url=f"sqlite:///{tmp_path}/bypass.db",
        api_token=None,
        dev_bypass=True,
        cors_origins=("http://localhost:3000",),
    )
    return create_app(settings)


@pytest.fixture
def fresh_engine(tmp_path):
    engine = make_engine(f"sqlite:///{tmp_path}/fresh.db")
    Base.metadata.create_all(engine)
    return engine


@pytest.fixture
def fresh_session(fresh_engine) -> Iterator[Session]:
    factory = make_session_factory(fresh_engine)
    session = factory()
    try:
        yield session
    finally:
        session.close()
