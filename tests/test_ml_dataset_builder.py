"""Phase 4 Milestone 2 (authoritative plan): the labeled match-outcome
dataset builder, ml.dataset.builder.

Two kinds of tests here, matching this codebase's own convention
(tests/test_ml_features_assembler.py):

- Pure, DB-free tests: the Arrow-schema/pydantic-model field-name contract
  (guarding against the two independently-hand-written shapes drifting
  apart), the parquet round-trip, and content-hash determinism. These always
  run.
- A real-Postgres integration test seeding one event with a match for every
  inclusion/exclusion rule this milestone documents -- normal, tie, unplayed,
  no scheduled_time, DQ'd (with a landed raw TBA payload), surrogate (ditto),
  a match with NO raw TBA payload at all, and a playoff-level match -- so the
  milestone's own required tests (label correctness including a tie and a
  DQ, count reconciliation, idempotency) are exercised against the real
  build_match_feature_row/database path, not a mock. Skips cleanly without a
  reachable database, the same requires_db pattern M1 established.
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import psycopg
import pyarrow.parquet as pq
import pytest

from data.config import Settings
from data.landing.raw_writer import RawPayloadRecord, RawPayloadWriter
from database.connection import Database, DatabaseConfig
from ml.dataset.builder import (
    DATASET_BUILDER_VERSION,
    EXCLUSION_REASON_DQ_AFFECTED,
    EXCLUSION_REASON_DQ_STATUS_UNKNOWN,
    EXCLUSION_REASON_NO_SCHEDULED_TIME,
    EXCLUSION_REASON_UNPLAYED,
    LABEL_BLUE_WIN,
    LABEL_RED_WIN,
    LABEL_TIE,
    TRAINING_ROW_ARROW_SCHEMA,
    DatasetManifest,
    TrainingFrameResult,
    TrainingRow,
    _compute_content_hash,
    _parse_dq_and_surrogates,
    _team_numbers_from_keys,
    build_training_frame,
    persist_training_frame,
)
from ml.features.assembler import EPA_WITHHELD_NO_PRIOR_EVENT, TeamFeatures

# ---------------------------------------------------------------------------
# Pure, DB-free tests
# ---------------------------------------------------------------------------


def _blank_team_features(team_number: int) -> TeamFeatures:
    """The simplest valid TeamFeatures: every optional value absent, every
    presence flag False, consistent with TeamFeatures' own model_validator."""
    return TeamFeatures(
        team_number=team_number,
        epa_total_present=False, epa_auto_present=False, epa_teleop_present=False, epa_endgame_present=False,
        epa_withheld_reason=EPA_WITHHELD_NO_PRIOR_EVENT,
        average_score_present=False, score_stddev_present=False,
        consistency_rating_present=False, reliability_score_present=False,
        matches_considered=0, matches_used=0,
        average_auto_points_present=False, auto_points_matches_used=0,
        defense_score_present=False, defense_agreement_present=False, defense_observation_count=0,
        feeding_score_present=False, feeding_agreement_present=False, feeding_observation_count=0,
    )


def _sample_row(**overrides: object) -> TrainingRow:
    defaults = dict(
        match_key="9900zzzmldataset_qm1",
        event_key="9900zzzmldataset",
        season=9900,
        comp_level="qualification",
        set_number=None,
        match_number=1,
        scheduled_time=datetime(2026, 3, 1, 12, 0, tzinfo=timezone.utc),
        label=LABEL_RED_WIN,
        score_margin=20,
        score_red=100,
        score_blue=80,
        red_teams=[_blank_team_features(900001)],
        blue_teams=[_blank_team_features(900002)],
        red_surrogate_team_numbers=[],
        blue_surrogate_team_numbers=[],
        dq_status_known=True,
    )
    defaults.update(overrides)
    return TrainingRow(**defaults)


def test_arrow_schema_field_names_match_training_row_and_team_features():
    # Guards TRAINING_ROW_ARROW_SCHEMA (hand-written, per its own module
    # comment) against silently drifting from the pydantic models it mirrors.
    assert set(TRAINING_ROW_ARROW_SCHEMA.names) == set(TrainingRow.model_fields.keys())

    red_teams_type = TRAINING_ROW_ARROW_SCHEMA.field("red_teams").type
    team_struct = red_teams_type.value_type
    assert set(team_struct.names) == set(TeamFeatures.model_fields.keys())

    blue_teams_type = TRAINING_ROW_ARROW_SCHEMA.field("blue_teams").type
    assert set(blue_teams_type.value_type.names) == set(TeamFeatures.model_fields.keys())


