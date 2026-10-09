"""PX-1b (`.agent/phase6/P6_M2_PX1B_SPEC.md`): the normalization, its edge cases, and the causality of its scales.

Pure and SYNTHETIC: no database, no real playoff data, not evidence.
"""

from __future__ import annotations

import math
from datetime import datetime, timedelta, timezone

import numpy as np
import pytest

from ml.features.scale import MIN_ALLIANCE_SCORES, ScaleLookup, _Timeline
from ml.models.team_vector import TEAM_FEATURE_NAMES
from ml.playoffs.px1 import PlayoffLogisticModel, PlayoffRow, composition_difference
from ml.playoffs.px1b import (SCALE_ABSENT, dataset_fingerprint, development_decision, drop_scale_absent,
                              valid_scale)
from tests.phase6_fixtures import team
from tests.test_phase6_px1 import synthetic_rows

T0 = datetime(2099, 3, 1, 12, tzinfo=timezone.utc)
POINT_FIELDS = {"epa_total": "epa", "epa_auto": "epa", "epa_teleop": "epa", "epa_endgame": "epa",
                "average_score": "score", "score_stddev": "score", "average_auto_points": "score"}


def _team(number: int, *, epa_scale: float | None = 10.0, score_scale: float | None = 40.0, **extra):
    values = dict(average_score=60.0 + number % 7, average_score_present=True, score_stddev=9.0,
                  score_stddev_present=True, consistency_rating=70.0, consistency_rating_present=True,
                  average_auto_points=12.0, average_auto_points_present=True, matches_used=8, matches_considered=8)
    values.update(extra)
    return team(number, 4.0 + number % 3, 15.0, 6.0, epa_scale=epa_scale, score_scale=score_scale, **values)


def _row(red, blue, *, red_win: bool = True, key: str = "m1") -> PlayoffRow:
    return PlayoffRow(key, "2099x", 2099, T0, 1, 1, 4, tuple(red), tuple(blue), red_win)


# --- §2: the transformation -----------------------------------------------------------------------------------


def test_normalized_composition_divides_each_point_field_by_its_own_scale_before_summing():
    red = [_team(1, epa_scale=10.0, score_scale=40.0), _team(2, epa_scale=20.0, score_scale=40.0),
           _team(3, epa_scale=10.0, score_scale=40.0)]  # team 2's EPA from an earlier season: its own scale
    blue = [_team(4), _team(5), _team(6)]
    normalized = composition_difference(red, blue, normalized=True)
    raw_teams = {t.team_number: t for t in (*red, *blue)}
    for name, kind in POINT_FIELDS.items():
        i = TEAM_FEATURE_NAMES.index(name)

        def side(teams):
            return sum(getattr(t, name) / (t.epa_scale if kind == "epa" else t.score_scale) for t in teams)
        assert normalized[i] == pytest.approx(side(red) - side(blue))
    for name in ("consistency_rating", "matches_used", "matches_considered"):  # unit-free: unchanged
        i = TEAM_FEATURE_NAMES.index(name)
        assert normalized[i] == pytest.approx(composition_difference(red, blue)[i])
    assert raw_teams  # the inputs are not mutated


def test_a_uniform_change_of_scoring_scale_leaves_the_normalized_features_unchanged():
    """The property H-PX1b relies on: a season with every point value k times larger, and scales k times larger,
    gives the same normalized composition, while the raw composition grows k times."""
    def scaled(n, k):
        t = _team(n)
        return team(n, t.epa_auto * k, t.epa_teleop * k, t.epa_endgame * k, epa_scale=10.0 * k,
                    score_scale=40.0 * k, average_score=t.average_score * k, average_score_present=True,
                    score_stddev=9.0 * k, score_stddev_present=True, consistency_rating=70.0,
                    consistency_rating_present=True, average_auto_points=12.0 * k, average_auto_points_present=True,
                    matches_used=8, matches_considered=8)
    base = composition_difference([scaled(n, 1) for n in (1, 2, 3)], [scaled(n, 1) for n in (4, 5, 6)],
                                  normalized=True)
    big = composition_difference([scaled(n, 4) for n in (1, 2, 3)], [scaled(n, 4) for n in (4, 5, 6)],
                                 normalized=True)
    raw = composition_difference([scaled(n, 4) for n in (1, 2, 3)], [scaled(n, 4) for n in (4, 5, 6)])
    raw_base = composition_difference([scaled(n, 1) for n in (1, 2, 3)], [scaled(n, 1) for n in (4, 5, 6)])
    assert np.allclose(base, big, equal_nan=True)
    i = TEAM_FEATURE_NAMES.index("epa_total")
    assert raw[i] == pytest.approx(4 * raw_base[i])


