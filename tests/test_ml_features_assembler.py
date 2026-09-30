"""Phase 4 Milestone 1 (authoritative plan): the leakage-safe feature
assembly layer, ml.features.assembler.

Mirrors tests/test_metrics_history.py's real-Postgres integration style: a
seeded sentinel event/teams/matches, a `database` fixture that cleans up
before and after, and direct assertions against the assembled
MatchFeatureRow, cross-checked by calling Phase 3's own reused functions
(average_score, score_stddev, consistency_rating, reliability_score,
aggregate_defense_feeding) directly on the same point-in-time-filtered input,
rather than hand-computing expected numbers -- this proves the module reuses
Phase 3's math unmodified, not merely that it produces some plausible number.

The central scenario spans three events and four matches, built specifically
to make every leakage path in the milestone brief concretely testable:

  9988zzzmlearly  (season 9988) -- a fully concluded PRIOR event. Team A's
                    real, trustworthy EPA source.
  9987zzzmllate   (season 9987) -- a PRIOR event that has NOT concluded
                    before as_of. Team C's EPA row lives here, and must be
                    withheld despite existing.
  9989zzzmltarget (season 9989) -- the TARGET event, with four matches in
                    play order:
    qm1 (10:00) -- Team A on red, own score 100. Before as_of.
    qm2 (14:00) -- Team A on blue, own score 120. Before as_of.
    qm3 (18:00) -- THE TARGET MATCH. as_of == qm3's own scheduled_time
                    exactly, so qm3 itself is excluded from every team's own
                    point-in-time history (scheduled_time < as_of is false
                    for a value equal to as_of).
    qm4 (22:00) -- Team A's own score 999 (deliberately extreme). AFTER
                    as_of -- must never contribute to anything.
  Team A also has a decoy team_event_stats row at 9989zzzmltarget itself
  (the target event) with epa_total=999.0 -- if the assembler ever used
  same-event EPA, this exact sentinel value would leak into the test.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

import psycopg
import pytest
from pydantic import ValidationError

from data.config import Settings
from data.metrics.aggregation import aggregate_defense_feeding
from data.metrics.schemas import ScoutingObservation
from data.metrics.statistics import (
    average_score,
    consistency_rating,
    reliability_score,
    score_stddev,
)
from database.connection import Database, DatabaseConfig
from ml.features.assembler import (
    EPA_WITHHELD_NO_PRIOR_EVENT,
    MatchFeatureRow,
    TeamFeatures,
    build_match_feature_row,
)

# Sentinel namespace: 9987-9989, distinct from every other module's own
# 9990-9999 range (see tests/test_metrics_history.py and siblings) so a
# failed run here can never collide with or clean up another module's rows.
_EVENT_CONCLUDED = "9988zzzmlearly"     # a fully concluded prior event
_EVENT_ONGOING = "9987zzzmllate"        # a prior event NOT concluded before as_of
_EVENT_TARGET = "9989zzzmltarget"       # the event under test

_TEAM_A = 989001   # scoring history + scouting observations + real prior EPA
_TEAM_B = 989002   # no scouting observations, no team_event_stats, ever
_TEAM_C = 989003   # team_event_stats exists, but at the NOT-yet-concluded event
_FILLERS = [989011, 989012, 989013, 989014, 989015, 989016]
_ALL_TEAMS = [_TEAM_A, _TEAM_B, _TEAM_C, *_FILLERS]

_T0 = datetime(2026, 3, 15, 10, 0, 0, tzinfo=timezone.utc)   # qm1
_T1 = datetime(2026, 3, 15, 14, 0, 0, tzinfo=timezone.utc)   # qm2
_AS_OF = datetime(2026, 3, 15, 18, 0, 0, tzinfo=timezone.utc)  # qm3 -- the cutoff
_T3 = datetime(2026, 3, 15, 22, 0, 0, tzinfo=timezone.utc)   # qm4 -- after as_of

_QM1 = f"{_EVENT_TARGET}_qm1"
_QM2 = f"{_EVENT_TARGET}_qm2"
_QM3 = f"{_EVENT_TARGET}_qm3"  # the target match
_QM4 = f"{_EVENT_TARGET}_qm4"
_QM_IRREGULAR = f"{_EVENT_TARGET}_qm5"
# The EPA source rule (ml.features.assembler.EPA_SOURCE_SQL) only offers an event
# the team completed a match at, finished before as_of -- a Statbotics row alone
# is not evidence the team played there. These give teams A and C that evidence.
_QM_CONCLUDED = f"{_EVENT_CONCLUDED}_qm1"
_QM_ONGOING = f"{_EVENT_ONGOING}_qm1"


@pytest.fixture(autouse=True)
def _statbotics_reference_epa_source(monkeypatch):
    """These tests exercise EPA selection over sentinel team_event_stats rows, i.e.
    the Statbotics reference source (ml.ratings.provider); production uses STRATAI."""
    monkeypatch.setenv("EPA_SOURCE", "statbotics")


def _database_available() -> bool:
    try:
        with psycopg.connect(str(Settings().database_url), connect_timeout=3):
            return True
    except Exception:
        return False


requires_db = pytest.mark.skipif(
    not _database_available(), reason="Requires a reachable PostgreSQL database via DATABASE_URL",
)


def _cleanup(database: Database) -> None:
    with database.cursor() as cursor:
        cursor.execute(
            "DELETE FROM scouting_observations WHERE event_key = %s", (_EVENT_TARGET,),
        )
        cursor.execute(
            "DELETE FROM match_teams WHERE match_key IN (%s, %s, %s, %s, %s, %s, %s)",
            (_QM1, _QM2, _QM3, _QM4, _QM_IRREGULAR, _QM_CONCLUDED, _QM_ONGOING),
        )
        cursor.execute(
            "DELETE FROM matches WHERE event_key IN (%s, %s, %s)", (_EVENT_TARGET, _EVENT_CONCLUDED, _EVENT_ONGOING),
        )
        cursor.execute(
            "DELETE FROM team_event_stats WHERE event_key IN (%s, %s, %s)",
            (_EVENT_CONCLUDED, _EVENT_ONGOING, _EVENT_TARGET),
        )
        cursor.execute("DELETE FROM teams WHERE team_number = ANY(%s::int[])", (_ALL_TEAMS,))
        cursor.execute(
            "DELETE FROM events WHERE event_key IN (%s, %s, %s)",
            (_EVENT_CONCLUDED, _EVENT_ONGOING, _EVENT_TARGET),
        )


def _insert_match(
    database: Database, match_key: str, *, match_number: int, scheduled_time: datetime,
    red_teams: list[int], blue_teams: list[int], score_red: int | None, score_blue: int | None,
) -> None:
    with database.cursor() as cursor:
        cursor.execute(
            """
            INSERT INTO matches (
                match_key, event_key, season, competition_level, match_number,
                scheduled_time, score_red, score_blue
            ) VALUES (%s, %s, %s, 'qualification', %s, %s, %s, %s)
            """,
            (match_key, _EVENT_TARGET, 9989, match_number, scheduled_time, score_red, score_blue),
        )
        for alliance_color, team_numbers in (("red", red_teams), ("blue", blue_teams)):
            for position, team_number in enumerate(team_numbers, start=1):
                cursor.execute(
                    "INSERT INTO match_teams (match_key, team_number, alliance_color, station_position) "
                    "VALUES (%s, %s, %s, %s)",
                    (match_key, team_number, alliance_color, position),
                )


def _insert_observation(
    database: Database, *, match_key: str, team_number: int, defense_rating: int | None,
    feeding_rating: int | None, submitted_at: datetime, scout_identifier: str,
) -> None:
    with database.cursor() as cursor:
        cursor.execute(
            """
            INSERT INTO scouting_observations (
                match_key, event_key, team_number, scout_identifier,
                defense_rating, feeding_rating, source, submitted_at
            ) VALUES (%s, %s, %s, %s, %s, %s, 'human_scout', %s)
            """,
            (match_key, _EVENT_TARGET, team_number, scout_identifier, defense_rating, feeding_rating, submitted_at),
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
            "INSERT INTO events (event_key, season, name, end_date) VALUES (%s, %s, %s, %s)",
            (_EVENT_CONCLUDED, 9988, "Sentinel Concluded Event", "2026-02-01"),
        )
        cursor.execute(
            "INSERT INTO events (event_key, season, name, end_date) VALUES (%s, %s, %s, %s)",
            (_EVENT_ONGOING, 9987, "Sentinel Not-Yet-Concluded Event", "2026-04-01"),
        )
        cursor.execute(
            "INSERT INTO events (event_key, season, name) VALUES (%s, %s, %s)",
            (_EVENT_TARGET, 9989, "Sentinel Target Event"),
        )
        for team_number in _ALL_TEAMS:
            cursor.execute(
                "INSERT INTO teams (team_number, name) VALUES (%s, %s)", (team_number, f"Sentinel {team_number}"),
            )
        # Team A's real, trustworthy EPA -- from the CONCLUDED prior event.
        cursor.execute(
            "INSERT INTO team_event_stats (team_number, event_key, season, epa_total, epa_auto, epa_teleop, "
            "epa_endgame) VALUES (%s, %s, %s, %s, %s, %s, %s)",
            (_TEAM_A, _EVENT_CONCLUDED, 9988, 42.0, 10.0, 25.0, 7.0),
        )
        # Team A's DECOY same-event EPA -- must never be used, at any as_of.
        cursor.execute(
            "INSERT INTO team_event_stats (team_number, event_key, season, epa_total) VALUES (%s, %s, %s, %s)",
            (_TEAM_A, _EVENT_TARGET, 9989, 999.0),
        )
        # Team C's EPA -- exists, but at an event that has NOT concluded before as_of.
        cursor.execute(
            "INSERT INTO team_event_stats (team_number, event_key, season, epa_total) VALUES (%s, %s, %s, %s)",
            (_TEAM_C, _EVENT_ONGOING, 9987, 55.0),
        )
        # Completed matches: A finished the concluded event; C has played at the
        # ongoing one, before as_of, but that event's end_date is still ahead.
        for match_key, event_key, season, when, team in (
            (_QM_CONCLUDED, _EVENT_CONCLUDED, 9988, datetime(2026, 1, 31, 12, tzinfo=timezone.utc), _TEAM_A),
            (_QM_ONGOING, _EVENT_ONGOING, 9987, datetime(2026, 3, 1, 12, tzinfo=timezone.utc), _TEAM_C),
        ):
            cursor.execute(
                "INSERT INTO matches (match_key, event_key, season, competition_level, match_number, "
                "scheduled_time, score_red, score_blue) VALUES (%s, %s, %s, 'qualification', 1, %s, 50, 40)",
                (match_key, event_key, season, when),
            )
            cursor.execute(
                "INSERT INTO match_teams (match_key, team_number, alliance_color, station_position) "
                "VALUES (%s, %s, 'red', 1)", (match_key, team),
            )

    _insert_match(
        db, _QM1, match_number=1, scheduled_time=_T0,
        red_teams=[_TEAM_A, *_FILLERS[0:2]], blue_teams=_FILLERS[2:5],
        score_red=100, score_blue=80,
    )
    _insert_match(
        db, _QM2, match_number=2, scheduled_time=_T1,
        red_teams=_FILLERS[0:3], blue_teams=[_TEAM_A, *_FILLERS[3:5]],
        score_red=70, score_blue=120,
    )
    _insert_match(
        db, _QM3, match_number=3, scheduled_time=_AS_OF,
        red_teams=[_TEAM_A, _TEAM_B, _TEAM_C], blue_teams=_FILLERS[0:3],
        score_red=150, score_blue=140,
    )
    _insert_match(
        db, _QM4, match_number=4, scheduled_time=_T3,
        red_teams=[_TEAM_A, *_FILLERS[0:2]], blue_teams=_FILLERS[2:5],
        score_red=999, score_blue=1,
    )
    _insert_match(
        db, _QM_IRREGULAR, match_number=6, scheduled_time=_T3,
        red_teams=[_TEAM_A], blue_teams=_FILLERS[0:2],
        score_red=None, score_blue=None,
    )

    # Included: before as_of on both gates.
    _insert_observation(
        db, match_key=_QM1, team_number=_TEAM_A, defense_rating=3, feeding_rating=None,
        submitted_at=_T0.replace(hour=10, minute=30), scout_identifier="scout1",
    )
    _insert_observation(
        db, match_key=_QM2, team_number=_TEAM_A, defense_rating=5, feeding_rating=None,
        submitted_at=_T1.replace(hour=14, minute=30), scout_identifier="scout2",
    )
    # Excluded: both the match (qm4) and the submission are after as_of.
    _insert_observation(
        db, match_key=_QM4, team_number=_TEAM_A, defense_rating=0, feeding_rating=None,
        submitted_at=_T3.replace(hour=22, minute=30), scout_identifier="scout3",
    )
    # Excluded: the match (qm1) is before as_of, but submitted_at is not --
    # a scout who watched an early match but submitted the rating late.
    _insert_observation(
        db, match_key=_QM1, team_number=_TEAM_A, defense_rating=1, feeding_rating=None,
        submitted_at=datetime(2026, 3, 16, 0, 0, tzinfo=timezone.utc), scout_identifier="scout4",
    )

    try:
        yield db
    finally:
        _cleanup(db)


# ---------------------------------------------------------------------------
# Point-in-time leakage tests -- the milestone's own named scenarios
# ---------------------------------------------------------------------------


@requires_db
def test_no_match_at_or_after_as_of_contributes_to_scoring(database: Database) -> None:
    row = build_match_feature_row(database, _QM3, _AS_OF)
    team_a = next(t for t in row.red_teams if t.team_number == _TEAM_A)

    # Only qm1 (100) and qm2 (120) are strictly before as_of; qm3 (== as_of)
    # and qm4 (999, after as_of) must not appear anywhere in the result.
    assert team_a.matches_considered == 2
    assert team_a.matches_used == 2
    assert team_a.average_score == average_score([100, 120])
    assert team_a.score_stddev == score_stddev([100, 120])
    assert team_a.consistency_rating == consistency_rating([100, 120])
    assert team_a.reliability_score == reliability_score(2, 2)
    # The strongest possible negative control: qm4's score (999) is so
    # extreme that any leak at all would be unmistakable in the average.
    assert team_a.average_score is not None and team_a.average_score < 200


@requires_db
def test_defense_score_excludes_both_future_match_and_late_submission(database: Database) -> None:
    row = build_match_feature_row(database, _QM3, _AS_OF)
    team_a = next(t for t in row.red_teams if t.team_number == _TEAM_A)

    included = [
        ScoutingObservation(
            match_key=_QM1, event_key=_EVENT_TARGET, team_number=_TEAM_A, scout_identifier="scout1",
            defense_rating=3, feeding_rating=None, source="human_scout", submitted_at=_T0,
        ),
        ScoutingObservation(
            match_key=_QM2, event_key=_EVENT_TARGET, team_number=_TEAM_A, scout_identifier="scout2",
            defense_rating=5, feeding_rating=None, source="human_scout", submitted_at=_T1,
        ),
    ]
    expected = aggregate_defense_feeding(included)

    assert team_a.defense_observation_count == 2
    assert team_a.defense_score == expected.defense_score
    assert team_a.defense_score_present is True
    assert team_a.contributing_scouting_sources == ["human_scout"]

    # Negative control: if either excluded observation (rating 0 or 1) had
    # leaked in, the median would differ from the 2-observation result.
    leaked = aggregate_defense_feeding(
        included
        + [
            ScoutingObservation(
                match_key=_QM4, event_key=_EVENT_TARGET, team_number=_TEAM_A, scout_identifier="scout3",
                defense_rating=0, feeding_rating=None, source="human_scout", submitted_at=_T3,
            ),
            ScoutingObservation(
                match_key=_QM1, event_key=_EVENT_TARGET, team_number=_TEAM_A, scout_identifier="scout4",
                defense_rating=1, feeding_rating=None, source="human_scout",
                submitted_at=datetime(2026, 3, 16, 0, 0, tzinfo=timezone.utc),
            ),
        ]
    )
    assert team_a.defense_score != leaked.defense_score


@requires_db
def test_feeding_absent_for_a_team_with_only_defense_ratings(database: Database) -> None:
    row = build_match_feature_row(database, _QM3, _AS_OF)
    team_a = next(t for t in row.red_teams if t.team_number == _TEAM_A)

    assert team_a.feeding_score is None
    assert team_a.feeding_score_present is False
    assert team_a.feeding_observation_count == 0


@requires_db
def test_team_with_zero_scouting_observations_is_missing_not_zero(database: Database) -> None:
    row = build_match_feature_row(database, _QM3, _AS_OF)
    team_b = next(t for t in row.red_teams if t.team_number == _TEAM_B)

    assert team_b.defense_score is None
    assert team_b.defense_score_present is False
    assert team_b.defense_observation_count == 0
    assert team_b.feeding_score is None
    assert team_b.feeding_score_present is False
    assert team_b.contributing_scouting_sources == []
    # Also has no prior scoring history at this event (only ever rostered
    # into qm3 itself, which is excluded).
    assert team_b.matches_considered == 0
    assert team_b.matches_used == 0
    assert team_b.average_score is None
    assert team_b.average_score_present is False


@requires_db
def test_determinism_same_match_and_as_of_produce_identical_row(database: Database) -> None:
    first = build_match_feature_row(database, _QM3, _AS_OF)
    second = build_match_feature_row(database, _QM3, _AS_OF)
    assert first == second


@requires_db
def test_sentinel_collision_zero_defense_rating_is_a_real_value_not_absence(database: Database) -> None:
    # A team whose only *counted* observations happen to aggregate toward a
    # low score must still be reported as present=True, distinct from a team
    # with genuinely zero observations (team_b, above). This is exercised
    # indirectly by team_a's own real data (ratings 3 and 5, never 0 in the
    # counted set) -- the direct point is that this module never conflates
    # "value happens to be low/0" with "absent": presence is driven solely by
    # whether aggregate_defense_feeding returned a non-None score, never by
    # comparing the value itself to any sentinel number.
    row = build_match_feature_row(database, _QM3, _AS_OF)
    team_a = next(t for t in row.red_teams if t.team_number == _TEAM_A)
    assert team_a.defense_score is not None
    assert team_a.defense_score_present is True
    assert team_a.defense_score != 0  # not incidentally testing the boundary itself


# ---------------------------------------------------------------------------
# EPA leakage tests -- the module's own most severe finding
# ---------------------------------------------------------------------------


@requires_db
def test_epa_uses_prior_concluded_event_never_the_same_event(database: Database) -> None:
    row = build_match_feature_row(database, _QM3, _AS_OF)
    team_a = next(t for t in row.red_teams if t.team_number == _TEAM_A)

    assert team_a.epa_source_event_key == _EVENT_CONCLUDED
    assert team_a.epa_total == 42.0
    assert team_a.epa_auto == 10.0
    assert team_a.epa_teleop == 25.0
    assert team_a.epa_endgame == 7.0
    assert team_a.epa_total_present is True
    assert team_a.epa_withheld_reason is None
    # The decoy same-event row (999.0) must never appear.
    assert team_a.epa_total != 999.0


@requires_db
def test_epa_withheld_when_no_team_event_stats_row_exists_at_all(database: Database) -> None:
    row = build_match_feature_row(database, _QM3, _AS_OF)
    team_b = next(t for t in row.red_teams if t.team_number == _TEAM_B)

    assert team_b.epa_total_present is False
    assert team_b.epa_source_event_key is None
    assert team_b.epa_withheld_reason == EPA_WITHHELD_NO_PRIOR_EVENT


@requires_db
def test_epa_withheld_when_the_only_row_is_at_a_not_yet_concluded_event(database: Database) -> None:
    row = build_match_feature_row(database, _QM3, _AS_OF)
    team_c = next(t for t in row.red_teams if t.team_number == _TEAM_C)

    # team_c HAS a team_event_stats row (55.0, at the "ongoing" event) -- it
    # must still be withheld, because that event's end_date is after as_of.
    assert team_c.epa_total_present is False
    assert team_c.epa_total != 55.0
    assert team_c.epa_source_event_key is None
    assert team_c.epa_withheld_reason == EPA_WITHHELD_NO_PRIOR_EVENT


# ---------------------------------------------------------------------------
# Structural / robustness tests
# ---------------------------------------------------------------------------


@requires_db
def test_irregular_roster_does_not_crash(database: Database) -> None:
    row = build_match_feature_row(database, _QM_IRREGULAR, _T3)
    assert len(row.red_teams) == 1
    assert len(row.blue_teams) == 2


@requires_db
def test_unknown_match_key_raises(database: Database) -> None:
    with pytest.raises(ValueError, match="No such match"):
        build_match_feature_row(database, "9989zzzmltarget_nonexistent", _AS_OF)


@requires_db
def test_naive_as_of_is_rejected_before_any_query_runs(database: Database) -> None:
    naive = datetime(2026, 3, 15, 18, 0, 0)  # no tzinfo
    with pytest.raises(ValueError, match="timezone-aware"):
        build_match_feature_row(database, _QM3, naive)


@requires_db
def test_row_shape_is_match_feature_row(database: Database) -> None:
    row = build_match_feature_row(database, _QM3, _AS_OF)
    assert isinstance(row, MatchFeatureRow)
    assert row.match_key == _QM3
    assert row.event_key == _EVENT_TARGET
    assert row.season == 9989
    assert row.as_of == _AS_OF
    assert all(isinstance(t, TeamFeatures) for t in row.red_teams + row.blue_teams)


# ---------------------------------------------------------------------------
# Pure model-invariant tests -- no database required
# ---------------------------------------------------------------------------


def _make_team_features(**overrides: Any) -> TeamFeatures:
    defaults: dict[str, Any] = dict(
        team_number=1114,
        epa_total=None, epa_total_present=False,
        epa_auto=None, epa_auto_present=False,
        epa_teleop=None, epa_teleop_present=False,
        epa_endgame=None, epa_endgame_present=False,
        epa_source_event_key=None, epa_withheld_reason=EPA_WITHHELD_NO_PRIOR_EVENT,
        average_score=None, average_score_present=False,
        score_stddev=None, score_stddev_present=False,
        consistency_rating=None, consistency_rating_present=False,
        reliability_score=None, reliability_score_present=False,
        matches_considered=0, matches_used=0,
        average_auto_points_present=False, auto_points_matches_used=0,
        defense_score=None, defense_score_present=False,
        defense_agreement=None, defense_agreement_present=False,
        defense_observation_count=0,
        feeding_score=None, feeding_score_present=False,
        feeding_agreement=None, feeding_agreement_present=False,
        feeding_observation_count=0,
        contributing_scouting_sources=[],
    )
    defaults.update(overrides)
    return TeamFeatures(**defaults)


def test_team_features_rejects_present_true_with_no_value():
    with pytest.raises(ValidationError, match="inconsistent"):
        _make_team_features(average_score=None, average_score_present=True)


def test_team_features_rejects_present_false_with_a_value():
    with pytest.raises(ValidationError, match="inconsistent"):
        _make_team_features(average_score=95.0, average_score_present=False)


def test_team_features_rejects_matches_used_exceeding_matches_considered():
    with pytest.raises(ValidationError, match="matches_used"):
        _make_team_features(matches_considered=1, matches_used=2)


def test_team_features_rejects_epa_present_without_source_event_key():
    with pytest.raises(ValidationError, match="epa_source_event_key"):
        _make_team_features(epa_total=42.0, epa_total_present=True, epa_withheld_reason=None)


def test_team_features_rejects_epa_present_with_a_withheld_reason_still_set():
    with pytest.raises(ValidationError, match="epa_withheld_reason"):
        _make_team_features(
            epa_total=42.0, epa_total_present=True, epa_source_event_key="2026casj",
            epa_withheld_reason=EPA_WITHHELD_NO_PRIOR_EVENT,
        )


def test_team_features_rejects_no_epa_present_with_no_reason_given():
    with pytest.raises(ValidationError, match="epa_withheld_reason"):
        _make_team_features(epa_withheld_reason=None)


def test_team_features_sentinel_collision_zero_is_a_real_present_value():
    # The milestone's own named "sentinel-collision" case, at the model
    # level: a real defense_score of exactly 0.0 (DEFENSE_RATING_
    # DESCRIPTIONS[0] in data/metrics/schemas.py is "no defense observed", a
    # genuine measured value, not a missing-data placeholder) must construct
    # with defense_score_present=True -- proving presence is driven solely by
    # whether a value exists, never by comparing the value itself to 0 or any
    # other number a naive "0 means missing" convention might use.
    features = _make_team_features(
        defense_score=0.0, defense_score_present=True, defense_observation_count=2,
    )
    assert features.defense_score == 0.0
    assert features.defense_score_present is True

    # And the converse must be rejected: presence=False can never coexist
    # with a real value, even 0.0 -- 0.0 is exactly the value most likely to
    # be mistaken for "unset" by a careless caller, so this is the one value
    # most worth pinning directly.
    with pytest.raises(ValidationError, match="inconsistent"):
        _make_team_features(defense_score=0.0, defense_score_present=False)


def test_team_features_valid_shape_constructs_cleanly():
    features = _make_team_features(
        average_score=95.0, average_score_present=True,
        epa_total=42.0, epa_total_present=True, epa_source_event_key="2026casj", epa_withheld_reason=None,
    )
    assert features.average_score == 95.0
    assert features.epa_source_event_key == "2026casj"


def test_match_feature_row_rejects_naive_as_of():
    team = _make_team_features()
    with pytest.raises(ValidationError, match="timezone-aware"):
        MatchFeatureRow(
            match_key="2026casj_qm1", as_of=datetime(2026, 3, 15, 18, 0, 0),
            event_key="2026casj", season=2026, red_teams=[team], blue_teams=[team],
        )


def test_match_feature_row_allows_a_wholly_empty_alliance():
    # A real, already-observed shape (RUNNING_NOTES.md 2026-08-01's frc0
    # unassigned-roster placeholder, also exercised in
    # tests/test_metrics_history.py's own qm4 fixture) -- constructing this
    # must not crash, even though it is never the expected case.
    row = MatchFeatureRow(
        match_key="2026casj_qm1", as_of=_AS_OF, event_key="2026casj", season=2026,
        red_teams=[], blue_teams=[_make_team_features()],
    )
    assert row.red_teams == []
    assert len(row.blue_teams) == 1
