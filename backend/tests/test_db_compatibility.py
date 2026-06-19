from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

import pytest
from sqlalchemy import inspect, text
from sqlalchemy.exc import DBAPIError, IntegrityError

from postmortem.app import create_app
from postmortem.config import Settings
from postmortem.db import (
    Base,
    _is_duplicate_column_error,
    _is_duplicate_object_error,
    ensure_schema_compatibility,
    make_engine,
)


def _create_issue_6_evidence_refs_table(engine):
    with engine.begin() as connection:
        connection.execute(
            text(
                """
                CREATE TABLE evidence_refs (
                    id VARCHAR(36) NOT NULL PRIMARY KEY,
                    timeline_event_id VARCHAR(36),
                    artifact_id VARCHAR(36) NOT NULL,
                    source_name VARCHAR(255) NOT NULL,
                    line_start INTEGER NOT NULL,
                    line_end INTEGER NOT NULL,
                    snippet TEXT NOT NULL,
                    confidence_score FLOAT NOT NULL,
                    created_at DATETIME NOT NULL
                )
                """
            )
        )


def _insert_evidence_ref(engine, ref_id, *, role="supporting", verifier_status="unverified", **owners):
    values = {
        "id": ref_id,
        "timeline_event_id": None,
        "hypothesis_id": None,
        "impact_claim_id": None,
        "action_item_id": None,
        "counterclaim_id": None,
        "role": role,
        "verifier_status": verifier_status,
        **owners,
    }
    with engine.begin() as connection:
        connection.execute(
            text(
                """
                INSERT INTO evidence_refs (
                    id, timeline_event_id, hypothesis_id, impact_claim_id,
                    action_item_id, counterclaim_id, role, verifier_status, artifact_id,
                    source_name, line_start, line_end, snippet, confidence_score,
                    created_at
                ) VALUES (
                    :id, :timeline_event_id, :hypothesis_id, :impact_claim_id,
                    :action_item_id, :counterclaim_id, :role, :verifier_status, 'artifact-id',
                    'api.log', 1, 1, 'line one', 1.0, '2026-06-01 00:00:00'
                )
                """
            ),
            values,
        )


def _assert_invalid_refs_rejected(engine):
    with pytest.raises(IntegrityError):
        _insert_evidence_ref(engine, "zero-owner")
    with pytest.raises(IntegrityError):
        _insert_evidence_ref(
            engine,
            "multiple-owners",
            timeline_event_id="timeline-id",
            hypothesis_id="hypothesis-id",
        )
    with pytest.raises(IntegrityError):
        _insert_evidence_ref(
            engine,
            "invalid-role",
            timeline_event_id="timeline-id",
            role="untrusted",
        )


def test_fresh_schema_enforces_evidence_ref_invariants(tmp_path):
    engine = make_engine(f"sqlite:///{tmp_path}/fresh.db")
    Base.metadata.create_all(engine)

    _assert_invalid_refs_rejected(engine)
    _insert_evidence_ref(engine, "valid-ref", timeline_event_id="timeline-id")


def test_create_app_upgrades_issue_6_evidence_refs_table(tmp_path):
    database_url = f"sqlite:///{tmp_path}/issue-6.db"
    engine = make_engine(database_url)
    _create_issue_6_evidence_refs_table(engine)

    create_app(
        Settings(
            database_url=database_url,
            api_token=None,
            dev_bypass=True,
            cors_origins=(),
        )
    )

    inspector = inspect(engine)
    columns = {column["name"] for column in inspector.get_columns("evidence_refs")}
    assert {
        "hypothesis_id",
        "impact_claim_id",
        "action_item_id",
        "role",
        "verifier_status",
    } <= columns
    indexes = {index["name"] for index in inspector.get_indexes("evidence_refs")}
    assert {
        "ix_evidence_refs_hypothesis_id",
        "ix_evidence_refs_impact_claim_id",
        "ix_evidence_refs_action_item_id",
    } <= indexes
    _assert_invalid_refs_rejected(engine)
    _insert_evidence_ref(engine, "valid-ref", timeline_event_id="timeline-id")


