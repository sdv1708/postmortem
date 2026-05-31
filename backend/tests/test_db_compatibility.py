from __future__ import annotations

from sqlalchemy import inspect, text

from postmortem.app import create_app
from postmortem.config import Settings
from postmortem.db import make_engine


def test_create_app_upgrades_issue_6_evidence_refs_table(tmp_path):
    database_url = f"sqlite:///{tmp_path}/issue-6.db"
    engine = make_engine(database_url)
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

