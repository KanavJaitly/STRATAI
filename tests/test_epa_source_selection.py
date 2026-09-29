"""Deterministic point-in-time EPA source selection (decided 2026-09-29).

One sentinel world (seasons 9961-9962, teams 99911-99913) exercises the rule in
ml.features.assembler.EPA_SOURCE_SQL, and checks that
automation.data_readiness derives the same source independently:

- a Championship division and Einstein end the same day -> Einstein
  (latest completed match) is the source for the team's next event;
- a DCMP division and the DCMP finals -> the finals;
- identical latest-match timestamps -> event_key ascending;
- a Saturday-morning division match never sees the same-day Einstein/finals EPA
  (the event is not finished before as_of), which end_date alone would allow;
- repeated execution returns the same source.
"""

from __future__ import annotations

import json
from datetime import date, datetime, timezone

import psycopg
import pytest

from automation import data_readiness as dr
from data.config import Settings
from database.connection import Database, DatabaseConfig
from ml.features.assembler import _point_in_time_epa

T_CHAMPS, T_DCMP, T_TIE = 99911, 99912, 99913
SEASONS = (9961, 9962)


def at(y: int, m: int, d: int, hh: int, mm: int = 0) -> datetime:
    return datetime(y, m, d, hh, mm, tzinfo=timezone.utc)


# event_key -> (season, end_date, [(team, scheduled_time), ...]); every match is completed.
EVENTS = {
    "9961zzzreg":    (9961, date(9961, 3, 10), [(T_CHAMPS, at(9961, 3, 9, 12)), (T_DCMP, at(9961, 3, 9, 13)),
                                                 (T_TIE, at(9961, 3, 9, 14))]),
    # Championship: division plays through Saturday morning, Einstein Saturday afternoon.
    "9961zzzcur":    (9961, date(9961, 4, 20), [(T_CHAMPS, at(9961, 4, 18, 10)), (T_CHAMPS, at(9961, 4, 20, 9))]),
    "9961zzzcmptx":  (9961, date(9961, 4, 20), [(T_CHAMPS, at(9961, 4, 20, 15))]),
    # District championship: division, then finals, same day.
    "9961zzzmicmp1": (9961, date(9961, 4, 6), [(T_DCMP, at(9961, 4, 4, 10)), (T_DCMP, at(9961, 4, 6, 9, 30))]),
    "9961zzzmicmp":  (9961, date(9961, 4, 6), [(T_DCMP, at(9961, 4, 6, 15, 39))]),
    # Two same-day events whose latest matches are simultaneous: event_key decides.
    "9961zzzsameb":  (9961, date(9961, 4, 13), [(T_TIE, at(9961, 4, 13, 12))]),
    "9961zzzsamea":  (9961, date(9961, 4, 13), [(T_TIE, at(9961, 4, 13, 12))]),
    # Each team's next event, where the rule is observed.
    "9962zzznext":   (9962, date(9962, 3, 10), [(T_CHAMPS, at(9962, 3, 9, 12)), (T_DCMP, at(9962, 3, 9, 13)),
                                                 (T_TIE, at(9962, 3, 9, 14))]),
}
TEAMS = (T_CHAMPS, T_DCMP, T_TIE)


def _database_available() -> bool:
    try:
        with psycopg.connect(str(Settings().database_url), connect_timeout=3):
            return True
    except Exception:
        return False


pytestmark = pytest.mark.skipif(not _database_available(), reason="Requires a reachable PostgreSQL database")


def _cleanup(db: Database) -> None:
    keys = list(EVENTS)
    with db.cursor() as cursor:
        cursor.execute("DELETE FROM team_event_stats WHERE event_key = ANY(%s)", (keys,))
        cursor.execute("DELETE FROM match_teams WHERE match_key LIKE '996_zzz%%'")
        cursor.execute("DELETE FROM matches WHERE event_key = ANY(%s)", (keys,))
        cursor.execute("DELETE FROM raw_source_payloads WHERE source = 'tba' AND source_object_type = 'event_ranking' "
                       "AND source_object_id = ANY(%s)", (keys,))
        cursor.execute("DELETE FROM raw_source_payloads WHERE source = 'tba' AND source_object_type = 'match' "
                       "AND source_object_id LIKE '996_zzz%%'")
        cursor.execute("DELETE FROM events WHERE event_key = ANY(%s)", (keys,))
        cursor.execute("DELETE FROM teams WHERE team_number = ANY(%s)", (list(TEAMS),))


