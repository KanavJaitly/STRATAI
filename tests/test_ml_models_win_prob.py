"""Phase 4 Milestone 6: win-probability model, symmetric by construction,
ml.models.win_prob.

Every TeamFeatures/TrainingRow value in this file is synthetic and
explicitly hand-constructed for unit testing -- none of it represents a
real match, a real team, or a real EPA value, and none of it is used to
produce, or stand in for, this milestone's actual required deliverable (a
real, dated beats-M4-baseline backtest result on a real held-out season,
recorded in RUNNING_NOTES.md once real Statbotics EPA data is available
again -- see .agent/phase4/PHASE_STATUS.md). This file exists only to prove
the model code itself is correct: the milestone's own named tests (exact
symmetry, order-independence, no-strategy-leakage) plus protocol
conformance, missing-feature handling, reproducibility, and save/load.
"""

from __future__ import annotations

import json
import random
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from ml.backtest.harness import Model
from ml.dataset.builder import LABEL_BLUE_WIN, LABEL_RED_WIN, LABEL_TIE, TrainingRow
from ml.features.assembler import EPA_WITHHELD_NO_PRIOR_EVENT, MatchFeatureRow, TeamFeatures
from ml.models.team_vector import TEAM_FEATURE_NAMES
from ml.models.win_prob import FEATURE_NAMES, WIN_PROB_MODEL_VERSION, WinProbXGBModel, _alliance_vector

_T0 = datetime(2026, 3, 1, 10, 0, tzinfo=timezone.utc)


def _team_features(team_number: int, *, average_score: float | None = None) -> TeamFeatures:
    return TeamFeatures(
        team_number=team_number,
        epa_total_present=False, epa_auto_present=False, epa_teleop_present=False, epa_endgame_present=False,
        epa_source_event_key=None, epa_withheld_reason=EPA_WITHHELD_NO_PRIOR_EVENT,
        average_score=average_score, average_score_present=average_score is not None,
        score_stddev_present=False, consistency_rating_present=False, reliability_score_present=False,
        matches_considered=5, matches_used=5,
        defense_score_present=False, defense_agreement_present=False, defense_observation_count=0,
        feeding_score_present=False, feeding_agreement_present=False, feeding_observation_count=0,
    )


def _random_alliance(rng: random.Random, base: int) -> list[TeamFeatures]:
    return [_team_features(base + i, average_score=rng.uniform(10.0, 60.0)) for i in range(3)]


def _row(
    *, match_key: str, red_teams: list[TeamFeatures], blue_teams: list[TeamFeatures],
    label: str, scheduled_time: datetime = _T0,
) -> TrainingRow:
    if label == LABEL_RED_WIN:
        score_red, score_blue = 100, 80
    elif label == LABEL_BLUE_WIN:
        score_red, score_blue = 80, 100
    else:
        score_red = score_blue = 90
    return TrainingRow(
        match_key=match_key, event_key="9980zzztest", season=9980, comp_level="qualification",
        set_number=None, match_number=1, scheduled_time=scheduled_time, label=label,
        score_margin=score_red - score_blue, score_red=score_red, score_blue=score_blue,
        red_teams=red_teams, blue_teams=blue_teams,
        red_surrogate_team_numbers=[], blue_surrogate_team_numbers=[], dq_status_known=True,
    )


def _synthetic_rows(count: int = 60) -> list[TrainingRow]:
    """A synthetic dataset where the stronger alliance (higher summed
    average_score) tends to win -- real, deterministic signal for the model
    to learn, mirroring test_ml_models_ranking_xgb.py's own construction."""
    rng = random.Random(99)
    rows: list[TrainingRow] = []
    for match_index in range(count):
        red_teams = [_team_features(9800 + match_index * 6 + i, average_score=rng.uniform(10.0, 60.0)) for i in range(3)]
        blue_teams = [_team_features(9800 + match_index * 6 + 3 + i, average_score=rng.uniform(10.0, 60.0)) for i in range(3)]
        red_sum = sum(t.average_score for t in red_teams)
        blue_sum = sum(t.average_score for t in blue_teams)
        label = LABEL_RED_WIN if red_sum > blue_sum else LABEL_BLUE_WIN
        rows.append(_row(
            match_key=f"9980zzztest_qm{match_index + 1}", red_teams=red_teams, blue_teams=blue_teams,
            label=label, scheduled_time=_T0 + timedelta(hours=match_index),
        ))
    return rows


def _match_features(red_teams: list[TeamFeatures], blue_teams: list[TeamFeatures]) -> MatchFeatureRow:
    return MatchFeatureRow(
        match_key="9980zzztest_qm1", as_of=_T0, event_key="9980zzztest", season=9980,
        red_teams=red_teams, blue_teams=blue_teams,
    )


# ---------------------------------------------------------------------------
# Pure helpers
# ---------------------------------------------------------------------------


