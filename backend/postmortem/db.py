from __future__ import annotations

from collections.abc import Iterator

from sqlalchemy import create_engine, inspect, text
from sqlalchemy.engine import Engine
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker


EVIDENCE_REF_OWNER_CHECK = """\
(CASE WHEN timeline_event_id IS NOT NULL THEN 1 ELSE 0 END) +
(CASE WHEN hypothesis_id IS NOT NULL THEN 1 ELSE 0 END) +
(CASE WHEN impact_claim_id IS NOT NULL THEN 1 ELSE 0 END) +
(CASE WHEN action_item_id IS NOT NULL THEN 1 ELSE 0 END) = 1"""
EVIDENCE_REF_ROLE_CHECK = "role IN ('supporting', 'contradicting')"


class Base(DeclarativeBase):
    pass


def make_engine(database_url: str) -> Engine:
    connect_args = {"check_same_thread": False} if database_url.startswith("sqlite") else {}
    return create_engine(database_url, connect_args=connect_args, future=True)


def make_session_factory(engine: Engine) -> sessionmaker[Session]:
    return sessionmaker(bind=engine, autoflush=False, expire_on_commit=False, future=True)


def _is_duplicate_column_error(exc: DBAPIError, dialect_name: str) -> bool:
    if dialect_name == "sqlite":
        return "duplicate column name" in str(exc.orig).lower()
    return getattr(exc.orig, "sqlstate", None) == "42701" or getattr(
        exc.orig, "pgcode", None
    ) == "42701"


def _is_duplicate_object_error(exc: DBAPIError) -> bool:
    return getattr(exc.orig, "sqlstate", None) == "42710" or getattr(
        exc.orig, "pgcode", None
    ) == "42710"


def _ensure_evidence_ref_constraints(engine: Engine) -> None:
    if engine.dialect.name == "sqlite":
        checks = {
            "exactly_one_owner": EVIDENCE_REF_OWNER_CHECK,
            "allowed_role": EVIDENCE_REF_ROLE_CHECK,
        }
        with engine.begin() as connection:
            invalid_count = connection.scalar(
                text(
                    f"""
                    SELECT COUNT(*) FROM evidence_refs
                    WHERE NOT ({EVIDENCE_REF_OWNER_CHECK})
                       OR NOT ({EVIDENCE_REF_ROLE_CHECK})
                    """
                )
            )
            if invalid_count:
                raise RuntimeError("existing evidence_refs violate ownership or role constraints")
            for name, condition in checks.items():
                for column in (
                    "timeline_event_id",
                    "hypothesis_id",
                    "impact_claim_id",
                    "action_item_id",
                    "role",
                ):
                    condition = condition.replace(column, f"NEW.{column}")
                for operation in ("INSERT", "UPDATE"):
                    connection.execute(
                        text(
                            f"""
                            CREATE TRIGGER IF NOT EXISTS ck_evidence_refs_{name}_{operation.lower()}
                            BEFORE {operation} ON evidence_refs
                            WHEN NOT ({condition})
                            BEGIN
                                SELECT RAISE(ABORT, 'ck_evidence_refs_{name}');
                            END
                            """
                        )
                    )
    elif engine.dialect.name == "postgresql":
        checks = {
            "ck_evidence_refs_exactly_one_owner": EVIDENCE_REF_OWNER_CHECK,
            "ck_evidence_refs_allowed_role": EVIDENCE_REF_ROLE_CHECK,
        }
        for name, condition in checks.items():
            try:
                with engine.begin() as connection:
                    connection.execute(
                        text(f"ALTER TABLE evidence_refs ADD CONSTRAINT {name} CHECK ({condition})")
                    )
            except DBAPIError as exc:
                if not _is_duplicate_object_error(exc):
                    raise


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
        # Citation-integrity status added in slice #7 (ADR 0014); existing refs
        # default to 'unverified' until a run re-verifies them.
        "verifier_status": "VARCHAR(24) NOT NULL DEFAULT 'unverified'",
    }
    indexes = {
        "hypothesis_id": "ix_evidence_refs_hypothesis_id",
        "impact_claim_id": "ix_evidence_refs_impact_claim_id",
        "action_item_id": "ix_evidence_refs_action_item_id",
    }
    for column, ddl in additions.items():
        if column not in existing:
            try:
                with engine.begin() as connection:
                    connection.execute(
                        text(f"ALTER TABLE evidence_refs ADD COLUMN {column} {ddl}")
                    )
            except DBAPIError as exc:
                if not _is_duplicate_column_error(exc, engine.dialect.name):
                    raise
    with engine.begin() as connection:
        for column, index in indexes.items():
            connection.execute(
                text(f"CREATE INDEX IF NOT EXISTS {index} ON evidence_refs ({column})")
            )
    _ensure_evidence_ref_constraints(engine)


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
