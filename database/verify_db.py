from __future__ import annotations

from pathlib import Path
import sys

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from data.config import Settings
from database.connection import Database, DatabaseConfig


def verify_database() -> None:
    """Check that all expected tables exist in the configured database, raising if any are missing."""
    settings = Settings()
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
        "canonical_lineage",
        "scouting_observations",
        "team_metrics",
        "scouting_access_codes",
        "game_manuals",
        "game_spec_versions",
        "capability_profiles",
        "human_review_artifacts",
        "season_rulesets",
    }

    missing = expected_tables - tables
    if missing:
        raise RuntimeError(f"Missing expected tables: {sorted(missing)}")

    print("Database verification passed. All expected tables exist.")


if __name__ == "__main__":
    verify_database()