def test_create_app_adds_counterclaim_owner_to_evidence_refs(tmp_path):
    """An existing evidence_refs table gains the counterclaim owner (ADR 0034).

    The 5-owner exactly-one-owner invariant must hold afterward: a counterclaim-
    only citation is valid, while pairing the counterclaim owner with another
    owner is rejected.
    """
    database_url = f"sqlite:///{tmp_path}/issue-28.db"
    engine = make_engine(database_url)
    _create_issue_6_evidence_refs_table(engine)

    create_app(
        Settings(database_url=database_url, api_token=None, dev_bypass=True, cors_origins=())
    )

    inspector = inspect(engine)
    columns = {column["name"] for column in inspector.get_columns("evidence_refs")}
    assert "counterclaim_id" in columns
    indexes = {index["name"] for index in inspector.get_indexes("evidence_refs")}
    assert "ix_evidence_refs_counterclaim_id" in indexes

    # A counterclaim-owned citation is now a valid single owner.
    _insert_evidence_ref(engine, "counterclaim-ref", counterclaim_id="counterclaim-id")
    # Pairing the new owner with another still violates exactly-one-owner.
    with pytest.raises(IntegrityError):
        _insert_evidence_ref(
            engine,
            "counterclaim-plus-timeline",
            counterclaim_id="counterclaim-id",
            timeline_event_id="timeline-id",
        )
    # The pre-existing invariants still hold after the owner set grew.
    _assert_invalid_refs_rejected(engine)


def _create_issue_7_claim_tables(engine):
    """Hypotheses + impact_claims as they existed before slice #8 (no support cols)."""
    with engine.begin() as connection:
        connection.execute(
            text(
                """
                CREATE TABLE hypotheses (
                    id VARCHAR(36) NOT NULL PRIMARY KEY,
                    run_id VARCHAR(36) NOT NULL,
                    rank INTEGER NOT NULL,
                    title VARCHAR(255) NOT NULL,
                    summary TEXT NOT NULL,
                    assumption BOOLEAN NOT NULL,
                    review_status VARCHAR(16) NOT NULL,
                    unknowns JSON NOT NULL,
                    validation_steps JSON NOT NULL,
                    created_at DATETIME NOT NULL
                )
                """
            )
        )
        connection.execute(
            text(
                """
                CREATE TABLE impact_claims (
                    id VARCHAR(36) NOT NULL PRIMARY KEY,
                    hypothesis_id VARCHAR(36) NOT NULL,
                    sequence INTEGER NOT NULL,
                    description TEXT NOT NULL,
                    assumption BOOLEAN NOT NULL,
                    created_at DATETIME NOT NULL
                )
                """
            )
        )


def test_create_app_upgrades_issue_7_claim_tables(tmp_path):
    database_url = f"sqlite:///{tmp_path}/issue-7.db"
    engine = make_engine(database_url)
    # evidence_refs must exist for the upgrade to run; pre-create the claim tables
    # without the slice-#8 support columns.
    _create_issue_6_evidence_refs_table(engine)
    _create_issue_7_claim_tables(engine)

    create_app(
        Settings(database_url=database_url, api_token=None, dev_bypass=True, cors_origins=())
    )

    inspector = inspect(engine)
    for table in ("hypotheses", "impact_claims"):
        columns = {column["name"] for column in inspector.get_columns(table)}
        assert {"support_status", "support_rationale"} <= columns


def test_create_app_migrates_impact_claims_to_run_level(tmp_path):
    """Existing impact_claims are re-owned to the run without losing data (ADR 0033)."""
    database_url = f"sqlite:///{tmp_path}/issue-27.db"
    engine = make_engine(database_url)
    _create_issue_6_evidence_refs_table(engine)
    _create_issue_7_claim_tables(engine)

    # Seed a hypothesis and an impact claim under the pre-#27 hypothesis-owned shape.
    with engine.begin() as connection:
        connection.execute(
            text(
                """
                INSERT INTO hypotheses (
                    id, run_id, rank, title, summary, assumption, review_status,
                    unknowns, validation_steps, created_at
                ) VALUES (
                    'hyp-1', 'run-xyz', 1, 'Cause', 'Summary', 0, 'proposed',
                    '[]', '[]', '2026-06-01 00:00:00'
                )
                """
            )
        )
        connection.execute(
            text(
                """
                INSERT INTO impact_claims (
                    id, hypothesis_id, sequence, description, assumption, created_at
                ) VALUES (
                    'imp-1', 'hyp-1', 1, 'Users saw 500s', 0, '2026-06-01 00:00:00'
                )
                """
            )
        )

    create_app(
        Settings(database_url=database_url, api_token=None, dev_bypass=True, cors_origins=())
    )

    columns = {column["name"] for column in inspect(engine).get_columns("impact_claims")}
    # Re-owned to the run; the former hypothesis ownership column is gone.
    assert "run_id" in columns
    assert "hypothesis_id" not in columns
    with engine.begin() as connection:
        rows = connection.execute(
            text("SELECT id, run_id, description FROM impact_claims")
        ).all()
    # The impact data is preserved and its run_id is backfilled from the hypothesis.
    assert rows == [("imp-1", "run-xyz", "Users saw 500s")]


