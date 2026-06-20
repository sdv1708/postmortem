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
(CASE WHEN action_item_id IS NOT NULL THEN 1 ELSE 0 END) +
(CASE WHEN counterclaim_id IS NOT NULL THEN 1 ELSE 0 END) = 1"""
EVIDENCE_REF_ROLE_CHECK = "role IN ('supporting', 'contradicting')"
# Challenge Severity is an enumerated invariant (ADR 0034): a persisted challenge
# must carry one of the three causal-role severities.
HYPOTHESIS_CHALLENGE_SEVERITY_CHECK = "severity IN ('critical', 'material', 'minor')"
# A Causal Factor plays exactly one of the three causal roles (ADR 0039): every
# finalized conclusion has one Failure Mechanism and zero or more Triggers and
# Amplifying Conditions.
CAUSAL_FACTOR_ROLE_CHECK = (
    "role IN ('failure_mechanism', 'trigger', 'amplifying_condition')"
)
# A Remediation Proposal carries one of four review states (ADR 0041): the
# generated default 'proposed', or the human dispositions 'accepted', 'rejected',
# and 'deferred'.
ACTION_ITEM_REVIEW_STATUS_CHECK = (
    "review_status IN ('proposed', 'accepted', 'rejected', 'deferred')"
)
# An accepted Remediation Proposal must point at exactly one of a finalized Causal
# Factor or a documented Evidence Gap, so its purpose is explicit (ADR 0041, PRD
# story 53); any other state carries no link target.
ACTION_ITEM_LINK_CHECK = """\
(review_status = 'accepted' AND
 (CASE WHEN causal_factor_id IS NOT NULL THEN 1 ELSE 0 END) +
 (CASE WHEN evidence_gap_challenge_id IS NOT NULL THEN 1 ELSE 0 END) = 1)
OR
(review_status <> 'accepted' AND causal_factor_id IS NULL
 AND evidence_gap_challenge_id IS NULL)"""

# Tables that are append-only human judgments (ADR 0039 / 0040): a finalized Root
# Cause Conclusion and its Causal Factors are never edited, replaced in place, or
# deleted, and the Conclusion Discrepancies that dispute a conclusion are likewise
# append-only flags. The immutability is enforced in the service and API layers
# and, where the database supports it, by triggers that abort any UPDATE or DELETE.
_IMMUTABLE_APPEND_ONLY_TABLES = (
    "root_cause_conclusions",
    "causal_factors",
    "conclusion_discrepancies",
)


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
                    "counterclaim_id",
                    "role",
                ):
                    condition = condition.replace(column, f"NEW.{column}")
                for operation in ("INSERT", "UPDATE"):
                    # Drop first so a condition change (e.g. adding the counterclaim
                    # owner, ADR 0034) replaces the old trigger; CREATE ... IF NOT
                    # EXISTS would otherwise keep a stale 4-owner check in place.
                    connection.execute(
                        text(f"DROP TRIGGER IF EXISTS ck_evidence_refs_{name}_{operation.lower()}")
                    )
                    connection.execute(
                        text(
                            f"""
                            CREATE TRIGGER ck_evidence_refs_{name}_{operation.lower()}
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
            # Drop-then-add so a changed condition (the counterclaim owner,
            # ADR 0034) supersedes an existing constraint instead of being
            # skipped as a duplicate. Each runs in its own transaction.
            with engine.begin() as connection:
                connection.execute(text(f"ALTER TABLE evidence_refs DROP CONSTRAINT IF EXISTS {name}"))
            try:
                with engine.begin() as connection:
                    connection.execute(
                        text(f"ALTER TABLE evidence_refs ADD CONSTRAINT {name} CHECK ({condition})")
                    )
            except DBAPIError as exc:
                if not _is_duplicate_object_error(exc):
                    raise


