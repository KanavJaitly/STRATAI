from __future__ import annotations

from datetime import datetime, timezone

import pytest

from data.config import Settings
from data.landing.raw_writer import (
    RawPayloadRecord,
    RawPayloadWriter,
    compute_payload_checksum,
)
from database.connection import Database, DatabaseConfig
from database.migrate import run_migrations


class DummyCursor:
    def __init__(self, fetchone_result: tuple | None) -> None:
        self._fetchone_result = fetchone_result
        self.executed: list[tuple[str, tuple | None]] = []

    def execute(self, query: str, params: tuple | None = None) -> None:
        self.executed.append((query, params))

    def fetchone(self) -> tuple | None:
        return self._fetchone_result

    def __enter__(self) -> "DummyCursor":
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        pass


class DummyConnection:
    """Mimics a single psycopg connection that may yield several cursors in
    sequence (one per write_many() record) or just one (a single write() call).
    """

    def __init__(self, fetchone_queue: list[tuple | None], cursors_out: list[DummyCursor]) -> None:
        self._fetchone_queue = fetchone_queue
        self._cursors_out = cursors_out

    def cursor(self) -> DummyCursor:
        cursor = DummyCursor(self._fetchone_queue.pop(0))
        self._cursors_out.append(cursor)
        return cursor

    def commit(self) -> None:
        pass

    def rollback(self) -> None:
        pass

    def __enter__(self) -> "DummyConnection":
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        pass


