from __future__ import annotations

from typing import Any

import pytest

from data import pipeline
from data.clients.schemas import EventSummary, Match, StatboticsTeamEventMetrics, TeamInfo
from data.clients.source_connector import SourceResponse
from data.config import Settings
from data.orchestrator import PipelineRunRecorder, WatermarkStore, sync_event
from data.pipeline import PendingPayload
from data.serving.repository import CanonicalRepository
from database.connection import Database, DatabaseConfig

# ---------------------------------------------------------------------------
# Sentinel fixtures. Season 9998 / event "9998zzzpipe" so integration runs can
# never collide with real competition data.
# ---------------------------------------------------------------------------

S_EVENT = "9998zzzpipe"
S_TEAMS = [998001, 998002, 998003, 998004, 998005, 998006]
S_TEAM_KEYS = [f"frc{number}" for number in S_TEAMS]
S_MATCH = f"{S_EVENT}_qm1"


def raw_event() -> dict[str, Any]:
    return {
        "key": S_EVENT, "name": "Pipeline Sentinel Regional", "event_code": "zzzpipe",
        "year": 9998, "start_date": "9998-03-14", "end_date": "9998-03-16",
        "city": "San Jose", "state_prov": "CA", "country": "USA",
    }


def raw_teams() -> list[dict[str, Any]]:
    return [
        {
            "key": f"frc{number}", "team_number": number, "nickname": f"Sentinel {number}",
            "city": "San Jose", "state_prov": "CA", "country": "USA", "rookie_year": 2001,
        }
        for number in S_TEAMS
    ]


def raw_match(**overrides: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "key": S_MATCH, "event_key": S_EVENT, "comp_level": "qm",
        "set_number": 1, "match_number": 1, "time": 1700000000,
        "alliances": {
            "red": {"score": 100, "team_keys": S_TEAM_KEYS[:3]},
            "blue": {"score": 90, "team_keys": S_TEAM_KEYS[3:]},
        },
        "winning_alliance": "red",
    }
    payload.update(overrides)
    return payload


def raw_team_event(team_number: int) -> dict[str, Any]:
    """Statbotics's real nested /team_event shape.

    Nested exactly as their response serializer emits it. The flat shape this
    fixture used originally was invented, and mocking it is what let a wrong
    client contract survive undetected; landing the real shape here means the
    end-to-end test proves a genuine Statbotics payload reaches team_event_stats.
    """
    return {
        "team": team_number, "year": 9998, "event": S_EVENT,
        "epa": {
            "total_points": 50.0,
            "breakdown": {"auto_points": 10.0, "teleop_points": 30.0, "endgame_points": 10.0},
            "stats": {"mean": 48.0},
        },
        "record": {
            "qual": {"wins": 6, "losses": 2, "ties": 0, "count": 8},
            "total": {"wins": 8, "losses": 2, "ties": 0, "count": 10},
        },
    }


class FakeTBAClient:
    """A TBAClient stand-in returning the same validated models the real one does.

    Deliberately returns Pydantic models rather than raw dicts: the pipeline
    round-trips those models back into source-shaped payloads, so a test using
    plain dicts would bypass exactly the conversion most likely to break.
    """

    def __init__(
        self,
        *,
        event: dict[str, Any] | None = None,
        matches: list[dict[str, Any]] | None = None,
        teams: list[dict[str, Any]] | None = None,
    ) -> None:
        self.event = event if event is not None else raw_event()
        self.matches = matches if matches is not None else [raw_match()]
        self.teams = teams if teams is not None else raw_teams()
        self.team_info_calls: list[int] = []

    def fetch_event(self, event_key: str) -> SourceResponse[EventSummary]:
        return SourceResponse(self.event, EventSummary.model_validate(self.event))

    def fetch_event_matches(self, event_key: str) -> list[SourceResponse[Match]]:
        return [SourceResponse(p, Match.model_validate(p)) for p in self.matches]

    def fetch_event_teams(self, event_key: str) -> list[SourceResponse[TeamInfo]]:
        return [SourceResponse(p, TeamInfo.model_validate(p)) for p in self.teams]

    def fetch_team_info(self, team_number: int) -> SourceResponse[TeamInfo]:
        self.team_info_calls.append(team_number)
        payload = {
            "key": f"frc{team_number}", "team_number": team_number,
            "nickname": f"Backfilled {team_number}",
        }
        return SourceResponse(payload, TeamInfo.model_validate(payload))


