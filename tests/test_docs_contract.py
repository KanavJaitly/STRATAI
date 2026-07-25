"""Contract tests: the documentation, the schema, and the connectors must agree.

Milestone 10's job is accuracy, so these tests are anti-drift guards rather than new
behaviour coverage. They assert things that are true today and would quietly stop being
true as the pipeline evolves:

  * docs/data_pipeline.md documents exactly the tables the database has -- in BOTH
    directions, so adding a table without documenting it fails
  * the columns, keys, and cascade rules the docs promise actually exist
  * migration filenames are sequential and all of them are documented and applied
  * Settings resolves the defaults the quickstart claims
  * the connector methods the pipeline depends on hit the URLs the docs say they do
  * the vocabularies quoted in the docs match the constants in the code

Deliberately NOT duplicated here: HTTP retry behaviour (tests/test_tba_client.py,
tests/test_statbotics_client.py), migration ordering/skip semantics
(tests/test_migrations.py), env loading and ENV validation (tests/test_config.py),
normalization and validation rules (tests/test_normalizer.py,
tests/test_staging_validator.py), and pipeline flow (tests/test_pipeline.py,
tests/test_data_quality.py).
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any
from unittest.mock import Mock

import httpx
import pytest

from data.clients.schemas import EventSummary, TeamInfo
from data.clients.source_connector import SourceConnector
from data.clients.statbotics import StatboticsClient
from data.clients.tba import TBAClient
from data.config import Settings
from data.pipeline import (
    OBJECT_TYPE_EVENT,
    OBJECT_TYPE_MATCH,
    OBJECT_TYPE_TEAM,
    OBJECT_TYPE_TEAM_EVENT,
    SOURCE_STATBOTICS,
    SOURCE_TBA,
)
from data.staging import quality
from database.connection import Database, DatabaseConfig

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DOCS_PATH = PROJECT_ROOT / "docs" / "data_pipeline.md"
MIGRATIONS_DIR = PROJECT_ROOT / "database" / "migrations"

# Tables created by a migration file. migrations_applied is created by migrate.py itself
# rather than by a migration, and the docs say so.
DOCUMENTED_BY_MIGRATION_RUNNER = {"migrations_applied"}


@pytest.fixture(scope="module")
def docs_text() -> str:
    assert DOCS_PATH.exists(), f"{DOCS_PATH} is missing"
    return DOCS_PATH.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def documented_tables(docs_text: str) -> set[str]:
    """Table names from the schema reference's `#### \\`table\\`` headings."""
    return set(re.findall(r"^####\s+`([a-z_]+)`", docs_text, flags=re.MULTILINE))


# ===========================================================================
# Documentation structure. No database required.
# ===========================================================================


def test_docs_cover_every_documented_section(docs_text: str):
    for heading in (
        "## 1. Scope",
        "## 2. Architecture",
        "## 3. Data flow, end to end",
        "## 4. Schema reference",
        "## 5. Incremental state",
        "## 6. Data quality and lineage",
        "## 7. Local quickstart",
        "## 8. Operating the pipeline",
        "## 9. Known issues and limitations",
        "## 10. Extending the pipeline",
    ):
        assert heading in docs_text, f"docs missing section: {heading}"


def test_docs_document_the_known_failing_config_test(docs_text: str):
    # A new developer's first test run shows this failure; the docs must explain it
    # rather than leave them guessing.
    assert "test_settings_allows_missing_statbotics_api_key" in docs_text
    assert "--deselect" in docs_text


def test_docs_reference_only_module_paths_that_exist(docs_text: str):
    referenced = set(re.findall(r"`((?:data|database)/[a-z_]+(?:/[a-z_]+)*\.py)`", docs_text))
    assert referenced, "expected the docs to reference module paths"
    missing = sorted(path for path in referenced if not (PROJECT_ROOT / path).exists())
    assert missing == [], f"docs reference non-existent modules: {missing}"


def test_readme_points_at_the_pipeline_docs():
    readme = (PROJECT_ROOT / "README.md").read_text(encoding="utf-8")
    assert "docs/data_pipeline.md" in readme
    # The old quickstart used Windows-only paths that do not exist in this repo.
    assert ".venv\\Scripts" not in readme


# ===========================================================================
# Migration hygiene. No database required.
# ===========================================================================


