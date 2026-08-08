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
from data.metrics.schemas import MAX_RATING, MIN_RATING, ScoutingObservation
from data.metrics.scoutradioz import (
    ScoutRadiozFieldMapping,
    ScoutRadiozRatingMapping,
    _row_expresses_no_rating,
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


def test_missing_rating_cell_maps_to_none_not_a_crash():
    """A cell a truncated CSV line stops before arrives as None, not "".

    csv.DictReader fills the columns a short row never reached with None. That
    is the same absence as a blank cell and must be read as one -- reaching
    int(None) here raises TypeError, which import_scoutradioz_csv's per-row
    handler does not catch, so a single short line would abort the entire
    import (pinned end to end by the integration test of the same name below).
    """
    raw, parsed = _row()
    raw = dict(raw, qDefenseQuality=None)
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


# ---------------------------------------------------------------------------
# Opt-in target range floor (ScoutRadiozRatingMapping.target_min)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("source_min,source_max,raw_value,expected", [
    # 0-10 -> 0-5. Odd raw values land on exact .5 ties here (raw/2), resolved
    # by round()'s ties-to-even: 1 -> 0, 3 -> 2, 5 -> 2, 7 -> 4, 9 -> 4. Pinned
    # as observed behaviour, not endorsed as correct -- see RUNNING_NOTES'
    # rescale-compression entry. test_rating_rescale_boundaries_and_even_
    # midpoints covers only the even half of this scale, which is exactly why
    # this test exists.
    (0, 10, "0", 0), (0, 10, "1", 0), (0, 10, "2", 1), (0, 10, "3", 2), (0, 10, "4", 2),
    (0, 10, "5", 2), (0, 10, "6", 3), (0, 10, "7", 4), (0, 10, "8", 4), (0, 10, "9", 4),
    (0, 10, "10", 5),
    # 1-10 -> 0-5: the scale the 2026mrcmp import actually used, whose raw 1 ->
    # canonical 0 collapse is what target_min was added to fix.
    (1, 10, "1", 0), (1, 10, "2", 1), (1, 10, "3", 1), (1, 10, "4", 2), (1, 10, "5", 2),
    (1, 10, "6", 3), (1, 10, "7", 3), (1, 10, "8", 4), (1, 10, "9", 4), (1, 10, "10", 5),
])
def test_default_target_min_leaves_every_existing_mapping_identical(
    source_min, source_max, raw_value, expected
):
    # The regression guard for target_min being additive. Every value of both
    # scales this codebase has used, under a mapping that does NOT pass
    # target_min. If any of these moved, the field was not opt-in.
    mapping = ScoutRadiozFieldMapping(
        defense_rating=ScoutRadiozRatingMapping(
            column="qDefenseQuality", source_min=source_min, source_max=source_max,
        ),
    )
    raw, parsed = _row()
    raw = dict(raw, qDefenseQuality=raw_value)
    payload = map_scoutradioz_row_to_observation_payload(raw, parsed, mapping)
    assert payload["defense_rating"] == expected


def test_target_min_defaults_to_min_rating():
    mapping = ScoutRadiozRatingMapping(column="qDefenseQuality", source_min=1, source_max=10)
    assert mapping.target_min == MIN_RATING


@pytest.mark.parametrize("raw_value,expected", [
    ("1", 1), ("2", 1), ("3", 2), ("4", 2), ("5", 3),
    ("6", 3), ("7", 4), ("8", 4), ("9", 5), ("10", 5),
])
def test_target_min_one_maps_the_source_floor_to_a_real_low_rating(raw_value, expected):
    # The 2026mrcmp mapping. The point of the whole field is the first case:
    # raw 1 is a real, weak defense rating and must not land on canonical 0,
    # which this column reserves for "did not defend" via excluded_values.
    mapping = ScoutRadiozFieldMapping(
        defense_rating=ScoutRadiozRatingMapping(
            column="qDefenseQuality", source_min=1, source_max=10,
            excluded_values=("0",), target_min=1,
        ),
    )
    raw, parsed = _row()
    raw = dict(raw, qDefenseQuality=raw_value)
    payload = map_scoutradioz_row_to_observation_payload(raw, parsed, mapping)
    assert payload["defense_rating"] == expected


def test_target_min_leaves_canonical_zero_unreachable_for_a_rated_row():
    # Stronger than the parametrized case above: across the whole real fixture,
    # no row that expresses a rating at all can produce canonical 0 under this
    # mapping. That is what makes a stored 0 unambiguous -- it can now only
    # have come from a column that does not set target_min.
    mapping = ScoutRadiozFieldMapping(
        defense_rating=ScoutRadiozRatingMapping(
            column="qDefenseQuality", source_min=1, source_max=10,
            excluded_values=("0",), target_min=1,
        ),
    )
    with ScoutRadiozCsvImporter(FIXTURE_PATH) as importer:
        rows = list(importer.read_rows())
    rated = [r for r in rows if not _row_expresses_no_rating(r.raw, mapping)]
    assert rated, "fixture must contain at least one rated row for this to mean anything"
    for response in rated:
        payload = map_scoutradioz_row_to_observation_payload(response.raw, response.parsed, mapping)
        assert payload["defense_rating"] != 0