class FakeStatboticsClient:
    """A StatboticsClient stand-in, optionally failing for specific teams."""

    def __init__(self, *, fail_for: set[int] | None = None) -> None:
        self.fail_for = fail_for or set()
        self.calls: list[tuple[int, str]] = []

    def fetch_team_event_metrics(
        self, team_number: int, event_key: str
    ) -> SourceResponse[StatboticsTeamEventMetrics]:
        self.calls.append((team_number, event_key))
        if team_number in self.fail_for:
            raise RuntimeError(f"simulated Statbotics 404 for team {team_number}")
        payload = raw_team_event(team_number)
        return SourceResponse(payload, StatboticsTeamEventMetrics.model_validate(payload))


def batch_by_type(batches, object_type: str):
    return next(batch for batch in batches if batch.object_type == object_type)


# ===========================================================================
# Extraction: no database, no network.
# ===========================================================================


def test_extract_event_produces_one_batch_per_object_type():
    tba = FakeTBAClient()
    result = pipeline.extract_event(S_EVENT, tba=tba, statbotics=FakeStatboticsClient())

    assert [(b.source, b.object_type) for b in result.batches] == [
        ("tba", "event"), ("tba", "team"), ("tba", "match"), ("statbotics", "team_event"),
    ]
    assert batch_by_type(result.batches, "event").object_ids == [S_EVENT]
    assert batch_by_type(result.batches, "team").object_ids == S_TEAM_KEYS
    assert batch_by_type(result.batches, "match").object_ids == [S_MATCH]
    assert batch_by_type(result.batches, "team_event").object_ids == [f"{n}_{S_EVENT}" for n in S_TEAMS]
    assert result.errors == []


def test_extract_event_lands_payloads_in_source_wire_shape():
    # The staging validators/normalizers read TBA's real field names, so the
    # round-trip through the client models must restore them ("year", not
    # "season"; "comp_level", not "competition_level"; nested alliances).
    result = pipeline.extract_event(S_EVENT, tba=FakeTBAClient())

    event_payload = batch_by_type(result.batches, "event").records[0].payload
    assert event_payload["year"] == 9998
    assert event_payload["state_prov"] == "CA"  # additive EventSummary field survives
    assert event_payload["start_date"] == "9998-03-14"  # JSON-serializable for JSONB

    match_payload = batch_by_type(result.batches, "match").records[0].payload
    assert match_payload["comp_level"] == "qm"
    assert match_payload["time"] == 1700000000
    assert match_payload["alliances"]["red"]["team_keys"] == S_TEAM_KEYS[:3]

    # And each round-tripped payload actually normalizes.
    assert pipeline.normalize_event("tba", event_payload).season == 9998
    assert pipeline.normalize_match("tba", match_payload).red_teams == S_TEAMS[:3]


def test_extract_event_backfills_teams_missing_from_the_event_team_list():
    # Team 998006 plays a match but TBA's event team list omits it; without the
    # backfill the match_teams foreign key would fail at load time.
    tba = FakeTBAClient(teams=raw_teams()[:5])
    result = pipeline.extract_event(S_EVENT, tba=tba)

    assert tba.team_info_calls == [998006]
    assert batch_by_type(result.batches, "team").object_ids == S_TEAM_KEYS
    assert result.errors == []


def test_extract_event_records_backfill_failure_without_aborting():
    class NoTeamLookupTBAClient(FakeTBAClient):
        def fetch_team_info(self, team_number: int) -> SourceResponse[TeamInfo]:
            raise RuntimeError("simulated team lookup failure")

    result = pipeline.extract_event(S_EVENT, tba=NoTeamLookupTBAClient(teams=raw_teams()[:5]))

    assert len(batch_by_type(result.batches, "team").records) == 5
    assert any("Roster backfill failed for frc998006" in error for error in result.errors)


