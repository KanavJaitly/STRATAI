"""A single persistent, read-only PostgreSQL session for long read-only jobs.

Database.connection() opens a new connection per call, which dominates the
cost of building Phase 4's training frame (about 26 short queries per match,
each on a fresh connection). ReadOnlySessionDatabase keeps one connection
open for the whole job and sets default_transaction_read_only, so every
statement runs in its own read-only transaction: the queries and their
results are unchanged, and any attempt to write fails in the database itself.

It is a drop-in Database for readers only. Nothing in the pipeline's write
path uses it.
"""

from __future__ import annotations

from collections.abc import Generator
from contextlib import contextmanager

import psycopg

from database.connection import Database, DatabaseConfig


class ReadOnlySessionDatabase(Database):
    def __init__(self, config: DatabaseConfig) -> None:
        super().__init__(config)
        self._conn = psycopg.connect(config.database_url, autocommit=True)
        with self._conn.cursor() as cursor:
            cursor.execute("SET default_transaction_read_only = on")

    @contextmanager
    def connection(self) -> Generator[psycopg.Connection, None, None]:
        yield self._conn

    @contextmanager
    def cursor(self) -> Generator[psycopg.Cursor, None, None]:
        with self._conn.cursor() as cursor:
            yield cursor

    def close(self) -> None:
        self._conn.close()
