"""Tests for automation.data_readiness -- the historical-data readiness gate (D8).

Pure classification tests run everywhere. requires_db tests build a tiny
sentinel world (teams 99901/99902, seasons 9951-9953) in the real database,
following tests/test_rankings.py's sentinel-and-cleanup convention, and check
every category against the gate's real SQL -- including the assembler's silent
fall-back to older EPA when the expected row is missing.
"""

from __future__ import annotations

import json
from datetime import date, datetime, timezone

import psycopg
import pytest

from automation import data_readiness as dr
from data.config import Settings
from database.connection import Database, DatabaseConfig

SEASONS = (9951, 9952, 9953)
HELD_OUT = 9953
TEAM_A, TEAM_B = 99901, 99902


# --- pure classification ----------------------------------------------------


def report(counts: dict[str, int], *, required: int = 10, valid: int = 10, missing_ranks: int = 0) -> dr.ReadinessReport:
    return dr.ReadinessReport(
        status=dr.UNKNOWN, computed_at="t", seasons=list(SEASONS), held_out_season=HELD_OUT,
        appearance_counts={"9951": counts}, required_source_rows=required, valid_source_rows=valid,
        rankings_events_required=3, rankings_missing=[f"e{i}" for i in range(missing_ranks)],
    )


def test_all_resolved_is_complete():
    status, reasons = dr.classify(report({dr.CATEGORY_OK: 50, dr.CATEGORY_NO_PRIOR_EVENT: 7}))
    assert status == dr.COMPLETE
    assert "7 legitimately withheld" in reasons[0]


def test_no_valid_rows_is_failed():
    status, _ = dr.classify(report({dr.CATEGORY_MISSING_ROW: 50}, required=10, valid=0))
    assert status == dr.FAILED


@pytest.mark.parametrize("category", [dr.CATEGORY_INVALID_ROW, dr.CATEGORY_SOURCE_MISMATCH, dr.CATEGORY_AMBIGUOUS_SOURCE])
def test_invalid_categories_block_as_invalid(category):
    status, _ = dr.classify(report({dr.CATEGORY_OK: 50, category: 1}))
    assert status == dr.INVALID


def test_invalid_outranks_partial():
    status, _ = dr.classify(report({dr.CATEGORY_MISSING_ROW: 3, dr.CATEGORY_INVALID_ROW: 1}, valid=5))
    assert status == dr.INVALID


def test_missing_rows_are_partial_never_legitimate():
    status, reasons = dr.classify(report({dr.CATEGORY_OK: 50, dr.CATEGORY_MISSING_ROW: 1}, valid=9))
    assert status == dr.PARTIAL
    assert "9/10" in reasons[0]


def test_missing_held_out_rankings_are_partial():
    status, _ = dr.classify(report({dr.CATEGORY_OK: 50}, missing_ranks=1))
    assert status == dr.PARTIAL


def test_no_appearances_is_unknown():
    assert dr.classify(report({}))[0] == dr.UNKNOWN


def test_locked_split_matches_decision_d7():
    assert dr.REQUIRED_SEASONS == (2024, 2025, 2026)
    assert dr.HELD_OUT_SEASON == 2026


# --- real SQL against a sentinel world ------------------------------------------


def _database_available() -> bool:
    try:
        with psycopg.connect(str(Settings().database_url), connect_timeout=3):
            return True
    except Exception:
        return False


requires_db = pytest.mark.skipif(not _database_available(), reason="Requires a reachable PostgreSQL database")

# (event_key, season, end_date, teams that play one qualification match there)
BASE_EVENTS = [
    ("9951zzza", 9951, date(9951, 3, 10), (TEAM_A, TEAM_B)),
    ("9952zzza", 9952, date(9952, 3, 10), (TEAM_A,)),
    ("9953zzza", 9953, date(9953, 3, 10), (TEAM_A, TEAM_B)),
]
TIE_EVENTS = [  # a division and its finals ending the same day, played by team B
    ("9952zzzdiv", 9952, date(9952, 4, 20), (TEAM_B,)),
    ("9952zzzfin", 9952, date(9952, 4, 20), (TEAM_B,)),
]
NO_SHOW_EVENT = ("9952zzznoshow", 9952, date(9952, 6, 1), ())
ALL_EVENTS = [key for key, *_ in (*BASE_EVENTS, *TIE_EVENTS, NO_SHOW_EVENT)]


