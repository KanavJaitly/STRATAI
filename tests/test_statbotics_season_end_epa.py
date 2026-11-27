"""Rule A1 for the reference Statbotics EPA source (audit 2026-11-26).

`EPA_SOURCE=statbotics` (the hosted deployment's source, render.yaml) selects a team's prior-event EPA from
team_event_stats by D13. A team-event whose Statbotics record has zero qualification matches carries Statbotics'
season-end rating (docs/ratings/data_contract.md section 9), so before the season's last completed match it is future
information. The evaluated D18 source has always refused it (rule A1, ml/ratings/statbotics_primary.py); this pins the
same rule on both paths of the reference source: the per-team SQL and the prefetched candidates.

Reuses the leakage fixtures of tests/test_ml_features_assembler.py (synthetic events 9988zzzmlearly / 9989zzzmltarget,
teams 98900x); the season-end marker is a synthetic Statbotics payload removed afterwards.
"""

from __future__ import annotations

import json

import tests.test_ml_features_assembler as base
from database.connection import Database
from ml.ratings.provider import StatboticsPointInTimeEpa, Unavailable
from tests.test_ml_features_assembler import database, requires_db  # noqa: F401  (pytest fixtures)

_OBJECT_ID = f"{base._TEAM_A}_{base._EVENT_CONCLUDED}"
_LATER_EVENT = "9988zzzmlaudit"  # a later event of the concluded event's season (9988), so the season is not over
_LATER_MATCH = f"{_LATER_EVENT}_qm1"


def _season_continues(database: Database) -> None:
    """A completed match in season 9988 after the cutoff: the season's last completed match is now after _AS_OF."""
    later = base._T3.replace(day=base._T3.day + 1)
    with database.cursor() as cursor:
        cursor.execute("INSERT INTO events (event_key, season, name, end_date) VALUES (%s, 9988, 'audit A1', %s) "
                       "ON CONFLICT DO NOTHING", (_LATER_EVENT, later.date()))
        cursor.execute("INSERT INTO matches (match_key, event_key, season, competition_level, match_number, "
                       "scheduled_time, score_red, score_blue) VALUES (%s, %s, 9988, 'qualification', 1, %s, 10, 9) "
                       "ON CONFLICT DO NOTHING", (_LATER_MATCH, _LATER_EVENT, later))


def _season_cleanup(database: Database) -> None:
    with database.cursor() as cursor:
        cursor.execute("DELETE FROM matches WHERE match_key = %s", (_LATER_MATCH,))
        cursor.execute("DELETE FROM events WHERE event_key = %s", (_LATER_EVENT,))


def _mark_season_end(database: Database, qual_count: int) -> None:
    payload = {"team": base._TEAM_A, "event": base._EVENT_CONCLUDED, "record": {"qual": {"count": qual_count}}}
    with database.cursor() as cursor:
        cursor.execute("DELETE FROM raw_source_payloads WHERE source = 'statbotics' AND source_object_type = "
                       "'team_event' AND source_object_id = %s", (_OBJECT_ID,))
        cursor.execute("INSERT INTO raw_source_payloads (source, source_object_type, source_object_id, season, "
                       "event_key, payload_json, payload_checksum, is_current) VALUES ('statbotics', 'team_event', "
                       "%s, 2026, %s, %s, %s, TRUE)",
                       (_OBJECT_ID, base._EVENT_CONCLUDED, json.dumps(payload), f"audit-a1-{qual_count}"))


def _unmark(database: Database) -> None:
    with database.cursor() as cursor:
        cursor.execute("DELETE FROM raw_source_payloads WHERE source = 'statbotics' AND source_object_type = "
                       "'team_event' AND source_object_id = %s", (_OBJECT_ID,))


def _both(database: Database, as_of: datetime):
    plain = StatboticsPointInTimeEpa(database).point_in_time_epa(base._TEAM_A, base._EVENT_TARGET, as_of)
    prefetched = StatboticsPointInTimeEpa(database).prefetched([base._TEAM_A]).point_in_time_epa(
        base._TEAM_A, base._EVENT_TARGET, as_of)
    return plain, prefetched


@requires_db
def test_a_season_end_value_is_not_a_prior_event_epa_during_the_season(database: Database) -> None:
    try:
        _season_continues(database)
        _mark_season_end(database, 0)
        plain, prefetched = _both(database, base._AS_OF)
        assert isinstance(plain, Unavailable) and isinstance(prefetched, Unavailable)
    finally:
        _unmark(database)
        _season_cleanup(database)


@requires_db
def test_a_season_end_value_is_available_after_the_season(database: Database) -> None:
    after = base._T3.replace(day=base._T3.day + 2)  # after the later season-9988 match: the season is over
    try:
        _season_continues(database)
        _mark_season_end(database, 0)
        plain, prefetched = _both(database, after)
        assert not isinstance(plain, Unavailable) and plain == prefetched
        assert plain.event_key == base._EVENT_CONCLUDED
    finally:
        _unmark(database)
        _season_cleanup(database)
        _season_cleanup(database)


@requires_db
def test_a_record_with_qualification_matches_is_unaffected(database: Database) -> None:
    try:
        _season_continues(database)
        _mark_season_end(database, 10)
        plain, prefetched = _both(database, base._AS_OF)
        assert not isinstance(plain, Unavailable) and plain == prefetched
        assert plain.event_key == base._EVENT_CONCLUDED
    finally:
        _unmark(database)
        _season_cleanup(database)