def test_impact_migration_keeps_evidence_ref_foreign_keys_valid(tmp_path):
    """Re-owning impact_claims must not dangle EvidenceRef foreign keys (ADR 0033)."""
    database_url = f"sqlite:///{tmp_path}/issue-27-fk.db"
    engine = make_engine(database_url)
    _create_issue_7_claim_tables(engine)  # hypotheses + pre-#27 impact_claims
    # An evidence_refs table from the post-#8 era (already has impact_claim_id),
    # with a citation owned by an impact claim.
    with engine.begin() as connection:
        connection.execute(
            text(
                """
                CREATE TABLE evidence_refs (
                    id VARCHAR(36) NOT NULL PRIMARY KEY,
                    timeline_event_id VARCHAR(36),
                    hypothesis_id VARCHAR(36),
                    impact_claim_id VARCHAR(36) REFERENCES impact_claims(id) ON DELETE CASCADE,
                    action_item_id VARCHAR(36),
                    role VARCHAR(16) NOT NULL DEFAULT 'supporting',
                    artifact_id VARCHAR(36) NOT NULL,
                    source_name VARCHAR(255) NOT NULL,
                    line_start INTEGER NOT NULL,
                    line_end INTEGER NOT NULL,
                    snippet TEXT NOT NULL,
                    confidence_score FLOAT NOT NULL,
                    verifier_status VARCHAR(24) NOT NULL DEFAULT 'unverified',
                    created_at DATETIME NOT NULL
                )
                """
            )
        )
        connection.execute(
            text(
                """
                INSERT INTO hypotheses (
                    id, run_id, rank, title, summary, assumption, review_status,
                    unknowns, validation_steps, created_at
                ) VALUES (
                    'hyp-1', 'run-xyz', 1, 'Cause', 'Summary', 0, 'proposed',
                    '[]', '[]', '2026-06-01 00:00:00'
                )
                """
            )
        )
        connection.execute(
            text(
                """
                INSERT INTO impact_claims (
                    id, hypothesis_id, sequence, description, assumption, created_at
                ) VALUES (
                    'imp-1', 'hyp-1', 1, 'Users saw 500s', 0, '2026-06-01 00:00:00'
                )
                """
            )
        )
        connection.execute(
            text(
                """
                INSERT INTO evidence_refs (
                    id, impact_claim_id, role, artifact_id, source_name,
                    line_start, line_end, snippet, confidence_score, verifier_status, created_at
                ) VALUES (
                    'ref-1', 'imp-1', 'supporting', 'art-1', 'api.log',
                    1, 1, 'line one', 1.0, 'verified', '2026-06-01 00:00:00'
                )
                """
            )
        )

    create_app(
        Settings(database_url=database_url, api_token=None, dev_bypass=True, cors_origins=())
    )

    with engine.connect().execution_options(isolation_level="AUTOCOMMIT") as connection:
        connection.exec_driver_sql("PRAGMA foreign_keys=ON")
        # The impact-owned citation still references the rebuilt impact_claims table
        # (not a dropped legacy/temp table), so the FK integrity check is clean.
        fk_tables = {
            row[2] for row in connection.exec_driver_sql(
                "PRAGMA foreign_key_list(evidence_refs)"
            ).fetchall()
        }
        assert "impact_claims" in fk_tables
        assert "impact_claims_legacy" not in fk_tables
        assert "impact_claims_new" not in fk_tables
        # No evidence_refs citation dangles after the rebuild. (Other foreign_key
        # _check rows can appear only because this minimal fixture omits the
        # analysis_runs row that impact_claims.run_id points at — unrelated to the
        # citation FK under test, which is what the buggy migration broke.)
        violations = connection.exec_driver_sql("PRAGMA foreign_key_check").fetchall()
        evidence_ref_violations = [row for row in violations if row[0] == "evidence_refs"]
        assert evidence_ref_violations == []
        # The citation and its migrated, re-owned impact claim both survive.
        ref = connection.exec_driver_sql(
            "SELECT impact_claim_id FROM evidence_refs WHERE id = 'ref-1'"
        ).fetchall()
        claim = connection.exec_driver_sql(
            "SELECT run_id FROM impact_claims WHERE id = 'imp-1'"
        ).fetchall()
    assert ref == [("imp-1",)]
    assert claim == [("run-xyz",)]