def test_extract_event_treats_statbotics_failure_as_non_fatal():
    statbotics = FakeStatboticsClient(fail_for={998003})
    result = pipeline.extract_event(S_EVENT, tba=FakeTBAClient(), statbotics=statbotics)

    team_event = batch_by_type(result.batches, "team_event")
    assert len(team_event.records) == 5  # the other five still extracted
    assert f"{998003}_{S_EVENT}" not in team_event.object_ids
    assert len(result.errors) == 1
    assert "998003" in result.errors[0]


def test_extract_event_without_statbotics_omits_team_event_batch():
    result = pipeline.extract_event(S_EVENT, tba=FakeTBAClient(), statbotics=None)
    assert [b.object_type for b in result.batches] == ["event", "team", "match"]


# ===========================================================================
# Staging: contiguous-prefix watermark policy, no database.
# ===========================================================================


def test_stage_batch_normalizes_pending_payloads_and_advances_watermark():
    pending = [
        PendingPayload(11, f"frc{S_TEAMS[0]}", raw_teams()[0]),
        PendingPayload(12, f"frc{S_TEAMS[1]}", raw_teams()[1]),
    ]
    staged = pipeline.stage_batch("tba", "team", pending, after_raw_id=10)

    assert [team.team_number for team in staged.entities] == S_TEAMS[:2]
    assert staged.watermark_id == 12
    assert staged.skipped == []


def test_stage_batch_stops_watermark_at_first_invalid_payload_but_keeps_loading():
    # A duplicate team on one alliance passes the client model but fails the
    # staging validator -- a realistically-malformed payload, not a synthetic one.
    invalid = raw_match(key=f"{S_EVENT}_qm2", match_number=2)
    invalid["alliances"]["red"]["team_keys"] = [S_TEAM_KEYS[0], S_TEAM_KEYS[0], S_TEAM_KEYS[2]]
    pending = [
        PendingPayload(21, S_MATCH, raw_match()),
        PendingPayload(22, f"{S_EVENT}_qm2", invalid),
        PendingPayload(23, f"{S_EVENT}_qm3", raw_match(key=f"{S_EVENT}_qm3", match_number=3)),
    ]
    staged = pipeline.stage_batch("tba", "match", pending, after_raw_id=20)

    assert [match.match_key for match in staged.entities] == [S_MATCH, f"{S_EVENT}_qm3"]
    assert staged.watermark_id == 21  # stops short of the bad record, not at 23
    assert [record.raw_id for record in staged.skipped] == [22]
    assert "cannot appear twice" in staged.skipped[0].reason


def test_stage_batch_with_nothing_pending_leaves_watermark_untouched():
    staged = pipeline.stage_batch("tba", "match", [], after_raw_id=42)
    assert staged.entities == []
    assert staged.watermark_id == 42

    fresh = pipeline.stage_batch("tba", "match", [], after_raw_id=0)
    assert fresh.watermark_id is None  # never synced, nothing to record


# ===========================================================================
# Integration: real pipeline_runs / source_watermarks / canonical behaviour.
# Auto-skips when no PostgreSQL is reachable via the configured DATABASE_URL.
# ===========================================================================


def _database_available() -> bool:
    try:
        import psycopg

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
        cursor.execute("DELETE FROM match_teams WHERE match_key LIKE %s", (f"{S_EVENT}%",))
        cursor.execute("DELETE FROM team_event_stats WHERE event_key = %s", (S_EVENT,))
        cursor.execute("DELETE FROM matches WHERE event_key = %s", (S_EVENT,))
        cursor.execute("DELETE FROM teams WHERE team_number = ANY(%s::int[])", (S_TEAMS,))
        cursor.execute("DELETE FROM events WHERE event_key = %s", (S_EVENT,))
        cursor.execute("DELETE FROM raw_source_payloads WHERE source_object_id LIKE %s", (f"%{S_EVENT}%",))
        cursor.execute(
            "DELETE FROM raw_source_payloads WHERE source_object_id = ANY(%s::text[])", (S_TEAM_KEYS,)
        )
        cursor.execute("DELETE FROM pipeline_runs WHERE scope_key = %s", (S_EVENT,))
        cursor.execute("DELETE FROM source_watermarks WHERE scope_key = %s", (S_EVENT,))


