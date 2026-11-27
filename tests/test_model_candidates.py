"""The research candidates WP-NORM-EPA-v1 and RANK-BLEND-v1 (audit 2026-11-26, workstreams 1 and 2).

Pure checks on SYNTHETIC rows (invented teams, events and values): the definitions in the frozen specs
(.agent/model_candidates/), their missing-data rules, symmetry, scale invariance, training cutoffs, the
point-in-time rule of the ranking snapshot, and that neither candidate is wired into serving.
"""

from __future__ import annotations

import math
import random
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from ml.backtest.ranking_midpoint import MIDPOINT, decision_snapshots
from ml.candidates import ranking_blend
from ml.candidates.win_prob_norm_epa import (
    TRAINING_SEASONS,
    NormEpaLogistic,
    fit_coefficient,
    match_feature,
    raw_feature,
    team_z,
    training_rows,
)
from ml.dataset.builder import TrainingRow
from ml.features.assembler import TeamFeatures
from scripts.evaluate_model_candidates import check_database_url, check_season

ROOT = Path(__file__).resolve().parents[1]
T0 = datetime(2030, 3, 1, 9, tzinfo=timezone.utc)


def team(number: int, *, epa: float | None = None, scale: float | None = None, avg: float | None = None,
         **other) -> TeamFeatures:
    flags = {f"{name}_present": False for name in (
        "epa_auto", "epa_teleop", "epa_endgame", "score_stddev", "consistency_rating", "reliability_score",
        "average_auto_points", "defense_score", "defense_agreement", "feeding_score", "feeding_agreement")}
    return TeamFeatures(team_number=number, epa_total=epa, epa_total_present=epa is not None,
                        epa_source_event_key="9990prior" if epa is not None else None,
                        epa_withheld_reason=None if epa is not None else "no_prior_event",
                        epa_scale=scale, epa_scale_present=scale is not None,
                        average_score=avg, average_score_present=avg is not None,
                        matches_considered=0, matches_used=0, auto_points_matches_used=0,
                        defense_observation_count=0, feeding_observation_count=0, **{**flags, **other})


def row(red, blue, *, label="red_win", season=2030, key="9990test_qm1", level="qualification", when=T0) -> TrainingRow:
    return TrainingRow(match_key=key, event_key=key.split("_")[0], season=season, comp_level=level,
                       scheduled_time=when, label=label, score_margin=1, score_red=1, score_blue=0,
                       red_teams=list(red), blue_teams=list(blue), dq_status_known=True)


def three(base: int, epa: float, scale: float) -> list[TeamFeatures]:
    return [team(base + i, epa=epa, scale=scale) for i in range(3)]


# --- WP-NORM-EPA-v1 ------------------------------------------------------------------------------------------------


def test_each_team_is_normalized_by_its_own_scale_and_the_feature_is_antisymmetric():
    assert team_z(team(1, epa=30.0, scale=60.0)) == 0.5
    assert team_z(team(1, epa=30.0)) is None and team_z(team(1)) is None  # (a scale without EPA cannot exist)
    mixed = row([team(1, epa=20, scale=40), team(2, epa=90, scale=90), team(3, epa=10, scale=40)],
                three(10, 45.0, 90.0))
    assert match_feature(mixed) == pytest.approx((0.5 + 1.0 + 0.25) - 1.5)
    swapped = row(mixed.blue_teams, mixed.red_teams)
    assert match_feature(swapped) == pytest.approx(-match_feature(mixed))


def test_the_feature_is_in_season_units_while_the_raw_feature_is_not():
    # The diagnosis in one line: the same match in a season scoring k times higher keeps x, but not the raw feature.
    low = row(three(1, 20.0, 40.0), three(10, 10.0, 40.0))
    high = row(three(1, 20.0 * 3.3, 40.0 * 3.3), three(10, 10.0 * 3.3, 40.0 * 3.3))
    assert match_feature(low) == pytest.approx(match_feature(high))
    assert raw_feature(high) == pytest.approx(3.3 * raw_feature(low))


def test_missing_epa_or_scale_or_a_short_alliance_gives_no_probability():
    full = three(1, 20.0, 40.0)
    assert match_feature(row(full, [*three(10, 10.0, 40.0)[:2], team(19, epa=10.0)])) is None
    assert match_feature(row(full, three(10, 10.0, 40.0)[:2])) is None
    model = NormEpaLogistic(coefficient=2.0)
    assert model.predict(row(full, [*three(10, 10.0, 40.0)[:2], team(19)])) is None  # withheld, never substituted


def test_the_logistic_has_no_intercept_so_swapping_alliances_gives_the_complement():
    model = NormEpaLogistic(coefficient=1.96227)
    match = row(three(1, 30.0, 40.0), three(10, 15.0, 40.0))
    p, q = model.predict(match), model.predict(row(match.blue_teams, match.red_teams))
    assert p + q == pytest.approx(1.0) and p > 0.5
    assert model.predict(row(three(1, 20.0, 40.0), three(10, 20.0, 40.0))) == pytest.approx(0.5)