def test_alliance_vector_empty_alliance_is_all_nan():
    vector = _alliance_vector([])
    assert vector.shape == (len(FEATURE_NAMES) // 2,)
    assert all(value != value for value in vector)  # NaN != NaN


def test_alliance_vector_any_missing_team_makes_that_feature_nan_not_zero():
    present_team = _team_features(9800, average_score=40.0)
    absent_team = _team_features(9801)  # average_score absent
    vector = _alliance_vector([present_team, absent_team])
    average_score_index = TEAM_FEATURE_NAMES.index("average_score")
    assert vector[average_score_index] != vector[average_score_index]  # NaN, not 40.0 and not 0.0


def test_alliance_vector_sums_present_values_across_the_alliance():
    teams = [_team_features(9800 + i, average_score=10.0 * (i + 1)) for i in range(3)]
    vector = _alliance_vector(teams)
    average_score_index = TEAM_FEATURE_NAMES.index("average_score")
    assert vector[average_score_index] == 10.0 + 20.0 + 30.0


# ---------------------------------------------------------------------------
# Protocol conformance and guard rails
# ---------------------------------------------------------------------------


def test_win_prob_xgb_conforms_to_model_protocol():
    assert isinstance(WinProbXGBModel(), Model)


def test_win_prob_xgb_predict_rating_raises_not_implemented():
    with pytest.raises(NotImplementedError):
        WinProbXGBModel().predict_rating(_team_features(9800, average_score=20.0))


def test_win_prob_xgb_predict_before_fit_raises():
    red = _random_alliance(random.Random(1), 9800)
    blue = _random_alliance(random.Random(2), 9900)
    with pytest.raises(RuntimeError, match="before fit"):
        WinProbXGBModel().predict_win_prob(_match_features(red, blue))


def test_win_prob_xgb_fit_raises_on_zero_training_rows():
    with pytest.raises(ValueError, match="zero training rows"):
        WinProbXGBModel().fit([])


def test_win_prob_xgb_fit_raises_when_every_row_is_a_tie():
    red = _random_alliance(random.Random(1), 9800)
    blue = _random_alliance(random.Random(2), 9900)
    tie_row = _row(match_key="9980zzztest_qm1", red_teams=red, blue_teams=blue, label=LABEL_TIE)
    with pytest.raises(ValueError, match="zero non-tie"):
        WinProbXGBModel().fit([tie_row])


def test_win_prob_model_version_is_a_real_string():
    assert isinstance(WIN_PROB_MODEL_VERSION, str) and WIN_PROB_MODEL_VERSION


# ---------------------------------------------------------------------------
# The milestone's own named guarantees
# ---------------------------------------------------------------------------


def test_win_prob_xgb_exact_symmetry_across_many_random_alliances():
    """swap(red, blue) => p -> 1-p, exactly (to floating-point tolerance),
    for many independently-random alliance pairings -- the milestone's own
    named exact-symmetry test."""
    model = WinProbXGBModel(num_boost_round=20)
    model.fit(_synthetic_rows(count=40))

    rng = random.Random(42)
    for trial in range(25):
        red = _random_alliance(rng, 9800 + trial * 10)
        blue = _random_alliance(rng, 9900 + trial * 10)
        p_forward = model.predict_win_prob(_match_features(red, blue))
        p_swapped = model.predict_win_prob(_match_features(blue, red))
        assert p_forward == pytest.approx(1.0 - p_swapped, abs=1e-9)


def test_win_prob_xgb_order_independence_same_inputs_different_call_order():
    """Same two alliances, called in a different order relative to other
    predictions, still gives identical output -- the milestone's own named
    order-independence test. Confirms there is no hidden mutable state."""
    model = WinProbXGBModel(num_boost_round=20)
    model.fit(_synthetic_rows(count=40))

    red = _random_alliance(random.Random(5), 9800)
    blue = _random_alliance(random.Random(6), 9900)
    match = _match_features(red, blue)

    p1 = model.predict_win_prob(match)
    # Interleave unrelated predictions between the two calls being compared.
    other_red = _random_alliance(random.Random(7), 9950)
    other_blue = _random_alliance(random.Random(8), 9960)
    model.predict_win_prob(_match_features(other_red, other_blue))
    model.predict_win_prob(_match_features(other_blue, other_red))
    p2 = model.predict_win_prob(match)

    assert p1 == p2


def test_win_prob_xgb_no_strategy_leakage_field_in_inputs():
    """No field anywhere in TeamFeatures/MatchFeatureRow encodes a
    recommendation source or "AI strategy" vs "coach strategy" -- the
    milestone's own named no-strategy-leakage test, checked structurally
    against the real schema rather than by convention."""
    disallowed_substrings = ("strategy", "recommendation", "coach", "proposer", "proposal", "source_type")
    for field_name in TeamFeatures.model_fields:
        lowered = field_name.lower()
        assert not any(bad in lowered for bad in disallowed_substrings), field_name
    for field_name in MatchFeatureRow.model_fields:
        lowered = field_name.lower()
        assert not any(bad in lowered for bad in disallowed_substrings), field_name


def test_win_prob_xgb_recovers_signal_correlated_with_true_strength():
    """The model's headline claim: given data where the stronger alliance
    (by summed average_score) tends to win, predicted win probability is
    meaningfully above 0.5 for a clearly-stronger red alliance."""
    model = WinProbXGBModel(num_boost_round=40)
    model.fit(_synthetic_rows(count=80))

    strong_red = [_team_features(9800 + i, average_score=55.0) for i in range(3)]
    weak_blue = [_team_features(9900 + i, average_score=15.0) for i in range(3)]
    p = model.predict_win_prob(_match_features(strong_red, weak_blue))
    assert p > 0.6


# ---------------------------------------------------------------------------
# Fitting behavior
# ---------------------------------------------------------------------------


def test_win_prob_xgb_handles_fully_missing_features_without_crashing():
    model = WinProbXGBModel(num_boost_round=10)
    model.fit(_synthetic_rows(count=20))
    fully_absent_red = [_team_features(9800 + i) for i in range(3)]
    fully_absent_blue = [_team_features(9900 + i) for i in range(3)]
    p = model.predict_win_prob(_match_features(fully_absent_red, fully_absent_blue))
    assert isinstance(p, float)
    assert p == pytest.approx(0.5, abs=1e-6)  # symmetric inputs must give exactly 0.5


def test_win_prob_xgb_reproducibility_same_seed_same_data_gives_identical_predictions():
    rows = _synthetic_rows(count=40)
    red = _random_alliance(random.Random(11), 9800)
    blue = _random_alliance(random.Random(12), 9900)
    match = _match_features(red, blue)

    model_a = WinProbXGBModel(random_seed=7, num_boost_round=15)
    model_a.fit(rows)
    model_b = WinProbXGBModel(random_seed=7, num_boost_round=15)
    model_b.fit(rows)

    assert model_a.predict_win_prob(match) == model_b.predict_win_prob(match)


def test_win_prob_xgb_validation_fold_is_empty_with_a_single_row():
    red = _random_alliance(random.Random(1), 9800)
    blue = _random_alliance(random.Random(2), 9900)
    row = _row(match_key="a", red_teams=red, blue_teams=blue, label=LABEL_RED_WIN, scheduled_time=_T0)
    model = WinProbXGBModel(num_boost_round=10)
    model.fit([row])
    assert model.fit_validation_row_count == 0
    assert model.best_iteration is None


def test_win_prob_xgb_excludes_ties_and_counts_them():
    red = _random_alliance(random.Random(1), 9800)
    blue = _random_alliance(random.Random(2), 9900)
    rows = _synthetic_rows(count=20) + [
        _row(match_key="tie1", red_teams=red, blue_teams=blue, label=LABEL_TIE, scheduled_time=_T0 + timedelta(hours=99)),
    ]
    model = WinProbXGBModel(num_boost_round=10)
    model.fit(rows)
    assert model.fit_excluded_tie_count == 1


# ---------------------------------------------------------------------------
# Save / load
# ---------------------------------------------------------------------------


def test_win_prob_xgb_save_load_round_trip(tmp_path: Path):
    rows = _synthetic_rows(count=30)
    model = WinProbXGBModel(random_seed=3, num_boost_round=15)
    model.fit(rows)
    red = _random_alliance(random.Random(21), 9800)
    blue = _random_alliance(random.Random(22), 9900)
    match = _match_features(red, blue)
    expected = model.predict_win_prob(match)

    path = tmp_path / "win_prob_xgb.json"
    model.save(path)
    loaded = WinProbXGBModel.load(path)

    assert loaded.predict_win_prob(match) == expected
    assert loaded.best_iteration == model.best_iteration


def test_win_prob_xgb_save_before_fit_raises(tmp_path: Path):
    with pytest.raises(RuntimeError, match="unfit"):
        WinProbXGBModel().save(tmp_path / "x.json")


def test_win_prob_xgb_load_rejects_a_foreign_file(tmp_path: Path):
    path = tmp_path / "foreign.json"
    path.write_text('{"model": "ranking_xgb", "version": "1.0.0"}', encoding="utf-8")
    with pytest.raises(ValueError, match="does not contain a win_prob_xgb model"):
        WinProbXGBModel.load(path)


def test_win_prob_xgb_load_rejects_a_feature_list_mismatch(tmp_path: Path):
    rows = _synthetic_rows(count=10)
    model = WinProbXGBModel(num_boost_round=5)
    model.fit(rows)
    path = tmp_path / "win_prob_xgb.json"
    model.save(path)

    data = json.loads(path.read_text(encoding="utf-8"))
    data["feature_names"] = ["red_epa_total"]
    path.write_text(json.dumps(data), encoding="utf-8")

    with pytest.raises(ValueError, match="does not match"):
        WinProbXGBModel.load(path)
