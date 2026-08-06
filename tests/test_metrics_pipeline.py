"""Phase 3 Milestone 10: the metrics computation pipeline, end to end.

Mirrors tests/test_scouting_submission.py's real-Postgres integration style: a
seeded sentinel event/teams/matches, a `database` fixture that cleans up
before and after, and direct SQL assertions against team_metrics and
canonical_lineage, not just the returned objects.

Match lineage is landed for real (RawPayloadWriter + LineageStore, exactly as
sync_event would) rather than skipped, specifically so the lineage test has
something genuine to trace -- a match inserted by raw SQL alone (as most
other integration tests in this codebase do, since they don't need lineage)
would leave compute_event_team_metrics with nothing to find, which would
prove nothing about whether the tracing logic actually works.
"""

from __future__ import annotations

from datetime import datetime, timezone

import psycopg
import pytest

from data.config import Settings
from data.landing.raw_writer import RawPayloadRecord, RawPayloadWriter
from data.lineage import LineageEntry, LineageStore
from data.metrics.compute import (
    compute_event_team_metrics,
    compute_team_metrics,
    team_metrics_entity_key,
)
from data.metrics.submission import submit_human_scout_observation
from data.serving.repository import CanonicalRepository
from database.connection import Database, DatabaseConfig

# Sentinel namespace, distinct from every other module's (9990-9999).
_S_EVENT = "9990zzzmetrics"
_S_MATCH_1 = f"{_S_EVENT}_qm1"
_S_MATCH_2 = f"{_S_EVENT}_qm2"
_S_MATCH_3 = f"{_S_EVENT}_qm3"  # unplayed: scheduled but no score yet
_S_TEAM_SCOUTED = 990201   # plays 2 matches, has scouting observations
_S_TEAM_UNSCOUTED = 990202  # plays 1 match, zero observations
_S_TEAM_UNPLAYED = 990203   # rostered into the unplayed match only


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
        cursor.execute(
            "DELETE FROM canonical_lineage WHERE entity_type = 'match' AND entity_key LIKE %s", (f"{_S_EVENT}%",)
        )
        cursor.execute("DELETE FROM team_metrics WHERE event_key = %s", (_S_EVENT,))
        cursor.execute("DELETE FROM scouting_observations WHERE event_key = %s", (_S_EVENT,))
        cursor.execute(
            "DELETE FROM raw_source_payloads WHERE source = 'human_scout' AND source_object_id LIKE %s",
            (f"{_S_EVENT}%",),
        )
        cursor.execute(
            "DELETE FROM raw_source_payloads WHERE source = 'tba' AND source_object_id LIKE %s", (f"{_S_EVENT}%",)
        )
        cursor.execute(
            "DELETE FROM raw_source_payloads WHERE source = 'scoutradioz' AND source_object_id LIKE %s",
            (f"{_S_MATCH_2}%",),
        )
        cursor.execute(
            "DELETE FROM match_teams WHERE match_key IN (%s, %s, %s)", (_S_MATCH_1, _S_MATCH_2, _S_MATCH_3)
        )
        cursor.execute("DELETE FROM matches WHERE event_key = %s", (_S_EVENT,))
        cursor.execute(
            "DELETE FROM teams WHERE team_number = ANY(%s::int[])",
            ([_S_TEAM_SCOUTED, _S_TEAM_UNSCOUTED, _S_TEAM_UNPLAYED],),
        )
        cursor.execute("DELETE FROM events WHERE event_key = %s", (_S_EVENT,))
        cursor.execute("DELETE FROM pipeline_runs WHERE scope_key = %s", (_S_EVENT,))


