"""Phase 4 Milestone 11 through the assembler: average_auto_points.

Sentinel events carry real-season prefixes (2024zzzm11...) because the adapter
is season-aware by design; the 'zzz' codes never exist in TBA. Breakdowns are
the real captured fixtures.
"""

from __future__ import annotations

import copy
import json
import math
from datetime import datetime, timezone
from pathlib import Path

import psycopg
import pytest

from data.config import Settings
from database.connection import Database, DatabaseConfig
from ml.features.assembler import build_team_features
from ml.features.score_breakdown import ScoreBreakdownSchemaError, UnsupportedSeasonError
from ml.models.team_vector import TEAM_FEATURE_NAMES, team_features_to_vector

FIXTURES = Path(__file__).parent / "fixtures"
TEAM, OTHER, NO_RAW = 99921, 99922, 99923
EVENTS = {"2024zzzm11": 2024, "2025zzzm11": 2025, "2026zzzm11": 2026, "2023zzzm11": 2023}


def breakdown(season: int) -> dict:
    return json.loads((FIXTURES / f"tba_score_breakdown_{season}.json").read_text(encoding="utf-8"))["alliance_breakdown"]


def at(hour: int) -> datetime:
    return datetime(2026, 3, 15, hour, tzinfo=timezone.utc)


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
        cursor.execute("DELETE FROM raw_source_payloads WHERE source = 'tba' AND source_object_type = 'match' "
                       "AND source_object_id LIKE '20__zzzm11_%%'")
        cursor.execute("DELETE FROM match_teams WHERE match_key LIKE '20__zzzm11_%%'")
        cursor.execute("DELETE FROM matches WHERE event_key = ANY(%s)", (keys,))
        cursor.execute("DELETE FROM events WHERE event_key = ANY(%s)", (keys,))
        cursor.execute("DELETE FROM teams WHERE team_number = ANY(%s)", ([TEAM, OTHER, NO_RAW],))


def _match(db: Database, event: str, number: int, when: datetime, *, played: bool = True,
           sb: dict | None | str = "season", teams=(TEAM, OTHER)) -> None:
    season = EVENTS[event]
    key = f"{event}_qm{number}"
    with db.cursor() as cursor:
        cursor.execute(
            "INSERT INTO matches (match_key, event_key, season, competition_level, match_number, scheduled_time, "
            "score_red, score_blue) VALUES (%s, %s, %s, 'qualification', %s, %s, %s, %s)",
            (key, event, season, number, when, 50 if played else None, 40 if played else None))
        red, blue = teams
        for team, color in ((red, "red"), (blue, "blue")):
            cursor.execute("INSERT INTO match_teams (match_key, team_number, alliance_color, station_position) "
                           "VALUES (%s, %s, %s, 1)", (key, team, color))
        if sb is None or teams[0] == NO_RAW:
            if sb is None:  # payload exists, TBA published no breakdown
                cursor.execute(
                    "INSERT INTO raw_source_payloads (source, source_object_type, source_object_id, event_key, "
                    "match_key, payload_json, payload_checksum) VALUES ('tba', 'match', %s, %s, %s, %s, %s)",
                    (key, event, key, json.dumps({"key": key, "score_breakdown": None}), f"m11-{key}"))
            return
        body = breakdown(2024 if season == 2023 else season) if sb == "season" else sb
        cursor.execute(
            "INSERT INTO raw_source_payloads (source, source_object_type, source_object_id, event_key, match_key, "
            "payload_json, payload_checksum) VALUES ('tba', 'match', %s, %s, %s, %s, %s)",
            (key, event, key, json.dumps({"key": key, "score_breakdown": {"red": body, "blue": body}}), f"m11-{key}"))