@pytest.fixture
def database() -> Database:
    from database.migrate import run_migrations

    settings = Settings()
    run_migrations(settings)
    db = Database(DatabaseConfig(settings.database_url))
    _cleanup(db)
    try:
        yield db
    finally:
        _cleanup(db)


def _run(database: Database, **kwargs: Any):
    kwargs.setdefault("tba", FakeTBAClient())
    kwargs.setdefault("statbotics", FakeStatboticsClient())
    return sync_event(S_EVENT, database=database, **kwargs)


def _scalar(database: Database, sql: str, params: tuple = ()) -> Any:
    with database.cursor() as cursor:
        cursor.execute(sql, params)
        row = cursor.fetchone()
    return None if row is None else row[0]


def _watermarks(database: Database) -> dict[tuple[str, str], str | None]:
    with database.cursor() as cursor:
        cursor.execute(
            "SELECT source, object_type, watermark_value FROM source_watermarks WHERE scope_key = %s",
            (S_EVENT,),
        )
        return {(row[0], row[1]): row[2] for row in cursor.fetchall()}


def _runs(database: Database) -> list[tuple]:
    with database.cursor() as cursor:
        cursor.execute(
            """
            SELECT id, pipeline_name, source, scope_key, status, records_processed,
                   error_message, stage_counts, finished_at
            FROM pipeline_runs WHERE scope_key = %s ORDER BY id
            """,
            (S_EVENT,),
        )
        return cursor.fetchall()


@requires_db
def test_sync_event_runs_end_to_end(database):
    result = _run(database)

    # Landing: every extracted payload is new on a first run.
    assert result.landed == {
        "tba.event": 1, "tba.team": 6, "tba.match": 1, "statbotics.team_event": 6,
    }
    # Serving: canonical rows for all four entity types.
    assert result.loaded == {"teams": 6, "events": 1, "matches": 1, "team_event_stats": 6}
    assert result.skipped == []
    assert result.extraction_errors == []

    assert _scalar(database, "SELECT COUNT(*) FROM teams WHERE team_number = ANY(%s::int[])", (S_TEAMS,)) == 6
    assert _scalar(database, "SELECT name FROM events WHERE event_key = %s", (S_EVENT,)) == "Pipeline Sentinel Regional"
    assert _scalar(database, "SELECT score_red FROM matches WHERE match_key = %s", (S_MATCH,)) == 100
    assert _scalar(database, "SELECT COUNT(*) FROM match_teams WHERE match_key = %s", (S_MATCH,)) == 6
    assert _scalar(
        database,
        "SELECT matches_played FROM team_event_stats WHERE team_number = %s AND event_key = %s",
        (S_TEAMS[0], S_EVENT),
    ) == 10  # 8 + 2 + 0, derived by the staging layer

    # Run bookkeeping.
    runs = _runs(database)
    assert len(runs) == 1
    run_id, name, source, scope_key, status, records, error, stage_counts, finished_at = runs[0]
    assert (run_id, name, source, scope_key, status) == (result.run_id, "event_sync", "tba", S_EVENT, "succeeded")
    assert records == 14  # 6 teams + 1 event + 1 match + 6 team_event_stats
    assert error is None
    assert finished_at is not None
    assert stage_counts["landed"] == result.landed
    assert stage_counts["loaded"] == result.loaded
    assert stage_counts["skipped"] == []

    # Watermarks: one per (source, object_type), each a real raw id.
    marks = _watermarks(database)
    assert set(marks) == {("tba", "event"), ("tba", "team"), ("tba", "match"), ("statbotics", "team_event")}
    assert all(value is not None and int(value) > 0 for value in marks.values())
    max_raw_id = _scalar(database, "SELECT MAX(id) FROM raw_source_payloads")
    assert max(int(value) for value in marks.values()) <= max_raw_id