def _cleanup(db: Database) -> None:
    with db.cursor() as cursor:
        cursor.execute("DELETE FROM team_event_stats WHERE event_key = ANY(%s)", (ALL_EVENTS,))
        cursor.execute("DELETE FROM match_teams WHERE match_key LIKE '995_zzz%%'")
        cursor.execute("DELETE FROM matches WHERE event_key = ANY(%s)", (ALL_EVENTS,))
        cursor.execute("DELETE FROM raw_source_payloads WHERE source = 'tba' AND source_object_type = 'event_ranking' "
                       "AND source_object_id = ANY(%s)", (ALL_EVENTS,))
        cursor.execute("DELETE FROM events WHERE event_key = ANY(%s)", (ALL_EVENTS,))
        cursor.execute("DELETE FROM teams WHERE team_number = ANY(%s)", ([TEAM_A, TEAM_B],))


def _add_event(db: Database, event_key: str, season: int, end: date, teams: tuple[int, ...]) -> None:
    with db.cursor() as cursor:
        cursor.execute("INSERT INTO events (event_key, season, name, start_date, end_date) VALUES (%s, %s, %s, %s, %s)",
                       (event_key, season, "sentinel", end, end))
        if not teams:
            return
        match_key = f"{event_key}_qm1"
        cursor.execute(
            "INSERT INTO matches (match_key, event_key, season, competition_level, match_number, scheduled_time, "
            "score_red, score_blue, winning_alliance) VALUES (%s, %s, %s, 'qualification', 1, %s, 10, 5, 'red')",
            (match_key, event_key, season, datetime(end.year, end.month, end.day - 1, 12, tzinfo=timezone.utc)),
        )
        for index, team in enumerate(teams):
            cursor.execute("INSERT INTO match_teams (match_key, team_number, alliance_color, station_position) "
                           "VALUES (%s, %s, %s, 1)", (match_key, team, "red" if index == 0 else "blue"))


def _add_ranking(db: Database, event_key: str) -> None:
    payload = {"rankings": [{"team_key": f"frc{TEAM_A}", "rank": 1}, {"team_key": f"frc{TEAM_B}", "rank": 2}]}
    with db.cursor() as cursor:
        cursor.execute(
            "INSERT INTO raw_source_payloads (source, source_object_type, source_object_id, season, event_key, "
            "payload_json, payload_checksum) VALUES ('tba', 'event_ranking', %s, %s, %s, %s, %s)",
            (event_key, HELD_OUT, event_key, json.dumps(payload), f"sentinel-{event_key}"),
        )


def _add_stats(db: Database, team: int, event_key: str, *, epa: str | None = "40.5", played: int | None = 12) -> None:
    with db.cursor() as cursor:
        cursor.execute(
            "INSERT INTO team_event_stats (team_number, event_key, season, epa_total, epa_auto, epa_teleop, "
            "matches_played) VALUES (%s, %s, %s, %s::numeric, 10, 20, %s)",
            (team, event_key, int(event_key[:4]), epa, played),
        )


@pytest.fixture
def world():
    from database.migrate import run_migrations

    settings = Settings()
    run_migrations(settings)
    db = Database(DatabaseConfig(settings.database_url))
    _cleanup(db)

    def build(*, tie: bool = False, no_show: bool = False, ranking: bool = True) -> Database:
        with db.cursor() as cursor:
            for team in (TEAM_A, TEAM_B):
                cursor.execute("INSERT INTO teams (team_number, name) VALUES (%s, 'sentinel')", (team,))
        for event in (*BASE_EVENTS, *(TIE_EVENTS if tie else ()), *((NO_SHOW_EVENT,) if no_show else ())):
            _add_event(db, *event)
        if ranking:
            _add_ranking(db, "9953zzza")
        return db

    try:
        yield build
    finally:
        _cleanup(db)


def assess(db: Database) -> dr.ReadinessReport:
    return dr.assess_readiness(db, seasons=SEASONS, held_out_season=HELD_OUT)


def complete_stats(db: Database) -> None:
    # Required sources: A@9952 (A's prior for 9953), A@9951 (for 9952), B@9951 (for 9953).
    for team, event in ((TEAM_A, "9951zzza"), (TEAM_A, "9952zzza"), (TEAM_B, "9951zzza")):
        _add_stats(db, team, event)