def _create_legacy_run_stage_events_table(engine):
    with engine.begin() as connection:
        connection.execute(
            text(
                """
                CREATE TABLE run_stage_events (
                    id VARCHAR(36) NOT NULL PRIMARY KEY,
                    run_id VARCHAR(36) NOT NULL,
                    sequence INTEGER NOT NULL,
                    stage VARCHAR(64) NOT NULL,
                    status VARCHAR(16) NOT NULL,
                    attempt INTEGER NOT NULL,
                    warning_codes JSON NOT NULL,
                    created_at DATETIME NOT NULL
                )
                """
            )
        )
        for seq, stage in enumerate(
            [
                "normalizing_evidence",
                "extracting_timeline_candidates",
                "generating_rca_hypotheses",
                "verifying_citations",
            ],
            start=1,
        ):
            connection.execute(
                text(
                    """
                    INSERT INTO run_stage_events (
                        id, run_id, sequence, stage, status, attempt, warning_codes, created_at
                    ) VALUES (
                        :id, 'run-1', :seq, :stage, 'succeeded', 1, '[]', '2026-06-01 00:00:00'
                    )
                    """
                ),
                {"id": f"evt-{seq}", "seq": seq, "stage": stage},
            )


def test_create_app_renames_legacy_run_stage_identifiers(tmp_path):
    """Persisted run stage identifiers are renamed to the ADR 0033 names.

    Otherwise an old run's stage values fall outside the RunStage literal and
    reading it through the API fails response validation.
    """
    from postmortem.schemas import RunStageEventRead

    database_url = f"sqlite:///{tmp_path}/issue-27-stages.db"
    engine = make_engine(database_url)
    _create_issue_6_evidence_refs_table(engine)
    _create_legacy_run_stage_events_table(engine)

    create_app(
        Settings(database_url=database_url, api_token=None, dev_bypass=True, cors_origins=())
    )

    with engine.connect().execution_options(isolation_level="AUTOCOMMIT") as connection:
        stages = [
            row[0]
            for row in connection.exec_driver_sql(
                "SELECT stage FROM run_stage_events ORDER BY sequence"
            ).fetchall()
        ]
    assert stages == [
        "normalizing_evidence",
        "extracting_incident_facts",
        "analyzing_causal_hypotheses",
        "verifying_citations",
    ]
    # The migrated values are all accepted by the API response schema.
    for seq, stage in enumerate(stages, start=1):
        RunStageEventRead.model_validate(
            {
                "id": f"evt-{seq}",
                "sequence": seq,
                "stage": stage,
                "status": "succeeded",
                "attempt": 1,
                "started_at": None,
                "completed_at": None,
                "duration_ms": None,
                "usage": None,
                "warning_codes": [],
                "error": None,
            }
        )


def _create_issue_11_postmortems_table(engine):
    """Postmortems before slice #12 had no refusal/sufficiency columns."""
    with engine.begin() as connection:
        connection.execute(
            text(
                """
                CREATE TABLE postmortems (
                    id VARCHAR(36) NOT NULL PRIMARY KEY,
                    run_id VARCHAR(36) NOT NULL UNIQUE,
                    summary TEXT NOT NULL,
                    lessons_learned JSON NOT NULL,
                    composer_version VARCHAR(64) NOT NULL,
                    created_at DATETIME NOT NULL
                )
                """
            )
        )


