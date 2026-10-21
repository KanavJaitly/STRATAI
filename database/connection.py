from __future__ import annotations

from contextlib import contextmanager
import functools
import threading
from typing import Any, Callable, Generator, TypeVar

import psycopg
from psycopg.conninfo import conninfo_to_dict
from pydantic import PostgresDsn


T = TypeVar("T")
DEFAULT_CONNECT_TIMEOUT_SECONDS = 10  # P10-M1 (Phase 7 R7): a connection attempt never hangs


class DatabaseConfig:
    """Database connection configuration.

    `connect_timeout` bounds every connection attempt. `statement_timeout_ms`, when set, cancels any statement that
    runs longer (the API sets it; batch jobs leave it unset)."""

    def __init__(self, database_url: PostgresDsn, *, connect_timeout: int = DEFAULT_CONNECT_TIMEOUT_SECONDS,
                 statement_timeout_ms: int | None = None) -> None:
        self.database_url = str(database_url)
        self.connect_timeout = connect_timeout
        self.statement_timeout_ms = statement_timeout_ms

    def connect_kwargs(self) -> dict[str, object]:
        """Keyword arguments for psycopg.connect. A statement timeout is appended to any `options` the URL already
        carries (for example a search_path), never in place of them (review P10-R1)."""
        kwargs: dict[str, object] = {"connect_timeout": self.connect_timeout}
        if self.statement_timeout_ms:
            existing = conninfo_to_dict(self.database_url).get("options") or ""
            kwargs["options"] = f"{existing} -c statement_timeout={int(self.statement_timeout_ms)}".strip()
        return kwargs


class Database:
    """PostgreSQL database connection helper."""

    def __init__(self, config: DatabaseConfig) -> None:
        self._config = config

    @contextmanager
    def connection(self) -> Generator[psycopg.Connection, None, None]:
        with psycopg.connect(self._config.database_url, **self._config.connect_kwargs()) as conn:
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


class SnapshotDatabase(Database):
    """One connection inside one REPEATABLE READ, READ ONLY transaction: every read through it sees the same
    database state, however many statements it runs. Used for the reads that must agree with each other."""

    def __init__(self, config: DatabaseConfig, conn: psycopg.Connection) -> None:
        super().__init__(config)
        self._conn = conn

    @contextmanager
    def connection(self) -> Generator[psycopg.Connection, None, None]:
        yield _HeldConnection(self._conn)  # type: ignore[misc]

    @contextmanager
    def cursor(self) -> Generator[psycopg.Cursor, None, None]:
        with self._conn.cursor() as cur:
            yield cur



