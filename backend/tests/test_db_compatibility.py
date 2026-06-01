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


def _insert_evidence_ref(engine, ref_id, *, role="supporting", **owners):
    values = {
        "id": ref_id,
        "timeline_event_id": None,
        "hypothesis_id": None,
        "impact_claim_id": None,
        "action_item_id": None,
        "role": role,
        **owners,
    }
    with engine.begin() as connection:
        connection.execute(
            text(
                """
                INSERT INTO evidence_refs (
                    id, timeline_event_id, hypothesis_id, impact_claim_id,
                    action_item_id, role, artifact_id, source_name, line_start,
                    line_end, snippet, confidence_score, created_at
                ) VALUES (
                    :id, :timeline_event_id, :hypothesis_id, :impact_claim_id,
                    :action_item_id, :role, 'artifact-id', 'api.log', 1, 1,
                    'line one', 1.0, '2026-06-01 00:00:00'
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
    assert {"hypothesis_id", "impact_claim_id", "action_item_id", "role"} <= columns
    indexes = {index["name"] for index in inspector.get_indexes("evidence_refs")}
    assert {
        "ix_evidence_refs_hypothesis_id",
        "ix_evidence_refs_impact_claim_id",
        "ix_evidence_refs_action_item_id",
    } <= indexes
    _assert_invalid_refs_rejected(engine)
    _insert_evidence_ref(engine, "valid-ref", timeline_event_id="timeline-id")


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