def test_migration_filenames_are_sequential_and_well_formed():
    files = sorted(path.name for path in MIGRATIONS_DIR.glob("*.sql"))
    assert files, "no migrations found"

    numbers = []
    for name in files:
        match = re.match(r"^(\d{4})_[a-z0-9_]+\.sql$", name)
        assert match is not None, f"migration filename does not match NNNN_name.sql: {name}"
        numbers.append(int(match.group(1)))

    assert numbers == list(range(1, len(numbers) + 1)), (
        f"migration numbers must run 0001..{len(numbers):04d} with no gaps or duplicates, got {numbers}"
    )


def test_docs_document_every_migration_file(docs_text: str):
    on_disk = {path.name for path in MIGRATIONS_DIR.glob("*.sql")}
    documented = set(re.findall(r"`(\d{4}_[a-z0-9_]+\.sql)`", docs_text))
    assert on_disk - documented == set(), f"undocumented migrations: {sorted(on_disk - documented)}"
    assert documented - on_disk == set(), f"docs list missing migrations: {sorted(documented - on_disk)}"


def test_docs_state_the_no_alembic_constraint(docs_text: str):
    assert "no Alembic" in docs_text or "No Alembic" in docs_text


# ===========================================================================
# Config contract. No database required.
# ===========================================================================


@pytest.fixture
def env_settings(monkeypatch) -> Settings:
    monkeypatch.setenv("DATABASE_URL", "postgresql://user:pass@localhost:5432/testdb")
    monkeypatch.setenv("TBA_API_KEY", "test-key")
    monkeypatch.setenv("ENV", "development")
    return Settings()


def test_settings_defaults_match_the_documented_values(env_settings: Settings):
    # These defaults are quoted in the docs and relied on by the clients.
    assert env_settings.tba_timeout == 10.0
    assert env_settings.tba_max_retries == 3
    assert env_settings.tba_backoff_factor == 0.5
    assert env_settings.statbotics_timeout == 10.0
    assert env_settings.statbotics_max_retries == 3
    assert env_settings.statbotics_backoff_factor == 0.5
    assert env_settings.env == "development"


def test_settings_rejects_a_non_postgres_database_url(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "mysql://user:pass@localhost:3306/stratai")
    monkeypatch.setenv("TBA_API_KEY", "test-key")
    with pytest.raises(Exception):  # pydantic ValidationError on the PostgresDsn field
        Settings()


# ===========================================================================
# Connector contract. No database or network required.
# ===========================================================================


class DummyResponse(httpx.Response):
    def __init__(self, status_code: int, json_body: Any) -> None:
        super().__init__(status_code, request=httpx.Request("GET", "https://example.com"))
        self._json_body = json_body

    def json(self) -> Any:
        return self._json_body


def test_both_clients_satisfy_the_source_connector_contract(env_settings: Settings):
    for client_cls in (TBAClient, StatboticsClient):
        assert issubclass(client_cls, SourceConnector)
        client = client_cls(settings=env_settings)
        try:
            assert isinstance(client.source_name, str) and client.source_name
            assert callable(client.close)
        finally:
            client.close()


def test_client_source_names_match_the_strings_the_pipeline_writes(env_settings: Settings):
    # raw_source_payloads.source, source_watermarks.source, data_quality_issues.source and
    # canonical_lineage.source all carry these values; a rename would silently orphan
    # every existing watermark.
    assert TBAClient.source_name == SOURCE_TBA == "tba"
    assert StatboticsClient.source_name == SOURCE_STATBOTICS == "statbotics"


def test_fetch_event_requests_the_documented_single_event_url(monkeypatch, env_settings: Settings):
    # Added in Milestone 8 and used by every sync, but never covered by a client test
    # until now -- the pipeline tests use fakes, so the real URL was unexercised.
    client = TBAClient(settings=env_settings)
    body = {"key": "2025casj", "name": "Silicon Valley Regional", "year": 2025,
            "city": "San Jose", "state_prov": "CA", "country": "USA"}
    request = Mock(return_value=DummyResponse(200, body))
    monkeypatch.setattr(client, "_client", Mock(request=request))

    event = client.fetch_event("2025casj")

    assert request.call_args_list[0][0][1].endswith("/event/2025casj")
    assert isinstance(event, EventSummary)
    assert (event.key, event.season, event.state_prov) == ("2025casj", 2025, "CA")


