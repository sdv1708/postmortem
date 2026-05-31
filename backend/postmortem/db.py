from __future__ import annotations

from collections.abc import Iterator

from sqlalchemy import create_engine, inspect, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker


class Base(DeclarativeBase):
    pass


def make_engine(database_url: str) -> Engine:
    connect_args = {"check_same_thread": False} if database_url.startswith("sqlite") else {}
    return create_engine(database_url, connect_args=connect_args, future=True)


def make_session_factory(engine: Engine) -> sessionmaker[Session]:
    return sessionmaker(bind=engine, autoflush=False, expire_on_commit=False, future=True)


def ensure_schema_compatibility(engine: Engine) -> None:
    """Apply the narrow schema additions needed by existing MVP databases.

    The project does not have a migration framework yet. ``create_all`` creates
    new tables but does not add columns to tables created by earlier slices, so
    keep the small evidence_refs upgrade explicit and idempotent.
    """
    inspector = inspect(engine)
    if "evidence_refs" not in inspector.get_table_names():
        return

    existing = {column["name"] for column in inspector.get_columns("evidence_refs")}
    additions = {
        "hypothesis_id": "VARCHAR(36) REFERENCES hypotheses(id) ON DELETE CASCADE",
        "impact_claim_id": "VARCHAR(36) REFERENCES impact_claims(id) ON DELETE CASCADE",
        "action_item_id": "VARCHAR(36) REFERENCES action_items(id) ON DELETE CASCADE",
        "role": "VARCHAR(16) NOT NULL DEFAULT 'supporting'",
    }
    indexes = {
        "hypothesis_id": "ix_evidence_refs_hypothesis_id",
        "impact_claim_id": "ix_evidence_refs_impact_claim_id",
        "action_item_id": "ix_evidence_refs_action_item_id",
    }
    with engine.begin() as connection:
        for column, ddl in additions.items():
            if column not in existing:
                connection.execute(text(f"ALTER TABLE evidence_refs ADD COLUMN {column} {ddl}"))
        for column, index in indexes.items():
            connection.execute(
                text(f"CREATE INDEX IF NOT EXISTS {index} ON evidence_refs ({column})")
            )


def session_scope(session_factory: sessionmaker[Session]) -> Iterator[Session]:
    session = session_factory()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