def _land_match_with_lineage(database: Database, match_key: str, match_number: int) -> None:
    """Land a raw TBA match payload and record its lineage, exactly as sync_event would.

    So compute_event_team_metrics's lineage step has something real to trace
    -- a match inserted by plain SQL alone (as elsewhere in this test suite)
    would leave nothing in canonical_lineage to find.
    """
    writer = RawPayloadWriter(database)
    lineage = LineageStore(database)
    payload = {"key": match_key, "event_key": _S_EVENT, "match_number": match_number}
    writer.write(RawPayloadRecord(source="tba", source_object_type="match", source_object_id=match_key, payload=payload))
    with database.cursor() as cursor:
        cursor.execute(
            "SELECT id FROM raw_source_payloads WHERE source = 'tba' AND source_object_type = 'match' "
            "AND source_object_id = %s AND is_current",
            (match_key,),
        )
        (raw_id,) = cursor.fetchone()
    lineage.record([LineageEntry(entity_type="match", entity_key=match_key, raw_payload_id=raw_id, source="tba")])


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
            (_S_EVENT, 9990, "Sentinel Metrics Event"),
        )
        cursor.execute(
            "INSERT INTO teams (team_number, name) VALUES (%s, %s), (%s, %s), (%s, %s)",
            (_S_TEAM_SCOUTED, "Scouted", _S_TEAM_UNSCOUTED, "Unscouted", _S_TEAM_UNPLAYED, "Unplayed-only"),
        )
        cursor.execute(
            "INSERT INTO matches (match_key, event_key, season, competition_level, match_number, score_red, score_blue) "
            "VALUES (%s, %s, 9990, 'qualification', 1, 50, 30)",
            (_S_MATCH_1, _S_EVENT),
        )
        cursor.execute(
            "INSERT INTO matches (match_key, event_key, season, competition_level, match_number, score_red, score_blue) "
            "VALUES (%s, %s, 9990, 'qualification', 2, 60, 20)",
            (_S_MATCH_2, _S_EVENT),
        )
        cursor.execute(
            "INSERT INTO matches (match_key, event_key, season, competition_level, match_number, score_red, score_blue) "
            "VALUES (%s, %s, 9990, 'qualification', 3, NULL, NULL)",
            (_S_MATCH_3, _S_EVENT),
        )
        # _S_TEAM_SCOUTED: red in qm1 (scores 50), red in qm2 (scores 60) -> [50, 60].
        cursor.execute(
            "INSERT INTO match_teams (match_key, team_number, alliance_color) VALUES (%s, %s, 'red')",
            (_S_MATCH_1, _S_TEAM_SCOUTED),
        )
        cursor.execute(
            "INSERT INTO match_teams (match_key, team_number, alliance_color) VALUES (%s, %s, 'red')",
            (_S_MATCH_2, _S_TEAM_SCOUTED),
        )
        # _S_TEAM_UNSCOUTED: blue in qm1 only (scores 30).
        cursor.execute(
            "INSERT INTO match_teams (match_key, team_number, alliance_color) VALUES (%s, %s, 'blue')",
            (_S_MATCH_1, _S_TEAM_UNSCOUTED),
        )
        # _S_TEAM_UNPLAYED: rostered into qm3 only, which has no score yet.
        cursor.execute(
            "INSERT INTO match_teams (match_key, team_number, alliance_color) VALUES (%s, %s, 'red')",
            (_S_MATCH_3, _S_TEAM_UNPLAYED),
        )

    _land_match_with_lineage(db, _S_MATCH_1, 1)
    _land_match_with_lineage(db, _S_MATCH_2, 2)
    _land_match_with_lineage(db, _S_MATCH_3, 3)

    # Two observations for _S_TEAM_SCOUTED, from two different sources, via
    # the real submission path (so raw_payload_id is genuine, not faked).
    submit_human_scout_observation(
        {
            "match_key": _S_MATCH_1, "event_key": _S_EVENT, "team_number": _S_TEAM_SCOUTED,
            "scout_identifier": "alice", "defense_rating": 3, "submitted_at": "2026-08-05T15:00:00Z",
        },
        database=db,
    )
    # A real raw payload for the scoutradioz row too (not left NULL) -- so the
    # lineage test below has genuine raw_payload_id-backed provenance to find
    # for both sources, not just human_scout's.
    writer = RawPayloadWriter(db)
    scoutradioz_object_id = f"{_S_MATCH_2}:{_S_TEAM_SCOUTED}:bob"
    writer.write(RawPayloadRecord(
        source="scoutradioz", source_object_type="scouting_observation",
        source_object_id=scoutradioz_object_id,
        payload={"match_key": _S_MATCH_2, "team_key": f"frc{_S_TEAM_SCOUTED}", "qDefenseQuality": "10"},
    ))
    with db.cursor() as cursor:
        cursor.execute(
            "SELECT id FROM raw_source_payloads WHERE source = 'scoutradioz' "
            "AND source_object_type = 'scouting_observation' AND source_object_id = %s AND is_current",
            (scoutradioz_object_id,),
        )
        (scoutradioz_raw_id,) = cursor.fetchone()
        cursor.execute(
            "INSERT INTO scouting_observations "
            "(match_key, event_key, team_number, scout_identifier, defense_rating, source, submitted_at, raw_payload_id) "
            "VALUES (%s, %s, %s, %s, %s, 'scoutradioz', %s, %s)",
            (_S_MATCH_2, _S_EVENT, _S_TEAM_SCOUTED, "frc11:bob", 5, datetime.now(timezone.utc), scoutradioz_raw_id),
        )

    try:
        yield db
    finally:
        _cleanup(db)