def test_fetch_event_teams_requests_the_documented_roster_url(monkeypatch, env_settings: Settings):
    client = TBAClient(settings=env_settings)
    body = [
        {"key": "frc1114", "team_number": 1114, "nickname": "Simbotics"},
        {"key": "frc254", "team_number": 254, "nickname": "The Cheesy Poofs"},
    ]
    request = Mock(return_value=DummyResponse(200, body))
    monkeypatch.setattr(client, "_client", Mock(request=request))

    teams = client.fetch_event_teams("2025casj")

    assert request.call_args_list[0][0][1].endswith("/event/2025casj/teams")
    assert [team.team_number for team in teams] == [1114, 254]
    assert all(isinstance(team, TeamInfo) for team in teams)


def test_fetch_event_teams_handles_an_empty_roster(monkeypatch, env_settings: Settings):
    client = TBAClient(settings=env_settings)
    monkeypatch.setattr(client, "_client", Mock(request=Mock(return_value=DummyResponse(200, None))))
    assert client.fetch_event_teams("2025casj") == []


# ===========================================================================
# Vocabulary contract: the words the docs use are the words the code uses.
# ===========================================================================


def test_object_type_vocabulary_matches_the_docs(docs_text: str):
    assert (OBJECT_TYPE_EVENT, OBJECT_TYPE_TEAM, OBJECT_TYPE_MATCH, OBJECT_TYPE_TEAM_EVENT) == (
        "event", "team", "match", "team_event",
    )
    # The lineage/schema section quotes this shared vocabulary explicitly.
    assert "`event`, `team`, `match`, `team_event`" in docs_text


def test_severity_vocabulary_matches_the_database_constraint_and_docs(docs_text: str, documented_tables):
    severities = {quality.SEVERITY_WARNING, quality.SEVERITY_ERROR, quality.SEVERITY_CRITICAL}
    assert severities == {"warning", "error", "critical"}
    assert "severity IN ('warning','error','critical')" in docs_text
    for severity in severities:
        assert severity in docs_text


def test_issue_type_vocabulary_is_stable():
    # Written into data_quality_issues.issue_type, so these strings are data, not labels.
    assert quality.ISSUE_VALIDATION_FAILURE == "validation_failure"
    assert quality.ISSUE_OUT_OF_RANGE == "out_of_range"
    assert quality.ISSUE_IMPLAUSIBLE_VALUE == "implausible_value"
    assert quality.ISSUE_INCONSISTENT_VALUES == "inconsistent_values"
    assert quality.ISSUE_MISSING_REFERENCE == "missing_reference"
    assert quality.ISSUE_EXTRACTION_FAILURE == "extraction_failure"


def test_documented_plausibility_bounds_match_the_code(docs_text: str):
    assert quality.FIRST_FRC_SEASON == 1992
    assert quality.MAX_PLAUSIBLE_TEAM_NUMBER == 100_000
    assert quality.MAX_PLAUSIBLE_ALLIANCE_SCORE == 1_000
    assert quality.MIN_PLAUSIBLE_EPA == -50.0
    assert quality.EXPECTED_ALLIANCE_SIZE == 3
    assert quality.MAX_SCHEDULE_LOOKAHEAD.days == 730
    for quoted in ("1992", "100 000", "1 000", "−50", "730"):
        assert quoted in docs_text, f"docs do not quote plausibility bound {quoted!r}"


# ===========================================================================
# CLI contract. No database required.
# ===========================================================================


def test_documented_cli_entry_point_exists_and_parses_its_documented_flags():
    from data import orchestrator

    assert callable(orchestrator.main)
    with pytest.raises(SystemExit) as exit_info:
        orchestrator.main(["--help"])
    assert exit_info.value.code == 0


def test_cli_requires_an_event_key():
    from data import orchestrator

    with pytest.raises(SystemExit) as exit_info:
        orchestrator.main([])
    assert exit_info.value.code != 0


# ===========================================================================
# Schema contract. Requires a reachable database.
# ===========================================================================


def _database_available() -> bool:
    try:
        import psycopg

        with psycopg.connect(str(Settings().database_url), connect_timeout=3):
            return True
    except Exception:
        return False


requires_db = pytest.mark.skipif(
    not _database_available(),
    reason="Requires a reachable PostgreSQL database via DATABASE_URL",
)