@requires_db
def test_rerunning_an_unchanged_sync_does_no_work_and_creates_no_duplicates(database):
    first = _run(database)
    marks_after_first = _watermarks(database)

    second = _run(database)

    # Nothing new landed, so nothing was above the watermark to reprocess:
    # the staging and serving stages are true no-ops, not deduplicated writes.
    assert second.landed == {"tba.event": 0, "tba.team": 0, "tba.match": 0, "statbotics.team_event": 0}
    assert second.loaded == {"teams": 0, "events": 0, "matches": 0, "team_event_stats": 0}
    assert second.records_loaded == 0
    assert second.run_id != first.run_id

    # No duplicate canonical rows.
    assert _scalar(database, "SELECT COUNT(*) FROM teams WHERE team_number = ANY(%s::int[])", (S_TEAMS,)) == 6
    assert _scalar(database, "SELECT COUNT(*) FROM matches WHERE event_key = %s", (S_EVENT,)) == 1
    assert _scalar(database, "SELECT COUNT(*) FROM match_teams WHERE match_key = %s", (S_MATCH,)) == 6
    assert _scalar(database, "SELECT COUNT(*) FROM team_event_stats WHERE event_key = %s", (S_EVENT,)) == 6
    # No duplicate raw rows either (the landing layer deduplicated them).
    assert _scalar(
        database, "SELECT COUNT(*) FROM raw_source_payloads WHERE source_object_id = %s", (S_MATCH,)
    ) == 1

    # Watermarks held their position, and both runs are recorded as succeeded.
    assert _watermarks(database) == marks_after_first
    runs = _runs(database)
    assert [row[4] for row in runs] == ["succeeded", "succeeded"]
    assert runs[1][5] == 0  # records_processed


@requires_db
def test_changed_payload_advances_watermark_and_updates_canonical_row(database):
    _run(database)
    match_mark_before = int(_watermarks(database)[("tba", "match")])

    # A corrected score: a genuinely different payload for the same match.
    corrected = FakeTBAClient(matches=[raw_match(alliances={
        "red": {"score": 111, "team_keys": S_TEAM_KEYS[:3]},
        "blue": {"score": 90, "team_keys": S_TEAM_KEYS[3:]},
    })])
    second = _run(database, tba=corrected)

    assert second.landed["tba.match"] == 1  # new version landed
    assert second.landed["tba.team"] == 0  # unchanged payloads still skipped
    assert second.loaded == {"teams": 0, "events": 0, "matches": 1, "team_event_stats": 0}

    assert int(_watermarks(database)[("tba", "match")]) > match_mark_before
    assert _scalar(database, "SELECT score_red FROM matches WHERE match_key = %s", (S_MATCH,)) == 111
    assert _scalar(database, "SELECT COUNT(*) FROM matches WHERE event_key = %s", (S_EVENT,)) == 1
    assert _scalar(database, "SELECT COUNT(*) FROM match_teams WHERE match_key = %s", (S_MATCH,)) == 6
    # Both payload versions retained in the landing layer; only one is current.
    assert _scalar(
        database, "SELECT COUNT(*) FROM raw_source_payloads WHERE source_object_id = %s", (S_MATCH,)
    ) == 2
    assert _scalar(
        database,
        "SELECT COUNT(*) FROM raw_source_payloads WHERE source_object_id = %s AND is_current",
        (S_MATCH,),
    ) == 1