def test_target_min_applies_to_a_degenerate_source_scale_too():
    mapping = ScoutRadiozFieldMapping(
        defense_rating=ScoutRadiozRatingMapping(
            column="qDefenseQuality", source_min=5, source_max=5, target_min=1,
        ),
    )
    raw, parsed = _row()
    raw = dict(raw, qDefenseQuality="5")
    payload = map_scoutradioz_row_to_observation_payload(raw, parsed, mapping)
    assert payload["defense_rating"] == 1


@pytest.mark.parametrize("target_min", [-1, MAX_RATING, MAX_RATING + 1])
def test_out_of_range_target_min_is_rejected_at_construction(target_min):
    # Rejected where the mistake is (building the mapping), not later as a
    # confusing out-of-range rating on every single row. MAX_RATING itself is
    # rejected because it collapses the target range to a single point.
    with pytest.raises(ValueError, match="target_min"):
        ScoutRadiozRatingMapping(
            column="qDefenseQuality", source_min=1, source_max=10, target_min=target_min,
        )


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
# Opt-in per-column value exclusion (ScoutRadiozRatingMapping.excluded_values)
# ---------------------------------------------------------------------------


def test_excluded_values_defaults_off_across_the_whole_real_fixture():
    # The regression test for the exclusion feature: a mapping that does not
    # configure excluded_values must behave exactly as it did before the
    # feature existed, for every row of the real captured export -- every one
    # of the 66 rows still produces a rating, no row is ever excluded, and in
    # particular a raw "0" is still a real rating of 0, never None. If this
    # fails, the opt-in default has leaked into a global rule and
    # _rescale_rating's "0 is always a real, meaningful rating" contract is
    # broken for every other column in the project.
    with ScoutRadiozCsvImporter(FIXTURE_PATH) as importer:
        rows = list(importer.read_rows())
    assert len(rows) == 66

    zero_rows = 0
    for response in rows:
        assert _row_expresses_no_rating(response.raw, _DEFENSE_0_10) is False
        payload = map_scoutradioz_row_to_observation_payload(response.raw, response.parsed, _DEFENSE_0_10)
        assert payload["defense_rating"] is not None
        if response.raw["qDefenseQuality"] == "0":
            zero_rows += 1
            assert payload["defense_rating"] == 0

    assert zero_rows == 33  # half the real export, all still rated 0 by default


def test_configured_excluded_value_maps_the_rating_to_none():
    mapping = ScoutRadiozFieldMapping(
        defense_rating=ScoutRadiozRatingMapping(
            column="qDefenseQuality", source_min=1, source_max=10, excluded_values=("0",),
        ),
    )
    raw, parsed = _row()

    excluded = map_scoutradioz_row_to_observation_payload(dict(raw, qDefenseQuality="0"), parsed, mapping)
    assert excluded["defense_rating"] is None
    assert _row_expresses_no_rating(dict(raw, qDefenseQuality="0"), mapping) is True

    # A non-excluded value on the same column is unaffected.
    rated = map_scoutradioz_row_to_observation_payload(dict(raw, qDefenseQuality="10"), parsed, mapping)
    assert rated["defense_rating"] == 5
    assert _row_expresses_no_rating(dict(raw, qDefenseQuality="10"), mapping) is False


def test_row_is_excluded_only_when_every_configured_rating_is_excluded():
    # The reason exclusion is per-column rather than a whole-row predicate: a
    # form where defense=0 means "played no defense" but the feeding column
    # carries a genuine rating must keep the feeding observation, not discard
    # the row wholesale.
    mapping = ScoutRadiozFieldMapping(
        defense_rating=ScoutRadiozRatingMapping(
            column="qDefenseQuality", source_min=1, source_max=10, excluded_values=("0",),
        ),
        feeding_rating=ScoutRadiozRatingMapping(column="ShotPercentage", source_min=0, source_max=100),
    )
    raw, parsed = _row()
    raw = dict(raw, qDefenseQuality="0", ShotPercentage="100")

    assert _row_expresses_no_rating(raw, mapping) is False
    payload = map_scoutradioz_row_to_observation_payload(raw, parsed, mapping)
    assert payload["defense_rating"] is None
    assert payload["feeding_rating"] == 5