# ---------------------------------------------------------------------------
# compute_team_metrics: hand-computed values, partial data, missing event
# ---------------------------------------------------------------------------


@requires_db
def test_compute_team_metrics_matches_hand_computed_values(database: Database) -> None:
    metrics = compute_team_metrics(database, _S_TEAM_SCOUTED, _S_EVENT)

    assert metrics.team_number == _S_TEAM_SCOUTED
    assert metrics.event_key == _S_EVENT
    assert metrics.season == 9990

    scoring = metrics.scoring
    assert scoring.matches_scheduled == 2
    assert scoring.matches_used == 2
    assert scoring.average_score == 55.0  # mean(50, 60)
    assert scoring.score_stddev == 5.0  # population stddev of [50, 60]
    assert scoring.reliability_score == 100.0  # 2 used / 2 scheduled

    defense_feeding = metrics.defense_feeding
    assert defense_feeding.defense_observation_count == 2
    assert defense_feeding.defense_score == 4.0  # median(3, 5)
    assert not defense_feeding.defense_insufficient_data
    assert defense_feeding.feeding_insufficient_data
    assert defense_feeding.contributing_sources == ["human_scout", "scoutradioz"]


@requires_db
def test_compute_team_metrics_handles_zero_observations_without_crashing(database: Database) -> None:
    # The milestone's own named success criterion: matches but no
    # observations produces a complete object, never a crash.
    metrics = compute_team_metrics(database, _S_TEAM_UNSCOUTED, _S_EVENT)

    assert metrics.scoring.matches_scheduled == 1
    assert metrics.scoring.average_score == 30.0
    assert metrics.defense_feeding.defense_insufficient_data
    assert metrics.defense_feeding.feeding_insufficient_data
    assert metrics.defense_feeding.contributing_sources == []


@requires_db
def test_compute_team_metrics_handles_an_unplayed_match(database: Database) -> None:
    metrics = compute_team_metrics(database, _S_TEAM_UNPLAYED, _S_EVENT)

    assert metrics.scoring.matches_scheduled == 1
    assert metrics.scoring.matches_used == 0
    assert metrics.scoring.average_score is None


@requires_db
def test_compute_team_metrics_raises_for_a_nonexistent_event(database: Database) -> None:
    with pytest.raises(ValueError, match="9990zzznonexistent"):
        compute_team_metrics(database, _S_TEAM_SCOUTED, "9990zzznonexistent")


@requires_db
def test_compute_team_metrics_handles_a_team_never_rostered_at_the_event(database: Database) -> None:
    # A team with zero matches AND zero observations at a real, existing event
    # -- more extreme than the named "matches but no observations" criterion,
    # and just as required to produce a complete object, never a crash.
    never_rostered_team = 990299
    metrics = compute_team_metrics(database, never_rostered_team, _S_EVENT)

    assert metrics.scoring.matches_scheduled == 0
    assert metrics.scoring.matches_used == 0
    assert metrics.scoring.average_score is None
    assert metrics.defense_feeding.defense_insufficient_data
    assert metrics.defense_feeding.feeding_insufficient_data


def test_team_metrics_entity_key_format():
    assert team_metrics_entity_key(1114, "2026casj") == "1114_2026casj"


# ---------------------------------------------------------------------------
# compute_event_team_metrics: persistence, idempotency, lineage
# ---------------------------------------------------------------------------


@requires_db
def test_compute_event_team_metrics_persists_every_rostered_team(database: Database) -> None:
    result = compute_event_team_metrics(_S_EVENT, database=database)

    assert result.event_key == _S_EVENT
    assert result.teams_computed == 3

    with database.cursor() as cursor:
        cursor.execute(
            "SELECT team_number, average_score, defense_score FROM team_metrics "
            "WHERE event_key = %s ORDER BY team_number",
            (_S_EVENT,),
        )
        rows = cursor.fetchall()

    assert rows == [
        (_S_TEAM_SCOUTED, 55.0, 4.0),
        (_S_TEAM_UNSCOUTED, 30.0, None),
        (_S_TEAM_UNPLAYED, None, None),
    ]


