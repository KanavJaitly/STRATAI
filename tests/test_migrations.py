from __future__ import annotations

from pathlib import Path

import pytest

from data.config import Settings
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