def _ensure_append_only_immutability(engine: Engine) -> None:
    """Block UPDATE/DELETE on the append-only conclusion tables (ADR 0039).

    A finalized Root Cause Conclusion is an immutable human judgment: it is never
    edited, replaced in place, or deleted (PRD #26 stories 42-43). The service and
    API layers expose no mutation path, and this adds the database trust floor
    "where supported" — SQLite ABORT triggers and PostgreSQL row triggers that
    raise on any UPDATE or DELETE. Later disagreement is recorded through separate
    append-only Conclusion Discrepancies and Superseding Conclusions, never by
    touching an existing row, so blocking in-place mutation does not constrain
    those future slices.

    Idempotent: triggers are dropped and recreated so a contract change supersedes
    a stale trigger instead of being skipped.
    """
    if engine.dialect.name == "sqlite":
        with engine.begin() as connection:
            existing = {
                row[0]
                for row in connection.execute(
                    text("SELECT name FROM sqlite_master WHERE type = 'table'")
                )
            }
            for table in _IMMUTABLE_APPEND_ONLY_TABLES:
                if table not in existing:
                    continue
                for operation in ("UPDATE", "DELETE"):
                    trigger = f"ck_{table}_no_{operation.lower()}"
                    connection.execute(text(f"DROP TRIGGER IF EXISTS {trigger}"))
                    connection.execute(
                        text(
                            f"""
                            CREATE TRIGGER {trigger}
                            BEFORE {operation} ON {table}
                            BEGIN
                                SELECT RAISE(ABORT, '{table} are immutable (ADR 0039)');
                            END
                            """
                        )
                    )
    elif engine.dialect.name == "postgresql":
        with engine.begin() as connection:
            connection.execute(
                text(
                    """
                    CREATE OR REPLACE FUNCTION postmortem_block_mutation()
                    RETURNS trigger AS $$
                    BEGIN
                        RAISE EXCEPTION 'table % is append-only (ADR 0039)', TG_TABLE_NAME;
                    END;
                    $$ LANGUAGE plpgsql;
                    """
                )
            )
            existing_tables = set(inspect(engine).get_table_names())
            for table in _IMMUTABLE_APPEND_ONLY_TABLES:
                if table not in existing_tables:
                    continue
                trigger = f"ck_{table}_append_only"
                connection.execute(text(f"DROP TRIGGER IF EXISTS {trigger} ON {table}"))
                connection.execute(
                    text(
                        f"""
                        CREATE TRIGGER {trigger}
                        BEFORE UPDATE OR DELETE ON {table}
                        FOR EACH ROW EXECUTE FUNCTION postmortem_block_mutation()
                        """
                    )
                )


def _add_columns_if_missing(
    engine: Engine, inspector, table: str, additions: dict[str, str]
) -> None:
    """Idempotently add columns to ``table`` if it exists and lacks them.

    Each ``ALTER TABLE ADD COLUMN`` runs in its own transaction so a column that
    another process added concurrently is tolerated via the duplicate-column
    error rather than aborting the rest of the batch.
    """
    if table not in inspector.get_table_names():
        return
    existing = {column["name"] for column in inspector.get_columns(table)}
    for column, ddl in additions.items():
        if column in existing:
            continue
        try:
            with engine.begin() as connection:
                connection.execute(text(f"ALTER TABLE {table} ADD COLUMN {column} {ddl}"))
        except DBAPIError as exc:
            if not _is_duplicate_column_error(exc, engine.dialect.name):
                raise


