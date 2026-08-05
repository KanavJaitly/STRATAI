"""Phase 3 Milestone 9: ScoutRadioz field mapping and the CSV-import orchestration.

Two kinds of coverage:

  * Pure mapping/rescaling tests against the real captured fixture
    (tests/fixtures/scoutradioz_matchscouting_2026mrcmp.csv) -- no database.
  * Real-Postgres, requires_db-gated integration tests of import_scoutradioz_csv
    end to end, using a small synthetic CSV built in a tmp_path with this
    file's own dedicated sentinel namespace (9992zzzradioz), following the
    same seeded-event/cleanup pattern tests/test_scouting_submission.py
    established -- including the milestone's own central success criterion:
    a ScoutRadioz-sourced observation and a human_scout one for the same
    match/team coexist and aggregate together correctly.
"""

from __future__ import annotations

from pathlib import Path

import psycopg
import pytest

from data.clients.scoutradioz import ScoutRadiozCsvImporter
from data.config import Settings
from data.metrics.aggregation import aggregate_defense_feeding
from data.metrics.schemas import ScoutingObservation
from data.metrics.scoutradioz import (
    ScoutRadiozFieldMapping,
    ScoutRadiozRatingMapping,
    import_scoutradioz_csv,
    map_scoutradioz_row_to_observation_payload,
)
from data.metrics.submission import PayloadValidationError, submit_human_scout_observation
from database.connection import Database, DatabaseConfig

FIXTURE_PATH = Path(__file__).parent / "fixtures" / "scoutradioz_matchscouting_2026mrcmp.csv"

_DEFENSE_0_10 = ScoutRadiozFieldMapping(
    defense_rating=ScoutRadiozRatingMapping(column="qDefenseQuality", source_min=0, source_max=10),
)


def _row(match_key: str = "2026mrcmp_qm1", team_key: str = "frc1672") -> tuple[dict, object]:
    with ScoutRadiozCsvImporter(FIXTURE_PATH) as importer:
        response = next(r for r in importer.read_rows() if r.parsed.match_key == match_key and r.parsed.team_key == team_key)
    return response.raw, response.parsed


# ---------------------------------------------------------------------------
# Pure mapping / rescaling (no database)
# ---------------------------------------------------------------------------


def test_maps_metadata_fields_correctly():
    raw, parsed = _row()
    payload = map_scoutradioz_row_to_observation_payload(raw, parsed, _DEFENSE_0_10)

    assert payload["match_key"] == "2026mrcmp_qm1"
    assert payload["event_key"] == "2026mrcmp"
    assert payload["team_number"] == 1672
    assert payload["scout_identifier"] == "frc11:Matthew Paccione"
    assert payload["source"] == "scoutradioz"


def test_submitted_at_is_parsed_and_utc_aware():
    raw, parsed = _row()
    payload = map_scoutradioz_row_to_observation_payload(raw, parsed, _DEFENSE_0_10)

    observation = ScoutingObservation.model_validate(payload)
    assert observation.submitted_at.tzinfo is not None
    assert observation.submitted_at.utcoffset().total_seconds() == 0
    assert observation.submitted_at.hour == 15  # "3:15:00 PM"


def test_midnight_boundary_time_parses_correctly():
    raw, parsed = _row(match_key="2026mrcmp_qm104", team_key="frc1923")
    assert parsed.time == "4/18/2026 12:00:00 AM"
    payload = map_scoutradioz_row_to_observation_payload(raw, parsed, _DEFENSE_0_10)
    observation = ScoutingObservation.model_validate(payload)
    assert observation.submitted_at.hour == 0


@pytest.mark.parametrize("raw_value,expected", [("0", 0), ("2", 1), ("4", 2), ("6", 3), ("8", 4), ("10", 5)])
def test_rating_rescale_boundaries_and_even_midpoints(raw_value, expected):
    mapping = ScoutRadiozFieldMapping(
        defense_rating=ScoutRadiozRatingMapping(column="qDefenseQuality", source_min=0, source_max=10),
    )
    raw, parsed = _row()
    raw = dict(raw, qDefenseQuality=raw_value)
    payload = map_scoutradioz_row_to_observation_payload(raw, parsed, mapping)
    assert payload["defense_rating"] == expected


def test_blank_rating_cell_maps_to_none_not_zero():
    raw, parsed = _row()
    raw = dict(raw, qDefenseQuality="")
    payload = map_scoutradioz_row_to_observation_payload(raw, parsed, _DEFENSE_0_10)
    assert payload["defense_rating"] is None


def test_unmapped_rating_is_absent_from_the_payload():
    mapping = ScoutRadiozFieldMapping()  # neither defense nor feeding configured
    raw, parsed = _row()
    payload = map_scoutradioz_row_to_observation_payload(raw, parsed, mapping)
    assert "defense_rating" not in payload
    assert "feeding_rating" not in payload


