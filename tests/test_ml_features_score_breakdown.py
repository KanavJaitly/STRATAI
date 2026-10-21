"""Phase 4 Milestone 11: season-aware score_breakdown adapters.

Fixtures are real TBA alliance breakdowns captured from this database
(tests/fixtures/tba_score_breakdown_{2024,2025,2026}.json, provenance inside).
The requires_db test runs the adapter over every real alliance-row.
"""

from __future__ import annotations

import copy
import json
from pathlib import Path

import psycopg
import pytest

from data.config import Settings
from ml.features.score_breakdown import (
    SUPPORTED_SEASONS,
    ScoreBreakdownSchemaError,
    UnsupportedSeasonError,
    auto_points,
)

FIXTURES = Path(__file__).parent / "fixtures"


def breakdown(season: int) -> dict:
    return json.loads((FIXTURES / f"tba_score_breakdown_{season}.json").read_text(encoding="utf-8"))["alliance_breakdown"]


# Each season's auto-period components, named independently of the adapter:
# the logical definition the adapter must reproduce under each schema.
AUTO_COMPONENTS = {
    2024: lambda b: b["autoLeavePoints"] + b["autoTotalNotePoints"],
    2025: lambda b: b["autoMobilityPoints"] + b["autoCoralPoints"],
    2026: lambda b: b["hubScore"]["autoPoints"] + b["autoTowerPoints"],
}
TELEOP = {2024: "teleopPoints", 2025: "teleopPoints", 2026: "totalTeleopPoints"}


def test_every_training_and_held_out_season_is_supported():
    assert SUPPORTED_SEASONS == {2024, 2025, 2026}  # decision D7's split: 2024+2025 train, 2026 held out


@pytest.mark.parametrize("season", [2024, 2025, 2026])
def test_cross_season_parity_auto_points_is_the_auto_period_under_every_schema(season):
    b = breakdown(season)
    value = auto_points(season, b)
    assert value == AUTO_COMPONENTS[season](b)
    assert value == b["totalPoints"] - b[TELEOP[season]] - b["foulPoints"] - b.get("adjustPoints", 0)
    assert b["foulPoints"] > 0  # the fixtures were chosen so penalties are provably excluded


def test_2026_name_alike_field_is_not_the_logical_feature():
    b = breakdown(2026)
    assert b["autoTowerPoints"] > 0
    assert auto_points(2026, b) == b["totalAutoPoints"] != b["hubScore"]["autoPoints"]


@pytest.mark.parametrize("season", [2023, 2027, 1992, 9989])
def test_unsupported_season_raises_a_clear_error_never_a_zero(season):
    with pytest.raises(UnsupportedSeasonError, match=f"season {season}") as raised:
        auto_points(season, breakdown(2024))
    assert raised.value.season == season


@pytest.mark.parametrize("data_season, read_as", [(2024, 2026), (2026, 2024), (2026, 2025)])
def test_an_unseen_schema_for_a_supported_season_fails_loudly(data_season, read_as):
    with pytest.raises(ScoreBreakdownSchemaError):
        auto_points(read_as, breakdown(data_season))


@pytest.mark.parametrize("field, value", [
    ("autoPoints", None), ("autoPoints", "34"), ("autoPoints", True), ("autoPoints", -1), ("autoPoints", 34.5),
    ("foulPoints", None), ("totalPoints", "x"), ("adjustPoints", "0"),
])
def test_malformed_values_are_rejected(field, value):
    b = copy.deepcopy(breakdown(2024))
    b[field] = value
    with pytest.raises(ScoreBreakdownSchemaError):
        auto_points(2024, b)


def test_missing_field_is_rejected():
    b = copy.deepcopy(breakdown(2026))
    del b["totalAutoPoints"]
    with pytest.raises(ScoreBreakdownSchemaError, match="totalAutoPoints"):
        auto_points(2026, b)


def test_a_broken_decomposition_is_schema_drift_not_a_number():
    b = copy.deepcopy(breakdown(2025))
    b["totalPoints"] += 1
    with pytest.raises(ScoreBreakdownSchemaError, match="decomposition"):
        auto_points(2025, b)


@pytest.mark.parametrize("value", [None, [], "breakdown", 3])
def test_non_mapping_breakdown_is_rejected(value):
    with pytest.raises(ScoreBreakdownSchemaError):
        auto_points(2024, value)


@pytest.mark.parametrize("season", [2024, 2025, 2026])
def test_raw_body_is_never_modified(season):
    b = breakdown(season)
    before = copy.deepcopy(b)
    auto_points(season, b)
    assert b == before


def _database_available() -> bool:
    try:
        with psycopg.connect(str(Settings().database_url), connect_timeout=3):
            return True
    except Exception:
        return False


@pytest.mark.skipif(not _database_available(), reason="Requires a reachable PostgreSQL database")
def test_adapter_resolves_every_real_alliance_breakdown_and_matches_the_official_score():
    checked = {2024: 0, 2025: 0, 2026: 0}
    with psycopg.connect(str(Settings().database_url)) as connection:
        with connection.cursor(name="m11_parity") as cursor:
            cursor.itersize = 2000
            cursor.execute("""
                SELECT substr(source_object_id, 1, 4)::int, payload_json->'score_breakdown', payload_json->'alliances'
                FROM raw_source_payloads
                WHERE source = 'tba' AND source_object_type = 'match' AND is_current
                  AND substr(source_object_id, 1, 4) IN ('2024', '2025', '2026')
                  AND jsonb_typeof(payload_json->'score_breakdown') = 'object'
            """)
            for season, sb, alliances in cursor:
                for color in ("red", "blue"):
                    b = sb[color]
                    value = auto_points(season, b)
                    assert value == AUTO_COMPONENTS[season](b)
                    assert b["totalPoints"] == alliances[color]["score"]
                    checked[season] += 1
    if sum(checked.values()) == 0:
        pytest.skip("no TBA match payloads synced")
    assert all(count > 0 for count in checked.values()), checked