@requires_db
def test_load_team_metrics_round_trips_every_column_correctly(database: Database) -> None:
    # A full Phase 3 audit's own check on CanonicalRepository._upsert_team_metrics:
    # a 22-column INSERT is exactly the shape of bug where two adjacent columns
    # (e.g. consistency_rating/reliability_score, both floats in a similar
    # range) could silently swap without crashing and without any existing
    # test noticing, since most tests only read back a handful of columns.
    # This compares every single column against the in-memory object that
    # produced it, not just the few already spot-checked elsewhere.
    metrics = compute_team_metrics(database, _S_TEAM_SCOUTED, _S_EVENT)
    CanonicalRepository(database).load_team_metrics(metrics)

    with database.cursor() as cursor:
        cursor.execute(
            """
            SELECT team_number, event_key, season, matches_scheduled, matches_used,
                   average_score, score_stddev, consistency_rating, reliability_score,
                   good_day_count, average_day_count, bad_day_count,
                   defense_score, defense_observation_count, defense_agreement, defense_insufficient_data,
                   feeding_score, feeding_observation_count, feeding_agreement, feeding_insufficient_data,
                   contributing_sources
            FROM team_metrics WHERE team_number = %s AND event_key = %s
            """,
            (_S_TEAM_SCOUTED, _S_EVENT),
        )
        row = cursor.fetchone()

    scoring, defense_feeding = metrics.scoring, metrics.defense_feeding
    assert row == (
        metrics.team_number, metrics.event_key, metrics.season,
        scoring.matches_scheduled, scoring.matches_used,
        scoring.average_score, scoring.score_stddev, scoring.consistency_rating, scoring.reliability_score,
        scoring.good_day_count, scoring.average_day_count, scoring.bad_day_count,
        defense_feeding.defense_score, defense_feeding.defense_observation_count,
        defense_feeding.defense_agreement, defense_feeding.defense_insufficient_data,
        defense_feeding.feeding_score, defense_feeding.feeding_observation_count,
        defense_feeding.feeding_agreement, defense_feeding.feeding_insufficient_data,
        defense_feeding.contributing_sources,
    )


@requires_db
def test_compute_event_team_metrics_is_idempotent(database: Database) -> None:
    first = compute_event_team_metrics(_S_EVENT, database=database)
    second = compute_event_team_metrics(_S_EVENT, database=database)

    assert first.teams_computed == second.teams_computed == 3

    with database.cursor() as cursor:
        cursor.execute("SELECT COUNT(*) FROM team_metrics WHERE event_key = %s", (_S_EVENT,))
        (count,) = cursor.fetchone()
        cursor.execute(
            "SELECT team_number, average_score, defense_score, contributing_sources FROM team_metrics "
            "WHERE event_key = %s ORDER BY team_number",
            (_S_EVENT,),
        )
        rows = cursor.fetchall()

    assert count == 3  # no duplicate rows from re-running
    assert rows == [
        (_S_TEAM_SCOUTED, 55.0, 4.0, ["human_scout", "scoutradioz"]),
        (_S_TEAM_UNSCOUTED, 30.0, None, []),
        (_S_TEAM_UNPLAYED, None, None, []),
    ]
    # computed_at is deliberately NOT asserted identical: it is this table's
    # last-computed timestamp by design (mirrors team_event_stats.last_updated),
    # and is expected to advance on every recompute. "Re-running produces
    # identical stored values" means the computed METRICS, not that bookkeeping
    # timestamp -- confirmed the metric values above stayed exactly the same.


@requires_db
def test_compute_event_team_metrics_traces_lineage_to_matches_and_observations(database: Database) -> None:
    result = compute_event_team_metrics(_S_EVENT, database=database)
    assert result.lineage_recorded > 0

    key = team_metrics_entity_key(_S_TEAM_SCOUTED, _S_EVENT)
    with database.cursor() as cursor:
        cursor.execute(
            "SELECT source FROM canonical_lineage WHERE entity_type = 'team_metrics' AND entity_key = %s "
            "ORDER BY source",
            (key,),
        )
        sources = [row[0] for row in cursor.fetchall()]

    # Two matches (both "tba") plus two observations ("human_scout", "scoutradioz").
    assert sources.count("tba") == 2
    assert "human_scout" in sources
    assert "scoutradioz" in sources

    # Every traced raw_payload_id genuinely exists and is this team's own data.
    with database.cursor() as cursor:
        cursor.execute(
            "SELECT raw.source_object_type, raw.source_object_id FROM canonical_lineage lin "
            "JOIN raw_source_payloads raw ON raw.id = lin.raw_payload_id "
            "WHERE lin.entity_type = 'team_metrics' AND lin.entity_key = %s",
            (key,),
        )
        traced = set(cursor.fetchall())
    assert ("match", _S_MATCH_1) in traced
    assert ("match", _S_MATCH_2) in traced


