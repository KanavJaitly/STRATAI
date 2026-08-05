"""Phase 3 Milestone 7: the human scouting submission path, end to end.

Mirrors tests/test_pipeline.py's integration-test style for sync_event: a
seeded sentinel event/team/match, a `database` fixture that cleans up before
and after, and direct SQL assertions against the real tables submit_human_scout_
observation touches (raw_source_payloads, scouting_observations, pipeline_runs,
source_watermarks, canonical_lineage), not just the returned SubmissionResult.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import psycopg
import pytest

from data.config import Settings
from data.lineage import LineageStore
from data.metrics.submission import (
    PayloadValidationError,
    ScoutingAccessDeniedError,
    submit_human_scout_observation,
)
from data.serving.repository import CanonicalRepository
from database.connection import Database, DatabaseConfig

# Sentinel namespace, distinct from every other module's (9994-9999).
_S_EVENT = "9993zzzsub"
_S_TEAM = 920001
_S_FILLER_TEAM = 920002
_S_MATCH = f"{_S_EVENT}_qm1"


def _valid_payload(**overrides) -> dict:
    payload = {
        "match_key": _S_MATCH,
        "event_key": _S_EVENT,
        "team_number": _S_TEAM,
        "scout_identifier": "alice",
        "defense_rating": 3,
        "submitted_at": "2026-08-04T18:30:00Z",
    }
    payload.update(overrides)
    return payload


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
        cursor.execute("DELETE FROM scouting_observations WHERE event_key = %s", (_S_EVENT,))
        cursor.execute("DELETE FROM scouting_access_codes WHERE event_key = %s", (_S_EVENT,))
        # LIKE on _S_EVENT, not _S_MATCH: the nonexistent-match test lands a
        # payload keyed on f"{_S_EVENT}_qm999:...", which does not share
        # _S_MATCH's "_qm1" prefix and would otherwise leak across runs.
        cursor.execute(
            "DELETE FROM raw_source_payloads WHERE source = 'human_scout' AND source_object_id LIKE %s",
            (f"{_S_EVENT}%",),
        )
        cursor.execute("DELETE FROM matches WHERE event_key = %s", (_S_EVENT,))
        cursor.execute("DELETE FROM teams WHERE team_number = ANY(%s::int[])", ([_S_TEAM, _S_FILLER_TEAM],))
        cursor.execute("DELETE FROM events WHERE event_key = %s", (_S_EVENT,))
        cursor.execute("DELETE FROM pipeline_runs WHERE scope_key = %s", (_S_EVENT,))
        cursor.execute("DELETE FROM source_watermarks WHERE scope_key = %s", (_S_EVENT,))


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
            (_S_EVENT, 9993, "Sentinel Submission Event"),
        )
        cursor.execute("INSERT INTO teams (team_number, name) VALUES (%s, %s)", (_S_TEAM, "Sentinel Team"))
        cursor.execute("INSERT INTO teams (team_number, name) VALUES (%s, %s)", (_S_FILLER_TEAM, "Sentinel Filler"))
        cursor.execute(
            "INSERT INTO matches (match_key, event_key, season, competition_level, match_number) "
            "VALUES (%s, %s, %s, %s, %s)",
            (_S_MATCH, _S_EVENT, 9993, "qualification", 1),
        )
    try:
        yield db
    finally:
        _cleanup(db)


def _scalar(database: Database, sql: str, params: tuple = ()):
    with database.cursor() as cursor:
        cursor.execute(sql, params)
        row = cursor.fetchone()
    return None if row is None else row[0]


def _observation_rows(database: Database) -> list[tuple]:
    with database.cursor() as cursor:
        cursor.execute(
            "SELECT scout_identifier, defense_rating, feeding_rating, raw_payload_id "
            "FROM scouting_observations WHERE event_key = %s ORDER BY scout_identifier",
            (_S_EVENT,),
        )
        return cursor.fetchall()


def _raw_payload_count(database: Database, source_object_id: str) -> int:
    return _scalar(
        database,
        "SELECT COUNT(*) FROM raw_source_payloads WHERE source = 'human_scout' AND source_object_id = %s",
        (source_object_id,),
    )


# ---------------------------------------------------------------------------
# End-to-end: submit -> land -> stage -> canonical
# ---------------------------------------------------------------------------


@requires_db
def test_submit_human_scout_observation_runs_end_to_end(database: Database) -> None:
    result = submit_human_scout_observation(_valid_payload(), database=database)

    assert result.landed is True
    assert result.observation.defense_rating == 3
    assert result.raw_payload_id is not None
    assert result.skipped == []

    rows = _observation_rows(database)
    assert rows == [("alice", 3, None, result.raw_payload_id)]

    # Run bookkeeping: a real pipeline_runs row, succeeded.
    status = _scalar(database, "SELECT status FROM pipeline_runs WHERE id = %s", (result.run_id,))
    assert status == "succeeded"

    # Watermark advanced for this (source, object_type, event).
    watermark = _scalar(
        database,
        "SELECT watermark_value FROM source_watermarks WHERE source = 'human_scout' "
        "AND object_type = 'scouting_observation' AND scope_key = %s",
        (_S_EVENT,),
    )
    assert watermark is not None

    # Lineage traces the canonical row back to the exact payload it came from.
    # The lineage entity_key is scouting_observation_natural_key's 4-part form
    # (match_key:team_number:scout_identifier:source), not the 3-part
    # source_object_id used for raw_source_payloads -- source is a separate
    # column there, but entity_key_of-equivalents always include it.
    lineage = LineageStore(database)
    traced = lineage.trace_to_payload("scouting_observation", f"{_S_MATCH}:{_S_TEAM}:alice:human_scout")
    assert traced is not None
    raw_id, raw_payload = traced
    assert raw_id == result.raw_payload_id
    assert raw_payload["defense_rating"] == 3


# ---------------------------------------------------------------------------
# Dedup: identical resubmission creates no new row
# ---------------------------------------------------------------------------


@requires_db
def test_identical_resubmission_dedupes_creates_no_new_row(database: Database) -> None:
    payload = _valid_payload()
    first = submit_human_scout_observation(payload, database=database)
    second = submit_human_scout_observation(payload, database=database)

    assert first.landed is True
    assert second.landed is False  # identical checksum, not a new raw row

    source_object_id = f"{_S_MATCH}:{_S_TEAM}:alice"
    assert _raw_payload_count(database, source_object_id) == 1
    assert len(_observation_rows(database)) == 1

    # The second call did no new staging/loading work -- same raw_payload_id.
    assert second.raw_payload_id is None or second.raw_payload_id == first.raw_payload_id


# ---------------------------------------------------------------------------
# Correction: a changed rating creates a new version and updates the canonical row
# ---------------------------------------------------------------------------


@requires_db
def test_corrected_resubmission_creates_new_version_and_updates_canonical_row(database: Database) -> None:
    first = submit_human_scout_observation(_valid_payload(defense_rating=3), database=database)
    second = submit_human_scout_observation(_valid_payload(defense_rating=5), database=database)

    assert first.landed is True
    assert second.landed is True
    assert second.raw_payload_id != first.raw_payload_id

    source_object_id = f"{_S_MATCH}:{_S_TEAM}:alice"
    # Two raw payload versions exist, but only the newer is current.
    assert _raw_payload_count(database, source_object_id) == 2
    current = _scalar(
        database,
        "SELECT COUNT(*) FROM raw_source_payloads WHERE source = 'human_scout' "
        "AND source_object_id = %s AND is_current",
        (source_object_id,),
    )
    assert current == 1

    # Exactly one canonical row, reflecting the corrected value.
    rows = _observation_rows(database)
    assert rows == [("alice", 5, None, second.raw_payload_id)]


# ---------------------------------------------------------------------------
# Access gate
# ---------------------------------------------------------------------------


@requires_db
def test_submission_allowed_when_no_access_code_configured(database: Database) -> None:
    result = submit_human_scout_observation(_valid_payload(), database=database)
    assert result.landed is True


@requires_db
def test_access_gate_rejects_missing_code(database: Database) -> None:
    with database.cursor() as cursor:
        cursor.execute(
            "INSERT INTO scouting_access_codes (event_key, access_code) VALUES (%s, %s)",
            (_S_EVENT, "secret123"),
        )

    with pytest.raises(ScoutingAccessDeniedError):
        submit_human_scout_observation(_valid_payload(), database=database)

    # Nothing was landed for the rejected attempt.
    source_object_id = f"{_S_MATCH}:{_S_TEAM}:alice"
    assert _raw_payload_count(database, source_object_id) == 0
    assert _observation_rows(database) == []


@requires_db
def test_access_gate_rejects_wrong_code(database: Database) -> None:
    with database.cursor() as cursor:
        cursor.execute(
            "INSERT INTO scouting_access_codes (event_key, access_code) VALUES (%s, %s)",
            (_S_EVENT, "secret123"),
        )

    with pytest.raises(ScoutingAccessDeniedError):
        submit_human_scout_observation(_valid_payload(), database=database, access_code="wrong-code")


@requires_db
def test_access_gate_allows_correct_code(database: Database) -> None:
    with database.cursor() as cursor:
        cursor.execute(
            "INSERT INTO scouting_access_codes (event_key, access_code) VALUES (%s, %s)",
            (_S_EVENT, "secret123"),
        )

    result = submit_human_scout_observation(_valid_payload(), database=database, access_code="secret123")
    assert result.landed is True


# ---------------------------------------------------------------------------
# Malformed payload: rejected before anything lands, no pipeline_runs row
# ---------------------------------------------------------------------------


@requires_db
def test_malformed_payload_raises_and_lands_nothing(database: Database) -> None:
    payload = _valid_payload()
    del payload["scout_identifier"]

    with pytest.raises(PayloadValidationError):
        submit_human_scout_observation(payload, database=database)

    # "Lands nothing" was previously asserted by name only -- verify it: no
    # raw_source_payloads row for this match exists at all (a missing
    # scout_identifier means normalize_human_scout_observation raises before
    # a source_object_id can even be computed, so nothing narrower than the
    # match itself can be checked).
    raw_count = _scalar(
        database,
        "SELECT COUNT(*) FROM raw_source_payloads WHERE source = 'human_scout' AND source_object_id LIKE %s",
        (f"{_S_MATCH}%",),
    )
    assert raw_count == 0
    assert _observation_rows(database) == []
    run_count = _scalar(database, "SELECT COUNT(*) FROM pipeline_runs WHERE scope_key = %s", (_S_EVENT,))
    assert run_count == 0


# ---------------------------------------------------------------------------
# Multiple scouts on the same match/team
# ---------------------------------------------------------------------------


@requires_db
def test_submission_for_a_nonexistent_match_is_rejected_cleanly_not_a_raw_fk_violation(database: Database) -> None:
    # Without the referential quality check, this would reach
    # CanonicalRepository.load_scouting_observation and fail as a raw
    # psycopg foreign-key violation -- exactly the generic, unstructured
    # exception this architecture otherwise avoids. It must instead land (the
    # raw payload is still valid on its own terms) but never become a
    # canonical row, and must not raise at all.
    payload = _valid_payload(match_key=f"{_S_EVENT}_qm999")
    result = submit_human_scout_observation(payload, database=database)

    assert result.landed is True  # the raw payload itself is well-formed
    assert result.skipped != []  # but staging rejected it on referential grounds
    assert any(record.reason and "match_key" in record.reason for record in result.skipped)
    assert _observation_rows(database) == []  # never became a canonical row


@requires_db
def test_submission_for_a_nonexistent_team_is_rejected_cleanly(database: Database) -> None:
    payload = _valid_payload(team_number=929999)  # never inserted into teams
    result = submit_human_scout_observation(payload, database=database)

    assert result.landed is True
    assert result.skipped != []
    assert _scalar(
        database, "SELECT COUNT(*) FROM scouting_observations WHERE team_number = %s", (929999,)
    ) == 0


@requires_db
def test_different_scouts_on_the_same_match_and_team_create_separate_rows(database: Database) -> None:
    submit_human_scout_observation(_valid_payload(scout_identifier="alice", defense_rating=3), database=database)
    submit_human_scout_observation(_valid_payload(scout_identifier="bob", defense_rating=4), database=database)

    rows = _observation_rows(database)
    assert rows == [("alice", 3, None, rows[0][3]), ("bob", 4, None, rows[1][3])]


# ---------------------------------------------------------------------------
# Concurrency (MASTER_BUILD.md's testing checklist: "concurrency"). Verified
# by direct reproduction against the real database, mirroring test_pipeline.py's
# test_event_sync_lock_serializes_same_event_but_not_different_events -- run
# it first as an ad-hoc script before writing this permanent regression test,
# exactly the same "reproduce, don't just reason" discipline that test follows.
# ---------------------------------------------------------------------------


@requires_db
def test_concurrent_submissions_of_different_observations_all_succeed(database: Database) -> None:
    # Ten scouts rating ten different teams in the same match, submitted at
    # once. Each submission only ever reads/writes its own source_object_id,
    # so there is no shared row for two threads to contend over; this proves
    # that holds under real concurrent DB access, not just by inspection.
    import concurrent.futures

    settings = Settings()
    extra_teams = [_S_TEAM + i for i in range(1, 11)]
    with database.cursor() as cursor:
        for team_number in extra_teams:
            cursor.execute(
                "INSERT INTO teams (team_number, name) VALUES (%s, %s) ON CONFLICT DO NOTHING",
                (team_number, f"Sentinel {team_number}"),
            )
    try:
        def submit(team_number: int):
            db_local = Database(DatabaseConfig(settings.database_url))
            return submit_human_scout_observation(
                _valid_payload(team_number=team_number, scout_identifier=f"scout{team_number}"),
                database=db_local,
            )

        errors = []
        results = []
        with concurrent.futures.ThreadPoolExecutor(max_workers=10) as executor:
            futures = [executor.submit(submit, team_number) for team_number in extra_teams]
            for future in concurrent.futures.as_completed(futures):
                try:
                    results.append(future.result())
                except Exception as exc:  # pragma: no cover -- only populated on a real failure
                    errors.append(repr(exc))

        assert errors == []
        assert all(result.landed for result in results)
        count = _scalar(
            database, "SELECT COUNT(*) FROM scouting_observations WHERE team_number = ANY(%s::int[])",
            (extra_teams,),
        )
        assert count == 10
    finally:
        with database.cursor() as cursor:
            cursor.execute("DELETE FROM scouting_observations WHERE team_number = ANY(%s::int[])", (extra_teams,))
            cursor.execute("DELETE FROM teams WHERE team_number = ANY(%s::int[])", (extra_teams,))


@requires_db
def test_concurrent_identical_submissions_serialize_to_exactly_one_row(database: Database) -> None:
    # Fifteen threads submitting the byte-identical payload at once -- the
    # scout double-tapping "submit" scenario. RawPayloadWriter's own advisory
    # lock on (source, source_object_type, source_object_id) must serialize
    # these so exactly one lands as new and exactly one canonical row results,
    # never a duplicate row and never a raised exception from lock contention.
    import concurrent.futures

    settings = Settings()
    payload = _valid_payload()

    def submit(_: int):
        db_local = Database(DatabaseConfig(settings.database_url))
        return submit_human_scout_observation(payload, database=db_local)

    errors = []
    results = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=15) as executor:
        futures = [executor.submit(submit, i) for i in range(15)]
        for future in concurrent.futures.as_completed(futures):
            try:
                results.append(future.result())
            except Exception as exc:  # pragma: no cover -- only populated on a real failure
                errors.append(repr(exc))

    assert errors == []
    assert sum(1 for result in results if result.landed) == 1
    assert len(_observation_rows(database)) == 1
    source_object_id = f"{_S_MATCH}:{_S_TEAM}:alice"
    assert _raw_payload_count(database, source_object_id) == 1


# ---------------------------------------------------------------------------
# Failure recovery (MASTER_BUILD.md's testing checklist: "rollback behavior",
# "failure recovery"). Mirrors sync_event's own guarantee: a run that fails
# after landing but before the watermark advances must leave the watermark
# exactly where it was, so a retry reprocesses rather than skips.
# ---------------------------------------------------------------------------


@requires_db
def test_failure_during_load_leaves_watermark_untouched_and_marks_run_failed(database: Database) -> None:
    real_repository = CanonicalRepository(database)
    failing_repository = MagicMock(wraps=real_repository)
    failing_repository.load_scouting_observation.side_effect = RuntimeError("simulated load failure")

    payload = _valid_payload()
    with pytest.raises(RuntimeError, match="simulated load failure"):
        submit_human_scout_observation(payload, database=database, repository=failing_repository)

    # Landed (that happens before the failure point), but never became a
    # canonical row, and the watermark was never advanced past it.
    source_object_id = f"{_S_MATCH}:{_S_TEAM}:alice"
    assert _raw_payload_count(database, source_object_id) == 1
    assert _observation_rows(database) == []
    watermark = _scalar(
        database,
        "SELECT watermark_value FROM source_watermarks WHERE source = 'human_scout' "
        "AND object_type = 'scouting_observation' AND scope_key = %s",
        (_S_EVENT,),
    )
    assert watermark is None  # never advanced

    failed_run = _scalar(
        database, "SELECT status FROM pipeline_runs WHERE scope_key = %s ORDER BY id DESC LIMIT 1", (_S_EVENT,)
    )
    assert failed_run == "failed"

    # A real retry (no mock this time) recovers cleanly: the same landed
    # payload is still pending past the untouched watermark, gets staged and
    # loaded for the first time, and the run now succeeds.
    retry = submit_human_scout_observation(payload, database=database)
    assert retry.landed is False  # identical payload, already landed by the failed attempt
    assert retry.raw_payload_id is not None
    assert _observation_rows(database) == [("alice", 3, None, retry.raw_payload_id)]


# ---------------------------------------------------------------------------
# Correction semantics: a resubmission is a full replacement, not a merge
# ---------------------------------------------------------------------------


@requires_db
def test_corrected_resubmission_that_omits_a_field_clears_it_not_preserves_it(database: Database) -> None:
    # The first submission rates both defense and feeding. The "corrected"
    # resubmission only rates defense -- omitting feeding_rating entirely,
    # not setting it to some explicit value. A resubmission is documented as
    # landing a new, complete payload version, not a delta to merge into the
    # existing row, so the missing feeding_rating must clear the previous
    # value, not silently leave the stale 4 behind.
    submit_human_scout_observation(_valid_payload(defense_rating=3, feeding_rating=4), database=database)
    submit_human_scout_observation(_valid_payload(defense_rating=5), database=database)  # feeding_rating omitted

    rows = _observation_rows(database)
    assert rows == [("alice", 5, None, rows[0][3])]