def test_create_app_upgrades_issue_11_postmortems_table(tmp_path):
    database_url = f"sqlite:///{tmp_path}/issue-11.db"
    engine = make_engine(database_url)
    # Compatibility currently starts from the evidence_refs-era schema.
    _create_issue_6_evidence_refs_table(engine)
    _create_issue_11_postmortems_table(engine)

    create_app(
        Settings(database_url=database_url, api_token=None, dev_bypass=True, cors_origins=())
    )

    columns = {column["name"] for column in inspect(engine).get_columns("postmortems")}
    assert {
        "evidence_sufficiency",
        "evidence_gaps",
        "next_validation_steps",
        # Provisional/finalized lifecycle added in slice #29 (ADR 0035).
        "conclusion_status",
    } <= columns


def test_schema_compatibility_rejects_existing_orphaned_evidence_ref(tmp_path):
    database_url = f"sqlite:///{tmp_path}/orphaned-ref.db"
    engine = make_engine(database_url)
    _create_issue_6_evidence_refs_table(engine)
    with engine.begin() as connection:
        connection.execute(
            text(
                """
                INSERT INTO evidence_refs (
                    id, timeline_event_id, artifact_id, source_name, line_start,
                    line_end, snippet, confidence_score, created_at
                ) VALUES (
                    'orphaned-ref', NULL, 'artifact-id', 'api.log', 1, 1,
                    'line one', 1.0, '2026-06-01 00:00:00'
                )
                """
            )
        )

    with pytest.raises(RuntimeError, match="existing evidence_refs violate"):
        create_app(
            Settings(
                database_url=database_url,
                api_token=None,
                dev_bypass=True,
                cors_origins=(),
            )
        )


def test_schema_compatibility_tolerates_concurrent_column_additions(tmp_path, monkeypatch):
    engine = make_engine(f"sqlite:///{tmp_path}/concurrent-upgrade.db")
    _create_issue_6_evidence_refs_table(engine)
    barrier = Barrier(2)
    real_inspect = inspect

    def synchronized_inspect(bind):
        inspector = real_inspect(bind)
        real_get_columns = inspector.get_columns

        def get_columns(table_name):
            columns = real_get_columns(table_name)
            barrier.wait()
            return columns

        inspector.get_columns = get_columns
        return inspector

    monkeypatch.setattr("postmortem.db.inspect", synchronized_inspect)

    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = [executor.submit(ensure_schema_compatibility, engine) for _ in range(2)]
        for future in futures:
            future.result()


def test_duplicate_column_classifier_recognizes_postgres_sqlstate():
    class DuplicateColumnError(Exception):
        sqlstate = "42701"

    exc = DBAPIError("", {}, DuplicateColumnError())

    assert _is_duplicate_column_error(exc, "postgresql") is True


def test_duplicate_object_classifier_recognizes_postgres_sqlstate():
    class DuplicateObjectError(Exception):
        sqlstate = "42710"

    exc = DBAPIError("", {}, DuplicateObjectError())

    assert _is_duplicate_object_error(exc) is True


def _fresh_compat_engine(tmp_path):
    engine = make_engine(f"sqlite:///{tmp_path}/conclusion.db")
    Base.metadata.create_all(engine)
    ensure_schema_compatibility(engine)
    return engine


def test_conclusion_tables_and_immutability_triggers_are_created(tmp_path):
    engine = _fresh_compat_engine(tmp_path)
    tables = set(inspect(engine).get_table_names())
    assert {"root_cause_conclusions", "causal_factors"} <= tables

    with engine.connect() as connection:
        triggers = {
            row[0]
            for row in connection.execute(
                text("SELECT name FROM sqlite_master WHERE type = 'trigger'")
            )
        }
    # Both append-only tables block UPDATE and DELETE at the DB layer (ADR 0039).
    assert {
        "ck_root_cause_conclusions_no_update",
        "ck_root_cause_conclusions_no_delete",
        "ck_causal_factors_no_update",
        "ck_causal_factors_no_delete",
    } <= triggers