@requires_db
def test_failure_mid_run_records_a_failed_run_and_leaves_watermarks_untouched(database):
    class FailingRepository(CanonicalRepository):
        """Loads teams and events, then fails on matches -- a mid-load failure."""

        def load_matches(self, matches):
            raise RuntimeError("simulated serving-stage failure")

    with pytest.raises(RuntimeError, match="simulated serving-stage failure"):
        _run(database, repository=FailingRepository(database))

    # No watermark was created, so the next run reprocesses this ground.
    assert _watermarks(database) == {}

    runs = _runs(database)
    assert len(runs) == 1
    assert runs[0][4] == "failed"
    assert "simulated serving-stage failure" in runs[0][6]
    assert runs[0][8] is not None  # finished_at still stamped

    # The teams/events written before the failure are intact, and a clean rerun
    # converges rather than duplicating them.
    assert _scalar(database, "SELECT COUNT(*) FROM teams WHERE team_number = ANY(%s::int[])", (S_TEAMS,)) == 6
    result = _run(database)
    assert result.loaded == {"teams": 6, "events": 1, "matches": 1, "team_event_stats": 6}
    assert _scalar(database, "SELECT COUNT(*) FROM teams WHERE team_number = ANY(%s::int[])", (S_TEAMS,)) == 6
    assert _watermarks(database)[("tba", "match")] is not None


@requires_db
def test_failure_before_landing_leaves_a_failed_run_and_no_raw_rows(database):
    class ExplodingTBAClient(FakeTBAClient):
        def fetch_event_matches(self, event_key):
            raise RuntimeError("simulated extraction failure")

    with pytest.raises(RuntimeError, match="simulated extraction failure"):
        _run(database, tba=ExplodingTBAClient())

    assert _watermarks(database) == {}
    assert _scalar(
        database, "SELECT COUNT(*) FROM raw_source_payloads WHERE source_object_id LIKE %s", (f"%{S_EVENT}%",)
    ) == 0
    runs = _runs(database)
    assert runs[0][4] == "failed"
    assert "simulated extraction failure" in runs[0][6]


@requires_db
def test_invalid_payload_is_skipped_and_retried_while_good_records_load(database):
    bad = raw_match(key=f"{S_EVENT}_qm1", match_number=1)
    bad["alliances"]["red"]["team_keys"] = [S_TEAM_KEYS[0], S_TEAM_KEYS[0], S_TEAM_KEYS[2]]
    good = raw_match(key=f"{S_EVENT}_qm2", match_number=2)
    tba = FakeTBAClient(matches=[bad, good])

    result = _run(database, tba=tba)

    # The run succeeds: one malformed record must not block the event's others.
    assert [record.source_object_id for record in result.skipped] == [f"{S_EVENT}_qm1"]
    assert result.loaded["matches"] == 1
    assert _scalar(database, "SELECT COUNT(*) FROM matches WHERE event_key = %s", (S_EVENT,)) == 1
    assert _scalar(database, "SELECT match_key FROM matches WHERE event_key = %s", (S_EVENT,)) == f"{S_EVENT}_qm2"

    runs = _runs(database)
    assert runs[0][4] == "succeeded"
    assert len(runs[0][7]["skipped"]) == 1

    # The match watermark stopped short of the bad record, so the bad payload is
    # retried (still skipped) rather than silently abandoned.
    assert _watermarks(database)[("tba", "match")] is None
    second = _run(database, tba=FakeTBAClient(matches=[bad, good]))
    assert [record.source_object_id for record in second.skipped] == [f"{S_EVENT}_qm1"]
    assert second.landed["tba.match"] == 0  # nothing new landed; it was re-read from the landing layer
    assert second.loaded["matches"] == 1  # the good record re-upserted, not duplicated
    assert _scalar(database, "SELECT COUNT(*) FROM matches WHERE event_key = %s", (S_EVENT,)) == 1

    # And once the source corrects the payload, it flows through and the
    # watermark advances past it.
    fixed = raw_match(key=f"{S_EVENT}_qm1", match_number=1)
    third = _run(database, tba=FakeTBAClient(matches=[fixed, good]))
    assert third.skipped == []
    assert _scalar(database, "SELECT COUNT(*) FROM matches WHERE event_key = %s", (S_EVENT,)) == 2
    assert _watermarks(database)[("tba", "match")] is not None


