"""P5-M7 component adapters and the share detector (pure; synthetic breakdowns and shares)."""

from __future__ import annotations

import numpy as np
import pytest

from ml.features.score_breakdown import ScoreBreakdownSchemaError, UnsupportedSeasonError
from ml.features.score_components import ScoreComponents, score_components
from ml.meta.weekly import (
    TEST_EVENT_WELCH,
    TEST_ROW_WELCH,
    ComponentRow,
    ShareTable,
    clopper_pearson_upper,
    detect,
    event_week_permutation,
    holm,
    share_tables,
    weekly_distributions,
)

B2024 = {"autoPoints": 10, "autoLeavePoints": 4, "autoTotalNotePoints": 6, "teleopPoints": 30,
         "teleopTotalNotePoints": 22, "endGameTotalStagePoints": 8, "foulPoints": 5, "adjustPoints": 0,
         "totalPoints": 45}
B2026 = {"totalAutoPoints": 12, "totalTeleopPoints": 40, "endGameTowerPoints": 6, "foulPoints": 0,
         "adjustPoints": -1, "totalPoints": 51, "hubScore": {"endgamePoints": 9, "teleopPoints": 34}}


def test_components_sum_to_the_official_score():
    parts = score_components(2024, B2024)
    assert parts == ScoreComponents(auto=10, teleop=22, endgame=8, fouls=5, adjust=0, total=45)
    parts26 = score_components(2026, B2026)
    assert (parts26.teleop, parts26.endgame, parts26.adjust) == (25, 15, -1)
    assert parts26.share("endgame") == pytest.approx(15 / 51)


def test_broken_breakdowns_raise_never_zero():
    with pytest.raises(ScoreBreakdownSchemaError):
        score_components(2024, {**B2024, "endGameTotalStagePoints": 31})  # endgame above the teleop total
    with pytest.raises(ScoreBreakdownSchemaError):
        score_components(2024, {k: v for k, v in B2024.items() if k != "endGameTotalStagePoints"})
    with pytest.raises(UnsupportedSeasonError):
        score_components(2023, B2024)
    assert ScoreComponents(0, 0, 0, 0, 0, 0).share("auto") is None


def test_holm():
    assert holm([0.01, 0.04, 0.03, 0.5]) == [True, False, False, False]
    assert holm([0.001, 0.012, 0.02, 0.04]) == [True, True, True, True]


def _rows(n_events=6, per_event=10, shift_week=None) -> list[ComponentRow]:
    rng = np.random.default_rng(1)
    rows = []
    for e in range(n_events):
        week = e // 2 + 1
        for i in range(per_event):
            auto = int(rng.integers(5, 15)) + (20 if week == shift_week else 0)
            parts = ScoreComponents(auto, 30, 10, 2, 0, auto + 42)
            rows.append(ComponentRow(2024, f"2024e{e}", week, f"2024e{e}_qm{i}", "red", parts, parts.total))
    return rows


def test_test_choice_is_required():
    with pytest.raises(ValueError):
        share_tables(_rows(), None)  # type: ignore[arg-type]


@pytest.mark.parametrize("test", [TEST_ROW_WELCH, TEST_EVENT_WELCH])
def test_detector_flags_a_real_shift_with_its_effect_size(test):
    families = detect(share_tables(_rows(shift_week=3), test)[0])
    week3 = next(f for f in families if f["week"] == 3)
    auto = next(t for t in week3["tests"] if t["component"] == "auto")
    assert auto["share_difference"] > 0.1
    if test == TEST_ROW_WELCH:
        assert week3["flagged"]


def test_event_level_units_and_permutation_keep_events_whole():
    table = share_tables(_rows(), TEST_ROW_WELCH)[0]
    permuted = event_week_permutation(table, np.random.default_rng(3))
    for event in set(table.events.tolist()):
        assert len(set(permuted[table.events == event].tolist())) == 1
    assert sorted(permuted.tolist()) == sorted(table.weeks.tolist())
    event_table = share_tables(_rows(), TEST_EVENT_WELCH)[0]
    assert len(event_table.events) == 6


def test_week_w_uses_only_weeks_up_to_w():
    table = ShareTable(2024, np.array([1, 1, 2, 2, 3, 3]), np.array(list("abcdef")),
                       {c: np.array([0.1, 0.2, 0.1, 0.2, 0.9, 0.95]) for c in ("auto", "teleop", "endgame", "fouls")})
    week2 = next(f for f in detect(table) if f["week"] == 2)
    assert week2["n_earlier"] == 2 and week2["n_week"] == 2  # week 3 never enters week 2's family


def test_distributions_and_clopper_pearson():
    dist = weekly_distributions(_rows())
    assert set(dist["2024"]) == {"1", "2", "3"} and dist["2024"]["1"]["teleop"]["mean"] == 30
    assert clopper_pearson_upper(0, 100) == pytest.approx(0.0362, abs=1e-4)
    assert clopper_pearson_upper(100, 100) == 1.0