def test_parquet_round_trip_preserves_row_content(tmp_path: Path):
    row = _sample_row()
    manifest = DatasetManifest(
        season_keys=[9900], include_dq_affected=False, code_version=DATASET_BUILDER_VERSION,
        build_date=datetime.now(timezone.utc), row_count=1, excluded_count=0,
        excluded_by_reason={}, content_hash="deadbeef" * 4,
    )
    result = TrainingFrameResult(rows=[row], excluded=[], manifest=manifest)

    persisted = persist_training_frame(result, tmp_path)

    assert persisted.parquet_path.exists()
    assert persisted.manifest_path.exists()

    table = pq.read_table(persisted.parquet_path)
    assert table.num_rows == 1
    read_back = table.to_pylist()[0]
    assert read_back["match_key"] == row.match_key
    assert read_back["label"] == LABEL_RED_WIN
    assert read_back["score_margin"] == 20
    assert len(read_back["red_teams"]) == 1
    assert read_back["red_teams"][0]["team_number"] == 900001
    assert read_back["red_teams"][0]["epa_total_present"] is False

    manifest_on_disk = DatasetManifest.model_validate_json(persisted.manifest_path.read_text(encoding="utf-8"))
    assert manifest_on_disk == manifest


def test_parquet_round_trip_handles_zero_rows(tmp_path: Path):
    # The explicit TRAINING_ROW_ARROW_SCHEMA exists specifically so an empty
    # result (a season with nothing synced, or everything excluded) persists
    # a valid, readable artifact instead of crashing on schema inference from
    # zero rows.
    manifest = DatasetManifest(
        season_keys=[9900], include_dq_affected=False, code_version=DATASET_BUILDER_VERSION,
        build_date=datetime.now(timezone.utc), row_count=0, excluded_count=0,
        excluded_by_reason={}, content_hash="0" * 32,
    )
    result = TrainingFrameResult(rows=[], excluded=[], manifest=manifest)

    persisted = persist_training_frame(result, tmp_path)

    table = pq.read_table(persisted.parquet_path)
    assert table.num_rows == 0
    assert set(table.column_names) == set(TrainingRow.model_fields.keys())


def test_content_hash_deterministic_and_excludes_build_date():
    row = _sample_row()
    hash_a = _compute_content_hash([2024], False, [row])
    hash_b = _compute_content_hash([2024], False, [row])
    assert hash_a == hash_b

    # Season order must not matter -- [2024, 2026] and [2026, 2024] are the
    # same logical request.
    hash_forward = _compute_content_hash([2024, 2026], False, [row])
    hash_backward = _compute_content_hash([2026, 2024], False, [row])
    assert hash_forward == hash_backward

    # A different include_dq_affected setting is a materially different
    # build and must hash differently even over identical rows.
    hash_dq_included = _compute_content_hash([2024], True, [row])
    assert hash_dq_included != hash_a

    # A different row must hash differently.
    other_row = _sample_row(match_key="different_match", label=LABEL_BLUE_WIN, score_margin=-5)
    hash_other = _compute_content_hash([2024], False, [other_row])
    assert hash_other != hash_a


def test_training_row_rejects_unknown_label():
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        _sample_row(label="red_definitely_wins")


def test_team_numbers_from_keys_parses_and_collapses_b_teams():
    assert _team_numbers_from_keys(["frc1114", "frc254", "frc9999"]) == [1114, 254, 9999]
    # Off-season second-robot suffix collapses to the parent team number,
    # exactly as data.staging.normalizer.parse_tba_team_number documents.
    assert _team_numbers_from_keys(["frc254b"]) == [254]


def test_team_numbers_from_keys_skips_malformed_entries_without_raising():
    # parse_tba_team_number's pattern is start-anchored only (^frc(\d+)), so
    # "frc0extra!" still parses as team 0 -- that's pre-existing, shared
    # behavior this test must not assume away. A key that doesn't start with
    # "frc<digits>" at all is the genuine parse-failure case this function
    # exists to survive.
    assert _team_numbers_from_keys(["frc1114", "not-a-team-key", "12345"]) == [1114]
    assert _team_numbers_from_keys([]) == []