@pytest.fixture
def env_settings(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgresql://user:pass@localhost:5432/testdb")
    monkeypatch.setenv("TBA_API_KEY", "test-key")
    monkeypatch.setenv("ENV", "development")
    return Settings()


def _writer_with_dummy_connect(
    monkeypatch, fetchone_results: list[tuple | None]
) -> tuple[RawPayloadWriter, list[DummyCursor], list[int]]:
    queue = list(fetchone_results)
    cursors: list[DummyCursor] = []
    connect_calls: list[int] = []

    def fake_connect(*_args, **_kwargs) -> DummyConnection:
        connect_calls.append(1)
        return DummyConnection(queue, cursors)

    monkeypatch.setattr("database.connection.psycopg.connect", fake_connect)
    database = Database(DatabaseConfig("postgresql://user:pass@localhost:5432/testdb"))
    return RawPayloadWriter(database=database), cursors, connect_calls


# --- checksum determinism -------------------------------------------------

def test_checksum_is_deterministic_for_identical_payload():
    payload = {"key": "2025casj", "name": "Sacramento", "season": 2025}
    assert compute_payload_checksum(payload) == compute_payload_checksum(dict(payload))


def test_checksum_ignores_key_order():
    payload_a = {"a": 1, "b": {"x": 1, "y": 2}}
    payload_b = {"b": {"y": 2, "x": 1}, "a": 1}
    assert compute_payload_checksum(payload_a) == compute_payload_checksum(payload_b)


def test_checksum_differs_for_different_content():
    assert compute_payload_checksum({"a": 1}) != compute_payload_checksum({"a": 2})


def test_checksum_handles_list_payloads():
    # Some source endpoints return top-level arrays; the checksum must not assume a dict.
    assert compute_payload_checksum([1, 2, 3]) == compute_payload_checksum([1, 2, 3])
    assert compute_payload_checksum([1, 2, 3]) != compute_payload_checksum([3, 2, 1])


def test_checksum_handles_empty_payload():
    assert compute_payload_checksum({}) == compute_payload_checksum({})


# --- write() insert / dedup behavior -------------------------------------

def test_write_inserts_new_payload_and_stores_metadata_unchanged(monkeypatch):
    writer, cursors, _ = _writer_with_dummy_connect(monkeypatch, fetchone_results=[(1,)])
    payload = {"key": "frc1114", "team_number": 1114, "nickname": "Simbotics"}
    fetch_time = datetime(2026, 7, 20, tzinfo=timezone.utc)

    record = RawPayloadRecord(
        source="tba",
        source_object_type="team",
        source_object_id="frc1114",
        payload=payload,
        source_schema_version="v3",
        fetch_timestamp=fetch_time,
    )

    result = writer.write(record)

    assert result is True
    insert_query, insert_params = cursors[0].executed[1]  # [0] is the advisory-lock acquisition
    assert "INSERT INTO raw_source_payloads" in insert_query
    assert "ON CONFLICT (source, source_object_type, source_object_id, payload_checksum)" in insert_query
    assert insert_params[0] == "tba"
    assert insert_params[1] == "team"
    assert insert_params[2] == "frc1114"
    assert insert_params[3] == fetch_time
    assert insert_params[4].obj == payload  # psycopg Jsonb wrapper preserves the payload unmodified
    assert insert_params[5] == compute_payload_checksum(payload)
    assert insert_params[6] == "v3"


def test_write_demotes_prior_current_row_on_new_version(monkeypatch):
    writer, cursors, _ = _writer_with_dummy_connect(monkeypatch, fetchone_results=[(42,)])
    record = RawPayloadRecord(source="tba", source_object_type="team", source_object_id="frc1114", payload={"v": 2})

    writer.write(record)

    assert len(cursors[0].executed) == 3  # lock, insert, demotion update
    update_query, update_params = cursors[0].executed[2]
    assert "SET is_current = FALSE" in update_query
    assert update_params == ("tba", "team", "frc1114", 42)


def test_write_duplicate_payload_is_not_reinserted(monkeypatch):
    # Simulates ON CONFLICT DO NOTHING: no row returned from the INSERT.
    writer, cursors, _ = _writer_with_dummy_connect(monkeypatch, fetchone_results=[None])
    record = RawPayloadRecord(source="tba", source_object_type="team", source_object_id="frc1114", payload={"v": 1})

    result = writer.write(record)

    assert result is False
    # The demotion UPDATE must never run for a no-op duplicate (just the lock + insert attempt).
    assert len(cursors[0].executed) == 2


def test_write_default_fetch_timestamp_is_timezone_aware(monkeypatch):
    writer, cursors, _ = _writer_with_dummy_connect(monkeypatch, fetchone_results=[(1,)])
    record = RawPayloadRecord(source="tba", source_object_type="team", source_object_id="frc1114", payload={"v": 1})

    writer.write(record)

    _, insert_params = cursors[0].executed[1]
    fetch_timestamp = insert_params[3]
    assert isinstance(fetch_timestamp, datetime)
    assert fetch_timestamp.tzinfo is not None


def test_write_many_counts_only_new_insertions(monkeypatch):
    # First and third payloads are new, second is a duplicate.
    writer, _, connect_calls = _writer_with_dummy_connect(monkeypatch, fetchone_results=[(1,), None, (2,)])
    records = [
        RawPayloadRecord(source="tba", source_object_type="team", source_object_id="frc1114", payload={"v": 1}),
        RawPayloadRecord(source="tba", source_object_type="team", source_object_id="frc1114", payload={"v": 1}),
        RawPayloadRecord(source="tba", source_object_type="team", source_object_id="frc254", payload={"v": 1}),
    ]

    inserted_count = writer.write_many(records)

    assert inserted_count == 2
    # write_many must reuse a single connection across the whole batch rather
    # than opening one per record (critical for event-weekend write volumes).
    assert len(connect_calls) == 1


def test_write_handles_empty_dict_payload(monkeypatch):
    writer, cursors, _ = _writer_with_dummy_connect(monkeypatch, fetchone_results=[(1,)])
    record = RawPayloadRecord(source="tba", source_object_type="event", source_object_id="2025casj", payload={})

    result = writer.write(record)

    assert result is True
    assert cursors[0].executed[1][1][4].obj == {}


# ===========================================================================
# Integration tests: real dedup/versioning behaviour against the actual schema.
# Auto-skips when no PostgreSQL is reachable via the configured DATABASE_URL.
#
# Both tests below run against the *real* configured database and clean up by
# `source`. That is safe here only because `test_source` and `race_test` are
# values no connector can ever emit -- `source_name` is a ClassVar fixed to
# "tba" (data/clients/tba.py) or "statbotics" (data/clients/statbotics.py), so
# these deletes cannot match an ingested row. Cleaning up by `source` alone is
# NOT safe for a real source name: `raw_source_payloads` is the parent of two
# ON DELETE CASCADE foreign keys (0007), and every real row carries one of the
# two real sources, so such a delete takes the whole landing layer plus all
# lineage and quality issues with it. See tests/test_raw_writer_statbotics.py,
# where that had to be scoped by `source_object_id` instead.
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


@requires_db
def test_raw_writer_end_to_end_against_real_database():
    """Integration check: real dedup/versioning behavior against the actual schema."""
    settings = Settings()
    run_migrations(settings)
    database = Database(DatabaseConfig(settings.database_url))
    writer = RawPayloadWriter(database=database)

    with database.cursor() as cursor:
        cursor.execute(
            "DELETE FROM raw_source_payloads WHERE source = %s", ("test_source",)
        )

    first = RawPayloadRecord(
        source="test_source", source_object_type="team", source_object_id="frc9999", payload={"v": 1}
    )
    second_same = RawPayloadRecord(
        source="test_source", source_object_type="team", source_object_id="frc9999", payload={"v": 1}
    )
    third_changed = RawPayloadRecord(
        source="test_source", source_object_type="team", source_object_id="frc9999", payload={"v": 2}
    )

    assert writer.write(first) is True
    assert writer.write(second_same) is False
    assert writer.write(third_changed) is True
    # Re-running the whole sequence again must be a no-op (idempotent).
    assert writer.write(first) is False
    assert writer.write(third_changed) is False

    with database.cursor() as cursor:
        cursor.execute(
            "SELECT payload_json, is_current FROM raw_source_payloads "
            "WHERE source = %s AND source_object_id = %s ORDER BY id",
            ("test_source", "frc9999"),
        )
        rows = cursor.fetchall()

    assert len(rows) == 2
    assert rows[0][1] is False
    assert rows[1][1] is True

    with database.cursor() as cursor:
        cursor.execute("DELETE FROM raw_source_payloads WHERE source = %s", ("test_source",))


@requires_db
def test_concurrent_writes_of_different_new_versions_leave_exactly_one_current_row():
    """Regression test for a real race found in Milestone 5 acceptance review.

    Two threads writing two *different* new versions of the same object at the
    same time must never leave more than one row marked is_current: each
    write's checksum differs, so ON CONFLICT never fires for either, and
    without serializing on the object's identity both demotion UPDATEs could
    each miss the other's concurrently-inserted row.
    """
    import threading

    settings = Settings()
    run_migrations(settings)
    database = Database(DatabaseConfig(settings.database_url))
    writer = RawPayloadWriter(database=database)

    with database.cursor() as cursor:
        cursor.execute("DELETE FROM raw_source_payloads WHERE source = %s", ("race_test",))

    barrier = threading.Barrier(2)
    results: dict[str, bool] = {}

    def write_version(label: str, value: int) -> None:
        barrier.wait()
        record = RawPayloadRecord(
            source="race_test", source_object_type="team", source_object_id="9999", payload={"v": value}
        )
        results[label] = writer.write(record)

    t1 = threading.Thread(target=write_version, args=("A", 100))
    t2 = threading.Thread(target=write_version, args=("B", 200))
    t1.start()
    t2.start()
    t1.join()
    t2.join()

    assert results == {"A": True, "B": True}

    with database.cursor() as cursor:
        cursor.execute(
            "SELECT is_current FROM raw_source_payloads WHERE source = %s AND source_object_id = %s",
            ("race_test", "9999"),
        )
        rows = cursor.fetchall()

    assert len(rows) == 2
    assert sum(1 for row in rows if row[0]) == 1

    with database.cursor() as cursor:
        cursor.execute("DELETE FROM raw_source_payloads WHERE source = %s", ("race_test",))


def test_write_many_stops_after_failure_and_preserves_earlier_commits(monkeypatch, caplog):
    """Regression test found in the Phase 2 midpoint audit.

    A failure partway through a batch must not roll back records already
    committed earlier in the same call, must not attempt records after the
    failure, and must log how much progress was made — since the exception
    path has no way to return a partial count to the caller.
    """

    class RaisingCursor(DummyCursor):
        def execute(self, query: str, params: tuple | None = None) -> None:
            super().execute(query, params)
            if "INSERT INTO raw_source_payloads" in query and params[2] == "boom":
                raise RuntimeError("simulated write failure")

    cursors_created: list[DummyCursor] = []

    class FakeConnection:
        def __init__(self) -> None:
            self._call_count = 0

        def cursor(self) -> DummyCursor:
            self._call_count += 1
            cursor = DummyCursor((self._call_count,)) if self._call_count == 1 else RaisingCursor((99,))
            cursors_created.append(cursor)
            return cursor

        def commit(self) -> None:
            pass

        def rollback(self) -> None:
            pass

        def __enter__(self) -> "FakeConnection":
            return self

        def __exit__(self, exc_type, exc, tb) -> None:
            pass

    monkeypatch.setattr("database.connection.psycopg.connect", lambda *_a, **_kw: FakeConnection())
    database = Database(DatabaseConfig("postgresql://user:pass@localhost:5432/testdb"))
    writer = RawPayloadWriter(database=database)

    records = [
        RawPayloadRecord(source="tba", source_object_type="team", source_object_id="ok", payload={"v": 1}),
        RawPayloadRecord(source="tba", source_object_type="team", source_object_id="boom", payload={"v": 2}),
        RawPayloadRecord(source="tba", source_object_type="team", source_object_id="never_reached", payload={"v": 3}),
    ]

    with caplog.at_level("ERROR", logger="data.landing.raw_writer"):
        with pytest.raises(RuntimeError, match="simulated write failure"):
            writer.write_many(records)

    # Only two cursors were ever created: the successful record and the failing
    # one. The third record was never attempted.
    assert len(cursors_created) == 2
    assert "landing 1 record" in caplog.text
    assert "boom" in caplog.text
