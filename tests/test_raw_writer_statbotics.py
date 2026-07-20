from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from unittest.mock import Mock

import httpx
import pytest

from data.clients.statbotics import StatboticsClient
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
    """Mimics a single psycopg connection that may yield several cursors in sequence."""

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


class DummyHttpResponse(httpx.Response):
    def __init__(self, status_code: int, json_body: dict | list[Any]):
        super().__init__(status_code, request=httpx.Request("GET", "https://example.com"))
        self._json_body = json_body

    def json(self) -> Any:
        return self._json_body


@pytest.fixture
def env_settings(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgresql://user:pass@localhost:5432/testdb")
    monkeypatch.setenv("TBA_API_KEY", "test-key")
    monkeypatch.setenv("ENV", "development")
    return Settings()


def _writer_with_dummy_connect(monkeypatch, fetchone_results: list[tuple | None]) -> tuple[RawPayloadWriter, list[DummyCursor]]:
    queue = list(fetchone_results)
    cursors: list[DummyCursor] = []

    def fake_connect(*_args, **_kwargs) -> DummyConnection:
        return DummyConnection(queue, cursors)

    monkeypatch.setattr("database.connection.psycopg.connect", fake_connect)
    database = Database(DatabaseConfig("postgresql://user:pass@localhost:5432/testdb"))
    return RawPayloadWriter(database=database), cursors


# --- metadata / checksum / dedup, mirroring the generic RawPayloadWriter tests
# but exercised specifically with Statbotics-shaped payloads and identifiers ---

def test_statbotics_payload_lands_with_correct_metadata(monkeypatch):
    writer, cursors = _writer_with_dummy_connect(monkeypatch, fetchone_results=[(1,)])
    payload = {"team": 1114, "event": "2025casj", "epa_total": 45.2}
    fetch_time = datetime(2026, 7, 20, tzinfo=timezone.utc)

    record = RawPayloadRecord(
        source="statbotics",
        source_object_type="team_event",
        source_object_id="1114_2025casj",
        payload=payload,
        source_schema_version="v3",
        fetch_timestamp=fetch_time,
    )

    result = writer.write(record)

    assert result is True
    _, insert_params = cursors[0].executed[0]
    assert insert_params[0] == "statbotics"
    assert insert_params[1] == "team_event"
    assert insert_params[2] == "1114_2025casj"
    assert insert_params[3] == fetch_time
    assert insert_params[4].obj == payload
    assert insert_params[5] == compute_payload_checksum(payload)
    assert insert_params[6] == "v3"


def test_statbotics_checksum_is_deterministic():
    payload_a = {"team": 1114, "event": "2025casj", "epa_total": 45.2}
    payload_b = {"event": "2025casj", "team": 1114, "epa_total": 45.2}
    assert compute_payload_checksum(payload_a) == compute_payload_checksum(payload_b)


def test_statbotics_duplicate_payload_is_not_reinserted(monkeypatch):
    writer, cursors = _writer_with_dummy_connect(monkeypatch, fetchone_results=[None])
    record = RawPayloadRecord(
        source="statbotics", source_object_type="team_event", source_object_id="1114_2025casj",
        payload={"team": 1114, "event": "2025casj", "epa_total": 45.2},
    )

    result = writer.write(record)

    assert result is False
    assert len(cursors[0].executed) == 1  # no demotion UPDATE for a no-op duplicate


def test_statbotics_changed_payload_creates_new_version(monkeypatch):
    writer, cursors = _writer_with_dummy_connect(monkeypatch, fetchone_results=[(7,)])
    record = RawPayloadRecord(
        source="statbotics", source_object_type="team_event", source_object_id="1114_2025casj",
        payload={"team": 1114, "event": "2025casj", "epa_total": 47.9},
    )

    result = writer.write(record)

    assert result is True
    assert len(cursors[0].executed) == 2
    update_query, update_params = cursors[0].executed[1]
    assert "SET is_current = FALSE" in update_query
    assert update_params == ("statbotics", "team_event", "1114_2025casj", 7)


def test_tba_and_statbotics_with_same_object_id_are_treated_independently(monkeypatch):
    # Same source_object_type/id, different source: the dedup key includes
    # `source`, so both must be treated as independent, non-conflicting writes.
    writer, cursors = _writer_with_dummy_connect(monkeypatch, fetchone_results=[(1,), (2,)])

    tba_record = RawPayloadRecord(
        source="tba", source_object_type="team", source_object_id="9999", payload={"team_number": 9999}
    )
    statbotics_record = RawPayloadRecord(
        source="statbotics", source_object_type="team", source_object_id="9999", payload={"team": 9999}
    )

    assert writer.write(tba_record) is True
    assert writer.write(statbotics_record) is True

    tba_insert_params = cursors[0].executed[0][1]
    statbotics_insert_params = cursors[1].executed[0][1]
    assert tba_insert_params[0] == "tba"
    assert statbotics_insert_params[0] == "statbotics"
    assert tba_insert_params[2] == statbotics_insert_params[2] == "9999"


# --- full connector -> landing composition, using the real StatboticsClient ---

def test_statbotics_client_fetch_result_lands_through_raw_payload_writer(monkeypatch, env_settings):
    client = StatboticsClient(settings=env_settings)
    raw_match_data = [
        {"key": "2025casj_qm1", "event": "2025casj", "predicted_winner": "red", "red_win_prob": 0.63}
    ]
    mock_request = Mock(return_value=DummyHttpResponse(200, raw_match_data))
    monkeypatch.setattr(client, "_client", Mock(request=mock_request))

    parsed = client.fetch_event_match_stats("2025casj")
    assert parsed[0].key == "2025casj_qm1"

    writer, cursors = _writer_with_dummy_connect(monkeypatch, fetchone_results=[(1,)])
    # The raw dict (exactly as returned by the source) is what gets landed,
    # not a re-serialization of the parsed model, per the Milestone 4
    # requirement to store payloads unmodified.
    record = RawPayloadRecord(
        source=StatboticsClient.source_name,
        source_object_type="match",
        source_object_id=parsed[0].key,
        payload=raw_match_data[0],
    )

    result = writer.write(record)

    assert result is True
    _, insert_params = cursors[0].executed[0]
    assert insert_params[4].obj == raw_match_data[0]
    client.close()


# --- real-database integration check (matches the project's established convention) ---

@pytest.mark.skip("Requires local PostgreSQL database and valid DATABASE_URL")
def test_statbotics_and_tba_coexist_against_real_database():
    settings = Settings()
    run_migrations(settings)
    database = Database(DatabaseConfig(settings.database_url))
    writer = RawPayloadWriter(database=database)

    with database.cursor() as cursor:
        cursor.execute("DELETE FROM raw_source_payloads WHERE source IN (%s, %s)", ("tba", "statbotics"))

    tba_record = RawPayloadRecord(source="tba", source_object_type="team", source_object_id="frc9999", payload={"v": 1})
    statbotics_v1 = RawPayloadRecord(
        source="statbotics", source_object_type="team", source_object_id="frc9999", payload={"v": 1}
    )
    statbotics_v2 = RawPayloadRecord(
        source="statbotics", source_object_type="team", source_object_id="frc9999", payload={"v": 2}
    )

    assert writer.write(tba_record) is True
    assert writer.write(statbotics_v1) is True
    assert writer.write(statbotics_v1) is False  # duplicate, same source
    assert writer.write(statbotics_v2) is True  # new version, same source

    with database.cursor() as cursor:
        cursor.execute(
            "SELECT source, is_current FROM raw_source_payloads "
            "WHERE source_object_id = %s ORDER BY source, id",
            ("frc9999",),
        )
        rows = cursor.fetchall()

    # tba: 1 row (still current). statbotics: 2 rows (v1 demoted, v2 current).
    tba_rows = [r for r in rows if r[0] == "tba"]
    statbotics_rows = [r for r in rows if r[0] == "statbotics"]
    assert len(tba_rows) == 1 and tba_rows[0][1] is True
    assert len(statbotics_rows) == 2
    assert statbotics_rows[0][1] is False
    assert statbotics_rows[1][1] is True

    with database.cursor() as cursor:
        cursor.execute("DELETE FROM raw_source_payloads WHERE source IN (%s, %s)", ("tba", "statbotics"))
