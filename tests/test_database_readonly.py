"""ReadOnlySessionDatabase: same reads as Database, and no writes at all."""

from __future__ import annotations

import psycopg
import pytest

from data.config import Settings
from database.connection import Database, DatabaseConfig
from database.readonly import ReadOnlySessionDatabase


def _database_available() -> bool:
    try:
        with psycopg.connect(str(Settings().database_url), connect_timeout=3):
            return True
    except Exception:
        return False


pytestmark = pytest.mark.skipif(not _database_available(), reason="Requires a reachable PostgreSQL database")


def test_reads_match_the_per_query_database_and_writes_are_refused() -> None:
    config = DatabaseConfig(Settings().database_url)
    session = ReadOnlySessionDatabase(config)
    try:
        sql = "SELECT event_key, season FROM events ORDER BY event_key LIMIT 25"
        with session.cursor() as cursor:
            cursor.execute(sql)
            shared = cursor.fetchall()
        with Database(config).cursor() as cursor:
            cursor.execute(sql)
            assert cursor.fetchall() == shared
        with pytest.raises(psycopg.errors.ReadOnlySqlTransaction):
            with session.cursor() as cursor:
                cursor.execute("CREATE TEMP TABLE readonly_probe (a int)")
        with session.connection() as conn, conn.cursor() as cursor:  # the session survives a refused write
            cursor.execute("SHOW default_transaction_read_only")
            assert cursor.fetchone() == ("on",)
    finally:
        session.close()
