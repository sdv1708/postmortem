from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .api.artifacts import router as artifacts_router
from .api.incidents import router as incidents_router
from .auth import configure_auth
from .config import Settings
from .db import Base, make_engine, make_session_factory
from .services import ensure_default_workspace


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or Settings.from_env()
    configure_auth(settings)

    engine = make_engine(settings.database_url)
    Base.metadata.create_all(engine)
    session_factory = make_session_factory(engine)

    with session_factory() as session:
        ensure_default_workspace(session)
        session.commit()

    app = FastAPI(title="Postmortem Agent", version="0.0.1")
    app.state.engine = engine
    app.state.session_factory = session_factory
    app.state.settings = settings

    app.add_middleware(
        CORSMiddleware,
        allow_origins=list(settings.cors_origins),
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.get("/healthz", tags=["meta"])
    def healthz() -> dict[str, str]:
        return {"status": "ok"}

    app.include_router(incidents_router)
    app.include_router(artifacts_router)
    return app


app = create_app()
