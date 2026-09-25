"""Phase 4 Milestone 5: team rating / ranking model, ml.models.ranking_xgb.

Every TeamFeatures/TrainingRow value in this file is synthetic and
explicitly hand-constructed for unit testing -- none of it represents a
real match, a real team, or a real EPA value, and none of it is used to
produce, or stand in for, this milestone's actual required deliverable (a
real, dated backtest result on a real held-out season, comparing against
real final ranks via ml.backtest.run_ranking_backtest, recorded in
RUNNING_NOTES.md once real Statbotics EPA data is available again -- see
.agent/phase4/PHASE_STATUS.md). This file exists only to prove the model
code itself is correct: protocol conformance, missing-feature handling,
reproducibility, save/load, and the milestone's own named leakage smoke test
(shuffled labels collapse predictive signal), all against a synthetic
dataset with a deliberately constructed, known ground truth.
"""

from __future__ import annotations

import json
import random
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from ml.backtest.harness import Model
from ml.backtest.metrics import spearman_correlation
from ml.dataset.builder import LABEL_BLUE_WIN, LABEL_RED_WIN, LABEL_TIE, TrainingRow
from ml.features.assembler import EPA_WITHHELD_NO_PRIOR_EVENT, MatchFeatureRow, TeamFeatures
from ml.models.ranking_xgb import (
    FEATURE_NAMES,
    RANKING_MODEL_VERSION,
    RankingXGBModel,
    _row_targets,
    _team_features_to_vector,
    _validation_split_index,
)

_T0 = datetime(2026, 3, 1, 10, 0, tzinfo=timezone.utc)
_NUM_TEAMS = 24


def _team_features(team_number: int, *, average_score: float | None = None) -> TeamFeatures:
    """A synthetic team snapshot with only average_score meaningfully set --
    every other optional field absent (EPA included), matching the
    minimal-valid-construction pattern already used in
    tests/test_ml_models_baselines.py, extended here to also exercise a
    fully-EPA-absent team through the model's own NaN handling.
    """
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


def _skill(team_index: int) -> float:
    """team_index in [0, _NUM_TEAMS) -> a monotonically increasing synthetic
    skill value, also used directly as that team's average_score feature --
    the model has direct, perfect access to the ground-truth signal it is
    supposed to learn, by construction."""
    return 20.0 + 2.0 * team_index


def _synthetic_rows(*, count: int = 60, shuffle_outcomes: bool = False) -> list[TrainingRow]:
    """`count` synthetic matches, one hour apart starting at _T0, built from
    _NUM_TEAMS teams cycling through 3v3 alliances via fixed (not random)
    modular offsets. Each match's true score_margin is exactly the sum of
    skill across red minus the sum across blue -- a deterministic function
    of a real feature (average_score) the model is fed directly, so a model
    that fits this data at all should recover a strong positive correlation
    between predicted rating and true skill.

    shuffle_outcomes=True keeps every alliance's team composition identical
    but reassigns each row's (label, score_margin, score_red, score_blue)
    from a *different* row via a fixed-seed random permutation -- decoupling
    team features from outcome while keeping the dataset's shape identical,
    for the label-shuffle leakage smoke test. A simple reversal of row order
    was tried first and rejected: this dataset's team composition and true
    outcome both vary smoothly (near-linearly) with match_index, so
    reversing preserves enough of that smooth structure to still correlate
    strongly with true skill -- a real, instructive finding about this
    fixture, not a bug in the model. A fixed-seed random.Random shuffle
    (not simple reversal) is required to actually break the pairing.
    """
    rows: list[TrainingRow] = []
    outcomes: list[tuple[str, int, int, int]] = []
    for match_index in range(count):
        red_indices = [(match_index + offset) % _NUM_TEAMS for offset in (0, 1, 2)]
        blue_indices = [(match_index + offset) % _NUM_TEAMS for offset in (12, 13, 14)]
        red_skill = sum(_skill(i) for i in red_indices)
        blue_skill = sum(_skill(i) for i in blue_indices)
        margin = round(red_skill - blue_skill)
        if margin > 0:
            label = LABEL_RED_WIN
        elif margin < 0:
            label = LABEL_BLUE_WIN
        else:
            label = LABEL_TIE
        score_red, score_blue = 100 + max(margin, 0), 100 + max(-margin, 0)
        outcomes.append((label, margin, score_red, score_blue))

    outcome_indices = list(range(count))
    if shuffle_outcomes:
        random.Random(1234).shuffle(outcome_indices)

    for match_index in range(count):
        red_indices = [(match_index + offset) % _NUM_TEAMS for offset in (0, 1, 2)]
        blue_indices = [(match_index + offset) % _NUM_TEAMS for offset in (12, 13, 14)]
        red_teams = [_team_features(9800 + i, average_score=_skill(i)) for i in red_indices]
        blue_teams = [_team_features(9800 + i, average_score=_skill(i)) for i in blue_indices]

        label, margin, score_red, score_blue = outcomes[outcome_indices[match_index]]

        rows.append(TrainingRow(
            match_key=f"9970zzztest_qm{match_index + 1}", event_key="9970zzztest", season=9970,
            comp_level="qualification", set_number=None, match_number=match_index + 1,
            scheduled_time=_T0 + timedelta(hours=match_index), label=label,
            score_margin=margin, score_red=score_red, score_blue=score_blue,
            red_teams=red_teams, blue_teams=blue_teams,
            red_surrogate_team_numbers=[], blue_surrogate_team_numbers=[], dq_status_known=True,
        ))
    return rows


