"""Regression guard for the "directly measured, NOT inferred" defense/feeding constraint.

CLAUDE.md / RUNNING_NOTES.md, Critical Constraints:

    Defense/feeding scores = **directly measured**, NOT inferred from point output

Every other layer already defends this constraint structurally: data/metrics/
schemas.py's DefenseFeedingProfile invariants, 0008_metrics_schema.sql's
*_sufficiency_check CHECK constraints, and the fact that
data.metrics.aggregation.aggregate_defense_feeding is handed only
ScoutingObservation rows and so has no score to reach for in the first place.
What none of those catch is a *future* change that adds a score-derived
adjustment at the composition layer -- data.metrics.compute._assemble_team_metrics
holds a fully-built ScoringProfile and a fully-built DefenseFeedingProfile in
the same scope, so nothing but this test stops someone from letting one touch
the other (e.g. penalizing an erratic team's defense score by its
reliability_score, or synthesizing a defense rating for an unscouted team from
its scoring pattern).

This file exists because a 2026-08-05 audit flagged exactly such a violation as
suspected-present. Investigation found NO violation -- defense and feeding
already derive only from scouting_observations, and no score->defense/feeding
path has ever existed in this repository. These tests pin that permanently, so
the same question is answered by a red test rather than another manual audit.

Method: two teams at one event with *identical* scouting observations and
deliberately *very* different match scores. Every score-derived quantity
differs between them (average_score, score_stddev, consistency_rating,
reliability_score, and the good/average/bad day counts -- asserted to differ,
so the guard can never go vacuous by the two teams accidentally converging),
while their entire DefenseFeedingProfile must come out byte-identical.
Comparing the whole profile object, not just the two scores, means a future
field derived from point output is caught too.
"""

from __future__ import annotations

from datetime import datetime, timezone

import psycopg
import pytest

from data.config import Settings
from data.metrics.compute import compute_event_team_metrics, compute_team_metrics
from database.connection import Database, DatabaseConfig

# Sentinel namespace, distinct from every other module's (9990-9999).
_S_EVENT = "9991zzzconstraint"
_S_MATCH_1 = f"{_S_EVENT}_qm1"
_S_MATCH_2 = f"{_S_EVENT}_qm2"
_S_MATCH_3 = f"{_S_EVENT}_qm3"
_S_MATCH_4 = f"{_S_EVENT}_qm4"  # scheduled but unplayed; rosters _S_TEAM_ERRATIC only

# Both teams play matches 1-3, on opposite alliances, so the ONLY thing that
# differs between them is the point output recorded against their alliance.
_S_TEAM_STEADY = 990211   # red: scores [10, 12, 11]
_S_TEAM_ERRATIC = 990212  # blue: scores [200, 40, 30], plus one unplayed match

# A third team, rostered into the high-scoring matches but never scouted at
# all -- guards the "no observation means NO rating" half of the constraint.
_S_TEAM_UNSCOUTED = 990213

# The identical observations both scouted teams receive.
_S_SCOUT_ALPHA = "guard-scout-alpha"  # defense 3, feeding 2
_S_SCOUT_BETA = "guard-scout-beta"    # defense 5, feeding 4


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
            "DELETE FROM canonical_lineage WHERE entity_type = 'team_metrics' AND entity_key LIKE %s",
            (f"%{_S_EVENT}",),
        )
        cursor.execute("DELETE FROM team_metrics WHERE event_key = %s", (_S_EVENT,))
        cursor.execute("DELETE FROM scouting_observations WHERE event_key = %s", (_S_EVENT,))
        cursor.execute("DELETE FROM match_teams WHERE match_key LIKE %s", (f"{_S_EVENT}%",))
        cursor.execute("DELETE FROM matches WHERE event_key = %s", (_S_EVENT,))
        cursor.execute(
            "DELETE FROM teams WHERE team_number = ANY(%s::int[])",
            ([_S_TEAM_STEADY, _S_TEAM_ERRATIC, _S_TEAM_UNSCOUTED],),
        )
        cursor.execute("DELETE FROM events WHERE event_key = %s", (_S_EVENT,))
        cursor.execute("DELETE FROM pipeline_runs WHERE scope_key = %s", (_S_EVENT,))