@requires_db
def test_unsynced_statbotics_is_failed(world):
    result = assess(world())
    assert result.status == dr.FAILED
    assert result.required_source_rows == 3 and result.valid_source_rows == 0


@requires_db
def test_every_required_input_present_is_complete(world):
    db = world()
    complete_stats(db)
    result = assess(db)
    assert result.status == dr.COMPLETE, result.reasons
    totals = result.totals()
    assert totals[dr.CATEGORY_NO_PRIOR_EVENT] == 2  # both teams' first event: legitimate, counted
    assert totals[dr.CATEGORY_OK] == 3
    assert result.rankings_events_required == 1 and result.rankings_missing == []
    assert result.team_event_stats_rows == 3 and result.team_event_stats_fingerprint


@requires_db
def test_missing_expected_row_is_caught_even_though_the_assembler_would_fall_back(world):
    db = world()
    _add_stats(db, TEAM_A, "9951zzza")  # the older event exists ...
    _add_stats(db, TEAM_B, "9951zzza")  # ... but A@9952, A's true prior for 9953, does not
    result = assess(db)
    assert result.status == dr.PARTIAL
    example = result.examples[dr.CATEGORY_MISSING_ROW][0]
    assert (example["team_number"], example["expected_source"], example["selected_source"]) == (
        TEAM_A, "9952zzza", "9951zzza")


@requires_db
@pytest.mark.parametrize("epa, played", [(None, 12), ("NaN", 12), ("40.5", 0), ("40.5", None)])
def test_unusable_expected_row_is_invalid(world, epa, played):
    db = world()
    complete_stats(db)
    with db.cursor() as cursor:
        cursor.execute("UPDATE team_event_stats SET epa_total = %s::numeric, matches_played = %s "
                       "WHERE team_number = %s AND event_key = '9952zzza'", (epa, played, TEAM_A))
    result = assess(db)
    assert result.status == dr.INVALID
    assert dr.CATEGORY_INVALID_ROW in result.totals()


@requires_db
def test_non_finite_breakdown_component_is_invalid(world):
    db = world()
    complete_stats(db)
    with db.cursor() as cursor:
        cursor.execute("UPDATE team_event_stats SET epa_teleop = 'NaN'::numeric "
                       "WHERE team_number = %s AND event_key = '9952zzza'", (TEAM_A,))
    assert assess(db).status == dr.INVALID


@requires_db
def test_row_for_an_event_the_team_never_played_is_a_source_mismatch(world):
    db = world(no_show=True)
    complete_stats(db)
    _add_stats(db, TEAM_A, "9952zzznoshow")  # more recent than 9952zzza, but A played no match there
    result = assess(db)
    assert result.status == dr.INVALID
    assert result.examples[dr.CATEGORY_SOURCE_MISMATCH][0]["selected_source"] == "9952zzznoshow"


@requires_db
def test_division_and_finals_ending_the_same_day_are_ambiguous(world):
    db = world(tie=True)
    complete_stats(db)
    for event in ("9952zzzdiv", "9952zzzfin"):
        _add_stats(db, TEAM_B, event)
    result = assess(db)
    assert result.status == dr.INVALID
    assert result.examples[dr.CATEGORY_AMBIGUOUS_SOURCE][0]["team_number"] == TEAM_B


@requires_db
def test_missing_held_out_ranking_is_partial(world):
    db = world(ranking=False)
    complete_stats(db)
    result = assess(db)
    assert result.status == dr.PARTIAL
    assert result.rankings_missing == ["9953zzza"]


@requires_db
def test_unsynced_season_is_unknown(world):
    db = world()
    result = dr.assess_readiness(db, seasons=(*SEASONS, 9954), held_out_season=HELD_OUT)
    assert result.status == dr.UNKNOWN
    assert "9954" in result.reasons[0]


@requires_db
def test_gate_writes_nothing_persistent(world):
    db = world()
    complete_stats(db)
    assess(db)
    with db.cursor() as cursor:
        cursor.execute("SELECT count(*) FROM pg_tables WHERE tablename LIKE '_rd_%%'")
        assert cursor.fetchone()[0] == 0