@pytest.fixture(scope="module")
def world() -> Database:
    from database.migrate import run_migrations

    settings = Settings()
    run_migrations(settings)
    db = Database(DatabaseConfig(settings.database_url))
    _cleanup(db)
    with db.cursor() as cursor:
        for team in TEAMS:
            cursor.execute("INSERT INTO teams (team_number, name) VALUES (%s, 'sentinel')", (team,))
        for key, (season, end, matches) in EVENTS.items():
            cursor.execute("INSERT INTO events (event_key, season, name, start_date, end_date) "
                           "VALUES (%s, %s, 'sentinel', %s, %s)", (key, season, end, end))
            for number, (team, when) in enumerate(matches, start=1):
                match_key = f"{key}_qm{number}"
                cursor.execute(
                    "INSERT INTO matches (match_key, event_key, season, competition_level, match_number, "
                    "scheduled_time, score_red, score_blue, winning_alliance) "
                    "VALUES (%s, %s, %s, 'qualification', %s, %s, 30, 20, 'red')",
                    (match_key, key, season, number, when))
                cursor.execute("INSERT INTO match_teams (match_key, team_number, alliance_color, station_position) "
                               "VALUES (%s, %s, 'red', 1)", (match_key, team))
                cursor.execute(
                    "INSERT INTO raw_source_payloads (source, source_object_type, source_object_id, event_key, "
                    "match_key, payload_json, payload_checksum) VALUES ('tba', 'match', %s, %s, %s, %s, %s)",
                    (match_key, key, match_key, json.dumps({"key": match_key, "score_breakdown": None}),
                     f"epa-src-{match_key}"))
            for team in {team for team, _ in matches}:
                cursor.execute("INSERT INTO team_event_stats (team_number, event_key, season, epa_total, "
                               "matches_played) VALUES (%s, %s, %s, 40, 3)", (team, key, season))
        cursor.execute(
            "INSERT INTO raw_source_payloads (source, source_object_type, source_object_id, event_key, payload_json, "
            "payload_checksum) VALUES ('tba', 'event_ranking', '9962zzznext', '9962zzznext', %s, 'sentinel-epa-src')",
            (json.dumps({"rankings": [{"team_key": f"frc{t}", "rank": i} for i, t in enumerate(TEAMS, 1)]}),))
    try:
        yield db
    finally:
        _cleanup(db)


def source(db: Database, team: int, target: str, as_of: datetime) -> str | None:
    return _point_in_time_epa(db, team, target, as_of).source_event_key


NEXT_AS_OF = {T_CHAMPS: at(9962, 3, 9, 12), T_DCMP: at(9962, 3, 9, 13), T_TIE: at(9962, 3, 9, 14)}


def test_einstein_is_the_source_after_a_championship_division(world):
    assert source(world, T_CHAMPS, "9962zzznext", NEXT_AS_OF[T_CHAMPS]) == "9961zzzcmptx"


def test_dcmp_finals_are_the_source_after_a_dcmp_division(world):
    assert source(world, T_DCMP, "9962zzznext", NEXT_AS_OF[T_DCMP]) == "9961zzzmicmp"


def test_identical_latest_match_times_fall_back_to_event_key(world):
    assert source(world, T_TIE, "9962zzznext", NEXT_AS_OF[T_TIE]) == "9961zzzsamea"


def test_saturday_division_match_never_sees_same_day_einstein_or_finals(world):
    # end_date (midnight) is before both as_of values, but Einstein/finals are played later that day.
    assert source(world, T_CHAMPS, "9961zzzcur", at(9961, 4, 20, 9)) == "9961zzzreg"
    assert source(world, T_DCMP, "9961zzzmicmp1", at(9961, 4, 6, 9, 30)) == "9961zzzreg"


def test_einstein_match_sees_its_own_division_once_the_division_finished(world):
    assert source(world, T_CHAMPS, "9961zzzcmptx", at(9961, 4, 20, 15)) == "9961zzzcur"


def test_repeated_execution_returns_the_same_source(world):
    for team, as_of in NEXT_AS_OF.items():
        seen = {source(world, team, "9962zzznext", as_of) for _ in range(5)}
        assert len(seen) == 1


def test_readiness_gate_reproduces_the_assembler_for_every_appearance(world):
    resolutions = [r for r in dr.resolve_sources(world, seasons=SEASONS) if r[0] in TEAMS]
    assert len(resolutions) == sum(len(matches) for _, _, matches in EVENTS.values())
    for team, target, as_of, expected, selected in resolutions:
        assembler = source(world, team, target, as_of)
        assert selected == assembler, (team, target, as_of)
        assert expected == assembler, (team, target, as_of)
    assert dr.resolve_sources(world, seasons=SEASONS)[:len(resolutions)] == \
        dr.resolve_sources(world, seasons=SEASONS)[:len(resolutions)]


def test_gate_is_complete_and_counts_the_resolved_ties(world):
    report = dr.assess_readiness(world, seasons=SEASONS, held_out_season=9962)
    assert report.status == dr.COMPLETE, report.reasons
    assert dr.CATEGORY_SOURCE_MISMATCH not in report.totals()
    assert report.ties_resolved_by_latest_match == 2   # champs + DCMP teams at their next event
    assert report.ties_resolved_by_event_key == 1      # the simultaneous pair