@pytest.fixture(scope="module")
def db() -> Database:
    from database.migrate import run_migrations

    settings = Settings()
    run_migrations(settings)
    database = Database(DatabaseConfig(settings.database_url))
    _cleanup(database)
    with database.cursor() as cursor:
        for team in (TEAM, OTHER, NO_RAW):
            cursor.execute("INSERT INTO teams (team_number, name) VALUES (%s, 'sentinel')", (team,))
        for event, season in EVENTS.items():
            cursor.execute("INSERT INTO events (event_key, season, name) VALUES (%s, %s, 'sentinel')", (event, season))

    big = copy.deepcopy(breakdown(2024))
    big["autoPoints"] += 26                   # 60 auto, kept internally consistent
    big["autoTotalNotePoints"] += 26
    big["totalPoints"] += 26
    _match(database, "2024zzzm11", 1, at(10))                   # contributes 34
    _match(database, "2024zzzm11", 2, at(11), sb=None)          # played, TBA published no breakdown
    _match(database, "2024zzzm11", 3, at(12), played=False)     # unplayed: excluded like average_score
    _match(database, "2024zzzm11", 5, at(20), sb=big)           # after as_of: must never count
    _match(database, "2024zzzm11", 6, at(10), teams=(NO_RAW, OTHER))  # NO_RAW's match: no raw payload at all
    for event in ("2025zzzm11", "2026zzzm11", "2023zzzm11"):
        _match(database, event, 1, at(10))
    try:
        yield database
    finally:
        _cleanup(database)


AS_OF = at(18)


def test_mean_over_prior_completed_matches_with_a_breakdown(db):
    features = build_team_features(db, TEAM, "2024zzzm11", AS_OF)
    assert features.average_auto_points == 34.0
    assert features.average_auto_points_present
    assert features.auto_points_matches_used == 1    # qm2 had no breakdown
    assert features.matches_used == 2                # ... but is a real played match for average_score


def test_a_future_match_never_contributes(db):
    later = build_team_features(db, TEAM, "2024zzzm11", at(21))
    assert later.auto_points_matches_used == 2
    assert later.average_auto_points == (34 + 60) / 2
    assert build_team_features(db, TEAM, "2024zzzm11", AS_OF).average_auto_points == 34.0


def test_no_prior_matches_means_absent_not_zero(db):
    features = build_team_features(db, TEAM, "2024zzzm11", at(9))
    assert features.average_auto_points is None and not features.average_auto_points_present
    assert features.auto_points_matches_used == 0
    assert math.isnan(team_features_to_vector(features)[TEAM_FEATURE_NAMES.index("average_auto_points")])


def test_a_played_match_without_any_raw_payload_is_absent(db):
    features = build_team_features(db, NO_RAW, "2024zzzm11", AS_OF)
    assert features.matches_used == 1 and features.auto_points_matches_used == 0
    assert not features.average_auto_points_present


def test_2026_uses_total_auto_points_not_the_hub_component(db):
    features = build_team_features(db, TEAM, "2026zzzm11", AS_OF)
    expected = breakdown(2026)["totalAutoPoints"]
    assert features.average_auto_points == expected != breakdown(2026)["hubScore"]["autoPoints"]


@pytest.mark.parametrize("event", ["2024zzzm11", "2025zzzm11", "2026zzzm11"])
def test_assembler_contract_every_required_season_produces_the_feature(db, event):
    features = build_team_features(db, TEAM, event, AS_OF)
    assert features.average_auto_points_present and features.average_auto_points > 0
    vector = team_features_to_vector(features)
    assert vector[TEAM_FEATURE_NAMES.index("average_auto_points")] == features.average_auto_points


def test_unsupported_season_fails_loudly_through_the_assembler(db):
    with pytest.raises(UnsupportedSeasonError, match="season 2023"):
        build_team_features(db, TEAM, "2023zzzm11", AS_OF)


def test_the_opponent_alliance_breakdown_is_never_read(db):
    # OTHER is blue in every sentinel match; both sides carry the same fixture here, so
    # prove the side is chosen by alliance_color by giving blue a different body.
    with db.cursor() as cursor:
        cursor.execute(
            "UPDATE raw_source_payloads SET payload_json = jsonb_set(payload_json, '{score_breakdown,blue,autoPoints}', "
            "'0'::jsonb) WHERE source_object_id = '2024zzzm11_qm1'")
    try:
        with pytest.raises(ScoreBreakdownSchemaError):  # blue's decomposition no longer holds -> loud
            build_team_features(db, OTHER, "2024zzzm11", AS_OF)
        assert build_team_features(db, TEAM, "2024zzzm11", AS_OF).average_auto_points == 34.0
    finally:
        with db.cursor() as cursor:
            cursor.execute(
                "UPDATE raw_source_payloads SET payload_json = jsonb_set(payload_json, '{score_breakdown,blue,autoPoints}', "
                "%s::jsonb) WHERE source_object_id = '2024zzzm11_qm1'", (json.dumps(breakdown(2024)["autoPoints"]),))
