"""P10-D1 option B (Sven Morais, 2026-10-21): one database connection per request, no new dependency.

The tests that P10-D1 §4 prescribes for any connection change: transactions, concurrency, shutdown, reconnect,
timeouts, leaks and session state, plus `read_snapshot` on the request connection. They run on a **disposable**
database (`stratai_test_p10req_<pid>`), created from the isolated `stratai_test` connection and dropped at the end.
"""

from __future__ import annotations

import os
import threading
from typing import Generator

import psycopg
import pytest
from fastapi.testclient import TestClient
from psycopg import sql

from data.config import Settings
from database.connection import Database, DatabaseConfig, RequestDatabase, read_snapshot
from tests.test_live_epa import _isolated_db_name

pytestmark = pytest.mark.skipif(_isolated_db_name() is None, reason="needs the isolated stratai_test database")


@pytest.fixture(scope="module")
def url() -> Generator[str, None, None]:
    from database.migrate import run_migrations

    source = str(Settings().database_url)
    name = f"stratai_test_p10req_{os.getpid()}"
    target = source.rsplit("/", 1)[0] + "/" + name
    with psycopg.connect(source, autocommit=True) as admin:
        admin.execute(sql.SQL("DROP DATABASE IF EXISTS {} WITH (FORCE)").format(sql.Identifier(name)))
        admin.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(name)))
    try:
        run_migrations(Settings(database_url=target))
        with psycopg.connect(target, autocommit=True) as conn:
            conn.execute("CREATE TABLE p10_probe (id int PRIMARY KEY, note text)")
        yield target
    finally:
        with psycopg.connect(source, autocommit=True) as admin:
            admin.execute(sql.SQL("DROP DATABASE IF EXISTS {} WITH (FORCE)").format(sql.Identifier(name)))


@pytest.fixture
def clean(url) -> Generator[str, None, None]:
    with psycopg.connect(url, autocommit=True) as conn:
        conn.execute("TRUNCATE p10_probe")
    yield url


def _rows(url: str) -> list[tuple]:
    with psycopg.connect(url, autocommit=True) as conn:
        return conn.execute("SELECT id, note FROM p10_probe ORDER BY id").fetchall()


def _sessions(url: str) -> int:
    with psycopg.connect(url, autocommit=True) as conn:
        return conn.execute("SELECT count(*) FROM pg_stat_activity WHERE datname = current_database() "
                            "AND pid <> pg_backend_pid()").fetchone()[0]


def _pid(database) -> int:
    with database.cursor() as c:
        c.execute("SELECT pg_backend_pid()")
        return c.fetchone()[0]


# --- reuse, and transactions exactly as before -------------------------------------------------------------------


def test_top_level_calls_share_one_connection_and_each_is_its_own_transaction(clean):
    db = RequestDatabase(DatabaseConfig(clean))
    try:
        first = _pid(db)
        with db.cursor() as c:
            c.execute("INSERT INTO p10_probe VALUES (1, 'a')")
        assert _rows(clean) == [(1, "a")]  # committed at the end of its own call, as with a plain Database
        with pytest.raises(psycopg.errors.UniqueViolation):
            with db.cursor() as c:
                c.execute("INSERT INTO p10_probe VALUES (2, 'b')")
                c.execute("INSERT INTO p10_probe VALUES (1, 'dup')")
        assert _rows(clean) == [(1, "a")]  # the failed call rolled back entirely
        with db.cursor() as c:  # and the connection is usable again
            c.execute("INSERT INTO p10_probe VALUES (3, 'c')")
        assert _pid(db) == first and db.connections_opened == 1
        assert _rows(clean) == [(1, "a"), (3, "c")]
    finally:
        db.close()


def test_a_nested_call_gets_its_own_connection_so_transactions_never_merge(clean):
    """With per-call connections, an inner call committing could never commit the outer call's work. Reusing one
    connection naively would; a nested call therefore gets a fresh connection, as before."""
    db = RequestDatabase(DatabaseConfig(clean))
    try:
        with pytest.raises(RuntimeError):
            with db.cursor() as outer:
                outer.execute("INSERT INTO p10_probe VALUES (10, 'outer')")
                outer.execute("SELECT pg_backend_pid()")
                outer_pid = outer.fetchone()[0]
                inner_pid = _pid(db)  # nested: commits its own (empty) transaction on its own connection
                assert inner_pid != outer_pid
                raise RuntimeError("the outer call fails after the inner one committed")
        assert _rows(clean) == []  # the outer insert was rolled back, not committed by the inner call
    finally:
        db.close()


def test_two_threads_never_use_the_request_connection_at_the_same_time(clean):
    db = RequestDatabase(DatabaseConfig(clean))
    barrier = threading.Barrier(2)
    pids: list[int] = []

    def hold():
        with db.cursor() as c:
            c.execute("SELECT pg_backend_pid()")
            pids.append(c.fetchone()[0])
            barrier.wait(timeout=10)  # both calls are open at once here
            barrier.wait(timeout=10)

    threads = [threading.Thread(target=hold) for _ in range(2)]
    try:
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=30)
        assert len(pids) == 2 and pids[0] != pids[1]
    finally:
        db.close()