@requires_db
def test_compute_event_team_metrics_traces_lineage_to_an_unplayed_scheduled_match(database: Database) -> None:
    # Documented design decision, directly verified rather than assumed: an
    # unplayed-but-scheduled match still feeds matches_scheduled (and
    # therefore reliability_score), so its lineage must be traced too, not
    # only matches that contributed a score.
    compute_event_team_metrics(_S_EVENT, database=database)

    key = team_metrics_entity_key(_S_TEAM_UNPLAYED, _S_EVENT)
    with database.cursor() as cursor:
        cursor.execute(
            "SELECT raw.source_object_id FROM canonical_lineage lin "
            "JOIN raw_source_payloads raw ON raw.id = lin.raw_payload_id "
            "WHERE lin.entity_type = 'team_metrics' AND lin.entity_key = %s AND raw.source_object_type = 'match'",
            (key,),
        )
        traced_matches = {row[0] for row in cursor.fetchall()}

    assert traced_matches == {_S_MATCH_3}


@requires_db
def test_compute_event_team_metrics_lineage_is_not_duplicated_on_rerun(database: Database) -> None:
    compute_event_team_metrics(_S_EVENT, database=database)
    with database.cursor() as cursor:
        cursor.execute(
            "SELECT COUNT(*) FROM canonical_lineage WHERE entity_type = 'team_metrics' AND entity_key LIKE %s",
            (f"%{_S_EVENT}",),
        )
        (first_count,) = cursor.fetchone()

    compute_event_team_metrics(_S_EVENT, database=database)
    with database.cursor() as cursor:
        cursor.execute(
            "SELECT COUNT(*) FROM canonical_lineage WHERE entity_type = 'team_metrics' AND entity_key LIKE %s",
            (f"%{_S_EVENT}",),
        )
        (second_count,) = cursor.fetchone()

    assert first_count > 0
    assert second_count == first_count  # ON CONFLICT DO NOTHING: no duplicate lineage rows


@requires_db
def test_compute_event_team_metrics_records_a_pipeline_run(database: Database) -> None:
    result = compute_event_team_metrics(_S_EVENT, database=database)

    with database.cursor() as cursor:
        cursor.execute(
            "SELECT pipeline_name, source, scope_key, status FROM pipeline_runs WHERE id = %s",
            (result.run_id,),
        )
        row = cursor.fetchone()

    assert row == ("metrics_compute", None, _S_EVENT, "succeeded")


@requires_db
def test_compute_event_team_metrics_removes_a_stale_row_for_a_team_no_longer_rostered(
    database: Database,
) -> None:
    """Found during a full Phase 3 audit: a team a schedule correction removes
    from every match at an event must not keep a forever-stale team_metrics
    row. Simulates the "before" state directly (a team_metrics row for a team
    that was never actually added to match_teams in this fixture), then
    confirms compute_event_team_metrics cleans it up, including its lineage.
    """
    orphan_team = 990298
    with database.cursor() as cursor:
        cursor.execute("INSERT INTO teams (team_number, name) VALUES (%s, %s)", (orphan_team, "Orphan"))
        cursor.execute(
            "INSERT INTO team_metrics ("
            "  team_number, event_key, season, computed_at, matches_scheduled, matches_used,"
            "  defense_observation_count, defense_insufficient_data,"
            "  feeding_observation_count, feeding_insufficient_data"
            ") VALUES (%s, %s, 9990, NOW(), 3, 3, 0, TRUE, 0, TRUE)",
            (orphan_team, _S_EVENT),
        )
        entity_key = team_metrics_entity_key(orphan_team, _S_EVENT)
        cursor.execute(
            "INSERT INTO canonical_lineage (entity_type, entity_key, raw_payload_id, source) "
            "SELECT 'team_metrics', %s, id, 'tba' FROM raw_source_payloads LIMIT 1",
            (entity_key,),
        )

    try:
        result = compute_event_team_metrics(_S_EVENT, database=database)

        with database.cursor() as cursor:
            cursor.execute(
                "SELECT 1 FROM team_metrics WHERE team_number = %s AND event_key = %s", (orphan_team, _S_EVENT)
            )
            assert cursor.fetchone() is None  # the stale row is gone
            cursor.execute(
                "SELECT 1 FROM canonical_lineage WHERE entity_type = 'team_metrics' AND entity_key = %s",
                (entity_key,),
            )
            assert cursor.fetchone() is None  # its lineage went with it

        # The three real, still-rostered teams were computed normally, unaffected.
        assert result.teams_computed == 3
        assert result.orphaned_removed == 1
    finally:
        with database.cursor() as cursor:
            cursor.execute("DELETE FROM canonical_lineage WHERE entity_key = %s", (entity_key,))
            cursor.execute(
                "DELETE FROM team_metrics WHERE team_number = %s AND event_key = %s", (orphan_team, _S_EVENT)
            )
            cursor.execute("DELETE FROM teams WHERE team_number = %s", (orphan_team,))