def test_degenerate_scale_maps_to_min_rating_not_a_crash():
    mapping = ScoutRadiozFieldMapping(
        defense_rating=ScoutRadiozRatingMapping(column="qDefenseQuality", source_min=5, source_max=5),
    )
    raw, parsed = _row()
    raw = dict(raw, qDefenseQuality="5")
    payload = map_scoutradioz_row_to_observation_payload(raw, parsed, mapping)
    assert payload["defense_rating"] == 0


def test_malformed_team_key_raises_value_error():
    raw, parsed = _row()
    parsed = parsed.model_copy(update={"team_key": "notateam"})
    with pytest.raises(ValueError, match="notateam"):
        map_scoutradioz_row_to_observation_payload(raw, parsed, _DEFENSE_0_10)


def test_frc0_team_key_parses_but_is_rejected_at_validation_not_a_crash():
    # "frc0" is TBA's own unassigned-roster placeholder (see data/staging/
    # normalizer.py's is_unassigned_team_key); a ScoutRadioz export sources its
    # team keys from TBA, so the same sentinel could plausibly appear here. It
    # parses as team_number=0 (the regex has no reason to reject "0"), and the
    # shared validator -- not this mapping function -- is what correctly
    # rejects a non-positive team_number, exactly as it would for human_scout.
    from data.metrics.normalizer import normalize_scoutradioz_observation

    raw, parsed = _row()
    parsed = parsed.model_copy(update={"team_key": "frc0"})
    payload = map_scoutradioz_row_to_observation_payload(raw, parsed, _DEFENSE_0_10)
    assert payload["team_number"] == 0
    with pytest.raises(PayloadValidationError, match="team_number"):
        normalize_scoutradioz_observation(payload)


def test_blank_scouter_produces_an_empty_scout_identifier_not_a_fabricated_one():
    raw, parsed = _row(match_key="2026mrcmp_qm93", team_key="frc10918")
    assert parsed.scouter == ""
    payload = map_scoutradioz_row_to_observation_payload(raw, parsed, _DEFENSE_0_10)
    assert payload["scout_identifier"] == ""


def test_blank_scout_identifier_is_rejected_by_the_shared_validator():
    from data.metrics.normalizer import normalize_scoutradioz_observation

    raw, parsed = _row(match_key="2026mrcmp_qm93", team_key="frc10918")
    payload = map_scoutradioz_row_to_observation_payload(raw, parsed, _DEFENSE_0_10)
    with pytest.raises(PayloadValidationError, match="scout_identifier"):
        normalize_scoutradioz_observation(payload)


def test_notes_columns_fold_configured_columns_into_notes():
    mapping = ScoutRadiozFieldMapping(
        defense_rating=ScoutRadiozRatingMapping(column="qDefenseQuality", source_min=0, source_max=10),
        notes_columns=("superNotes",),
    )
    raw, parsed = _row()
    raw = dict(raw, superNotes="Robot tipped once")
    payload = map_scoutradioz_row_to_observation_payload(raw, parsed, mapping)
    assert payload["notes"] == "Robot tipped once"


def test_empty_notes_columns_are_omitted_not_included_as_blank():
    raw, parsed = _row()  # fixture's own superNotes is ""
    payload = map_scoutradioz_row_to_observation_payload(
        raw, parsed, ScoutRadiozFieldMapping(
            defense_rating=ScoutRadiozRatingMapping(column="qDefenseQuality", source_min=0, source_max=10),
            notes_columns=("superNotes",),
        ),
    )
    assert "notes" not in payload


# ---------------------------------------------------------------------------
# Real-Postgres integration: import_scoutradioz_csv end to end
# ---------------------------------------------------------------------------

_S_EVENT = "9992zzzradioz"
_S_MATCH = f"{_S_EVENT}_qm1"
_S_TEAM_A = 921001
_S_TEAM_B = 921002


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
        cursor.execute("DELETE FROM scouting_observations WHERE event_key = %s", (_S_EVENT,))
        cursor.execute(
            "DELETE FROM raw_source_payloads WHERE source_object_id LIKE %s", (f"{_S_MATCH}%",)
        )
        cursor.execute("DELETE FROM matches WHERE event_key = %s", (_S_EVENT,))
        cursor.execute("DELETE FROM teams WHERE team_number = ANY(%s::int[])", ([_S_TEAM_A, _S_TEAM_B],))
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
        cursor.execute("INSERT INTO events (event_key, season, name) VALUES (%s, %s, %s)", (_S_EVENT, 9992, "Sentinel ScoutRadioz Event"))
        cursor.execute("INSERT INTO teams (team_number, name) VALUES (%s, %s)", (_S_TEAM_A, "Sentinel Team A"))
        cursor.execute("INSERT INTO teams (team_number, name) VALUES (%s, %s)", (_S_TEAM_B, "Sentinel Team B"))
        cursor.execute(
            "INSERT INTO matches (match_key, event_key, season, competition_level, match_number) "
            "VALUES (%s, %s, %s, %s, %s)",
            (_S_MATCH, _S_EVENT, 9992, "qualification", 1),
        )
    try:
        yield db
    finally:
        _cleanup(db)