def test_parse_dq_and_surrogates_extracts_all_four_lists():
    payload = {
        "alliances": {
            "red": {
                "score": 100, "team_keys": ["frc1", "frc2", "frc3"],
                "dq_team_keys": ["frc2"], "surrogate_team_keys": [],
            },
            "blue": {
                "score": 80, "team_keys": ["frc4", "frc5", "frc6"],
                "dq_team_keys": [], "surrogate_team_keys": ["frc5"],
            },
        },
    }
    red_dq, blue_dq, red_surrogate, blue_surrogate = _parse_dq_and_surrogates(payload)
    assert red_dq == [2]
    assert blue_dq == []
    assert red_surrogate == []
    assert blue_surrogate == [5]


def test_parse_dq_and_surrogates_defensive_against_missing_and_null_shapes():
    # Missing keys entirely -- a hand-built/older-shaped payload.
    assert _parse_dq_and_surrogates({"alliances": {"red": {}, "blue": {}}}) == ([], [], [], [])
    # Explicit nulls at every nesting level -- not just absent keys.
    assert _parse_dq_and_surrogates({"alliances": None}) == ([], [], [], [])
    assert _parse_dq_and_surrogates({"alliances": {"red": None, "blue": None}}) == ([], [], [], [])
    assert _parse_dq_and_surrogates({}) == ([], [], [], [])
    assert _parse_dq_and_surrogates(None) == ([], [], [], [])


# ---------------------------------------------------------------------------
# Real-Postgres integration test
# ---------------------------------------------------------------------------

_SEASON = 9986
_EVENT = "9986zzzmldataset"

_TEAM_A = 986001  # plays the leakage-check matches
_FILLERS = [986011, 986012, 986013, 986014, 986015, 986016, 986017, 986018]
_ALL_TEAMS = [_TEAM_A, *_FILLERS]

_T_EARLY = datetime(2026, 4, 1, 9, 0, tzinfo=timezone.utc)
_T_NORMAL = datetime(2026, 4, 1, 10, 0, tzinfo=timezone.utc)
_T_TIE = datetime(2026, 4, 1, 10, 30, tzinfo=timezone.utc)
_T_DQ = datetime(2026, 4, 1, 11, 0, tzinfo=timezone.utc)
_T_SURROGATE = datetime(2026, 4, 1, 11, 30, tzinfo=timezone.utc)
_T_UNKNOWN_PAYLOAD = datetime(2026, 4, 1, 12, 0, tzinfo=timezone.utc)
_T_PLAYOFF = datetime(2026, 4, 1, 13, 0, tzinfo=timezone.utc)
_T_AFTER = datetime(2026, 4, 1, 14, 0, tzinfo=timezone.utc)  # after every as_of used below
_T_UNPLAYED = datetime(2026, 4, 1, 9, 45, tzinfo=timezone.utc)

_QM_EARLY = f"{_EVENT}_qm1"       # Team A, before -- feeds Team A's own history
_QM_NORMAL = f"{_EVENT}_qm2"      # Team A, THE leakage-check target row
_QM_TIE = f"{_EVENT}_qm3"         # a genuine tie
_QM_UNPLAYED = f"{_EVENT}_qm4"    # no score
_QM_NO_TIME = f"{_EVENT}_qm5"     # no scheduled_time
_QM_DQ = f"{_EVENT}_qm6"          # red team disqualified
_QM_SURROGATE = f"{_EVENT}_qm7"   # blue team is a surrogate
_QM_UNKNOWN = f"{_EVENT}_qm8"     # no raw TBA payload landed at all
_SF_PLAYOFF = f"{_EVENT}_sf1"     # playoff-level match
_QM_AFTER = f"{_EVENT}_qm9"       # Team A, AFTER as_of -- must never leak into qm2's row

_ALL_MATCH_KEYS = [
    _QM_EARLY, _QM_NORMAL, _QM_TIE, _QM_UNPLAYED, _QM_NO_TIME,
    _QM_DQ, _QM_SURROGATE, _QM_UNKNOWN, _SF_PLAYOFF, _QM_AFTER,
]


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
            "DELETE FROM raw_source_payloads WHERE source = 'tba' AND source_object_type = 'match' "
            "AND source_object_id = ANY(%s::text[])",
            (_ALL_MATCH_KEYS,),
        )
        cursor.execute("DELETE FROM match_teams WHERE match_key = ANY(%s::text[])", (_ALL_MATCH_KEYS,))
        cursor.execute("DELETE FROM matches WHERE event_key = %s", (_EVENT,))
        cursor.execute("DELETE FROM teams WHERE team_number = ANY(%s::int[])", (_ALL_TEAMS,))
        cursor.execute("DELETE FROM events WHERE event_key = %s", (_EVENT,))


