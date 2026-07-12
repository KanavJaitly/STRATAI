from __future__ import annotations

import os

import pytest

from data.config import Settings
from database.connection import Database, DatabaseConfig
from database.migrate import run_migrations


@pytest.mark.skip("Requires local PostgreSQL database and valid DATABASE_URL")
def test_verify_database_schema():
    settings = Settings()
    run_migrations(settings)

    database = Database(DatabaseConfig(settings.database_url))
    with database.cursor() as cursor:
        cursor.execute(
            "SELECT tablename FROM pg_catalog.pg_tables WHERE schemaname = 'public'"
        )
        tables = {row[0] for row in cursor.fetchall()}

    expected_tables = {
        "raw_source_payloads",
        "teams",
        "events",
        "matches",
        "match_teams",
        "team_event_stats",
        "migrations_applied",
        "pipeline_runs",
        "source_watermarks",
        "data_quality_issues",
    }
    assert expected_tables.issubset(tables)