def _insert_observation(
    database: Database, match_key: str, team_number: int, scout: str, defense: int, feeding: int,
) -> None:
    """Insert one scouting observation directly.

    Direct SQL rather than submit_human_scout_observation: this file asserts
    nothing about landing, lineage, or the submission gate (tests/
    test_scouting_submission.py and tests/test_metrics_pipeline.py already
    cover those end to end). What matters here is only that both teams end up
    with an identical set of observation rows, which direct inserts state
    unambiguously.
    """
    with database.cursor() as cursor:
        cursor.execute(
            "INSERT INTO scouting_observations "
            "(match_key, event_key, team_number, scout_identifier, defense_rating, feeding_rating, "
            " source, submitted_at) "
            "VALUES (%s, %s, %s, %s, %s, %s, 'human_scout', %s)",
            (match_key, _S_EVENT, team_number, scout, defense, feeding, datetime.now(timezone.utc)),
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
            (_S_EVENT, 9991, "Sentinel Constraint Event"),
        )
        cursor.execute(
            "INSERT INTO teams (team_number, name) VALUES (%s, %s), (%s, %s), (%s, %s)",
            (
                _S_TEAM_STEADY, "Steady Low Scorer",
                _S_TEAM_ERRATIC, "Erratic High Scorer",
                _S_TEAM_UNSCOUTED, "Never Scouted",
            ),
        )
        # score_red is _S_TEAM_STEADY's own score; score_blue is _S_TEAM_ERRATIC's.
        for match_key, match_number, score_red, score_blue in (
            (_S_MATCH_1, 1, 10, 200),
            (_S_MATCH_2, 2, 12, 40),
            (_S_MATCH_3, 3, 11, 30),
            (_S_MATCH_4, 4, None, None),  # unplayed
        ):
            cursor.execute(
                "INSERT INTO matches "
                "(match_key, event_key, season, competition_level, match_number, score_red, score_blue) "
                "VALUES (%s, %s, 9991, 'qualification', %s, %s, %s)",
                (match_key, _S_EVENT, match_number, score_red, score_blue),
            )
        for match_key in (_S_MATCH_1, _S_MATCH_2, _S_MATCH_3):
            cursor.execute(
                "INSERT INTO match_teams (match_key, team_number, alliance_color) VALUES (%s, %s, 'red')",
                (match_key, _S_TEAM_STEADY),
            )
            cursor.execute(
                "INSERT INTO match_teams (match_key, team_number, alliance_color) VALUES (%s, %s, 'blue')",
                (match_key, _S_TEAM_ERRATIC),
            )
            # Rides along on the high-scoring blue alliance, but is never scouted.
            cursor.execute(
                "INSERT INTO match_teams (match_key, team_number, alliance_color) VALUES (%s, %s, 'blue')",
                (match_key, _S_TEAM_UNSCOUTED),
            )
        # Only _S_TEAM_ERRATIC is rostered into the unplayed match, so its
        # reliability_score (matches_used / matches_scheduled) differs too.
        cursor.execute(
            "INSERT INTO match_teams (match_key, team_number, alliance_color) VALUES (%s, %s, 'blue')",
            (_S_MATCH_4, _S_TEAM_ERRATIC),
        )

    # The identical observation set for both scouted teams: same matches, same
    # scout identifiers, same ratings, same source. Anything that makes their
    # defense/feeding profiles differ can therefore ONLY have come from scores.
    for team_number in (_S_TEAM_STEADY, _S_TEAM_ERRATIC):
        _insert_observation(db, _S_MATCH_1, team_number, _S_SCOUT_ALPHA, defense=3, feeding=2)
        _insert_observation(db, _S_MATCH_2, team_number, _S_SCOUT_BETA, defense=5, feeding=4)

    try:
        yield db
    finally:
        _cleanup(db)


@requires_db
def test_the_two_teams_really_do_differ_on_every_score_derived_quantity(database: Database) -> None:
    """Anti-vacuity check for the guard below -- not a constraint test itself.

    If a future fixture edit accidentally gave both teams the same scores, the
    identical-defense/feeding assertions would still pass while proving
    nothing at all. This fails first, and loudly, if that ever happens.
    """
    steady = compute_team_metrics(database, _S_TEAM_STEADY, _S_EVENT).scoring
    erratic = compute_team_metrics(database, _S_TEAM_ERRATIC, _S_EVENT).scoring

    assert steady.average_score == 11.0  # mean(10, 12, 11)
    assert erratic.average_score == 90.0  # mean(200, 40, 30)

    assert steady.average_score != erratic.average_score
    assert steady.score_stddev != erratic.score_stddev
    assert steady.consistency_rating != erratic.consistency_rating
    # The specific quantity a "penalize erratic teams' defense" adjustment
    # would most naturally reach for: 3/3 scheduled vs 3/4.
    assert steady.reliability_score == 100.0
    assert erratic.reliability_score == 75.0
    # Day classification differs too: the steady team's three scores straddle
    # its own mean by more than 1 stddev in both directions, the erratic
    # team's do not.
    assert (steady.good_day_count, steady.average_day_count, steady.bad_day_count) == (1, 1, 1)
    assert (erratic.good_day_count, erratic.average_day_count, erratic.bad_day_count) == (1, 2, 0)


