"""Event qualification-ranking ingestion, data.rankings.

Closes the ranking-ground-truth gap ml.backtest.harness's own module
docstring names (Phase 4 Milestone 3). Two kinds of tests, matching this
codebase's established split:

- Pure, database-free: _parse_ranking_payload against hand-built (and
  deliberately malformed) TBA-shaped payloads.
- requires_db integration tests: a fake TBAClient (mirroring tests/
  test_pipeline.py's FakeTBAClient convention -- no real network call) landing
  and reading back real rows through the real RawPayloadWriter and a real
  database.
"""

from __future__ import annotations

from typing import Any

import psycopg
import pytest

from data.clients.schemas import EventRankings
from data.clients.source_connector import SourceResponse
from data.config import Settings
from data.rankings import (
    OBJECT_TYPE_EVENT_RANKING,
    _parse_ranking_payload,
    read_final_ranks_for_season,
    sync_event_rankings,
    sync_season_rankings,
)
from database.connection import Database, DatabaseConfig

# ---------------------------------------------------------------------------
# Pure tests: _parse_ranking_payload
# ---------------------------------------------------------------------------


def test_parse_ranking_payload_normal_case():
    payload = {"rankings": [{"team_key": "frc1114", "rank": 1}, {"team_key": "frc254", "rank": 2}]}
    assert _parse_ranking_payload(payload) == {1114: 1, 254: 2}


def test_parse_ranking_payload_collapses_offseason_b_team():
    payload = {"rankings": [{"team_key": "frc254b", "rank": 5}]}
    assert _parse_ranking_payload(payload) == {254: 5}


def test_parse_ranking_payload_none_payload_is_empty():
    assert _parse_ranking_payload(None) == {}


def test_parse_ranking_payload_non_dict_payload_is_empty():
    assert _parse_ranking_payload("not a dict") == {}
    assert _parse_ranking_payload([1, 2, 3]) == {}


def test_parse_ranking_payload_missing_rankings_key_is_empty():
    assert _parse_ranking_payload({}) == {}


def test_parse_ranking_payload_null_rankings_is_empty():
    # TBA's real null-body case, already landed as {"rankings": None, ...}
    # by the time it reaches storage in some hypothetical malformed payload --
    # defensive, since TBAClient.fetch_event_rankings itself already handles
    # the top-level null case before this function ever sees it.
    assert _parse_ranking_payload({"rankings": None}) == {}


def test_parse_ranking_payload_non_list_rankings_is_empty():
    assert _parse_ranking_payload({"rankings": "not a list"}) == {}


def test_parse_ranking_payload_skips_non_dict_entries():
    payload = {"rankings": [{"team_key": "frc1114", "rank": 1}, "garbage", None, 42]}
    assert _parse_ranking_payload(payload) == {1114: 1}


def test_parse_ranking_payload_skips_entries_missing_team_key_or_rank():
    payload = {"rankings": [
        {"team_key": "frc1114", "rank": 1},
        {"team_key": "frc254"},  # missing rank
        {"rank": 3},  # missing team_key
    ]}
    assert _parse_ranking_payload(payload) == {1114: 1}


def test_parse_ranking_payload_skips_unparseable_team_keys_but_keeps_the_rest():
    payload = {"rankings": [{"team_key": "frc1114", "rank": 1}, {"team_key": "not-a-team-key", "rank": 2}]}
    assert _parse_ranking_payload(payload) == {1114: 1}


# ---------------------------------------------------------------------------
# requires_db integration tests
# ---------------------------------------------------------------------------

_SEASON = 9940
_EVENT_A = "9940zzzranktesta"
_EVENT_B = "9940zzzranktestb"


def _database_available() -> bool:
    try:
        with psycopg.connect(str(Settings().database_url), connect_timeout=3):
            return True
    except Exception:
        return False


requires_db = pytest.mark.skipif(
    not _database_available(), reason="Requires a reachable PostgreSQL database via DATABASE_URL",
)


class FakeRankingsTBAClient:
    """Minimal TBAClient stand-in: only fetch_event_rankings, no real network
    call, mirroring tests/test_pipeline.py's FakeTBAClient convention."""

    def __init__(self, rankings_by_event: dict[str, dict[str, Any] | None]) -> None:
        self._rankings_by_event = rankings_by_event
        self.calls: list[str] = []

    def fetch_event_rankings(self, event_key: str) -> SourceResponse[EventRankings]:
        self.calls.append(event_key)
        raw = self._rankings_by_event.get(event_key)
        parsed = EventRankings.model_validate(raw) if raw is not None else EventRankings(rankings=[])
        return SourceResponse(raw, parsed)


