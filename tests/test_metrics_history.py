"""Phase 3 Milestone 4: match history retrieval against seeded sentinel-event data.

data.metrics.history.get_team_match_history is the first read path against the
canonical matches/match_teams tables that Milestone 3's statistics functions and
Milestone 1's ScoringProfile are built to consume. These tests seed real rows
through raw SQL (not the staging/serving pipeline -- this module is a pure
reader, and routing through normalization would test the pipeline, not this
read path) and assert the retrieved TeamMatchHistory matches manual inspection
of the seeded rows exactly, per the milestone's stated success criterion.
"""

from __future__ import annotations

import psycopg
import pytest

from data.config import Settings
from data.metrics.history import TeamMatchHistory, get_team_match_history
from database.connection import Database, DatabaseConfig

# Sentinel namespace, distinct from 9996 (Milestone 2), 9997 (data quality),
# 9998 (pipeline), and 9999 (repository/raw writer) fixtures, so a failed run
# of this module can never collide with or clean up another module's rows.
_S_EVENT = "9995zzzhist"
_S_TEAM = 950001              # the team under test
_S_TEAM_FUTURE_ONLY = 950002  # rostered only into an unplayed match
_S_TEAM_NOT_AT_EVENT = 950003 # exists in `teams`, never rostered at this event
_S_FILLER_TEAMS = [950004, 950005, 950006, 950007, 950008, 950009]
_S_ALL_TEAMS = [_S_TEAM, _S_TEAM_FUTURE_ONLY, _S_TEAM_NOT_AT_EVENT, *_S_FILLER_TEAMS]
_S_NONEXISTENT_TEAM = 959999  # never inserted into `teams` at all


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
    database: Database,
    match_key: str,
    *,
    competition_level: str = "qualification",
    set_number: int | None = None,
    match_number: int,
    red_teams: list[int],
    blue_teams: list[int],
    score_red: int | None = None,
    score_blue: int | None = None,
) -> None:
    with database.cursor() as cursor:
        cursor.execute(
            """
            INSERT INTO matches (
                match_key, event_key, season, competition_level,
                set_number, match_number, score_red, score_blue
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
            """,
            (match_key, _S_EVENT, 9995, competition_level, set_number, match_number, score_red, score_blue),
        )
        for alliance_color, team_numbers in (("red", red_teams), ("blue", blue_teams)):
            for position, team_number in enumerate(team_numbers, start=1):
                cursor.execute(
                    """
                    INSERT INTO match_teams (match_key, team_number, alliance_color, station_position)
                    VALUES (%s, %s, %s, %s)
                    """,
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
        cursor.execute(
            "INSERT INTO events (event_key, season, name) VALUES (%s, %s, %s)",
            (_S_EVENT, 9995, "Sentinel History Event"),
        )
        for team_number in _S_ALL_TEAMS:
            cursor.execute(
                "INSERT INTO teams (team_number, name) VALUES (%s, %s)",
                (team_number, f"Sentinel {team_number}"),
            )

    # qm1: _S_TEAM on red, played, red=100 blue=90 -> own score 100
    _insert_match(
        db, f"{_S_EVENT}_qm1", match_number=1,
        red_teams=[_S_TEAM, *_S_FILLER_TEAMS[0:2]], blue_teams=_S_FILLER_TEAMS[2:4],
        score_red=100, score_blue=90,
    )
    # qm2: _S_TEAM on blue, played, red=80 blue=110 -> own score 110
    _insert_match(
        db, f"{_S_EVENT}_qm2", match_number=2,
        red_teams=_S_FILLER_TEAMS[0:2], blue_teams=[_S_TEAM, *_S_FILLER_TEAMS[2:4]],
        score_red=80, score_blue=110,
    )
    # qm3: _S_TEAM on red, NOT YET PLAYED (both scores NULL) -> excluded from scores
    _insert_match(
        db, f"{_S_EVENT}_qm3", match_number=3,
        red_teams=[_S_TEAM, *_S_FILLER_TEAMS[0:2]], blue_teams=_S_FILLER_TEAMS[2:4],
        score_red=None, score_blue=None,
    )
    # qm4: unrelated to _S_TEAM, and deliberately irregular -- an empty red
    # alliance, mirroring the real frc0 unassigned-roster shape this pipeline
    # already stores (RUNNING_NOTES.md 2026-08-01). Exercises that a partial
    # roster on an unrelated match neither drops nor double-counts _S_TEAM's
    # own history.
    _insert_match(
        db, f"{_S_EVENT}_qm4", match_number=4,
        red_teams=[], blue_teams=_S_FILLER_TEAMS[4:6],
        score_red=None, score_blue=150,
    )
    # qm5: _S_TEAM_FUTURE_ONLY's only match, not yet played.
    _insert_match(
        db, f"{_S_EVENT}_qm5", match_number=5,
        red_teams=[_S_TEAM_FUTURE_ONLY], blue_teams=_S_FILLER_TEAMS[0:1],
        score_red=None, score_blue=None,
    )
    # A playoff final, inserted with an earlier match_number than the quals
    # above so play-order can only pass if the query orders by competition
    # level first, not by insertion order or raw match_number.
    _insert_match(
        db, f"{_S_EVENT}_f1m1", competition_level="final", set_number=1, match_number=1,
        red_teams=[_S_TEAM, *_S_FILLER_TEAMS[0:2]], blue_teams=_S_FILLER_TEAMS[2:4],
        score_red=200, score_blue=60,
    )

    try:
        yield db
    finally:
        _cleanup(db)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@requires_db
def test_team_with_zero_matches_never_rostered_at_event(database: Database) -> None:
    history = get_team_match_history(database, _S_TEAM_NOT_AT_EVENT, _S_EVENT)
    assert history == TeamMatchHistory(
        team_number=_S_TEAM_NOT_AT_EVENT, event_key=_S_EVENT,
        matches_scheduled=0, matches_used=0, scores=[],
    )


@requires_db
def test_team_with_zero_matches_nonexistent_team_does_not_raise(database: Database) -> None:
    # No FK/existence check is part of this function's contract -- a team
    # that was never even inserted into `teams` produces the identical
    # "no data" shape as a real team simply absent from this event's rosters.
    history = get_team_match_history(database, _S_NONEXISTENT_TEAM, _S_EVENT)
    assert history.matches_scheduled == 0
    assert history.matches_used == 0
    assert history.scores == []


@requires_db
def test_team_with_only_future_unplayed_matches(database: Database) -> None:
    history = get_team_match_history(database, _S_TEAM_FUTURE_ONLY, _S_EVENT)
    assert history.matches_scheduled == 1
    assert history.matches_used == 0
    assert history.scores == []


@requires_db
def test_team_on_mixed_alliance_colors_resolves_correct_score_each_match(database: Database) -> None:
    # qm1: _S_TEAM red, red=100 blue=90 -> 100 is _S_TEAM's own score, not 90.
    # qm2: _S_TEAM blue, red=80 blue=110 -> 110 is _S_TEAM's own score, not 80.
    history = get_team_match_history(database, _S_TEAM, _S_EVENT)
    assert 100 in history.scores
    assert 110 in history.scores
    assert 90 not in history.scores
    assert 80 not in history.scores


@requires_db
def test_event_with_an_irregular_roster_elsewhere_does_not_drop_or_double_count(database: Database) -> None:
    # qm4 (empty red alliance, unrelated to _S_TEAM) exists in this event
    # alongside _S_TEAM's own 4 matches (qm1, qm2, qm3, f1m1). _S_TEAM's own
    # counts must be exactly as if qm4 did not exist.
    history = get_team_match_history(database, _S_TEAM, _S_EVENT)
    assert history.matches_scheduled == 4
    assert history.matches_used == 3  # qm1, qm2, f1m1 played; qm3 not yet
    assert sorted(history.scores) == sorted([100, 110, 200])


@requires_db
def test_full_history_hand_computed(database: Database) -> None:
    # Manual read of the seeded rows: qm1 own=100 (played), qm2 own=110
    # (played), qm3 own=None (unplayed, excluded), f1m1 own=200 (played).
    # matches_scheduled counts all 4 rostered matches; matches_used counts
    # only the 3 with a recorded score.
    history = get_team_match_history(database, _S_TEAM, _S_EVENT)
    assert history.team_number == _S_TEAM
    assert history.event_key == _S_EVENT
    assert history.matches_scheduled == 4
    assert history.matches_used == 3
    assert len(history.scores) == 3


@requires_db
def test_scores_are_in_play_order_quals_before_playoffs(database: Database) -> None:
    # f1m1 (the final) was seeded with match_number=1, lower than every qual
    # match_number -- if the query ordered by raw match_number instead of
    # competition-level play order, its score (200) would appear first.
    history = get_team_match_history(database, _S_TEAM, _S_EVENT)
    assert history.scores == [100, 110, 200]


@requires_db
def test_match_keys_names_every_scheduled_match_in_play_order(database: Database) -> None:
    # Milestone 10 added match_keys (every match this team is rostered into,
    # parallel in spirit to scores but covering all of matches_scheduled, not
    # just matches_used) specifically so compute_event_team_metrics could
    # trace team_metrics lineage back to unplayed-but-scheduled matches too --
    # verified directly here, at the layer that owns the field, not only
    # indirectly through Milestone 10's own downstream lineage tests.
    history = get_team_match_history(database, _S_TEAM, _S_EVENT)
    assert history.match_keys == [f"{_S_EVENT}_qm1", f"{_S_EVENT}_qm2", f"{_S_EVENT}_qm3", f"{_S_EVENT}_f1m1"]
    assert len(history.match_keys) == history.matches_scheduled  # includes the unplayed qm3
    assert len(history.scores) == history.matches_used            # scores excludes it


@requires_db
def test_unplayed_match_never_appears_in_scores_but_still_counts_as_scheduled(database: Database) -> None:
    history = get_team_match_history(database, _S_TEAM, _S_EVENT)
    # qm3's own score would have been score_red (this team is on red in qm3);
    # both score_red and score_blue are NULL for qm3, so nothing from it
    # should appear in scores, yet it must still count toward matches_scheduled.
    assert None not in history.scores
    assert history.matches_scheduled > history.matches_used


@requires_db
def test_returns_team_match_history_dataclass(database: Database) -> None:
    history = get_team_match_history(database, _S_TEAM, _S_EVENT)
    assert isinstance(history, TeamMatchHistory)


@requires_db
def test_a_real_score_of_zero_counts_as_played_not_unplayed(database: Database) -> None:
    # A genuinely scored 0 (e.g. a shutout) must not be conflated with the
    # NULL that marks an unplayed match -- own_score is checked with
    # `is not None`, not truthiness, specifically to keep these distinct.
    _insert_match(
        database, f"{_S_EVENT}_qm6", match_number=6,
        red_teams=[_S_TEAM_NOT_AT_EVENT], blue_teams=_S_FILLER_TEAMS[0:1],
        score_red=0, score_blue=45,
    )
    history = get_team_match_history(database, _S_TEAM_NOT_AT_EVENT, _S_EVENT)
    assert history.matches_scheduled == 1
    assert history.matches_used == 1
    assert history.scores == [0]