def test_empty_cell_is_not_an_exclusion():
    # "not recorded" and "recorded as not applicable" are different facts. An
    # empty cell keeps its pre-existing behaviour (a None rating that the
    # shared validator then rejects), rather than being silently reclassified
    # as a deliberate exclusion.
    mapping = ScoutRadiozFieldMapping(
        defense_rating=ScoutRadiozRatingMapping(
            column="qDefenseQuality", source_min=1, source_max=10, excluded_values=("0",),
        ),
    )
    raw, parsed = _row()
    raw = dict(raw, qDefenseQuality="")

    assert _row_expresses_no_rating(raw, mapping) is False
    payload = map_scoutradioz_row_to_observation_payload(raw, parsed, mapping)
    assert payload["defense_rating"] is None


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
def test_import_scoutradioz_csv_skips_a_truncated_row_without_failing_the_batch(
    database: Database, tmp_path: Path,
) -> None:
    """One short line must not cost the whole file.

    A truncated line is the one malformed shape that does not arrive as a
    string: csv.DictReader reports the columns it never reached as None, so the
    rating cell is None rather than "". Reaching int(None) raises TypeError,
    which the per-row handler does not catch (ValueError/PayloadValidationError
    only), so before this the exception escaped to the run-level handler and
    every valid row in the file was lost with it.
    """
    rows = [
        *_valid_rows(),
        # Stops after `scouter`: qDefenseQuality and superNotes are never reached.
        f"frc11,2026,{_S_EVENT},{_S_MATCH},1,8/5/2026 3:15:00 PM,blue,frc{_S_TEAM_A},Carol",
    ]
    csv_path = _write_csv(tmp_path, rows)

    result = import_scoutradioz_csv(csv_path, _DEFENSE_0_10, database=database)

    assert result.rows_read == 3
    assert result.loaded == 2  # both valid rows still imported
    assert len(result.malformed_rows) == 1
    row_number, reason = result.malformed_rows[0]
    assert row_number == 4  # header is CSV row 1, so the third data row is row 4
    # Reported as an ordinary no-rating rejection, not counted as an exclusion:
    # nothing was recorded here, which is not the same fact as a form recording
    # "not applicable" (see _row_expresses_no_rating).
    assert "rating" in reason
    assert result.excluded_rows == 0

    with database.cursor() as cursor:
        cursor.execute("SELECT count(*) FROM scouting_observations WHERE event_key = %s", (_S_EVENT,))
        (count,) = cursor.fetchone()
    assert count == 2


@requires_db
def test_import_excludes_configured_rows_and_does_not_call_them_malformed(
    database: Database, tmp_path: Path,
) -> None:
    # An excluded row is a faithful recording the mapping says carries no
    # rating -- it must be counted separately, never reported beside genuinely
    # broken rows. Checked before mapping for exactly this reason: an excluded
    # row's only rating is None, and the shared validator rejects a payload
    # with no rating at all, so mapping it first would file it as malformed.
    mapping = ScoutRadiozFieldMapping(
        defense_rating=ScoutRadiozRatingMapping(
            column="qDefenseQuality", source_min=1, source_max=10, excluded_values=("0",),
        ),
    )
    rows = [
        f"frc11,2026,{_S_EVENT},{_S_MATCH},1,8/5/2026 3:15:00 PM,red,frc{_S_TEAM_A},Alice,0,",
        f"frc11,2026,{_S_EVENT},{_S_MATCH},1,8/5/2026 3:15:00 PM,red,frc{_S_TEAM_B},Bob,10,",
    ]
    csv_path = _write_csv(tmp_path, rows)

    result = import_scoutradioz_csv(csv_path, mapping, database=database)

    assert result.rows_read == 2
    assert result.excluded_rows == 1
    assert result.loaded == 1
    assert result.malformed_rows == []  # the exclusion is NOT a malformed row

    with database.cursor() as cursor:
        cursor.execute(
            "SELECT team_number, defense_rating FROM scouting_observations WHERE event_key = %s",
            (_S_EVENT,),
        )
        stored = cursor.fetchall()
    assert stored == [(_S_TEAM_B, 5)]  # the excluded row never landed an observation


@requires_db
def test_import_with_no_excluded_values_loads_zero_as_a_real_rating(
    database: Database, tmp_path: Path,
) -> None:
    # The default-off guarantee at the import level: the same "0" row that the
    # test above excludes is loaded as a real rating of 0 when the mapping
    # configures no excluded_values.
    rows = [
        f"frc11,2026,{_S_EVENT},{_S_MATCH},1,8/5/2026 3:15:00 PM,red,frc{_S_TEAM_A},Alice,0,",
    ]
    csv_path = _write_csv(tmp_path, rows)

    result = import_scoutradioz_csv(csv_path, _DEFENSE_0_10, database=database)

    assert result.excluded_rows == 0
    assert result.loaded == 1

    with database.cursor() as cursor:
        cursor.execute(
            "SELECT team_number, defense_rating FROM scouting_observations WHERE event_key = %s",
            (_S_EVENT,),
        )
        stored = cursor.fetchall()
    assert stored == [(_S_TEAM_A, 0)]


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
