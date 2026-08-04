"""Phase 3 cross-milestone integration check (M1 + M3 + M4), added during the
2026-08-04 Phase 3 retrospective audit.

Milestones 1, 3, and 4 were each built and tested independently: M1's
ScoringProfile against hand-built values, M3's statistics functions against
synthetic score lists, M4's get_team_match_history against seeded DB rows. No
existing test had ever piped real output from M4 through M3 into a real M1
ScoringProfile construction in one chain -- exactly the kind of gap that stays
invisible until Milestone 10 tries to wire the real pipeline and something
turns out not to fit. This module closes that gap now, while it's still cheap
to fix, per MASTER_BUILD.md's Phase Acceptance Review ("attempt to break every
subsystem").
"""

from __future__ import annotations

import psycopg
import pytest

from data.config import Settings
from data.metrics.history import get_team_match_history
from data.metrics.schemas import ScoringProfile
from data.metrics.statistics import (
    average_score,
    classify_match_days,
    consistency_rating,
    reliability_score,
    score_stddev,
)
from database.connection import Database, DatabaseConfig

# Sentinel namespace, distinct from every other module's (9995-9999).
_S_EVENT = "9994zzzint"
_S_TEAM_MANY_MATCHES = 940001    # 4 played (mixed colors) + 1 unplayed
_S_TEAM_ONE_MATCH = 940002       # exactly 1 played match
_S_TEAM_ZERO_MATCHES = 940003    # never rostered at this event
_S_FILLER_TEAMS = [940004, 940005, 940006, 940007]
_S_ALL_TEAMS = [_S_TEAM_MANY_MATCHES, _S_TEAM_ONE_MATCH, _S_TEAM_ZERO_MATCHES, *_S_FILLER_TEAMS]


def _database_available() -> bool:
    try:
        with psycopg.connect(str(Settings().database_url), connect_timeout=3):
            return True
    except Exception:
        return False


requires_db = pytest.mark.skipif(
    not _database_available(),
    reason="Requires a reachable PostgreSQL database via DATABASE_URL",
)


def _cleanup(database: Database) -> None:
    with database.cursor() as cursor:
        cursor.execute(
            "DELETE FROM match_teams WHERE match_key IN "
            "(SELECT match_key FROM matches WHERE event_key = %s)",
            (_S_EVENT,),
        )
        cursor.execute("DELETE FROM matches WHERE event_key = %s", (_S_EVENT,))
        cursor.execute("DELETE FROM teams WHERE team_number = ANY(%s::int[])", (_S_ALL_TEAMS,))
        cursor.execute("DELETE FROM events WHERE event_key = %s", (_S_EVENT,))


def _insert_match(
    database: Database, match_key: str, *, match_number: int,
    red_teams: list[int], blue_teams: list[int],
    score_red: int | None, score_blue: int | None,
) -> None:
    with database.cursor() as cursor:
        cursor.execute(
            """
            INSERT INTO matches (match_key, event_key, season, competition_level, match_number, score_red, score_blue)
            VALUES (%s, %s, %s, 'qualification', %s, %s, %s)
            """,
            (match_key, _S_EVENT, 9994, match_number, score_red, score_blue),
        )
        for alliance_color, team_numbers in (("red", red_teams), ("blue", blue_teams)):
            for position, team_number in enumerate(team_numbers, start=1):
                cursor.execute(
                    "INSERT INTO match_teams (match_key, team_number, alliance_color, station_position) "
                    "VALUES (%s, %s, %s, %s)",
                    (match_key, team_number, alliance_color, position),
                )