def _insert_match(
    database: Database, match_key: str, *, comp_level: str, match_number: int,
    scheduled_time: datetime | None, red_teams: list[int], blue_teams: list[int],
    score_red: int | None, score_blue: int | None, winning_alliance: str | None,
) -> None:
    with database.cursor() as cursor:
        cursor.execute(
            """
            INSERT INTO matches (
                match_key, event_key, season, competition_level, match_number,
                scheduled_time, score_red, score_blue, winning_alliance
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
            """,
            (match_key, _EVENT, _SEASON, comp_level, match_number, scheduled_time, score_red, score_blue, winning_alliance),
        )
        for alliance_color, team_numbers in (("red", red_teams), ("blue", blue_teams)):
            for position, team_number in enumerate(team_numbers, start=1):
                cursor.execute(
                    "INSERT INTO match_teams (match_key, team_number, alliance_color, station_position) "
                    "VALUES (%s, %s, %s, %s)",
                    (match_key, team_number, alliance_color, position),
                )


def _land_raw_tba_payload(
    database: Database, match_key: str, *, red_teams: list[int], blue_teams: list[int],
    score_red: int, score_blue: int, winning_alliance: str,
    red_dq: list[int] | None = None, blue_dq: list[int] | None = None,
    red_surrogate: list[int] | None = None, blue_surrogate: list[int] | None = None,
) -> None:
    """Land a raw TBA match payload shaped like a real TBA API response,
    reusing the production RawPayloadWriter rather than hand-writing the
    INSERT -- the same landing path a real sync uses."""
    payload = {
        "key": match_key,
        "event_key": _EVENT,
        "comp_level": "qm",
        "alliances": {
            "red": {
                "score": score_red,
                "team_keys": [f"frc{t}" for t in red_teams],
                "dq_team_keys": [f"frc{t}" for t in (red_dq or [])],
                "surrogate_team_keys": [f"frc{t}" for t in (red_surrogate or [])],
            },
            "blue": {
                "score": score_blue,
                "team_keys": [f"frc{t}" for t in blue_teams],
                "dq_team_keys": [f"frc{t}" for t in (blue_dq or [])],
                "surrogate_team_keys": [f"frc{t}" for t in (blue_surrogate or [])],
            },
        },
        "winning_alliance": winning_alliance,
    }
    RawPayloadWriter(database).write(
        RawPayloadRecord(source="tba", source_object_type="match", source_object_id=match_key, payload=payload),
    )