# --- lifecycle: close, reconnect, timeouts, leaks ----------------------------------------------------------------


def test_close_ends_the_connection_and_leaves_no_session(clean):
    db = RequestDatabase(DatabaseConfig(clean))
    _pid(db)
    assert _sessions(clean) == 1
    db.close()
    assert _sessions(clean) == 0
    db.close()  # idempotent


def test_an_error_on_a_broken_connection_is_raised_once_then_a_new_connection_is_used(clean):
    db = RequestDatabase(DatabaseConfig(clean))
    try:
        pid = _pid(db)
        with psycopg.connect(clean, autocommit=True) as admin:
            admin.execute("SELECT pg_terminate_backend(%s)", (pid,))
        with pytest.raises(psycopg.OperationalError):
            _pid(db)  # the call on the terminated connection fails (as a per-call connection's would)
        assert _pid(db) != pid and db.connections_opened == 2  # the next call reconnects
    finally:
        db.close()


def test_the_request_connection_keeps_its_timeouts(clean):
    db = RequestDatabase(DatabaseConfig(clean, statement_timeout_ms=200))
    try:
        with pytest.raises(psycopg.errors.QueryCanceled):
            with db.cursor() as c:
                c.execute("SELECT pg_sleep(3)")
        with db.cursor() as c:  # the same connection, still usable, still timed out
            c.execute("SHOW statement_timeout")
            assert c.fetchone()[0] == "200ms"
        assert db.connections_opened == 1
    finally:
        db.close()


# --- read_snapshot on the request connection ---------------------------------------------------------------------


def test_a_snapshot_on_a_request_database_uses_its_connection_and_restores_it(clean):
    db = RequestDatabase(DatabaseConfig(clean))
    try:
        pid = _pid(db)
        with read_snapshot(db) as snapshot:
            assert _pid(snapshot) == pid  # no new connection for the snapshot
            with psycopg.connect(clean) as other:  # a commit by another connection, while the snapshot is open
                other.execute("INSERT INTO p10_probe VALUES (20, 'x')")
            with snapshot.cursor() as c:
                c.execute("SELECT count(*) FROM p10_probe")
                assert c.fetchone()[0] == 0  # repeatable read: invisible inside the snapshot
            with pytest.raises(psycopg.errors.ReadOnlySqlTransaction):
                with snapshot.cursor() as c:
                    c.execute("INSERT INTO p10_probe VALUES (21, 'y')")
        with db.cursor() as c:  # restored: read-write, read committed, sees the commit
            c.execute("INSERT INTO p10_probe VALUES (22, 'z')")
            c.execute("SELECT count(*) FROM p10_probe")
            assert c.fetchone()[0] == 2
        assert db.connections_opened == 1
    finally:
        db.close()


def test_a_snapshot_taken_inside_a_call_uses_a_fresh_connection(clean):
    db = RequestDatabase(DatabaseConfig(clean))
    try:
        with db.cursor() as c:
            c.execute("SELECT pg_backend_pid()")
            outer = c.fetchone()[0]
            with read_snapshot(db) as snapshot:
                assert _pid(snapshot) != outer
    finally:
        db.close()


# --- through the API: one connection per request, never shared, never leaked --------------------------------------


def test_requests_through_the_app_use_one_request_connection_each_and_leave_no_session(clean, monkeypatch):
    from api import create_app

    opened: list[int] = []
    real_connect = psycopg.connect

    def counting_connect(*args, **kwargs):
        opened.append(threading.get_ident())
        return real_connect(*args, **kwargs)

    app = create_app(Settings(database_url=clean, api_prefix=""))
    with TestClient(app) as client:
        monkeypatch.setattr(psycopg, "connect", counting_connect)
        for _ in range(50):
            assert client.get("/events", params={"season": 2099}).status_code == 200
        monkeypatch.setattr(psycopg, "connect", real_connect)
    assert len(opened) == 50  # one connection per request, however many statements the request runs
    assert _sessions(clean) == 0  # every request's connection was closed


def test_concurrent_requests_never_share_a_connection(clean):
    """Each request's connection is its own: concurrent requests see distinct backends."""
    from fastapi import Depends

    from api import create_app
    from api.dependencies import get_database

    app = create_app(Settings(database_url=clean, api_prefix=""))
    barrier = threading.Barrier(4)
    seen: list[int] = []

    @app.get("/_p10_pid")
    def pid(database: Database = Depends(get_database)):
        backend = _pid(database)
        barrier.wait(timeout=20)  # all four requests hold their connection at once
        seen.append(backend)
        return {"pid": backend}

    with TestClient(app) as client:
        threads = [threading.Thread(target=lambda: client.get("/_p10_pid")) for _ in range(4)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=60)
    assert len(seen) == 4 and len(set(seen)) == 4
    assert _sessions(clean) == 0
