from __future__ import annotations

from contextlib import contextmanager
from typing import Generator

import psycopg
from pydantic import PostgresDsn


class DatabaseConfig:
    """Database connection configuration."""

    def __init__(self, database_url: PostgresDsn) -> None:
        self.database_url = str(database_url)


class Database:
    """PostgreSQL database connection helper."""

    def __init__(self, config: DatabaseConfig) -> None:
        self._config = config

    @contextmanager
    def connection(self) -> Generator[psycopg.Connection, None, None]:
        with psycopg.connect(self._config.database_url) as conn:
            try:
                yield conn
                conn.commit()
            except Exception:
                conn.rollback()
                raise

    @contextmanager
    def cursor(self) -> Generator[psycopg.Cursor, None, None]:
        with self.connection() as conn:
            with conn.cursor() as cur:
                yield cur