@pytest.fixture
def database() -> Database:
    from database.migrate import run_migrations

    settings = Settings()
    run_migrations(settings)
    return Database(DatabaseConfig(settings.database_url))


def _tables(database: Database) -> set[str]:
    with database.cursor() as cursor:
        cursor.execute("SELECT tablename FROM pg_tables WHERE schemaname = 'public'")
        return {row[0] for row in cursor.fetchall()}


def _columns(database: Database, table: str) -> dict[str, str]:
    with database.cursor() as cursor:
        cursor.execute(
            "SELECT column_name, data_type FROM information_schema.columns WHERE table_name = %s",
            (table,),
        )
        return {row[0]: row[1] for row in cursor.fetchall()}


def _constraint_defs(database: Database, table: str) -> list[str]:
    with database.cursor() as cursor:
        cursor.execute(
            "SELECT pg_get_constraintdef(oid) FROM pg_constraint WHERE conrelid = %s::regclass",
            (table,),
        )
        return [row[0] for row in cursor.fetchall()]


def _index_defs(database: Database, table: str) -> list[str]:
    with database.cursor() as cursor:
        cursor.execute("SELECT indexdef FROM pg_indexes WHERE tablename = %s", (table,))
        return [row[0] for row in cursor.fetchall()]


@requires_db
def test_documented_tables_and_actual_tables_are_the_same_set(database, documented_tables):
    actual = _tables(database)
    undocumented = actual - documented_tables
    assert undocumented == set(), (
        f"tables exist but are not documented in docs/data_pipeline.md: {sorted(undocumented)}"
    )
    phantom = documented_tables - actual - DOCUMENTED_BY_MIGRATION_RUNNER
    assert phantom == set(), f"docs document tables that do not exist: {sorted(phantom)}"


@requires_db
def test_every_migration_on_disk_is_recorded_as_applied(database):
    on_disk = {path.name for path in MIGRATIONS_DIR.glob("*.sql")}
    with database.cursor() as cursor:
        cursor.execute("SELECT migration_file FROM migrations_applied")
        applied = {row[0] for row in cursor.fetchall()}
    assert on_disk - applied == set(), f"unapplied migrations: {sorted(on_disk - applied)}"


@requires_db
@pytest.mark.parametrize("table,expected", [
    ("raw_source_payloads", {"id": "bigint", "source": "text", "source_object_type": "text",
                             "source_object_id": "text", "payload_json": "jsonb",
                             "payload_checksum": "text", "is_current": "boolean"}),
    ("teams", {"team_number": "integer", "name": "text", "state_province": "text"}),
    ("events", {"event_key": "text", "season": "integer", "state_prov": "text"}),
    ("matches", {"match_key": "text", "event_key": "text", "score_red": "integer",
                 "score_blue": "integer", "winning_alliance": "text"}),
    ("match_teams", {"match_key": "text", "team_number": "integer",
                     "alliance_color": "text", "station_position": "integer"}),
    ("team_event_stats", {"team_number": "integer", "event_key": "text",
                          "epa_total": "numeric", "matches_played": "integer"}),
    ("pipeline_runs", {"id": "bigint", "pipeline_name": "text", "status": "text",
                       "scope_key": "text", "stage_counts": "jsonb"}),
    ("source_watermarks", {"source": "text", "object_type": "text", "scope_key": "text",
                           "watermark_value": "text"}),
    ("data_quality_issues", {"pipeline_run_id": "bigint", "raw_payload_id": "bigint",
                             "field": "text", "issue_type": "text", "severity": "text",
                             "description": "text"}),
    ("canonical_lineage", {"entity_type": "text", "entity_key": "text",
                           "raw_payload_id": "bigint", "pipeline_run_id": "bigint",
                           "source": "text"}),
])
def test_documented_columns_exist_with_the_documented_types(database, table, expected):
    actual = _columns(database, table)
    for column, data_type in expected.items():
        assert column in actual, f"{table}.{column} is documented but missing"
        assert actual[column] == data_type, (
            f"{table}.{column} is {actual[column]}, docs say {data_type}"
        )