def test_px1_is_unchanged_by_the_option_and_px1b_round_trips():
    rows = synthetic_rows(300, 5)
    px1 = PlayoffLogisticModel.fit(rows)
    assert "normalized" not in px1.to_dict()["design"] and px1.to_dict()["spec"].endswith("P6_M2_PX1_SPEC.md")
    assert np.allclose(composition_difference(rows[0].red_teams, rows[0].blue_teams),
                       composition_difference(rows[0].red_teams, rows[0].blue_teams, normalized=False),
                       equal_nan=True)
    px1b = PlayoffLogisticModel.fit(rows, normalized=True, model_type="playoff_px1b")
    assert px1b.design.normalized and px1b.to_dict()["spec"].endswith("P6_M2_PX1B_SPEC.md")
    assert px1b.model_type == "playoff_px1b"
    for row in rows[:40]:
        assert abs(px1b.predict(row) + px1b.predict(row.swapped()) - 1.0) <= 1e-12  # antisymmetric


def test_px1b_save_load_keeps_the_normalization(tmp_path):
    rows = synthetic_rows(300, 6)
    px1b = PlayoffLogisticModel.fit(rows, normalized=True)
    path = tmp_path / "m.json"
    px1b.save(path)
    loaded = PlayoffLogisticModel.load(path)
    assert loaded.design.normalized and loaded.predict(rows[3]) == px1b.predict(rows[3])


def test_the_seed_only_comparator_never_normalizes_or_adds_columns():
    model = PlayoffLogisticModel.fit(synthetic_rows(300, 7), seed_only=True, normalized=True)
    assert model.design.names() == ["seed_difference"] and not model.design.normalized


# --- §1.3: scale edge cases -----------------------------------------------------------------------------------


@pytest.mark.parametrize("value, present, ok", [
    (25.0, True, True), (None, True, False), (25.0, False, False), (0.0, True, False), (-3.0, True, False),
    (math.nan, True, False), (math.inf, True, False)])
def test_a_scale_is_valid_only_when_present_finite_and_positive(value, present, ok):
    assert valid_scale(value, present) is ok


def test_rows_with_an_absent_or_invalid_scale_are_excluded_and_counted():
    good = _row([_team(1), _team(2), _team(3)], [_team(4), _team(5), _team(6)], key="good")
    no_epa_scale = _row([_team(1, epa_scale=None), _team(2), _team(3)], [_team(4), _team(5), _team(6)], key="a")
    # TeamFeatures itself refuses a scale <= 0; model_copy bypasses that to exercise PX-1b's own check
    zero = _team(6).model_copy(update={"score_scale": 0.0})
    zero_scale = _row([_team(1), _team(2), _team(3)], [_team(4), _team(5), zero], key="b")
    kept, excluded = drop_scale_absent([good, no_epa_scale, zero_scale])
    assert [r.match_key for r in kept] == ["good"] and excluded == {SCALE_ABSENT: 2}
    assert drop_scale_absent([good]) == ([good], {})


# --- §3: causality of the scales ------------------------------------------------------------------------------


def _timeline(n: int, *, start: datetime = T0, score: int = 50):
    return [(start + timedelta(minutes=i), score + (i % 9), score - (i % 5)) for i in range(n)]


def test_score_scale_uses_only_matches_strictly_before_the_prediction_time():
    rows = _timeline(300)
    as_of = rows[200][0]  # exactly 200 matches (400 alliance scores) precede it
    before_only = _Timeline(rows[:200]).scale(None)
    assert _Timeline(rows).scale(as_of) == pytest.approx(before_only)  # the match AT as_of is excluded
    # any later result -- including a wildly different playoff score -- cannot change the scale at as_of
    future = rows + [(as_of + timedelta(hours=1), 999, 0), (as_of, 999, 0)]
    future.sort(key=lambda r: r[0])
    assert _Timeline(future).scale(as_of) == pytest.approx(before_only)