@requires_db
def test_watermark_store_never_moves_backwards(database):
    store = WatermarkStore(database)
    assert store.get("tba", "match", S_EVENT) == 0  # unseen scope reads as "everything is new"

    store.advance("tba", "match", S_EVENT, 100)
    assert store.get("tba", "match", S_EVENT) == 100

    store.advance("tba", "match", S_EVENT, 50)  # a stale/replayed run
    assert store.get("tba", "match", S_EVENT) == 100

    store.advance("tba", "match", S_EVENT, None)  # a run that found nothing new
    assert store.get("tba", "match", S_EVENT) == 100
    assert _scalar(
        database,
        "SELECT last_synced_at IS NOT NULL FROM source_watermarks "
        "WHERE source = %s AND object_type = %s AND scope_key = %s",
        ("tba", "match", S_EVENT),
    ) is True


@requires_db
def test_run_recorder_marks_an_open_run_as_running(database):
    recorder = PipelineRunRecorder(database)
    run_id = recorder.start("event_sync", source="tba", scope_key=S_EVENT)

    with database.cursor() as cursor:
        cursor.execute("SELECT status, finished_at FROM pipeline_runs WHERE id = %s", (run_id,))
        assert cursor.fetchone() == ("running", None)

    recorder.succeed(run_id, records_processed=7, stage_counts={"landed": {"tba.match": 2}})
    assert _scalar(database, "SELECT status FROM pipeline_runs WHERE id = %s", (run_id,)) == "succeeded"
    assert _scalar(database, "SELECT records_processed FROM pipeline_runs WHERE id = %s", (run_id,)) == 7
    assert _scalar(database, "SELECT stage_counts FROM pipeline_runs WHERE id = %s", (run_id,)) == {
        "landed": {"tba.match": 2}
    }


@requires_db
def test_sync_without_statbotics_leaves_team_event_stats_untouched(database):
    result = _run(database, statbotics=None)

    assert "statbotics.team_event" not in result.landed
    assert result.loaded == {"teams": 6, "events": 1, "matches": 1, "team_event_stats": 0}
    assert _scalar(database, "SELECT COUNT(*) FROM team_event_stats WHERE event_key = %s", (S_EVENT,)) == 0
    assert set(_watermarks(database)) == {("tba", "event"), ("tba", "team"), ("tba", "match")}


@requires_db
def test_event_sync_lock_serializes_same_event_but_not_different_events(database):
    """Regression test found in the Phase 2 full-pipeline audit.

    Forcing two transactions to insert overlapping-but-different match
    rosters for the same match_key, then both prune before either commits,
    reproducibly hung: Postgres's row lock on the (match_key, team_number)
    unique key makes one writer block on the other, and a genuine lock-order
    cycle would surface as a deadlock error that aborts the whole run. Two
    concurrent sync_event calls for the same event are exactly this shape --
    "real-time updates must sync during an event as matches are played" makes
    an overlapping live-sync poll a realistic scenario, not a hypothetical one.

    _event_sync_lock closes this by holding a session-scoped advisory lock,
    keyed on event_key, for the whole sync_event call. This test verifies both
    halves of that fix: the same event_key fully serializes (no interleaving),
    while different event_keys never wait on each other (no scalability
    regression from over-serializing an unrelated event's sync).
    """
    import threading
    import time

    from data.orchestrator import _event_sync_lock

    order: list[str] = []

    def hold(label: str, event_key: str, seconds: float) -> None:
        with _event_sync_lock(database, event_key):
            order.append(f"{label}-acquired")
            time.sleep(seconds)
            order.append(f"{label}-released")

    # Same event_key: B must wait for A to fully release before acquiring.
    t1 = threading.Thread(target=hold, args=("A", S_EVENT, 0.4))
    t2 = threading.Thread(target=hold, args=("B", S_EVENT, 0.05))
    t1.start()
    time.sleep(0.1)  # ensure A acquires first
    t2.start()
    t1.join()
    t2.join()
    assert order == ["A-acquired", "A-released", "B-acquired", "B-released"]

    # Different event_keys: both proceed concurrently, not queued.
    order.clear()
    started = time.monotonic()
    threads = [
        threading.Thread(target=hold, args=(f"E{i}", f"{S_EVENT}_other_{i}", 0.3))
        for i in range(3)
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    elapsed = time.monotonic() - started
    assert elapsed < 0.6, f"unrelated events should not serialize on each other's lock, took {elapsed:.2f}s"
