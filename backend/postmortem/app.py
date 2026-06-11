from __future__ import annotations

import logging
import time
import uuid

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .api.analysis_runs import router as analysis_runs_router
from .api.artifacts import router as artifacts_router
from .api.evaluations import router as evaluations_router
from .api.incidents import router as incidents_router
from .api.scenarios import router as scenarios_router
from .auth import configure_auth
from .config import Settings
from .db import Base, ensure_schema_compatibility, make_engine, make_session_factory
from .logging import configure_logging, log_event, request_context
from .services import ensure_default_workspace


logger = logging.getLogger("postmortem.app")


def _database_label(database_url: str) -> str:
    if database_url.startswith("sqlite"):
        return database_url
    return database_url.split("://", 1)[0]


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or Settings.from_env()
    configure_logging(settings.log_level)
    log_event(
        logger,
        logging.INFO,
        "app_starting",
        database=_database_label(settings.database_url),
        dev_bypass=settings.dev_bypass,
        llm_configured=bool(settings.llm_api_key),
        log_level=settings.log_level,
    )
    configure_auth(settings)

    engine = make_engine(settings.database_url)
    Base.metadata.create_all(engine)
    ensure_schema_compatibility(engine)
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

    @app.middleware("http")
    async def log_requests(request, call_next):
        request_id = request.headers.get("x-request-id") or str(uuid.uuid4())
        started = time.perf_counter()
        with request_context(request_id):
            log_event(
                logger,
                logging.INFO,
                "http_request_started",
                method=request.method,
                path=request.url.path,
                client=request.client.host if request.client else None,
            )
            try:
                response = await call_next(request)
            except Exception:
                duration_ms = int((time.perf_counter() - started) * 1000)
                log_event(
                    logger,
                    logging.ERROR,
                    "http_request_failed",
                    method=request.method,
                    path=request.url.path,
                    duration_ms=duration_ms,
                )
                raise
            duration_ms = int((time.perf_counter() - started) * 1000)
            response.headers["X-Request-ID"] = request_id
            log_event(
                logger,
                logging.INFO,
                "http_request_completed",
                method=request.method,
                path=request.url.path,
                status_code=response.status_code,
                duration_ms=duration_ms,
            )
            return response

    @app.get("/healthz", tags=["meta"])
    def healthz() -> dict[str, str]:
        return {"status": "ok"}

    app.include_router(incidents_router)
    app.include_router(artifacts_router)
    app.include_router(analysis_runs_router)
    app.include_router(scenarios_router)
    app.include_router(evaluations_router)
    log_event(logger, logging.INFO, "app_ready")
    return app


app = create_app()