@pytest.fixture
def database() -> Database:
    from database.migrate import run_migrations

    settings = Settings()
    run_migrations(settings)
    db = Database(DatabaseConfig(settings.database_url))
    _cleanup(db)

    with db.cursor() as cursor:
        cursor.execute("INSERT INTO events (event_key, season, name) VALUES (%s, %s, %s)", (_EVENT, _SEASON, "Sentinel Dataset Event"))
        for team_number in _ALL_TEAMS:
            cursor.execute("INSERT INTO teams (team_number, name) VALUES (%s, %s)", (team_number, f"Sentinel {team_number}"))

    # qm1: Team A's own history, before every as_of used below.
    _insert_match(
        db, _QM_EARLY, comp_level="qualification", match_number=1, scheduled_time=_T_EARLY,
        red_teams=[_TEAM_A, *_FILLERS[0:2]], blue_teams=_FILLERS[2:5],
        score_red=50, score_blue=40, winning_alliance="red",
    )
    _land_raw_tba_payload(
        db, _QM_EARLY, red_teams=[_TEAM_A, *_FILLERS[0:2]], blue_teams=_FILLERS[2:5],
        score_red=50, score_blue=40, winning_alliance="red",
    )

    # qm2: THE target row -- Team A, normal match, no DQ/surrogate.
    _insert_match(
        db, _QM_NORMAL, comp_level="qualification", match_number=2, scheduled_time=_T_NORMAL,
        red_teams=[_TEAM_A, *_FILLERS[0:2]], blue_teams=_FILLERS[2:5],
        score_red=100, score_blue=80, winning_alliance="red",
    )
    _land_raw_tba_payload(
        db, _QM_NORMAL, red_teams=[_TEAM_A, *_FILLERS[0:2]], blue_teams=_FILLERS[2:5],
        score_red=100, score_blue=80, winning_alliance="red",
    )

    # qm3: a genuine tie.
    _insert_match(
        db, _QM_TIE, comp_level="qualification", match_number=3, scheduled_time=_T_TIE,
        red_teams=_FILLERS[0:3], blue_teams=_FILLERS[3:6],
        score_red=90, score_blue=90, winning_alliance="tie",
    )
    _land_raw_tba_payload(
        db, _QM_TIE, red_teams=_FILLERS[0:3], blue_teams=_FILLERS[3:6],
        score_red=90, score_blue=90, winning_alliance="tie",
    )

    # qm4: unplayed -- no score at all.
    _insert_match(
        db, _QM_UNPLAYED, comp_level="qualification", match_number=4, scheduled_time=_T_UNPLAYED,
        red_teams=_FILLERS[0:3], blue_teams=_FILLERS[3:6],
        score_red=None, score_blue=None, winning_alliance=None,
    )

    # qm5: no scheduled_time at all.
    _insert_match(
        db, _QM_NO_TIME, comp_level="qualification", match_number=5, scheduled_time=None,
        red_teams=_FILLERS[0:3], blue_teams=_FILLERS[3:6],
        score_red=60, score_blue=50, winning_alliance="red",
    )

    # qm6: red's filler-0 team disqualified.
    _insert_match(
        db, _QM_DQ, comp_level="qualification", match_number=6, scheduled_time=_T_DQ,
        red_teams=_FILLERS[0:3], blue_teams=_FILLERS[3:6],
        score_red=120, score_blue=30, winning_alliance="blue",
    )
    _land_raw_tba_payload(
        db, _QM_DQ, red_teams=_FILLERS[0:3], blue_teams=_FILLERS[3:6],
        score_red=120, score_blue=30, winning_alliance="blue", red_dq=[_FILLERS[0]],
    )

    # qm7: blue's filler-3 team is a surrogate, no DQ.
    _insert_match(
        db, _QM_SURROGATE, comp_level="qualification", match_number=7, scheduled_time=_T_SURROGATE,
        red_teams=_FILLERS[0:3], blue_teams=_FILLERS[3:6],
        score_red=70, score_blue=95, winning_alliance="blue",
    )
    _land_raw_tba_payload(
        db, _QM_SURROGATE, red_teams=_FILLERS[0:3], blue_teams=_FILLERS[3:6],
        score_red=70, score_blue=95, winning_alliance="blue", blue_surrogate=[_FILLERS[3]],
    )

    # qm8: played, but no raw TBA payload was ever landed for it.
    _insert_match(
        db, _QM_UNKNOWN, comp_level="qualification", match_number=8, scheduled_time=_T_UNKNOWN_PAYLOAD,
        red_teams=_FILLERS[0:3], blue_teams=_FILLERS[3:6],
        score_red=55, score_blue=44, winning_alliance="red",
    )

    # sf1: a playoff-level match.
    _insert_match(
        db, _SF_PLAYOFF, comp_level="semifinal", match_number=1, scheduled_time=_T_PLAYOFF,
        red_teams=_FILLERS[0:3], blue_teams=_FILLERS[3:6],
        score_red=200, score_blue=150, winning_alliance="red",
    )
    _land_raw_tba_payload(
        db, _SF_PLAYOFF, red_teams=_FILLERS[0:3], blue_teams=_FILLERS[3:6],
        score_red=200, score_blue=150, winning_alliance="red",
    )

    # qm9: Team A, AFTER every as_of exercised -- an extreme decoy score that
    # must never leak into qm2's own feature row.
    _insert_match(
        db, _QM_AFTER, comp_level="qualification", match_number=9, scheduled_time=_T_AFTER,
        red_teams=[_TEAM_A, *_FILLERS[0:2]], blue_teams=_FILLERS[2:5],
        score_red=999, score_blue=1, winning_alliance="red",
    )
    _land_raw_tba_payload(
        db, _QM_AFTER, red_teams=[_TEAM_A, *_FILLERS[0:2]], blue_teams=_FILLERS[2:5],
        score_red=999, score_blue=1, winning_alliance="red",
    )

    try:
        yield db
    finally:
        _cleanup(db)


@requires_db
def test_count_reconciliation_every_match_is_included_or_excluded_exactly_once(database: Database):
    result = build_training_frame(database, [_SEASON])
    assert result.manifest.row_count + result.manifest.excluded_count == len(_ALL_MATCH_KEYS)
    seen_keys = {row.match_key for row in result.rows} | {item.match_key for item in result.excluded}
    assert seen_keys == set(_ALL_MATCH_KEYS)


