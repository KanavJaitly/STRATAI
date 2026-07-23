from __future__ import annotations

from pathlib import Path

import pytest

from data.config import Settings
from database.connection import Database, DatabaseConfig


class DummyCursor:
    def __init__(self) -> None:
        self._executed: list[str] = []

    def execute(self, query: str, params: tuple | None = None) -> None:
        self._executed.append(query)

    def fetchone(self) -> tuple[int] | None:
        return (1,)

    def __enter__(self) -> "DummyCursor":
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        pass


class DummyConnection:
    def __init__(self) -> None:
        self.committed = False
        self.rolled_back = False

    def cursor(self) -> DummyCursor:
        return DummyCursor()

    def commit(self) -> None:
        self.committed = True

    def rollback(self) -> None:
        self.rolled_back = True

    def __enter__(self) -> "DummyConnection":
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        pass


def test_database_connection_context_manager(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgresql://user:pass@localhost:5432/testdb")
    monkeypatch.setenv("TBA_API_KEY", "test-key")
    monkeypatch.setenv("STATBOTICS_API_KEY", "test-key")
    monkeypatch.setenv("ENV", "development")

    monkeypatch.setattr("database.connection.psycopg.connect", lambda _: DummyConnection())

    settings = Settings()
    config = DatabaseConfig(settings.database_url)
    database = Database(config)

    with database.connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute("SELECT 1")
            assert cursor.fetchone() == (1,)

    assert conn.committed is True
    assert conn.rolled_back is False


def test_database_connection_rolls_back_on_exception(monkeypatch):
    # Found during the Phase 2 midpoint audit: this branch of connection()'s
    # try/except was never exercised by any existing test.
    monkeypatch.setenv("DATABASE_URL", "postgresql://user:pass@localhost:5432/testdb")
    monkeypatch.setenv("TBA_API_KEY", "test-key")
    monkeypatch.setenv("ENV", "development")

    created: list[DummyConnection] = []

    def fake_connect(_url):
        conn = DummyConnection()
        created.append(conn)
        return conn

    monkeypatch.setattr("database.connection.psycopg.connect", fake_connect)

    settings = Settings()
    database = Database(DatabaseConfig(settings.database_url))

    with pytest.raises(ValueError, match="boom"):
        with database.connection() as conn:
            raise ValueError("boom")

    assert created[0].rolled_back is True
    assert created[0].committed is False