def test_the_fit_recovers_a_known_coefficient_and_is_deterministic():
    rng = random.Random(7)
    xs = [rng.uniform(-3, 3) for _ in range(4000)]
    ys = [rng.random() < 1 / (1 + math.exp(-1.5 * x)) for x in xs]
    b = fit_coefficient(xs, ys)
    assert b == pytest.approx(1.5, abs=0.12) and fit_coefficient(xs, ys) == b
    with pytest.raises(ValueError):
        fit_coefficient([0.0, 0.0], [True, False])


def test_only_training_seasons_and_decided_matches_are_fitted_on():
    assert TRAINING_SEASONS == {2024, 2025}
    rng = random.Random(3)
    rows = []
    for n in range(300):
        diff = rng.uniform(-20, 20)
        red = rng.random() < 1 / (1 + math.exp(-diff / 20))
        rows.append(row(three(1, 30.0 + diff, 40.0), three(10, 30.0, 40.0), label="red_win" if red else "blue_win",
                        season=2024 + n % 2, key=f"9990t{n}_qm1"))
    ties = [row(three(1, 50.0, 40.0), three(10, 0.0, 40.0), label="tie", season=2024, key="9990tie_qm1")]
    later = [row(three(1, 90.0, 40.0), three(10, 0.0, 40.0), label="blue_win", season=season, key=f"9990l{season}_qm1")
             for season in (2026, 2027) for _ in range(50)]
    assert len(training_rows([*rows, *ties, *later])) == 300
    # Rows from 2026 or 2027 (here: absurd upsets) cannot move the fit.
    assert NormEpaLogistic.fit([*rows, *ties, *later]).coefficient == NormEpaLogistic.fit(rows).coefficient


# --- RANK-BLEND-v1 -------------------------------------------------------------------------------------------------


def test_the_blend_formula_and_its_missing_data_rules():
    assert ranking_blend.blend_rating(team(1, epa=30.0, avg=60.0)) == pytest.approx((30.0 + 20.0) / 2)
    assert ranking_blend.blend_rating(team(1, epa=30.0)) == 30.0  # no in-event matches yet
    assert ranking_blend.blend_rating(team(1, avg=45.0)) == 15.0  # no EPA (a rookie)
    assert ranking_blend.blend_rating(team(1)) is None
    assert ranking_blend.blend_rating_for_evaluation(team(1)) == ranking_blend.MISSING


def test_the_blend_reads_nothing_but_epa_and_the_in_event_average():
    plain = team(1, epa=30.0, avg=60.0)
    loaded = team(1, epa=30.0, avg=60.0, scale=999.0, reliability_score=10.0, reliability_score_present=True,
                  defense_score=4.0, defense_score_present=True, score_stddev=3.0, score_stddev_present=True)
    assert ranking_blend.blend_rating(plain) == ranking_blend.blend_rating(loaded)


def test_the_midpoint_rating_uses_nothing_from_the_snapshot_match_or_later():
    def schedule(later_avg: float) -> list[TrainingRow]:
        rows = []
        for k in range(1, 7):  # six qualification matches for team 1: the midpoint is its 3rd
            avg = None if k == 1 else (40.0 + k if k <= 3 else later_avg)
            rows.append(row([team(1, epa=25.0, avg=avg), team(2, epa=20.0), team(3, epa=15.0)],
                            three(10, 10.0, 40.0), key=f"9990mid_qm{k}", when=T0 + timedelta(hours=k)))
        return rows

    honest = decision_snapshots(schedule(later_avg=45.0), MIDPOINT)["9990mid"][1]
    leaked = decision_snapshots(schedule(later_avg=5000.0), MIDPOINT)["9990mid"][1]
    assert honest.k == 3 and honest.match_key == "9990mid_qm3"
    assert ranking_blend.blend_rating(honest.features) == ranking_blend.blend_rating(leaked.features)
    assert ranking_blend.blend_rating(honest.features) == pytest.approx((25.0 + 43.0 / 3) / 2)


# --- the evaluation's guards, and nothing served -------------------------------------------------------------------


def test_the_evaluation_refuses_training_seasons_and_the_untouched_holdout():
    assert check_season(2026, False) == "retrospective_evidence_only"
    with pytest.raises(SystemExit, match="training season"):
        check_season(2025, False)
    with pytest.raises(SystemExit, match="untouched holdout"):
        check_season(2027, False)
    assert check_season(2027, True) == "pre_registered_evaluation"
    with pytest.raises(SystemExit, match="refusing database"):
        check_database_url("postgresql://u:p@localhost/stratai")
    check_database_url("postgresql://u:p@localhost/stratai_test_audit")


def test_the_candidates_are_not_wired_into_serving():
    users = [path for folder in ("api", "workspaces", "data")
             for path in (ROOT / folder).rglob("*.py") if "ml.candidates" in path.read_text(encoding="utf-8")]
    assert users == []