def _match_features(red_epas: list[float | None] | None = None) -> MatchFeatureRow:
    red_epas = red_epas or [None, None, None]
    return MatchFeatureRow(
        match_key="9970zzztest_qm1", as_of=_T0, event_key="9970zzztest", season=9970,
        red_teams=[_team_features(9800 + i) for i in range(len(red_epas))],
        blue_teams=[_team_features(9900 + i) for i in range(len(red_epas))],
    )


# ---------------------------------------------------------------------------
# Pure helpers
# ---------------------------------------------------------------------------


def test_row_targets_red_win_gives_positive_red_negative_blue():
    row = _synthetic_rows(count=1)[0]
    # Force a known label/margin directly rather than relying on the
    # generator's own computed outcome, to pin the exact expected values.
    row = row.model_copy(update={"label": LABEL_RED_WIN, "score_margin": 15})
    assert _row_targets(row) == (15.0, -15.0)


def test_row_targets_blue_win_gives_negative_red_positive_blue():
    row = _synthetic_rows(count=1)[0].model_copy(update={"label": LABEL_BLUE_WIN, "score_margin": -9})
    assert _row_targets(row) == (-9.0, 9.0)


def test_row_targets_tie_gives_zero_for_both():
    row = _synthetic_rows(count=1)[0].model_copy(update={"label": LABEL_TIE, "score_margin": 0})
    assert _row_targets(row) == (0.0, 0.0)


def test_row_targets_uses_label_for_direction_not_score_margin_sign():
    # The documented rare-divergence case: label disagrees with score_margin's
    # own sign. Direction must follow label, magnitude must follow abs(margin).
    row = _synthetic_rows(count=1)[0].model_copy(update={"label": LABEL_RED_WIN, "score_margin": -5})
    assert _row_targets(row) == (5.0, -5.0)


def test_team_features_to_vector_uses_nan_for_every_absent_field():
    team = _team_features(9800)  # average_score absent too (default None)
    vector = _team_features_to_vector(team)
    assert vector.shape == (len(FEATURE_NAMES),)
    for name, value in zip(FEATURE_NAMES, vector):
        if name in ("matches_considered", "matches_used", "defense_observation_count", "feeding_observation_count"):
            assert value == 5 if name in ("matches_considered", "matches_used") else value == 0
        else:
            assert value != value, f"{name} should be NaN when absent"  # NaN != NaN


def test_team_features_to_vector_carries_a_present_value_through():
    team = _team_features(9800, average_score=42.0)
    vector = _team_features_to_vector(team)
    index = FEATURE_NAMES.index("average_score")
    assert vector[index] == 42.0


@pytest.mark.parametrize("row_count,expected", [(0, 0), (1, 1), (2, 1), (5, 4), (10, 8)])
def test_validation_split_index(row_count, expected):
    assert _validation_split_index(row_count, 0.2) == expected


# ---------------------------------------------------------------------------
# Protocol conformance and guard rails
# ---------------------------------------------------------------------------


def test_ranking_xgb_conforms_to_model_protocol():
    assert isinstance(RankingXGBModel(), Model)


def test_ranking_xgb_predict_rating_before_fit_raises():
    with pytest.raises(RuntimeError, match="before fit"):
        RankingXGBModel().predict_rating(_team_features(9800, average_score=20.0))


def test_ranking_xgb_predict_win_prob_raises_not_implemented():
    with pytest.raises(NotImplementedError):
        RankingXGBModel().predict_win_prob(_match_features())


def test_ranking_xgb_fit_raises_on_zero_training_rows():
    with pytest.raises(ValueError, match="zero training rows"):
        RankingXGBModel().fit([])


def test_ranking_xgb_fit_raises_when_every_alliance_is_empty():
    empty_row = _synthetic_rows(count=1)[0].model_copy(update={"red_teams": [], "blue_teams": []})
    with pytest.raises(ValueError, match="zero team-appearance samples"):
        RankingXGBModel().fit([empty_row])


def test_ranking_model_version_is_a_real_string():
    assert isinstance(RANKING_MODEL_VERSION, str) and RANKING_MODEL_VERSION


# ---------------------------------------------------------------------------
# Fitting behavior
# ---------------------------------------------------------------------------


def test_ranking_xgb_handles_fully_missing_features_without_crashing():
    rows = _synthetic_rows(count=20)
    model = RankingXGBModel(num_boost_round=10)
    model.fit(rows)
    fully_absent_team = _team_features(9800)  # every optional field absent
    prediction = model.predict_rating(fully_absent_team)
    assert isinstance(prediction, float)