def test_score_scale_is_absent_below_the_minimum_sample():
    rows = _timeline(MIN_ALLIANCE_SCORES // 2)  # 2 alliance scores per match
    assert _Timeline(rows).scale(None) is not None
    assert _Timeline(rows).scale(rows[-1][0]) is None  # one match fewer: below the minimum


class _StubScales(ScaleLookup):
    def __init__(self, seasons: dict[str, int], scales: dict[tuple[int, object], float]) -> None:
        self._seasons, self._scales, self.calls = seasons, scales, []

    def event_season(self, event_key):
        return self._seasons.get(event_key)

    def season_scale(self, season, before):
        self.calls.append((season, before))
        return self._scales.get((season, before))


def test_epa_scale_follows_the_season_the_epa_measures_and_never_a_later_one():
    as_of = T0
    stub = _StubScales({"2099a": 2099, "2098z": 2098, "2100q": 2100},
                       {(2099, as_of): 90.0, (2098, None): 40.0})
    assert stub.feature_scales(2099, as_of, "2099a") == (90.0, 90.0)  # same season: S(Y, as_of)
    assert stub.feature_scales(2099, as_of, "2098z") == (90.0, 40.0)  # earlier season: the whole, concluded season
    assert stub.feature_scales(2099, as_of, "2100q") == (90.0, None)  # later season: never used
    assert stub.feature_scales(2099, as_of, None) == (90.0, None)
    assert all(before is None or before == as_of for _, before in stub.calls)  # never a time after as_of


# --- §7: reproducibility and §5's decision rule -----------------------------------------------------------------


def test_dataset_fingerprint_is_order_free_and_sensitive_to_labels_and_scales():
    a = _row([_team(1), _team(2), _team(3)], [_team(4), _team(5), _team(6)], key="a")
    b = _row([_team(7), _team(8), _team(9)], [_team(10), _team(11), _team(12)], key="b")
    assert dataset_fingerprint([a, b]) == dataset_fingerprint([b, a])
    flipped = _row([_team(1), _team(2), _team(3)], [_team(4), _team(5), _team(6)], key="a", red_win=False)
    rescaled = _row([_team(1, score_scale=41.0), _team(2), _team(3)], [_team(4), _team(5), _team(6)], key="a")
    assert len({dataset_fingerprint([a, b]), dataset_fingerprint([flipped, b]),
                dataset_fingerprint([rescaled, b])}) == 3


@pytest.mark.parametrize("seed_high, raw_mean, proceed", [(-0.01, -0.001, True), (-0.01, 0.0, True),
                                                          (0.001, -0.05, False), (-0.01, 0.002, False)])
def test_development_decision_needs_both_dv1_and_dv2(seed_high, raw_mean, proceed):
    decision = development_decision({"ci_high": seed_high}, {"mean": raw_mean})
    assert decision["proceed_to_final"] is proceed and decision["acceptance"] is False


# --- §6 and the harness's refusals ------------------------------------------------------------------------------


def test_gate_2027_needs_both_comparisons_strictly_better():
    from ml.playoffs.px1b import gate_2027

    labels = [True, False] * 40
    events = [f"e{i // 8}" for i in range(80)]
    good = [0.8 if y else 0.2 for y in labels]
    coin = [0.5] * 80
    assert gate_2027(good, coin, coin, labels, events)["passed"] is True
    assert gate_2027(good, good, coin, labels, events)["passed"] is False  # not strictly better than M6/M7


def test_final_fit_refuses_unless_dev_1_proceeds(monkeypatch):
    import scripts.phase6_px1b as harness
    from scripts.phase6_playoff_track import Blocked

    monkeypatch.setattr(harness, "read_record", lambda name: None)
    with pytest.raises(Blocked):
        harness.run_final(None, None)
    monkeypatch.setattr(harness, "read_record", lambda name: {"decision": {"proceed_to_final": False}})
    with pytest.raises(Blocked):
        harness.run_final(None, None)


def test_final_fit_refuses_once_2027_outcomes_exist(monkeypatch):
    import scripts.phase6_px1b as harness
    from scripts.phase6_playoff_track import Blocked

    monkeypatch.setattr(harness, "read_record", lambda name: {"decision": {"proceed_to_final": True}})
    monkeypatch.setattr(harness, "_playoff_matches", lambda database, season: 12 if season == 2027 else 0)
    with pytest.raises(Blocked):
        harness.run_final(None, None)


def test_gate_2027_refuses_while_its_prerequisites_are_missing(monkeypatch, capsys):
    import data.rulesets
    import scripts.phase6_px1b as harness
    from scripts.phase6_playoff_track import Blocked

    monkeypatch.setattr(harness, "read_record", lambda name: None)
    monkeypatch.setattr(harness, "_playoff_matches", lambda database, season: 0)
    monkeypatch.setattr(data.rulesets, "approved_seasons", lambda database: {2024, 2025, 2026})
    with pytest.raises(Blocked):
        harness.run_gate2027(None, None)
    err = capsys.readouterr().err
    assert "p6_px1b_final_fit.json" in err and "2027 P6-M1 ruleset" in err and "2027 playoff data" in err
