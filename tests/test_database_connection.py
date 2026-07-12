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
    def cursor(self) -> DummyCursor:
        return DummyCursor()

    def commit(self) -> None:
        pass

    def rollback(self) -> None:
        pass

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