def _write_csv(tmp_path: Path, rows: list[str]) -> Path:
    header = "org_key,year,event_key,match_key,match_number,time,alliance,team_key,scouter,qDefenseQuality,superNotes"
    path = tmp_path / "export.csv"
    path.write_text("\n".join([header, *rows]) + "\n", encoding="utf-8")
    return path


def _valid_rows() -> list[str]:
    return [
        f"frc11,2026,{_S_EVENT},{_S_MATCH},1,8/5/2026 3:15:00 PM,red,frc{_S_TEAM_A},Alice,4,",
        f"frc11,2026,{_S_EVENT},{_S_MATCH},1,8/5/2026 3:15:00 PM,red,frc{_S_TEAM_B},Bob,8,Good match",
    ]


@requires_db
def test_import_scoutradioz_csv_runs_end_to_end(database: Database, tmp_path: Path) -> None:
    csv_path = _write_csv(tmp_path, _valid_rows())

    result = import_scoutradioz_csv(csv_path, _DEFENSE_0_10, database=database)

    assert result.event_key == _S_EVENT
    assert result.rows_read == 2
    assert result.landed == 2
    assert result.loaded == 2
    assert result.skipped == []
    assert result.malformed_rows == []

    with database.cursor() as cursor:
        cursor.execute(
            "SELECT team_number, scout_identifier, defense_rating, source FROM scouting_observations "
            "WHERE event_key = %s ORDER BY team_number",
            (_S_EVENT,),
        )
        rows = cursor.fetchall()

    assert rows == [
        (_S_TEAM_A, "frc11:Alice", 2, "scoutradioz"),
        (_S_TEAM_B, "frc11:Bob", 4, "scoutradioz"),
    ]


@requires_db
def test_import_scoutradioz_csv_lands_the_full_raw_row_not_just_mapped_fields(
    database: Database, tmp_path: Path,
) -> None:
    # Real bug found and fixed during this milestone's own Phase F bug hunt:
    # the payload landed in raw_source_payloads must carry every column the
    # export had, including ones field_mapping never names (e.g. a
    # game-specific column with no defense/feeding/notes destination at all),
    # or that data is permanently gone the moment this function returns --
    # exactly the "land raw, never a projection" bug this codebase already
    # fixed once for TBA/Statbotics (data/pipeline.py's own module docstring).
    csv_path = _write_csv(tmp_path, [
        f"frc11,2026,{_S_EVENT},{_S_MATCH},1,8/5/2026 3:15:00 PM,red,frc{_S_TEAM_A},Alice,4,",
    ])

    import_scoutradioz_csv(csv_path, _DEFENSE_0_10, database=database)

    with database.cursor() as cursor:
        cursor.execute(
            "SELECT payload_json FROM raw_source_payloads WHERE source = 'scoutradioz' "
            "AND source_object_id LIKE %s",
            (f"{_S_MATCH}%",),
        )
        (payload,) = cursor.fetchone()

    # The mapped canonical fields are present...
    assert payload["match_key"] == _S_MATCH
    assert payload["team_number"] == _S_TEAM_A
    # ...and so is the untouched raw row, including the header/columns
    # this import's field_mapping never referenced (year, alliance).
    assert payload["_raw_csv_row"]["year"] == "2026"
    assert payload["_raw_csv_row"]["alliance"] == "red"
    assert payload["_raw_csv_row"]["qDefenseQuality"] == "4"


@requires_db
def test_import_scoutradioz_csv_is_idempotent_on_a_repeat_import(database: Database, tmp_path: Path) -> None:
    csv_path = _write_csv(tmp_path, _valid_rows())

    first = import_scoutradioz_csv(csv_path, _DEFENSE_0_10, database=database)
    second = import_scoutradioz_csv(csv_path, _DEFENSE_0_10, database=database)

    assert first.landed == 2
    assert second.landed == 0  # byte-identical payloads land nothing new

    with database.cursor() as cursor:
        cursor.execute("SELECT COUNT(*) FROM scouting_observations WHERE event_key = %s", (_S_EVENT,))
        (count,) = cursor.fetchone()
    assert count == 2  # no duplicate rows from re-importing