@requires_db
def test_exclusion_reasons_are_correct(database: Database):
    result = build_training_frame(database, [_SEASON])
    excluded_by_key = {item.match_key: item.reason for item in result.excluded}

    assert excluded_by_key[_QM_UNPLAYED] == EXCLUSION_REASON_UNPLAYED
    assert excluded_by_key[_QM_NO_TIME] == EXCLUSION_REASON_NO_SCHEDULED_TIME
    assert excluded_by_key[_QM_DQ] == EXCLUSION_REASON_DQ_AFFECTED
    assert excluded_by_key[_QM_UNKNOWN] == EXCLUSION_REASON_DQ_STATUS_UNKNOWN

    # Everything else must have been included.
    included_keys = {row.match_key for row in result.rows}
    for key in (_QM_EARLY, _QM_NORMAL, _QM_TIE, _QM_SURROGATE, _SF_PLAYOFF, _QM_AFTER):
        assert key in included_keys, f"{key} should have been included"


@requires_db
def test_tie_is_labeled_and_kept_not_dropped(database: Database):
    result = build_training_frame(database, [_SEASON])
    tie_row = next(row for row in result.rows if row.match_key == _QM_TIE)
    assert tie_row.label == LABEL_TIE
    assert tie_row.score_margin == 0


@requires_db
def test_dq_affected_excluded_by_default_and_included_with_flag(database: Database):
    default_result = build_training_frame(database, [_SEASON])
    assert _QM_DQ not in {row.match_key for row in default_result.rows}

    included_result = build_training_frame(database, [_SEASON], include_dq_affected=True)
    dq_row = next(row for row in included_result.rows if row.match_key == _QM_DQ)
    assert dq_row.label == LABEL_BLUE_WIN
    assert dq_row.dq_status_known is True


@requires_db
def test_dq_status_unknown_excluded_by_default_and_included_with_flag(database: Database):
    default_result = build_training_frame(database, [_SEASON])
    assert _QM_UNKNOWN not in {row.match_key for row in default_result.rows}

    included_result = build_training_frame(database, [_SEASON], include_dq_affected=True)
    unknown_row = next(row for row in included_result.rows if row.match_key == _QM_UNKNOWN)
    assert unknown_row.dq_status_known is False


@requires_db
def test_surrogate_is_recorded_but_not_excluded(database: Database):
    result = build_training_frame(database, [_SEASON])
    surrogate_row = next(row for row in result.rows if row.match_key == _QM_SURROGATE)
    assert surrogate_row.blue_surrogate_team_numbers == [_FILLERS[3]]
    assert surrogate_row.red_surrogate_team_numbers == []
    assert surrogate_row.label == LABEL_BLUE_WIN


@requires_db
def test_playoff_match_is_kept_and_tagged(database: Database):
    result = build_training_frame(database, [_SEASON])
    playoff_row = next(row for row in result.rows if row.match_key == _SF_PLAYOFF)
    assert playoff_row.comp_level == "semifinal"


@requires_db
def test_no_leakage_features_are_point_in_time_label_is_from_final_score(database: Database):
    result = build_training_frame(database, [_SEASON])
    target_row = next(row for row in result.rows if row.match_key == _QM_NORMAL)

    # Label/score come from the match's own final recorded result.
    assert target_row.label == LABEL_RED_WIN
    assert target_row.score_red == 100
    assert target_row.score_blue == 80
    assert target_row.score_margin == 20

    # Features must reflect only qm1 (score 50) for Team A, never qm9's
    # decoy extreme score of 999 -- qm9 is scheduled strictly after qm2.
    team_a_features = next(t for t in target_row.red_teams if t.team_number == _TEAM_A)
    assert team_a_features.average_score == 50.0


@requires_db
def test_idempotent_rebuild_produces_identical_content_hash(database: Database):
    first = build_training_frame(database, [_SEASON])
    second = build_training_frame(database, [_SEASON])
    assert first.manifest.content_hash == second.manifest.content_hash
    assert first.manifest.row_count == second.manifest.row_count


@requires_db
def test_empty_season_keys_returns_empty_valid_result(database: Database):
    result = build_training_frame(database, [])
    assert result.rows == []
    assert result.excluded == []
    assert result.manifest.row_count == 0


@requires_db
def test_persist_real_build_round_trips_through_parquet(database: Database, tmp_path: Path):
    result = build_training_frame(database, [_SEASON])
    persisted = persist_training_frame(result, tmp_path)
    table = pq.read_table(persisted.parquet_path)
    assert table.num_rows == result.manifest.row_count
