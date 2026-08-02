"""Phase 3 Milestone 2: the metrics schema must match the Milestone 1 models.

0008_metrics_schema.sql claims two things that are easy to assert and easy to let
rot, so both are pinned here:

  * every column of team_metrics and scouting_observations is a field of a model
    in data/metrics/schemas.py, under its own name -- checked by comparing the
    live column set against model_fields, and by round-tripping a real
    TeamMetrics through the table using nothing but field names as column names
  * the table's CHECK constraints are transcriptions of that module's pydantic
    model_validators, so the database refuses exactly what the models refuse

The second matters most for defense and feeding. CLAUDE.md's critical constraint
is that those scores are directly measured, never inferred from point output, and
Milestone 1 enforces "a score exists if and only if its insufficient_data flag is
False" in DefenseFeedingProfile. If that invariant lived only in pydantic, any
future writer bypassing the model could persist a confident-looking score built
on zero observations. Here it is unstorable.

Schema only -- nothing in this module computes a metric.
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import psycopg
import pytest

from data.config import Settings
from data.metrics.schemas import (
    DefenseFeedingProfile,
    ScoringProfile,
    ScoutingObservation,
    TeamMetrics,
)
from database.connection import Database, DatabaseConfig

PROJECT_ROOT = Path(__file__).resolve().parents[1]
MIGRATION_PATH = PROJECT_ROOT / "database" / "migrations" / "0008_metrics_schema.sql"

# Sentinel namespace, distinct from the 9998/9999 keys used by the Milestone 7/8
# fixtures and the 2025zzzqual key used by Milestone 9, so a failed run of this
# module can never collide with or clean up another module's rows.
_S_EVENT = "9996zzzm2"
_S_MATCH = "9996zzzm2_qm1"
_S_TEAMS = [960001, 960002]
_S_SOURCE_OBJECT_ID = "9996zzzm2-metrics-schema-test"

_SUBMITTED_AT = datetime(2026, 8, 2, 12, 0, tzinfo=timezone.utc)


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


# ---------------------------------------------------------------------------
# Fixtures. Sentinel rows are seeded with raw SQL rather than through the
# staging layer: this milestone is testing the schema, and routing through
# normalization would make a constraint failure ambiguous between the two.
# ---------------------------------------------------------------------------


def _cleanup(database: Database) -> None:
    with database.cursor() as cursor:
        cursor.execute("DELETE FROM scouting_observations WHERE event_key = %s", (_S_EVENT,))
        cursor.execute("DELETE FROM team_metrics WHERE event_key = %s", (_S_EVENT,))
        cursor.execute("DELETE FROM matches WHERE match_key = %s", (_S_MATCH,))
        cursor.execute("DELETE FROM teams WHERE team_number = ANY(%s::int[])", (_S_TEAMS,))
        cursor.execute("DELETE FROM events WHERE event_key = %s", (_S_EVENT,))
        cursor.execute(
            "DELETE FROM raw_source_payloads WHERE source_object_id = %s",
            (_S_SOURCE_OBJECT_ID,),
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
            (_S_EVENT, 9996, "Sentinel Metrics Event"),
        )
        for team_number in _S_TEAMS:
            cursor.execute(
                "INSERT INTO teams (team_number, name) VALUES (%s, %s)",
                (team_number, f"Sentinel {team_number}"),
            )
        cursor.execute(
            "INSERT INTO matches (match_key, event_key, season, competition_level, match_number) "
            "VALUES (%s, %s, %s, %s, %s)",
            (_S_MATCH, _S_EVENT, 9996, "qualification", 1),
        )
    try:
        yield db
    finally:
        _cleanup(db)


def _insert_observation(database: Database, **overrides) -> None:
    row = dict(
        match_key=_S_MATCH,
        event_key=_S_EVENT,
        team_number=_S_TEAMS[0],
        scout_identifier="scout-a",
        defense_rating=3,
        feeding_rating=None,
        notes=None,
        source="human_scout",
        submitted_at=_SUBMITTED_AT,
        raw_payload_id=None,
    )
    row.update(overrides)
    columns = ", ".join(row)
    placeholders = ", ".join(f"%({name})s" for name in row)
    with database.cursor() as cursor:
        cursor.execute(
            f"INSERT INTO scouting_observations ({columns}) VALUES ({placeholders})", row
        )


def _flatten(metrics: TeamMetrics) -> dict:
    """TeamMetrics -> one flat row, using model field names as column names."""
    row = metrics.model_dump(exclude={"scoring", "defense_feeding"})
    row.update(metrics.scoring.model_dump())
    row.update(metrics.defense_feeding.model_dump())
    return row


def _rebuild(row: dict) -> TeamMetrics:
    """One flat row -> TeamMetrics, the inverse of _flatten."""
    identity = {
        name: row[name]
        for name in TeamMetrics.model_fields
        if name not in ("scoring", "defense_feeding")
    }
    return TeamMetrics(
        **identity,
        scoring=ScoringProfile(**{name: row[name] for name in ScoringProfile.model_fields}),
        defense_feeding=DefenseFeedingProfile(
            **{name: row[name] for name in DefenseFeedingProfile.model_fields}
        ),
    )


def _insert_metrics(database: Database, metrics: TeamMetrics) -> None:
    row = _flatten(metrics)
    columns = ", ".join(row)
    placeholders = ", ".join(f"%({name})s" for name in row)
    with database.cursor() as cursor:
        cursor.execute(f"INSERT INTO team_metrics ({columns}) VALUES ({placeholders})", row)


def _sample_metrics(**scoring_overrides) -> TeamMetrics:
    scoring = dict(
        matches_scheduled=12, matches_used=10, average_score=88.5, score_stddev=12.25,
        consistency_rating=76.0, reliability_score=83.5,
        good_day_count=2, average_day_count=6, bad_day_count=2,
    )
    scoring.update(scoring_overrides)
    return TeamMetrics(
        team_number=_S_TEAMS[0], event_key=_S_EVENT, season=9996,
        computed_at=_SUBMITTED_AT,
        scoring=ScoringProfile(**scoring),
        defense_feeding=DefenseFeedingProfile(
            defense_score=3.5, defense_observation_count=6, defense_agreement=0.8,
            defense_insufficient_data=False,
            feeding_score=None, feeding_observation_count=0, feeding_agreement=None,
            feeding_insufficient_data=True,
            contributing_sources=["human_scout", "scoutradioz"],
        ),
    )


def _columns(database: Database, table: str) -> set[str]:
    with database.cursor() as cursor:
        cursor.execute(
            "SELECT column_name FROM information_schema.columns WHERE table_name = %s",
            (table,),
        )
        return {row[0] for row in cursor.fetchall()}


# ===========================================================================
# The migration itself.
# ===========================================================================


@requires_db
def test_migration_is_idempotent(database):
    # migrate.py will not re-run a recorded migration, but the file must still be
    # safe to apply twice on its own -- a half-applied migration is repaired by
    # re-running it, and every other migration in this directory holds that
    # property. Inline CHECK constraints inside CREATE TABLE IF NOT EXISTS are
    # what make this work; 0007's ALTER/DROP/ADD pattern would not.
    sql = MIGRATION_PATH.read_text(encoding="utf-8")
    for _ in range(2):
        with database.cursor() as cursor:
            cursor.execute(sql)


# ===========================================================================
# Every column traces to a Milestone 1 field.
# ===========================================================================


@requires_db
def test_team_metrics_columns_are_exactly_the_milestone_1_fields(database):
    # TeamMetrics composes two sub-models; the table flattens them. Because the
    # sub-models share no field names, the mapping is identity -- which is the
    # whole justification for flattening rather than storing JSONB, so it is
    # asserted rather than assumed.
    expected = {
        name for name in TeamMetrics.model_fields if name not in ("scoring", "defense_feeding")
    }
    expected |= set(ScoringProfile.model_fields)
    expected |= set(DefenseFeedingProfile.model_fields)

    assert _columns(database, "team_metrics") == expected


@requires_db
def test_scouting_observations_columns_are_the_milestone_1_fields_plus_two(database):
    extra = _columns(database, "scouting_observations") - set(ScoutingObservation.model_fields)
    missing = set(ScoutingObservation.model_fields) - _columns(database, "scouting_observations")

    assert missing == set(), f"ScoutingObservation fields with no column: {sorted(missing)}"
    # id is a surrogate key (the natural key is the four-column unique index);
    # raw_payload_id is the lineage reference this milestone requires. Nothing else.
    assert extra == {"id", "raw_payload_id"}, f"unexplained columns: {sorted(extra)}"


@requires_db
def test_a_team_metrics_row_round_trips_through_the_flattened_columns(database):
    original = _sample_metrics()
    _insert_metrics(database, original)  # column names come straight from model_fields

    with database.cursor() as cursor:
        cursor.execute(
            "SELECT * FROM team_metrics WHERE team_number = %s AND event_key = %s",
            (_S_TEAMS[0], _S_EVENT),
        )
        names = [column.name for column in cursor.description]
        row = dict(zip(names, cursor.fetchone()))

    assert _rebuild(row) == original


# ===========================================================================
# scouting_observations: keys and references.
# ===========================================================================


@requires_db
@pytest.mark.parametrize("overrides", [
    pytest.param({"match_key": "9996zzzm2_qm999"}, id="unknown-match"),
    pytest.param({"team_number": 969999}, id="unknown-team"),
    pytest.param({"event_key": "9996zzznope"}, id="unknown-event"),
    pytest.param({"raw_payload_id": 2_147_483_647}, id="unknown-raw-payload"),
])
def test_scouting_observations_rejects_a_dangling_reference(database, overrides):
    with pytest.raises(psycopg.errors.ForeignKeyViolation):
        _insert_observation(database, **overrides)


@requires_db
def test_scouting_observations_rejects_a_duplicate_scout_submission(database):
    _insert_observation(database)
    with pytest.raises(psycopg.errors.UniqueViolation):
        _insert_observation(database, defense_rating=5)


@requires_db
@pytest.mark.parametrize("overrides", [
    pytest.param({"scout_identifier": "scout-b"}, id="different-scout"),
    pytest.param({"source": "scoutradioz"}, id="different-source"),
    pytest.param({"team_number": _S_TEAMS[1]}, id="different-team"),
])
def test_the_unique_key_still_admits_genuinely_distinct_observations(database, overrides):
    # The constraint must reject a resubmission without collapsing real data: two
    # scouts rating the same robot, or the same scout name arriving from a
    # different source, are distinct observations, not duplicates.
    _insert_observation(database)
    _insert_observation(database, **overrides)

    with database.cursor() as cursor:
        cursor.execute(
            "SELECT count(*) FROM scouting_observations WHERE event_key = %s", (_S_EVENT,)
        )
        assert cursor.fetchone()[0] == 2


@requires_db
def test_an_observation_survives_the_deletion_of_its_raw_payload(database):
    # The cascade decision, exercised rather than merely read off pg_constraint.
    # Scouting data is the only irreplaceable data in the system, so purging a raw
    # payload must clear the provenance pointer and leave the observation intact.
    with database.cursor() as cursor:
        cursor.execute(
            "INSERT INTO raw_source_payloads "
            "(source, source_object_type, source_object_id, payload_json, payload_checksum) "
            "VALUES (%s, %s, %s, %s, %s) RETURNING id",
            ("scoutradioz", "match", _S_SOURCE_OBJECT_ID, "{}", "sentinel-checksum"),
        )
        payload_id = cursor.fetchone()[0]

    _insert_observation(database, raw_payload_id=payload_id, source="scoutradioz")

    with database.cursor() as cursor:
        cursor.execute("DELETE FROM raw_source_payloads WHERE id = %s", (payload_id,))
        cursor.execute(
            "SELECT defense_rating, raw_payload_id FROM scouting_observations WHERE event_key = %s",
            (_S_EVENT,),
        )
        assert cursor.fetchall() == [(3, None)]


@requires_db
def test_a_scouted_match_cannot_be_deleted_out_from_under_its_observations(database):
    _insert_observation(database)
    with pytest.raises(psycopg.errors.ForeignKeyViolation):
        with database.cursor() as cursor:
            cursor.execute("DELETE FROM matches WHERE match_key = %s", (_S_MATCH,))


# ===========================================================================
# scouting_observations: the model's own invariants.
# ===========================================================================


@requires_db
def test_an_observation_asserting_neither_rating_is_rejected(database):
    # ScoutingObservation._require_at_least_one_rating.
    with pytest.raises(psycopg.errors.CheckViolation):
        _insert_observation(database, defense_rating=None, feeding_rating=None)


@requires_db
@pytest.mark.parametrize("overrides", [
    pytest.param({"defense_rating": 6}, id="defense-above-max"),
    pytest.param({"defense_rating": -1}, id="defense-below-min"),
    pytest.param({"feeding_rating": 6, "defense_rating": None}, id="feeding-above-max"),
])
def test_a_rating_outside_the_scale_is_rejected(database, overrides):
    with pytest.raises(psycopg.errors.CheckViolation):
        _insert_observation(database, **overrides)


@requires_db
def test_zero_is_a_storable_rating(database):
    # 0 means "confirmed no defense observed", not "unknown" -- if the schema
    # treated it as a sentinel, a real measurement would be silently unrecordable.
    _insert_observation(database, defense_rating=0, feeding_rating=0)
    with database.cursor() as cursor:
        cursor.execute(
            "SELECT defense_rating, feeding_rating FROM scouting_observations WHERE event_key = %s",
            (_S_EVENT,),
        )
        assert cursor.fetchall() == [(0, 0)]


@requires_db
@pytest.mark.parametrize("overrides", [
    pytest.param({"scout_identifier": ""}, id="empty-scout-identifier"),
    pytest.param({"source": ""}, id="empty-source"),
])
def test_an_empty_identifier_is_rejected(database, overrides):
    # Field(min_length=1) on the two identifiers that have no FK to enforce them.
    with pytest.raises(psycopg.errors.CheckViolation):
        _insert_observation(database, **overrides)


# ===========================================================================
# team_metrics: keys, references, and the ScoringProfile invariants.
# ===========================================================================


@requires_db
@pytest.mark.parametrize("field,value", [
    pytest.param("team_number", 969999, id="unknown-team"),
    pytest.param("event_key", "9996zzznope", id="unknown-event"),
])
def test_team_metrics_rejects_a_dangling_reference(database, field, value):
    row = _flatten(_sample_metrics())
    row[field] = value
    columns = ", ".join(row)
    placeholders = ", ".join(f"%({name})s" for name in row)
    with pytest.raises(psycopg.errors.ForeignKeyViolation):
        with database.cursor() as cursor:
            cursor.execute(
                f"INSERT INTO team_metrics ({columns}) VALUES ({placeholders})", row
            )


@requires_db
def test_team_metrics_holds_one_row_per_team_and_event(database):
    _insert_metrics(database, _sample_metrics())
    with pytest.raises(psycopg.errors.UniqueViolation):
        _insert_metrics(database, _sample_metrics(matches_used=8, good_day_count=1,
                                                  average_day_count=5, bad_day_count=2))


@requires_db
@pytest.mark.parametrize("scoring,reason", [
    pytest.param(
        dict(matches_scheduled=5, matches_used=6, average_score=10.0, score_stddev=1.0,
             consistency_rating=50.0, reliability_score=50.0,
             good_day_count=2, average_day_count=2, bad_day_count=2),
        "matches_used exceeds matches_scheduled", id="used-exceeds-scheduled",
    ),
    pytest.param(
        dict(matches_scheduled=5, matches_used=0, average_score=10.0),
        "no matches used, so nothing may be computed", id="value-with-no-matches",
    ),
    pytest.param(
        dict(matches_scheduled=5, matches_used=1, average_score=10.0, score_stddev=0.0),
        "variance is undefined for one sample", id="stddev-from-one-match",
    ),
    pytest.param(
        dict(matches_scheduled=5, matches_used=1, average_score=10.0,
             good_day_count=1, average_day_count=0, bad_day_count=0),
        "day classification needs a stddev", id="day-counts-from-one-match",
    ),
    pytest.param(
        dict(matches_scheduled=12, matches_used=10, average_score=88.5, score_stddev=12.25,
             consistency_rating=76.0, reliability_score=83.5,
             good_day_count=2, average_day_count=6, bad_day_count=1),
        "day counts must sum to matches_used", id="day-counts-do-not-sum",
    ),
    pytest.param(
        dict(matches_scheduled=12, matches_used=10, average_score=88.5, score_stddev=12.25,
             consistency_rating=76.0, reliability_score=83.5, good_day_count=10),
        "day counts must be set together", id="partial-day-counts",
    ),
    pytest.param(
        dict(matches_scheduled=12, matches_used=10, average_score=-1.0, score_stddev=12.25,
             consistency_rating=76.0, reliability_score=83.5,
             good_day_count=2, average_day_count=6, bad_day_count=2),
        "an FRC score is never negative", id="negative-average-score",
    ),
    pytest.param(
        dict(matches_scheduled=12, matches_used=10, average_score=88.5, score_stddev=12.25,
             consistency_rating=101.0, reliability_score=83.5,
             good_day_count=2, average_day_count=6, bad_day_count=2),
        "consistency_rating is scaled 0-100", id="consistency-above-scale",
    ),
])
def test_the_scoring_invariants_are_enforced_by_the_database(database, scoring, reason):
    # Each case is one clause of ScoringProfile._check_invariants or one of its
    # Field bounds. The row is assembled by hand rather than through the model,
    # because the model would refuse to construct it -- which is exactly the
    # bypass these constraints exist to close.
    row = _flatten(_sample_metrics())
    for name in ScoringProfile.model_fields:
        row[name] = scoring.get(name)

    columns = ", ".join(row)
    placeholders = ", ".join(f"%({name})s" for name in row)
    with pytest.raises(psycopg.errors.CheckViolation):
        with database.cursor() as cursor:
            cursor.execute(
                f"INSERT INTO team_metrics ({columns}) VALUES ({placeholders})", row
            )


@requires_db
def test_a_single_match_may_still_carry_an_average(database):
    # The average of one value is itself -- only the variance-derived fields are
    # undefined. A constraint that also nulled average_score would discard a real
    # measurement.
    _insert_metrics(database, _sample_metrics(
        matches_scheduled=6, matches_used=1, average_score=42.0, score_stddev=None,
        consistency_rating=None, reliability_score=None,
        good_day_count=None, average_day_count=None, bad_day_count=None,
    ))
    with database.cursor() as cursor:
        cursor.execute(
            "SELECT average_score, score_stddev FROM team_metrics WHERE event_key = %s",
            (_S_EVENT,),
        )
        assert cursor.fetchall() == [(42.0, None)]


# ===========================================================================
# team_metrics: the defense/feeding invariants.
#
# These enforce CLAUDE.md's "defense/feeding scores = directly measured, NOT
# inferred from point output" at the storage layer.
# ===========================================================================


@requires_db
@pytest.mark.parametrize("defense_feeding,reason", [
    pytest.param(
        dict(defense_score=4.0, defense_observation_count=0, defense_agreement=None,
             defense_insufficient_data=True,
             feeding_score=None, feeding_observation_count=0, feeding_agreement=None,
             feeding_insufficient_data=True, contributing_sources=[]),
        "a score cannot coexist with its insufficient_data flag",
        id="score-while-insufficient",
    ),
    pytest.param(
        dict(defense_score=None, defense_observation_count=4, defense_agreement=0.9,
             defense_insufficient_data=False,
             feeding_score=None, feeding_observation_count=0, feeding_agreement=None,
             feeding_insufficient_data=True, contributing_sources=["human_scout"]),
        "sufficient data must produce a score",
        id="sufficient-without-score",
    ),
    pytest.param(
        dict(defense_score=4.0, defense_observation_count=0, defense_agreement=0.9,
             defense_insufficient_data=False,
             feeding_score=None, feeding_observation_count=0, feeding_agreement=None,
             feeding_insufficient_data=True, contributing_sources=["human_scout"]),
        "zero observations cannot yield a score",
        id="score-from-zero-observations",
    ),
    pytest.param(
        dict(defense_score=None, defense_observation_count=0, defense_agreement=None,
             defense_insufficient_data=True,
             feeding_score=None, feeding_observation_count=0, feeding_agreement=None,
             feeding_insufficient_data=True, contributing_sources=["human_scout"]),
        "no real data means no contributing source",
        id="sources-without-data",
    ),
    pytest.param(
        dict(defense_score=4.0, defense_observation_count=4, defense_agreement=0.9,
             defense_insufficient_data=False,
             feeding_score=None, feeding_observation_count=0, feeding_agreement=None,
             feeding_insufficient_data=True, contributing_sources=[]),
        "a real score must name where it came from",
        id="data-without-sources",
    ),
    pytest.param(
        dict(defense_score=6.0, defense_observation_count=4, defense_agreement=0.9,
             defense_insufficient_data=False,
             feeding_score=None, feeding_observation_count=0, feeding_agreement=None,
             feeding_insufficient_data=True, contributing_sources=["human_scout"]),
        "the rating scale is 0-5",
        id="score-above-scale",
    ),
    pytest.param(
        dict(defense_score=4.0, defense_observation_count=4, defense_agreement=1.5,
             defense_insufficient_data=False,
             feeding_score=None, feeding_observation_count=0, feeding_agreement=None,
             feeding_insufficient_data=True, contributing_sources=["human_scout"]),
        "agreement is a 0.0-1.0 confidence signal",
        id="agreement-above-one",
    ),
])
def test_the_defense_feeding_invariants_are_enforced_by_the_database(
    database, defense_feeding, reason
):
    row = _flatten(_sample_metrics())
    row.update(defense_feeding)

    columns = ", ".join(row)
    placeholders = ", ".join(f"%({name})s" for name in row)
    with pytest.raises(psycopg.errors.CheckViolation):
        with database.cursor() as cursor:
            cursor.execute(
                f"INSERT INTO team_metrics ({columns}) VALUES ({placeholders})", row
            )


@requires_db
def test_zero_is_a_storable_defense_score(database):
    # Same principle as the observation scale: 0 is "confirmed none observed", a
    # real aggregate result, and must not be confused with insufficient data.
    metrics = _sample_metrics()
    row = _flatten(metrics)
    row.update(defense_score=0.0, defense_observation_count=5, defense_agreement=1.0,
               defense_insufficient_data=False)
    columns = ", ".join(row)
    placeholders = ", ".join(f"%({name})s" for name in row)
    with database.cursor() as cursor:
        cursor.execute(f"INSERT INTO team_metrics ({columns}) VALUES ({placeholders})", row)
        cursor.execute(
            "SELECT defense_score, defense_insufficient_data FROM team_metrics "
            "WHERE event_key = %s",
            (_S_EVENT,),
        )
        assert cursor.fetchall() == [(0.0, False)]


@requires_db
def test_a_wholly_unscouted_team_is_storable(database):
    # The common case during an event's first hours: real scoring statistics, no
    # scouting yet. Both flags set, no scores, no sources.
    metrics = TeamMetrics(
        team_number=_S_TEAMS[1], event_key=_S_EVENT, season=9996, computed_at=_SUBMITTED_AT,
        scoring=ScoringProfile(matches_scheduled=12, matches_used=3, average_score=70.0,
                               score_stddev=5.0, consistency_rating=80.0,
                               reliability_score=25.0, good_day_count=1,
                               average_day_count=1, bad_day_count=1),
        defense_feeding=DefenseFeedingProfile(
            defense_observation_count=0, defense_insufficient_data=True,
            feeding_observation_count=0, feeding_insufficient_data=True,
        ),
    )
    _insert_metrics(database, metrics)

    with database.cursor() as cursor:
        cursor.execute(
            "SELECT * FROM team_metrics WHERE team_number = %s AND event_key = %s",
            (_S_TEAMS[1], _S_EVENT),
        )
        names = [column.name for column in cursor.description]
        row = dict(zip(names, cursor.fetchone()))

    assert _rebuild(row) == metrics
    assert row["contributing_sources"] == []