@requires_db
def test_import_scoutradioz_csv_skips_malformed_rows_without_failing_the_batch(
    database: Database, tmp_path: Path,
) -> None:
    rows = [
        *_valid_rows(),
        # Blank scouter -> rejected (empty scout_identifier), not fatal to the rest.
        f"frc11,2026,{_S_EVENT},{_S_MATCH},1,8/5/2026 3:15:00 PM,blue,frc{_S_TEAM_A},,5,",
        # Malformed team_key -> rejected before it can even reach validation.
        f"frc11,2026,{_S_EVENT},{_S_MATCH},1,8/5/2026 3:15:00 PM,blue,notateam,Carol,5,",
    ]
    csv_path = _write_csv(tmp_path, rows)

    result = import_scoutradioz_csv(csv_path, _DEFENSE_0_10, database=database)

    assert result.rows_read == 4
    assert result.loaded == 2
    assert len(result.malformed_rows) == 2
    reasons = " ".join(reason for _row_number, reason in result.malformed_rows)
    assert "scout_identifier" in reasons
    assert "notateam" in reasons


@requires_db
def test_import_scoutradioz_csv_raises_for_a_multi_event_file(database: Database, tmp_path: Path) -> None:
    rows = [
        *_valid_rows(),
        f"frc11,2026,9992zzzother,9992zzzother_qm1,1,8/5/2026 3:15:00 PM,red,frc{_S_TEAM_A},Dana,5,",
    ]
    csv_path = _write_csv(tmp_path, rows)

    with pytest.raises(ValueError, match="more than one event_key"):
        import_scoutradioz_csv(csv_path, _DEFENSE_0_10, database=database)


@requires_db
def test_import_scoutradioz_csv_raises_for_a_header_only_file(database: Database, tmp_path: Path) -> None:
    csv_path = _write_csv(tmp_path, [])

    with pytest.raises(ValueError, match="no data rows"):
        import_scoutradioz_csv(csv_path, _DEFENSE_0_10, database=database)


@requires_db
def test_import_scoutradioz_csv_raises_clearly_for_a_misconfigured_field_mapping(
    database: Database, tmp_path: Path,
) -> None:
    # A column name that doesn't exist in this file is a caller configuration
    # mistake -- must fail loudly up front, not as a KeyError mid-batch or as
    # every row being reported "malformed".
    csv_path = _write_csv(tmp_path, _valid_rows())
    bad_mapping = ScoutRadiozFieldMapping(
        defense_rating=ScoutRadiozRatingMapping(column="qDefenseQualityTypo", source_min=0, source_max=10),
    )

    with pytest.raises(ValueError, match="qDefenseQualityTypo"):
        import_scoutradioz_csv(csv_path, bad_mapping, database=database)


@requires_db
def test_scoutradioz_and_human_scout_observations_coexist_and_aggregate_together(
    database: Database, tmp_path: Path,
) -> None:
    """The milestone's own central success criterion, exercised through the
    real production code paths (import_scoutradioz_csv AND
    submit_human_scout_observation), not hand-constructed objects.
    """
    csv_path = _write_csv(tmp_path, [
        f"frc11,2026,{_S_EVENT},{_S_MATCH},1,8/5/2026 3:15:00 PM,red,frc{_S_TEAM_A},ScoutBot,8,",
    ])
    import_scoutradioz_csv(csv_path, _DEFENSE_0_10, database=database)

    submit_human_scout_observation(
        {
            "match_key": _S_MATCH, "event_key": _S_EVENT, "team_number": _S_TEAM_A,
            "scout_identifier": "alice", "defense_rating": 2,
            "submitted_at": "2026-08-05T15:15:00Z",
        },
        database=database,
    )

    with database.cursor() as cursor:
        cursor.execute(
            "SELECT match_key, event_key, team_number, scout_identifier, defense_rating, "
            "feeding_rating, source, submitted_at FROM scouting_observations "
            "WHERE event_key = %s AND team_number = %s ORDER BY source",
            (_S_EVENT, _S_TEAM_A),
        )
        rows = cursor.fetchall()

    assert [r[6] for r in rows] == ["human_scout", "scoutradioz"]

    observations = [
        ScoutingObservation(
            match_key=r[0], event_key=r[1], team_number=r[2], scout_identifier=r[3],
            defense_rating=r[4], feeding_rating=r[5], source=r[6], submitted_at=r[7],
        )
        for r in rows
    ]
    profile = aggregate_defense_feeding(observations)

    assert profile.defense_observation_count == 2
    assert profile.defense_score == 3.0  # median(2, 4), pooled across both sources
    assert profile.contributing_sources == ["human_scout", "scoutradioz"]