def test_conclusion_discrepancy_table_and_immutability_triggers_are_created(tmp_path):
    engine = _fresh_compat_engine(tmp_path)
    assert "conclusion_discrepancies" in set(inspect(engine).get_table_names())
    with engine.connect() as connection:
        triggers = {
            row[0]
            for row in connection.execute(
                text("SELECT name FROM sqlite_master WHERE type = 'trigger'")
            )
        }
    # Conclusion Discrepancies are append-only flags: UPDATE/DELETE blocked (ADR 0040).
    assert {
        "ck_conclusion_discrepancies_no_update",
        "ck_conclusion_discrepancies_no_delete",
    } <= triggers


def test_conclusion_discrepancy_row_rejects_update_and_delete(tmp_path):
    engine = _fresh_compat_engine(tmp_path)
    with engine.begin() as connection:
        connection.execute(
            text(
                """
                INSERT INTO conclusion_discrepancies
                    (id, conclusion_id, run_id, explanation, raised_by_principal, created_at)
                VALUES ('d1', 'c1', 'r1', 'original', 'reviewer-1', '2026-06-19 00:00:00')
                """
            )
        )
    with pytest.raises(DBAPIError):
        with engine.begin() as connection:
            connection.execute(
                text("UPDATE conclusion_discrepancies SET explanation = 'edited' WHERE id = 'd1'")
            )
    with pytest.raises(DBAPIError):
        with engine.begin() as connection:
            connection.execute(text("DELETE FROM conclusion_discrepancies WHERE id = 'd1'"))
    with engine.connect() as connection:
        explanation = connection.scalar(
            text("SELECT explanation FROM conclusion_discrepancies WHERE id = 'd1'")
        )
    assert explanation == "original"


def test_finalized_conclusion_row_rejects_update_and_delete(tmp_path):
    engine = _fresh_compat_engine(tmp_path)
    # Foreign keys are not enforced by default on SQLite, so a bare row is enough
    # to exercise the immutability triggers without seeding a full run.
    with engine.begin() as connection:
        connection.execute(
            text(
                """
                INSERT INTO root_cause_conclusions
                    (id, run_id, summary, finalized_by_principal, finalized_at, created_at)
                VALUES ('c1', 'r1', 'original', 'reviewer-1',
                        '2026-06-18 00:00:00', '2026-06-18 00:00:00')
                """
            )
        )

    with pytest.raises(DBAPIError):
        with engine.begin() as connection:
            connection.execute(
                text("UPDATE root_cause_conclusions SET summary = 'edited' WHERE id = 'c1'")
            )

    with pytest.raises(DBAPIError):
        with engine.begin() as connection:
            connection.execute(text("DELETE FROM root_cause_conclusions WHERE id = 'c1'"))

    # The row is preserved unchanged after the blocked mutations.
    with engine.connect() as connection:
        summary = connection.scalar(
            text("SELECT summary FROM root_cause_conclusions WHERE id = 'c1'")
        )
    assert summary == "original"


def test_one_conclusion_per_run_is_enforced_at_db_level(tmp_path):
    engine = _fresh_compat_engine(tmp_path)
    with engine.begin() as connection:
        connection.execute(
            text(
                """
                INSERT INTO root_cause_conclusions
                    (id, run_id, summary, finalized_by_principal, finalized_at, created_at)
                VALUES ('c1', 'shared-run', 'first', 'reviewer-1',
                        '2026-06-18 00:00:00', '2026-06-18 00:00:00')
                """
            )
        )
    # A second conclusion for the same run is rejected by the unique index, so a
    # check-then-insert race cannot create two immutable conclusions (ADR 0039).
    with pytest.raises((IntegrityError, DBAPIError)):
        with engine.begin() as connection:
            connection.execute(
                text(
                    """
                    INSERT INTO root_cause_conclusions
                        (id, run_id, summary, finalized_by_principal, finalized_at, created_at)
                    VALUES ('c2', 'shared-run', 'racing', 'reviewer-2',
                            '2026-06-18 00:00:01', '2026-06-18 00:00:01')
                    """
                )
            )


def test_idempotent_compatibility_reruns_keep_immutability_triggers(tmp_path):
    engine = _fresh_compat_engine(tmp_path)
    # Re-running the compatibility pass drops and recreates the triggers without error.
    ensure_schema_compatibility(engine)
    with engine.connect() as connection:
        triggers = {
            row[0]
            for row in connection.execute(
                text("SELECT name FROM sqlite_master WHERE type = 'trigger'")
            )
        }
    assert "ck_causal_factors_no_delete" in triggers
