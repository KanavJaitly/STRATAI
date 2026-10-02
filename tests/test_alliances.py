"""data.alliances: TBA playoff-alliance landing and read-back (seeds/picks apart from outcomes)."""

from __future__ import annotations

from typing import Any

import psycopg
import pytest

from data.alliances import (
    OBJECT_TYPE_EVENT_ALLIANCES,
    Alliance,
    parse_alliance_outcomes_payload,
    parse_alliances_payload,
    read_event_alliance_outcomes,
    read_event_alliances,
    sync_event_alliances,
    sync_season_alliances,
)
from data.clients.schemas import EventAlliance
from data.clients.source_connector import SourceResponse
from data.config import Settings
from database.connection import Database, DatabaseConfig

_PAYLOAD = [
    {"name": "Alliance 1", "picks": ["frc190", "frc1218", "frc5732", "frc8704"], "declines": [],
     "status": {"status": "won", "level": "f", "record": {"wins": 5, "losses": 1, "ties": 0}}},
    {"name": "Alliance 2", "picks": ["frc254", "frc1678", "frc971"], "declines": ["frc111"],
     "backup": {"in": "frc604", "out": "frc971"},
     "status": {"status": "eliminated", "level": "f", "record": {"wins": 3, "losses": 2, "ties": 0}}},
]


def test_parse_seeds_captain_picks_backup_declines():
    first, second = parse_alliances_payload(_PAYLOAD)
    assert first == Alliance(seed=1, position=1, name="Alliance 1", captain=190, picks=(190, 1218, 5732, 8704),
                             backup=None, declines=())
    assert second == Alliance(seed=2, position=2, name="Alliance 2", captain=254, picks=(254, 1678, 971),
                              backup=604, declines=(111,))


def test_seed_falls_back_to_list_order_without_names():
    payload = [{"picks": ["frc1", "frc2", "frc3"]}, {"picks": ["frc4", "frc5", "frc6"]}]
    assert [a.seed for a in parse_alliances_payload(payload)] == [1, 2]


def test_names_contradicting_list_order_reject_the_payload():
    payload = [{"name": "Alliance 2", "picks": ["frc1"]}, {"name": "Alliance 1", "picks": ["frc2"]}]
    assert parse_alliances_payload(payload) == []


def test_division_named_alliances_are_unseeded():
    """Einstein and multi-division DCMP finals name alliances after divisions: no seed."""
    payload = [{"name": "Archimedes", "picks": ["frc1", "frc2", "frc3"]},
               {"name": "Curie", "picks": ["frc4", "frc5", "frc6"]}]
    alliances = parse_alliances_payload(payload)
    assert [(a.seed, a.position, a.name) for a in alliances] == [(None, 1, "Archimedes"), (None, 2, "Curie")]


def test_partially_seeded_names_reject_the_payload():
    payload = [{"name": "Alliance 1", "picks": ["frc1"]}, {"name": "Curie", "picks": ["frc2"]}]
    assert parse_alliances_payload(payload) == []


@pytest.mark.parametrize("payload", [None, {}, "x", [None, {"name": "Alliance 1"}]])
def test_null_or_malformed_payloads_give_no_alliances(payload):
    assert parse_alliances_payload(payload) == []


def test_outcomes_are_parsed_separately_and_never_appear_on_alliances():
    outcomes = parse_alliance_outcomes_payload(_PAYLOAD)
    assert [(o.seed, o.status, o.wins, o.losses) for o in outcomes] == [(1, "won", 5, 1), (2, "eliminated", 3, 2)]
    assert not any(hasattr(a, "status") or hasattr(a, "wins") for a in parse_alliances_payload(_PAYLOAD))


def _database_available() -> bool:
    try:
        with psycopg.connect(str(Settings().database_url), connect_timeout=3):
            return True
    except Exception:
        return False


requires_db = pytest.mark.skipif(not _database_available(), reason="Requires a reachable PostgreSQL database")

_SEASON = 9983
_EVENT_A, _EVENT_B = "9983zzzallianceA", "9983zzzallianceB"


class _FakeTBA:
    def __init__(self, by_event: dict[str, Any]) -> None:
        self.by_event = by_event

    def fetch_event_alliances(self, event_key: str) -> SourceResponse[list[EventAlliance]]:
        raw = self.by_event.get(event_key)
        return SourceResponse(raw, [EventAlliance.model_validate(i) for i in (raw or [])])


def _cleanup(database: Database) -> None:
    with database.cursor() as cursor:
        cursor.execute("DELETE FROM raw_source_payloads WHERE source = 'tba' AND source_object_type = %s "
                       "AND source_object_id = ANY(%s::text[])", (OBJECT_TYPE_EVENT_ALLIANCES, [_EVENT_A, _EVENT_B]))
        cursor.execute("DELETE FROM events WHERE event_key = ANY(%s::text[])", ([_EVENT_A, _EVENT_B],))


@pytest.fixture
def database():
    from database.migrate import run_migrations

    settings = Settings()
    run_migrations(settings)
    db = Database(DatabaseConfig(settings.database_url))
    _cleanup(db)
    with db.cursor() as cursor:
        for key in (_EVENT_A, _EVENT_B):
            cursor.execute("INSERT INTO events (event_key, season, name) VALUES (%s, %s, %s)", (key, _SEASON, key))
    try:
        yield db
    finally:
        _cleanup(db)


@requires_db
def test_land_dedup_and_read_back(database):
    tba = _FakeTBA({_EVENT_A: _PAYLOAD, _EVENT_B: None})
    assert sync_event_alliances(_EVENT_A, database=database, tba=tba) is True
    assert sync_event_alliances(_EVENT_A, database=database, tba=tba) is False  # unchanged: nothing new landed
    assert sync_season_alliances(_SEASON, database=database, tba=tba, delay_seconds=0) == {"events": 2, "landed": 1}
    alliances = read_event_alliances(database, _SEASON)
    assert set(alliances) == {_EVENT_A}  # the null-alliance event is absent, not empty
    assert alliances[_EVENT_A][1].captain == 254
    assert read_event_alliance_outcomes(database, _SEASON)[_EVENT_A][0].status == "won"
