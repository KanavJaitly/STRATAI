from __future__ import annotations

from pathlib import Path

import psycopg
import pytest

from data.config import Settings
from database.connection import Database, DatabaseConfig
import database.migrate as migrate_module
from database.migrate import run_migrations


class DummyCursor:
    def __init__(self, already_applied: set[str]) -> None:
        self.already_applied = already_applied
        self.executed: list[tuple[str, tuple | None]] = []
        self._last_query: str | None = None

    def execute(self, query: str, params: tuple | None = None) -> None:
        self.executed.append((query, params))
        self._last_query = query

    def fetchone(self) -> tuple[int] | None:
        if self._last_query and "SELECT 1 FROM migrations_applied" in self._last_query:
            migration_file = self.executed[-1][1][0]
            if migration_file in self.already_applied:
                return (1,)
            return None
        return None

    def __enter__(self) -> "DummyCursor":
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        pass


class DummyConnection:
    def __init__(self, cursor: DummyCursor) -> None:
        self._cursor = cursor

    def cursor(self) -> DummyCursor:
        return self._cursor

    def commit(self) -> None:
        pass

    def rollback(self) -> None:
        pass

    def __enter__(self) -> "DummyConnection":
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        pass


@pytest.fixture(autouse=True)
def env_settings(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgresql://user:pass@localhost:5432/testdb")
    monkeypatch.setenv("TBA_API_KEY", "test-key")
    monkeypatch.setenv("ENV", "development")
    return Settings()


def _run_with_dummy(monkeypatch, settings, already_applied: set[str]) -> DummyCursor:
    cursor = DummyCursor(already_applied)
    monkeypatch.setattr(
        "database.connection.psycopg.connect",
        lambda *_args, **_kwargs: DummyConnection(cursor),
    )
    run_migrations(settings)
    return cursor


def test_migrations_apply_in_sorted_order(monkeypatch, env_settings):
    cursor = _run_with_dummy(monkeypatch, env_settings, already_applied=set())

    migration_files = sorted(Path("database/migrations").glob("*.sql"))
    applied_inserts = [
        params[0]
        for query, params in cursor.executed
        if "INSERT INTO migrations_applied" in query
    ]

    assert applied_inserts == [f.name for f in migration_files]


def test_migrations_skip_already_applied(monkeypatch, env_settings):
    cursor = _run_with_dummy(monkeypatch, env_settings, already_applied={"0001_initial.sql"})

    applied_inserts = [
        params[0]
        for query, params in cursor.executed
        if "INSERT INTO migrations_applied" in query
    ]
    executed_sql_bodies = [query for query, _ in cursor.executed]

    assert "0001_initial.sql" not in applied_inserts
    assert "0002_add_indexes.sql" in applied_inserts
    assert not any("CREATE TABLE IF NOT EXISTS raw_source_payloads" in body for body in executed_sql_bodies)


def test_migrations_creates_tracking_table(monkeypatch, env_settings):
    cursor = _run_with_dummy(monkeypatch, env_settings, already_applied=set())

    assert any(
        "CREATE TABLE IF NOT EXISTS migrations_applied" in query
        for query, _ in cursor.executed
    )


# ---------------------------------------------------------------------------
# Real-Postgres rollback test (found during a system-wide audit: the mocked
# DummyConnection above never actually rolls anything back -- its rollback()
# is a no-op stub -- so nothing had ever exercised whether a failing
# migration genuinely leaves the database unchanged, or only appeared to
# because the double is too permissive to fail that way).
# ---------------------------------------------------------------------------


def _database_available() -> bool:
    try:
        import psycopg

        settings = Settings()
        with psycopg.connect(str(settings.database_url), connect_timeout=3):
            return True
    except Exception:
        return False


requires_db = pytest.mark.skipif(
    not _database_available(),
    reason="Requires a reachable PostgreSQL database via DATABASE_URL",
)

_ROLLBACK_TEST_MARKER = "9999_test_rollback_valid.sql"


@requires_db
def test_run_migrations_rolls_back_the_whole_batch_on_a_later_failure(monkeypatch, tmp_path):
    """The entire run is one transaction: an early success must not survive a later failure.

    run_migrations applies every unapplied migration inside a single
    database.cursor() block, so the whole batch commits or none of it does.
    That is only true if Database.connection()'s rollback-on-exception path
    genuinely works against real Postgres, not just against a mock whose
    rollback() is a no-op stub (as in the tests above). This drives a real
    failure -- invalid SQL a real server rejects -- through a temporary
    migrations directory containing one migration that would succeed
    followed by one that cannot, and checks the database itself afterward.

    Uses the session's isolated test database (not this file's autouse
    env_settings fixture, whose DATABASE_URL is a placeholder for the mocked
    tests above and does not point at a reachable database). Until 2026-10-04
    this cleared DATABASE_URL and let Settings() reload .env, which names the
    serving database, so the rolled-back batch and its cleanup ran there; the
    test-database guard (tests/db_guard.py) exposed it. The URL is now the one
    the guard accepted at session start.
    """
    from tests import db_guard

    if db_guard.session_database_url is None:
        pytest.skip("no isolated test database configured for this session")
    monkeypatch.setenv("DATABASE_URL", db_guard.session_database_url)
    real_settings = Settings()
    valid_migration = tmp_path / _ROLLBACK_TEST_MARKER
    valid_migration.write_text(
        "CREATE TABLE test_rollback_should_not_persist (id INT PRIMARY KEY)"
    )
    broken_migration = tmp_path / "9999_test_rollback_broken.sql"
    broken_migration.write_text("SELECT * FROM table_that_does_not_exist_anywhere")

    monkeypatch.setattr(migrate_module, "MIGRATIONS_DIR", tmp_path)

    with pytest.raises(psycopg.Error):
        run_migrations(real_settings)

    database = Database(DatabaseConfig(real_settings.database_url))
    try:
        with database.cursor() as cursor:
            cursor.execute(
                "SELECT 1 FROM migrations_applied WHERE migration_file = %s",
                (_ROLLBACK_TEST_MARKER,),
            )
            assert cursor.fetchone() is None, (
                "the earlier-succeeding migration was recorded as applied even "
                "though a later migration in the same batch failed"
            )

            cursor.execute(
                "SELECT to_regclass('test_rollback_should_not_persist')"
            )
            row = cursor.fetchone()
            assert row is not None and row[0] is None, (
                "the earlier-succeeding migration's CREATE TABLE survived a "
                "rollback triggered by a later migration's failure"
            )
    finally:
        with database.cursor() as cursor:
            cursor.execute("DROP TABLE IF EXISTS test_rollback_should_not_persist")
            cursor.execute(
                "DELETE FROM migrations_applied WHERE migration_file = %s",
                (_ROLLBACK_TEST_MARKER,),
            )