def test_ranking_xgb_validation_fold_is_populated_with_enough_rows():
    model = RankingXGBModel(num_boost_round=10)
    model.fit(_synthetic_rows(count=30))
    assert model.fit_validation_row_count is not None and model.fit_validation_row_count > 0
    assert model.best_iteration is not None


def test_ranking_xgb_validation_fold_is_empty_with_a_single_row():
    row = _synthetic_rows(count=1)[0]
    model = RankingXGBModel(num_boost_round=10)
    model.fit([row])
    assert model.fit_validation_row_count == 0
    assert model.best_iteration is None
    # Still produces a real prediction despite no early stopping.
    assert isinstance(model.predict_rating(row.red_teams[0]), float)


def test_ranking_xgb_reproducibility_same_seed_same_data_gives_identical_predictions():
    rows = _synthetic_rows(count=30)
    probe = _team_features(9800, average_score=_skill(5))

    model_a = RankingXGBModel(random_seed=7, num_boost_round=15)
    model_a.fit(rows)
    model_b = RankingXGBModel(random_seed=7, num_boost_round=15)
    model_b.fit(rows)

    assert model_a.predict_rating(probe) == model_b.predict_rating(probe)


def test_ranking_xgb_recovers_signal_correlated_with_true_skill():
    """The model's headline claim: given data where average_score IS the
    ground-truth skill signal, predicted ratings correlate strongly with
    true skill for teams the model has seen."""
    rows = _synthetic_rows(count=60)
    model = RankingXGBModel(num_boost_round=50)
    model.fit(rows)

    predicted = [model.predict_rating(_team_features(9800 + i, average_score=_skill(i))) for i in range(_NUM_TEAMS)]
    true_skill = [_skill(i) for i in range(_NUM_TEAMS)]
    correlation = spearman_correlation(predicted, true_skill)
    assert correlation is not None and correlation > 0.7


def test_ranking_xgb_label_shuffle_smoke_test_collapses_signal():
    """Milestone 5's own named leakage smoke test: shuffling which outcome
    goes with which alliance destroys the team-feature/outcome relationship,
    so a model trained on the shuffled data should recover far less (or no)
    correlation with true skill than the correctly-labeled model does --
    proof this model has no back-channel signal beyond what fit() is
    supposed to learn from labels."""
    true_rows = _synthetic_rows(count=60, shuffle_outcomes=False)
    shuffled_rows = _synthetic_rows(count=60, shuffle_outcomes=True)

    true_model = RankingXGBModel(num_boost_round=50)
    true_model.fit(true_rows)
    shuffled_model = RankingXGBModel(num_boost_round=50)
    shuffled_model.fit(shuffled_rows)

    true_skill = [_skill(i) for i in range(_NUM_TEAMS)]
    true_predicted = [true_model.predict_rating(_team_features(9800 + i, average_score=_skill(i))) for i in range(_NUM_TEAMS)]
    shuffled_predicted = [shuffled_model.predict_rating(_team_features(9800 + i, average_score=_skill(i))) for i in range(_NUM_TEAMS)]

    true_correlation = spearman_correlation(true_predicted, true_skill)
    shuffled_correlation = spearman_correlation(shuffled_predicted, true_skill)
    assert true_correlation is not None and shuffled_correlation is not None
    assert true_correlation > 0.7
    assert true_correlation - shuffled_correlation > 0.4


# ---------------------------------------------------------------------------
# Save / load
# ---------------------------------------------------------------------------


def test_ranking_xgb_save_load_round_trip(tmp_path: Path):
    rows = _synthetic_rows(count=30)
    model = RankingXGBModel(random_seed=3, num_boost_round=15)
    model.fit(rows)
    probe = _team_features(9800, average_score=_skill(5))
    expected = model.predict_rating(probe)

    path = tmp_path / "ranking_xgb.json"
    model.save(path)
    loaded = RankingXGBModel.load(path)

    assert loaded.predict_rating(probe) == expected
    assert loaded.best_iteration == model.best_iteration
    assert loaded.fit_train_row_count == model.fit_train_row_count


def test_ranking_xgb_save_before_fit_raises(tmp_path: Path):
    with pytest.raises(RuntimeError, match="unfit"):
        RankingXGBModel().save(tmp_path / "x.json")


def test_ranking_xgb_load_rejects_a_foreign_file(tmp_path: Path):
    path = tmp_path / "foreign.json"
    path.write_text('{"model": "epa_win_prob", "version": "1.0.0"}', encoding="utf-8")
    with pytest.raises(ValueError, match="does not contain a ranking_xgb model"):
        RankingXGBModel.load(path)


def test_ranking_xgb_load_rejects_a_feature_list_mismatch(tmp_path: Path):
    rows = _synthetic_rows(count=10)
    model = RankingXGBModel(num_boost_round=5)
    model.fit(rows)
    path = tmp_path / "ranking_xgb.json"
    model.save(path)

    data = json.loads(path.read_text(encoding="utf-8"))
    data["feature_names"] = ["epa_total"]  # a stale/foreign feature list
    path.write_text(json.dumps(data), encoding="utf-8")

    with pytest.raises(ValueError, match="does not match"):
        RankingXGBModel.load(path)