@pytest.fixture
def database() -> Database:
    from database.migrate import run_migrations

    settings = Settings()
    run_migrations(settings)
    db = Database(DatabaseConfig(settings.database_url))
    _cleanup(db)
    with db.cursor() as cursor:
        cursor.execute("INSERT INTO events (event_key, season, name) VALUES (%s, %s, %s)", (_S_EVENT, 9994, "Sentinel Integration Event"))
        for team_number in _S_ALL_TEAMS:
            cursor.execute("INSERT INTO teams (team_number, name) VALUES (%s, %s)", (team_number, f"Sentinel {team_number}"))

    # _S_TEAM_MANY_MATCHES: qm1 red=100 (own), qm2 blue=110 (own), qm3 red=90 (own),
    # qm4 blue=140 (own), qm5 unplayed.
    _insert_match(db, f"{_S_EVENT}_qm1", match_number=1, red_teams=[_S_TEAM_MANY_MATCHES], blue_teams=_S_FILLER_TEAMS[0:1], score_red=100, score_blue=95)
    _insert_match(db, f"{_S_EVENT}_qm2", match_number=2, red_teams=_S_FILLER_TEAMS[0:1], blue_teams=[_S_TEAM_MANY_MATCHES], score_red=85, score_blue=110)
    _insert_match(db, f"{_S_EVENT}_qm3", match_number=3, red_teams=[_S_TEAM_MANY_MATCHES], blue_teams=_S_FILLER_TEAMS[1:2], score_red=90, score_blue=80)
    _insert_match(db, f"{_S_EVENT}_qm4", match_number=4, red_teams=_S_FILLER_TEAMS[1:2], blue_teams=[_S_TEAM_MANY_MATCHES], score_red=70, score_blue=140)
    _insert_match(db, f"{_S_EVENT}_qm5", match_number=5, red_teams=[_S_TEAM_MANY_MATCHES], blue_teams=_S_FILLER_TEAMS[2:3], score_red=None, score_blue=None)

    # _S_TEAM_ONE_MATCH: exactly one played match.
    _insert_match(db, f"{_S_EVENT}_qm6", match_number=6, red_teams=[_S_TEAM_ONE_MATCH], blue_teams=_S_FILLER_TEAMS[3:4], score_red=120, score_blue=60)

    try:
        yield db
    finally:
        _cleanup(db)


def _run_full_chain(database: Database, team_number: int) -> ScoringProfile:
    """The exact chain a future Milestone 10 pipeline will run for real."""
    history = get_team_match_history(database, team_number, _S_EVENT)
    day_counts = classify_match_days(history.scores)
    return ScoringProfile(
        matches_scheduled=history.matches_scheduled,
        matches_used=history.matches_used,
        average_score=average_score(history.scores),
        score_stddev=score_stddev(history.scores),
        consistency_rating=consistency_rating(history.scores),
        reliability_score=reliability_score(history.matches_used, history.matches_scheduled),
        good_day_count=day_counts["good"] if day_counts else None,
        average_day_count=day_counts["average"] if day_counts else None,
        bad_day_count=day_counts["bad"] if day_counts else None,
    )


@requires_db
def test_full_chain_many_matches_hand_computed(database: Database) -> None:
    # Own scores in play order: 100 (qm1), 110 (qm2), 90 (qm3), 140 (qm4); qm5 unplayed.
    profile = _run_full_chain(database, _S_TEAM_MANY_MATCHES)
    assert profile.matches_scheduled == 5
    assert profile.matches_used == 4
    assert profile.average_score == pytest.approx(110.0)  # (100+110+90+140)/4
    assert profile.score_stddev is not None
    assert profile.consistency_rating is not None
    assert profile.reliability_score == pytest.approx(80.0)  # 4/5 * 100
    assert profile.good_day_count + profile.average_day_count + profile.bad_day_count == 4


@requires_db
def test_full_chain_one_match_stays_in_the_matches_used_one_bucket(database: Database) -> None:
    profile = _run_full_chain(database, _S_TEAM_ONE_MATCH)
    assert profile.matches_scheduled == 1
    assert profile.matches_used == 1
    assert profile.average_score == 120.0
    # Everything variance-derived must be None -- and, critically, constructing
    # ScoringProfile did not raise: M3's "below MIN_MATCHES_FOR_STDDEV -> None"
    # contract and M1's "matches_used == 1 -> only average_score" invariant
    # agree with each other on real, DB-sourced data, not just in isolation.
    assert profile.score_stddev is None
    assert profile.consistency_rating is None
    assert profile.reliability_score is None
    assert profile.good_day_count is None


@requires_db
def test_full_chain_zero_matches_stays_in_the_matches_used_zero_bucket(database: Database) -> None:
    profile = _run_full_chain(database, _S_TEAM_ZERO_MATCHES)
    assert profile.matches_scheduled == 0
    assert profile.matches_used == 0
    assert profile.average_score is None
    assert profile.reliability_score is None


@requires_db
def test_full_chain_never_raises_across_every_matches_used_bucket(database: Database) -> None:
    # The real point of this module: sweep every team seeded in this fixture
    # and confirm the chain constructs a valid ScoringProfile every time, with
    # no bucket requiring a special case in the calling code.
    for team_number in (_S_TEAM_MANY_MATCHES, _S_TEAM_ONE_MATCH, _S_TEAM_ZERO_MATCHES):
        _run_full_chain(database, team_number)  # raises on failure