@requires_db
def test_identical_scouting_yields_identical_defense_and_feeding_despite_different_scores(
    database: Database,
) -> None:
    """THE constraint: point output must not influence defense or feeding, at all.

    Compares the entire DefenseFeedingProfile, not only the two scores, so a
    future score-derived *agreement*, *count*, or any newly added field is
    caught by this same test rather than slipping past a two-field assertion.
    """
    steady = compute_team_metrics(database, _S_TEAM_STEADY, _S_EVENT).defense_feeding
    erratic = compute_team_metrics(database, _S_TEAM_ERRATIC, _S_EVENT).defense_feeding

    assert steady == erratic, (
        "Defense/feeding differ between two teams with identical scouting observations. "
        "The only thing that differs between them is match score, so some code path is "
        "inferring defense/feeding from point output -- see this module's docstring."
    )

    # Pinned against the directly-measured values themselves, so the pair can
    # never agree by both being wrong (e.g. both None, or both penalized by
    # the same amount).
    assert steady.defense_score == 4.0  # median(3, 5) -- unadjusted
    assert steady.feeding_score == 3.0  # median(2, 4) -- unadjusted
    assert steady.defense_observation_count == 2
    assert steady.feeding_observation_count == 2
    assert not steady.defense_insufficient_data
    assert not steady.feeding_insufficient_data
    assert steady.defense_agreement == pytest.approx(0.6)  # 1 - pstdev(3,5) / (5/2)
    assert steady.feeding_agreement == pytest.approx(0.6)
    assert steady.contributing_sources == ["human_scout"]


@requires_db
def test_the_constraint_still_holds_for_the_persisted_team_metrics_rows(database: Database) -> None:
    """The same guard one layer down, against what actually lands in team_metrics.

    compute_team_metrics returning equal profiles would not, on its own, rule
    out a score-derived adjustment applied on the way to the database in
    CanonicalRepository.load_team_metrics.
    """
    compute_event_team_metrics(_S_EVENT, database=database)

    with database.cursor() as cursor:
        cursor.execute(
            "SELECT team_number, average_score, defense_score, defense_agreement, "
            "       feeding_score, feeding_agreement, defense_insufficient_data, feeding_insufficient_data "
            "FROM team_metrics WHERE event_key = %s AND team_number = ANY(%s::int[]) ORDER BY team_number",
            (_S_EVENT, [_S_TEAM_STEADY, _S_TEAM_ERRATIC]),
        )
        steady_row, erratic_row = cursor.fetchall()

    # Different average_score (column 1), identical defense/feeding (columns 2-7).
    assert steady_row[1] != erratic_row[1]
    assert steady_row[2:] == erratic_row[2:]
    assert steady_row[2] == 4.0
    assert steady_row[4] == 3.0


@requires_db
def test_an_unscouted_team_gets_no_defense_or_feeding_rating_however_it_scores(
    database: Database,
) -> None:
    """The other half of the constraint: absent scouting means NO rating.

    A team with zero observations must come out insufficient_data/None -- never
    a value synthesized from its scoring pattern, and never a substituted
    default. _S_TEAM_UNSCOUTED rides the same high-scoring blue alliance as
    _S_TEAM_ERRATIC, so a point-output-derived rating would have ample signal
    to fabricate one from.
    """
    metrics = compute_team_metrics(database, _S_TEAM_UNSCOUTED, _S_EVENT)

    # It genuinely has a strong scoring record -- the fabrication signal is present.
    assert metrics.scoring.average_score == 90.0

    defense_feeding = metrics.defense_feeding
    assert defense_feeding.defense_score is None
    assert defense_feeding.feeding_score is None
    assert defense_feeding.defense_insufficient_data
    assert defense_feeding.feeding_insufficient_data
    assert defense_feeding.defense_observation_count == 0
    assert defense_feeding.feeding_observation_count == 0
    assert defense_feeding.defense_agreement is None
    assert defense_feeding.feeding_agreement is None
    assert defense_feeding.contributing_sources == []

    # And the same NULLs reach the database -- no default substituted on write.
    compute_event_team_metrics(_S_EVENT, database=database)
    with database.cursor() as cursor:
        cursor.execute(
            "SELECT defense_score, feeding_score, defense_insufficient_data, feeding_insufficient_data "
            "FROM team_metrics WHERE event_key = %s AND team_number = %s",
            (_S_EVENT, _S_TEAM_UNSCOUTED),
        )
        assert cursor.fetchone() == (None, None, True, True)