def _migrate_impact_claims_to_run_level(engine: Engine, inspector) -> None:
    """Re-own existing ``impact_claims`` from a hypothesis to the run (ADR 0033).

    Earlier slices stored Impact Claims under ``hypothesis_id``; they are now
    run-level incident facts keyed by ``run_id``. This upgrades existing
    databases in place without losing impact data: each claim's ``run_id`` is
    backfilled from its former hypothesis. The migration is idempotent — once a
    database has the new shape (``run_id`` present, ``hypothesis_id`` absent) it
    is skipped — and runs after the support columns are ensured so the copy can
    rely on them.

    SQLite cannot drop a ``NOT NULL`` column, so the table is rebuilt; PostgreSQL
    adds the column, backfills, enforces ``NOT NULL``, then drops the old one. The
    EvidenceRef ownership constraint is untouched because ``impact_claim_id``
    stays a valid owner and claim ids are preserved.

    The SQLite rebuild deliberately keeps the canonical name ``impact_claims``: it
    builds a temporary ``impact_claims_new`` table, drops the old ``impact_claims``,
    then renames the new table into place. Renaming the *referenced* table instead
    (old → legacy) would make SQLite rewrite ``evidence_refs.impact_claim_id`` to
    point at the legacy name, which then gets dropped — leaving a dangling foreign
    key. Renaming only the new temporary table never touches existing references,
    so EvidenceRefs keep resolving to the rebuilt table and ``PRAGMA
    foreign_key_check`` stays clean.
    """
    if "impact_claims" not in inspector.get_table_names():
        return
    columns = {column["name"] for column in inspector.get_columns("impact_claims")}
    if "run_id" in columns or "hypothesis_id" not in columns:
        # Already migrated (or a fresh DB created from the current model).
        return

    if engine.dialect.name == "sqlite":
        # PRAGMA foreign_keys is connection-scoped and only effective outside a
        # transaction, so run the whole rebuild on one AUTOCOMMIT connection with
        # enforcement disabled. DROP IF EXISTS guards a re-run after a partial
        # failure (the idempotency check above otherwise re-enters this branch).
        with engine.connect().execution_options(isolation_level="AUTOCOMMIT") as connection:
            connection.exec_driver_sql("PRAGMA foreign_keys=OFF")
            connection.exec_driver_sql("DROP TABLE IF EXISTS impact_claims_new")
            connection.exec_driver_sql(
                """
                CREATE TABLE impact_claims_new (
                    id VARCHAR(36) NOT NULL PRIMARY KEY,
                    run_id VARCHAR(36) NOT NULL REFERENCES analysis_runs(id) ON DELETE CASCADE,
                    sequence INTEGER NOT NULL,
                    description TEXT NOT NULL,
                    assumption BOOLEAN NOT NULL DEFAULT 0,
                    support_status VARCHAR(16) NOT NULL DEFAULT 'unevaluated',
                    support_rationale TEXT,
                    created_at DATETIME NOT NULL
                )
                """
            )
            # Inner join on the former hypothesis backfills run_id; any orphaned
            # claim (its hypothesis already gone) carries no run and is dropped.
            connection.exec_driver_sql(
                """
                INSERT INTO impact_claims_new
                    (id, run_id, sequence, description, assumption,
                     support_status, support_rationale, created_at)
                SELECT ic.id, h.run_id, ic.sequence, ic.description, ic.assumption,
                       COALESCE(ic.support_status, 'unevaluated'),
                       ic.support_rationale, ic.created_at
                FROM impact_claims ic
                JOIN hypotheses h ON h.id = ic.hypothesis_id
                """
            )
            # Drop the old table, then rename the new one into its place. Renaming
            # the *new* (unreferenced) table never rewrites existing
            # evidence_refs.impact_claim_id references, so they keep resolving to
            # ``impact_claims`` and PRAGMA foreign_key_check stays clean.
            connection.exec_driver_sql("DROP TABLE impact_claims")
            connection.exec_driver_sql(
                "ALTER TABLE impact_claims_new RENAME TO impact_claims"
            )
            connection.exec_driver_sql(
                "CREATE INDEX ix_impact_claims_run_id ON impact_claims (run_id)"
            )
            connection.exec_driver_sql("PRAGMA foreign_keys=ON")
    elif engine.dialect.name == "postgresql":
        with engine.begin() as connection:
            connection.execute(
                text(
                    "ALTER TABLE impact_claims ADD COLUMN run_id VARCHAR(36) "
                    "REFERENCES analysis_runs(id) ON DELETE CASCADE"
                )
            )
            connection.execute(
                text(
                    """
                    UPDATE impact_claims AS ic
                    SET run_id = h.run_id
                    FROM hypotheses AS h
                    WHERE h.id = ic.hypothesis_id
                    """
                )
            )
            # Drop claims that could not be re-owned so the NOT NULL invariant can
            # be enforced without weakening it.
            connection.execute(text("DELETE FROM impact_claims WHERE run_id IS NULL"))
            connection.execute(text("ALTER TABLE impact_claims ALTER COLUMN run_id SET NOT NULL"))
            connection.execute(text("ALTER TABLE impact_claims DROP COLUMN hypothesis_id"))
            connection.execute(
                text("CREATE INDEX IF NOT EXISTS ix_impact_claims_run_id ON impact_claims (run_id)")
            )