class RequestDatabase(Database):
    """P10-D1 option B (Sven Morais, 2026-10-21): one connection for one request, with no new dependency.

    It is made per request by `api.dependencies.get_database` and closed when the request ends. It is never shared
    between requests.
    - **A top-level `connection()` / `cursor()` call reuses the request's connection.** Each call is still its own
      transaction: commit on success, rollback on error, exactly as with a plain `Database`.
    - **A call made while the connection is in use gets a fresh connection,** as before. That covers a nested call or
      another thread. Transaction boundaries never merge: an inner commit can never commit an outer call's work.
    - **A closed or broken connection is replaced on the next call.** The call that hit the failure raises, as a
      per-call connection would.
    - **`read_snapshot` uses the request connection when it is idle** (REPEATABLE READ, READ ONLY), then restores
      it.
    - Timeouts come from the same `DatabaseConfig`, so they are unchanged.
    """

    def __init__(self, config: DatabaseConfig) -> None:
        super().__init__(config)
        self._lock = threading.Lock()
        self._conn: psycopg.Connection | None = None
        self._in_use = False
        self._closed = False
        self.connections_opened = 0

    def _take(self) -> psycopg.Connection | None:
        """The request connection, marked in use; None when it is busy or the request is over (the caller then uses
        a fresh connection)."""
        with self._lock:
            if self._in_use or self._closed:
                return None
            if self._conn is None or self._conn.closed or self._conn.broken:
                if self._conn is not None:
                    self._conn.close()
                self._conn = psycopg.connect(self._config.database_url, **self._config.connect_kwargs())
                self.connections_opened += 1
            self._in_use = True
            return self._conn

    def _give_back(self) -> None:
        with self._lock:
            self._in_use = False

    @contextmanager
    def connection(self) -> Generator[psycopg.Connection, None, None]:
        conn = self._take()
        if conn is None:
            with super().connection() as fresh:
                yield fresh
            return
        try:
            yield conn
            conn.commit()
        except BaseException:
            try:
                conn.rollback()
            except Exception:  # the connection is gone: it is replaced on the next call
                conn.close()
            raise
        finally:
            self._give_back()

    @contextmanager
    def snapshot_connection(self) -> Generator[psycopg.Connection | None, None, None]:
        """The idle request connection inside one REPEATABLE READ, READ ONLY transaction, or None if it is busy."""
        conn = self._take()
        if conn is None:
            yield None
            return
        try:
            conn.isolation_level = psycopg.IsolationLevel.REPEATABLE_READ
            conn.read_only = True
            yield conn
        finally:
            try:
                conn.rollback()
                conn.isolation_level = None  # back to the server default (read committed), read-write
                conn.read_only = None
            except Exception:
                conn.close()
            self._give_back()

    def close(self) -> None:
        with self._lock:
            self._closed = True
            if self._conn is not None:
                self._conn.close()
                self._conn = None


class _HeldConnection:
    """The snapshot's connection as callers see it: `commit` and `rollback` do nothing, so code written for a plain
    `Database.connection()` (some readers end their read transaction explicitly) cannot end the snapshot and
    silently start a new one. Only `read_snapshot` ends it."""

    def __init__(self, conn: psycopg.Connection) -> None:
        self._conn = conn

    def commit(self) -> None:
        pass

    def rollback(self) -> None:
        pass

    def __getattr__(self, name: str) -> Any:
        return getattr(self._conn, name)


@contextmanager
def read_snapshot(database: Database) -> Generator[Database, None, None]:
    """P10-M2 (Phase 7 R9): `database` as one consistent read snapshot.

    Without it, each statement opened its own connection. A live sync committing between two related reads (a
    team's scores, then its auto points) could make them disagree, and the result failed its own invariants: a 500
    under live load, found by the P10-M2 simulated event.

    Only a plain `Database` is wrapped. A snapshot is reused as it is. Another `Database` subclass (the read-only
    session of batch jobs, or a test double) is passed through unchanged, because it manages its own connection."""
    if isinstance(database, RequestDatabase):  # P10-D1 B: the request's own connection, when idle
        with database.snapshot_connection() as conn:
            if conn is not None:
                yield SnapshotDatabase(database._config, conn)
                return
        with read_snapshot(Database(database._config)) as snapshot:  # busy: a fresh snapshot, as before
            yield snapshot
        return
    if type(database) is not Database:
        yield database
        return
    config = database._config
    with psycopg.connect(config.database_url, **config.connect_kwargs()) as conn:
        conn.isolation_level = psycopg.IsolationLevel.REPEATABLE_READ
        conn.read_only = True
        try:
            yield SnapshotDatabase(config, conn)
        finally:
            conn.rollback()


def consistent_reads(function: Callable[..., T]) -> Callable[..., T]:
    """Run `function(database, ...)` with every read through `database` on one snapshot (`read_snapshot`), so one
    response is one database version (review P10-R1: the strength view, event analysis and pre-match report each
    made many reads, and a live sync could commit between them). Nested calls reuse the outer snapshot.

    Reads made through another object are not covered: an EPA provider or scale lookup built on the app's own
    `Database` (docs/phase10.md, P10-R4)."""
    @functools.wraps(function)
    def wrapper(database: Database, *args: Any, **kwargs: Any) -> T:
        with read_snapshot(database) as snapshot:
            return function(snapshot, *args, **kwargs)
    return wrapper