def _cleanup(database: Database) -> None:
    with database.cursor() as cursor:
        cursor.execute(
            "DELETE FROM raw_source_payloads WHERE source = 'tba' AND source_object_type = %s "
            "AND source_object_id = ANY(%s::text[])",
            (OBJECT_TYPE_EVENT_RANKING, [_EVENT_A, _EVENT_B]),
        )
        cursor.execute("DELETE FROM events WHERE event_key = ANY(%s::text[])", ([_EVENT_A, _EVENT_B],))


@pytest.fixture
def database() -> Database:
    from database.migrate import run_migrations

    settings = Settings()
    run_migrations(settings)
    db = Database(DatabaseConfig(settings.database_url))
    _cleanup(db)
    with db.cursor() as cursor:
        cursor.execute(
            "INSERT INTO events (event_key, season, name) VALUES (%s, %s, %s)", (_EVENT_A, _SEASON, "Sentinel A"),
        )
        cursor.execute(
            "INSERT INTO events (event_key, season, name) VALUES (%s, %s, %s)", (_EVENT_B, _SEASON, "Sentinel B"),
        )
    try:
        yield db
    finally:
        _cleanup(db)


@requires_db
def test_sync_event_rankings_lands_and_dedups(database: Database):
    tba = FakeRankingsTBAClient({_EVENT_A: {"rankings": [{"team_key": "frc1114", "rank": 1}]}})

    assert sync_event_rankings(_EVENT_A, database=database, tba=tba) is True
    # Re-syncing an unchanged ranking lands nothing new -- RawPayloadWriter's
    # own checksum dedup, the same idempotency guarantee every other object
    # type in this pipeline already has.
    assert sync_event_rankings(_EVENT_A, database=database, tba=tba) is False


@requires_db
def test_sync_season_rankings_covers_every_synced_event_of_that_season(database: Database):
    tba = FakeRankingsTBAClient({
        _EVENT_A: {"rankings": [{"team_key": "frc1114", "rank": 1}]},
        _EVENT_B: {"rankings": [{"team_key": "frc254", "rank": 1}]},
    })
    result = sync_season_rankings(_SEASON, database=database, tba=tba, delay_seconds=0.0)
    assert result == {"events": 2, "landed": 2}
    assert sorted(tba.calls) == [_EVENT_A, _EVENT_B]


@requires_db
def test_sync_season_rankings_handles_a_null_ranking_event(database: Database):
    # TBA's real null-body case for an event with no computed ranking yet.
    tba = FakeRankingsTBAClient({_EVENT_A: {"rankings": [{"team_key": "frc1114", "rank": 1}]}, _EVENT_B: None})
    result = sync_season_rankings(_SEASON, database=database, tba=tba, delay_seconds=0.0)
    assert result == {"events": 2, "landed": 2}


@requires_db
def test_read_final_ranks_for_season_round_trips_real_landed_data(database: Database):
    tba = FakeRankingsTBAClient({
        _EVENT_A: {"rankings": [{"team_key": "frc1114", "rank": 1}, {"team_key": "frc254", "rank": 2}]},
        _EVENT_B: {"rankings": [{"team_key": "frc33", "rank": 1}]},
    })
    sync_season_rankings(_SEASON, database=database, tba=tba, delay_seconds=0.0)

    final_ranks = read_final_ranks_for_season(database, _SEASON)
    assert final_ranks == {
        _EVENT_A: {1114: 1, 254: 2},
        _EVENT_B: {33: 1},
    }


@requires_db
def test_read_final_ranks_for_season_omits_events_with_no_landed_or_empty_ranking(database: Database):
    tba = FakeRankingsTBAClient({_EVENT_A: {"rankings": [{"team_key": "frc1114", "rank": 1}]}, _EVENT_B: None})
    sync_season_rankings(_SEASON, database=database, tba=tba, delay_seconds=0.0)

    final_ranks = read_final_ranks_for_season(database, _SEASON)
    assert final_ranks == {_EVENT_A: {1114: 1}}
    assert _EVENT_B not in final_ranks


@requires_db
def test_read_final_ranks_for_season_empty_when_nothing_synced(database: Database):
    assert read_final_ranks_for_season(database, _SEASON) == {}