@requires_db
def test_reserved_columns_documented_as_unpopulated_still_exist(database):
    # The docs promise these are retained but never written; if one were dropped the
    # docs would be wrong, and if one started being populated the docs would be too.
    assert set(_columns(database, "raw_source_payloads")) >= {
        "season", "event_key", "match_key", "schema_version",
    }
    assert "event_type" in _columns(database, "events")
    assert {"resolved", "resolved_at"} <= set(_columns(database, "data_quality_issues"))


@requires_db
@pytest.mark.parametrize("table,expected_pk", [
    ("teams", "PRIMARY KEY (team_number)"),
    ("events", "PRIMARY KEY (event_key)"),
    ("matches", "PRIMARY KEY (match_key)"),
    ("team_event_stats", "PRIMARY KEY (team_number, event_key)"),
    ("raw_source_payloads", "PRIMARY KEY (id)"),
])
def test_documented_primary_keys(database, table, expected_pk):
    assert any(expected_pk in defn for defn in _constraint_defs(database, table)), (
        f"{table} is missing documented {expected_pk}"
    )


@requires_db
@pytest.mark.parametrize("table,column,target", [
    ("matches", "event_key", "events(event_key)"),
    ("match_teams", "match_key", "matches(match_key)"),
    ("match_teams", "team_number", "teams(team_number)"),
    ("team_event_stats", "team_number", "teams(team_number)"),
    ("team_event_stats", "event_key", "events(event_key)"),
])
def test_documented_foreign_keys(database, table, column, target):
    expected = f"FOREIGN KEY ({column}) REFERENCES {target}"
    assert any(expected in defn for defn in _constraint_defs(database, table)), (
        f"{table} is missing documented FK {expected}"
    )


@requires_db
def test_documented_cascade_rules(database):
    # These are load-bearing: without them, deleting a run or a raw payload fails on a
    # foreign-key violation, which is exactly what integration teardown does.
    issue_fks = [d for d in _constraint_defs(database, "data_quality_issues") if "FOREIGN KEY" in d]
    assert any("pipeline_run_id" in d and "ON DELETE CASCADE" in d for d in issue_fks)
    assert any("raw_payload_id" in d and "ON DELETE CASCADE" in d for d in issue_fks)

    lineage_fks = [d for d in _constraint_defs(database, "canonical_lineage") if "FOREIGN KEY" in d]
    assert any("raw_payload_id" in d and "ON DELETE CASCADE" in d for d in lineage_fks)
    # Provenance outlives the run that recorded it.
    assert any("pipeline_run_id" in d and "ON DELETE SET NULL" in d for d in lineage_fks)


@requires_db
def test_documented_unique_indexes(database):
    for table, columns in (
        ("raw_source_payloads", "(source, source_object_type, source_object_id, payload_checksum)"),
        ("source_watermarks", "(source, object_type, scope_key)"),
        ("canonical_lineage", "(entity_type, entity_key, raw_payload_id)"),
        ("match_teams", "(match_key, team_number)"),
    ):
        assert any("UNIQUE INDEX" in defn and columns in defn for defn in _index_defs(database, table)), (
            f"{table} is missing documented unique index on {columns}"
        )

    # 0004 replaced the original dedup index; if it came back, payload versioning breaks.
    assert not any("idx_raw_source_key" in defn for defn in _index_defs(database, "raw_source_payloads"))


@requires_db
def test_documented_check_constraints(database):
    assert any(
        "status" in defn and "'running'" in defn and "'succeeded'" in defn and "'failed'" in defn
        for defn in _constraint_defs(database, "pipeline_runs")
    )
    assert any(
        "severity" in defn and "'warning'" in defn and "'error'" in defn and "'critical'" in defn
        for defn in _constraint_defs(database, "data_quality_issues")
    )
    assert any(
        "alliance_color" in defn and "'red'" in defn and "'blue'" in defn
        for defn in _constraint_defs(database, "match_teams")
    )


@requires_db
def test_verify_db_expected_tables_match_the_documented_set(database, documented_tables):
    # database/verify_db.py keeps its own list; it must not drift from the docs either.
    from database.verify_db import verify_database

    verify_database()  # raises if any expected table is missing

    source = (PROJECT_ROOT / "database" / "verify_db.py").read_text(encoding="utf-8")
    listed = set(re.findall(r'^\s+"([a-z_]+)",$', source, flags=re.MULTILINE))
    assert listed <= documented_tables, (
        f"verify_db.py expects tables the docs do not document: {sorted(listed - documented_tables)}"
    )