def ensure_schema_compatibility(engine: Engine) -> None:
    """Apply the narrow schema additions needed by existing MVP databases.

    The project does not have a migration framework yet. ``create_all`` creates
    new tables but does not add columns to tables created by earlier slices, so
    keep these small, explicit, idempotent column upgrades per table.
    """
    inspector = inspect(engine)
    if "evidence_refs" not in inspector.get_table_names():
        return

    _add_columns_if_missing(
        engine,
        inspector,
        "evidence_refs",
        {
            "hypothesis_id": "VARCHAR(36) REFERENCES hypotheses(id) ON DELETE CASCADE",
            "impact_claim_id": "VARCHAR(36) REFERENCES impact_claims(id) ON DELETE CASCADE",
            "action_item_id": "VARCHAR(36) REFERENCES action_items(id) ON DELETE CASCADE",
            # Counterclaim ownership for falsifier-generated Major Claims (ADR 0034).
            # create_all has already created the counterclaims table, so the FK
            # target exists before this column is added to an existing database.
            "counterclaim_id": "VARCHAR(36) REFERENCES counterclaims(id) ON DELETE CASCADE",
            "role": "VARCHAR(16) NOT NULL DEFAULT 'supporting'",
            # Citation-integrity status added in slice #7 (ADR 0014); existing refs
            # default to 'unverified' until a run re-verifies them.
            "verifier_status": "VARCHAR(24) NOT NULL DEFAULT 'unverified'",
        },
    )
    # Semantic claim-support columns added in slice #8 (ADR 0014); existing Major
    # Claims default to 'unevaluated' until the flagging stage classifies them.
    support_columns = {
        "support_status": "VARCHAR(16) NOT NULL DEFAULT 'unevaluated'",
        "support_rationale": "TEXT",
    }
    _add_columns_if_missing(engine, inspector, "hypotheses", support_columns)
    _add_columns_if_missing(engine, inspector, "impact_claims", support_columns)

    # Hypothesis provenance added in slice #30 (ADR 0036): existing hypotheses are
    # builder-generated, so they default to 'initial'. Proposed alternatives from
    # the falsifier's bounded expansion round carry 'proposed'.
    _add_columns_if_missing(
        engine,
        inspector,
        "hypotheses",
        {"origin": "VARCHAR(16) NOT NULL DEFAULT 'initial'"},
    )

    # Advisory Hypothesis Ranking added in slice #31 (ADR 0037): existing
    # hypotheses have no advisory rank or rationale until a run re-ranks them, so
    # both are nullable. ``rank`` continues to hold the original builder order.
    # Nullable INTEGER/JSON ddl is valid on both SQLite and PostgreSQL.
    _add_columns_if_missing(
        engine,
        inspector,
        "hypotheses",
        {
            "advisory_rank": "INTEGER",
            "ranking_rationale": "JSON",
        },
    )

    # Re-own Impact Claims from a hypothesis to the run (ADR 0033). Runs after the
    # support columns exist so the SQLite table rebuild can copy them.
    _migrate_impact_claims_to_run_level(engine, inspect(engine))

    # Rename persisted Run Stage identifiers to the ADR 0033 names so existing runs
    # still read through the renamed-stage API contract (RunStageEventRead only
    # accepts the new literals). Idempotent: the UPDATEs match only old values.
    if "run_stage_events" in inspector.get_table_names():
        with engine.begin() as connection:
            connection.execute(
                text(
                    "UPDATE run_stage_events SET stage = 'extracting_incident_facts' "
                    "WHERE stage = 'extracting_timeline_candidates'"
                )
            )
            connection.execute(
                text(
                    "UPDATE run_stage_events SET stage = 'analyzing_causal_hypotheses' "
                    "WHERE stage = 'generating_rca_hypotheses'"
                )
            )

    # Refusal/sufficiency assessment added in slice #12 (ADR 0032). Existing
    # postmortems default to 'sufficient'; the JSON lists read as NULL → [] until a
    # run re-drafts them. JSON ddl is valid on both SQLite and PostgreSQL.
    _add_columns_if_missing(
        engine,
        inspector,
        "postmortems",
        {
            "evidence_sufficiency": "VARCHAR(16) NOT NULL DEFAULT 'sufficient'",
            "evidence_gaps": "JSON",
            "next_validation_steps": "JSON",
            # Provisional/finalized lifecycle added in slice #29 (ADR 0035).
            # Existing automated drafts are provisional: no human Root Cause
            # Conclusion has been finalized for them.
            "conclusion_status": "VARCHAR(16) NOT NULL DEFAULT 'provisional'",
        },
    )

    # Remediation Proposal decision overlay added in slice #35 (ADR 0041). Existing
    # generated action items default to 'proposed' with no decision or link until a
    # reviewer decides. The CHECK constraints (review-status enum, accepted-link)
    # apply to fresh create_all tables; the service is the always-on trust floor for
    # databases whose action_items predate them. Nullable FK ddl is valid on both
    # SQLite and PostgreSQL.
    _add_columns_if_missing(
        engine,
        inspector,
        "action_items",
        {
            "review_status": "VARCHAR(16) NOT NULL DEFAULT 'proposed'",
            "decision_rationale": "TEXT",
            "decided_by_principal": "VARCHAR(255)",
            "decided_by_display": "VARCHAR(255)",
            # TIMESTAMP is portable: PostgreSQL-native, and accepted by SQLite (where
            # the model's DateTime type still governs value conversion). 'DATETIME'
            # is a SQLite-only spelling and errors on PostgreSQL.
            "decided_at": "TIMESTAMP",
            "causal_factor_id": "VARCHAR(36) REFERENCES causal_factors(id) ON DELETE SET NULL",
            "evidence_gap_challenge_id": (
                "VARCHAR(36) REFERENCES hypothesis_challenges(id) ON DELETE SET NULL"
            ),
            "evidence_gap_index": "INTEGER",
        },
    )

    indexes = {
        "hypothesis_id": "ix_evidence_refs_hypothesis_id",
        "impact_claim_id": "ix_evidence_refs_impact_claim_id",
        "action_item_id": "ix_evidence_refs_action_item_id",
        "counterclaim_id": "ix_evidence_refs_counterclaim_id",
    }
    with engine.begin() as connection:
        for column, index in indexes.items():
            connection.execute(
                text(f"CREATE INDEX IF NOT EXISTS {index} ON evidence_refs ({column})")
            )
    # Indexes backing the Remediation Proposal link lookups (ADR 0041).
    if "action_items" in inspect(engine).get_table_names():
        with engine.begin() as connection:
            for column, index in (
                ("causal_factor_id", "ix_action_items_causal_factor_id"),
                ("evidence_gap_challenge_id", "ix_action_items_evidence_gap_challenge_id"),
            ):
                connection.execute(
                    text(f"CREATE INDEX IF NOT EXISTS {index} ON action_items ({column})")
                )
    _ensure_evidence_ref_constraints(engine)
    # Root Cause Conclusion tables are created by create_all; make them append-only
    # immutable at the database layer where supported (ADR 0039).
    _ensure_append_only_immutability(engine)
    # Backstop the single-conclusion-per-run invariant at the DB boundary so a
    # check-then-insert race cannot persist two immutable conclusions for one run
    # (ADR 0039). create_all builds this for fresh databases; this idempotent index
    # upgrades a dev database whose table predates the unique constraint.
    if "root_cause_conclusions" in inspect(engine).get_table_names():
        with engine.begin() as connection:
            connection.execute(
                text(
                    "CREATE UNIQUE INDEX IF NOT EXISTS ux_root_cause_conclusions_run_id "
                    "ON root_cause_conclusions (run_id)"
                )
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
