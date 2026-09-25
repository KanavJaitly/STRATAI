"""Phase 4 Milestone 3: pure statistical metric functions, ml.backtest.metrics.

No database, no model, no TrainingRow -- every test here is a hand-computed
value fed to a pure function, exactly the milestone's own named
"Metric-correctness test: feed known predictions/labels, assert
hand-computed Brier / log-loss / ECE" requirement, extended to every metric
this module provides (accuracy, ROC-AUC, Spearman, top-k recall too).
"""

from __future__ import annotations

import math

import pytest

from ml.backtest.metrics import (
    accuracy,
    brier_score,
    expected_calibration_error,
    log_loss,
    roc_auc,
    spearman_correlation,
    top_k_recall,
)

# ---------------------------------------------------------------------------
# accuracy
# ---------------------------------------------------------------------------


def test_accuracy_hand_computed():
    assert accuracy([0.9, 0.1, 0.6, 0.4], [True, False, True, False]) == 1.0
    assert accuracy([0.9, 0.1], [False, True]) == 0.0


def test_accuracy_exactly_half_is_scored_incorrect():
    # A 0.5 prediction is not credited either direction.
    assert accuracy([0.5], [True]) == 0.0
    assert accuracy([0.5], [False]) == 0.0


def test_accuracy_empty_is_none():
    assert accuracy([], []) is None


def test_accuracy_rejects_mismatched_lengths():
    with pytest.raises(ValueError):
        accuracy([0.5, 0.6], [True])


# ---------------------------------------------------------------------------
# log_loss
# ---------------------------------------------------------------------------


def test_log_loss_hand_computed():
    result = log_loss([0.9, 0.1], [True, False])
    expected = -(math.log(0.9) + math.log(0.9)) / 2  # both predictions are 90% confident and correct
    assert result == pytest.approx(expected)


def test_log_loss_perfect_confident_correct_is_near_zero():
    result = log_loss([1.0, 0.0], [True, False])
    assert result == pytest.approx(0.0, abs=1e-10)


def test_log_loss_confident_wrong_is_large():
    result = log_loss([0.01, 0.99], [False, True])
    # A confidently wrong prediction costs a large, specific penalty.
    expected = -(math.log(0.99) + math.log(0.99)) / 2
    assert result == pytest.approx(expected)


def test_log_loss_empty_is_none():
    assert log_loss([], []) is None


# ---------------------------------------------------------------------------
# brier_score
# ---------------------------------------------------------------------------


def test_brier_score_hand_computed():
    result = brier_score([0.9, 0.1], [True, False])
    assert result == pytest.approx(((0.9 - 1) ** 2 + (0.1 - 0) ** 2) / 2)


def test_brier_score_perfect_is_zero():
    assert brier_score([1.0, 0.0], [True, False]) == pytest.approx(0.0)


def test_brier_score_worst_case_is_one():
    assert brier_score([0.0, 1.0], [True, False]) == pytest.approx(1.0)


def test_brier_score_empty_is_none():
    assert brier_score([], []) is None


# ---------------------------------------------------------------------------
# roc_auc
# ---------------------------------------------------------------------------


def test_roc_auc_perfect_separation_is_one():
    assert roc_auc([0.9, 0.1], [True, False]) == pytest.approx(1.0)


def test_roc_auc_perfectly_wrong_separation_is_zero():
    assert roc_auc([0.1, 0.9], [True, False]) == pytest.approx(0.0)


def test_roc_auc_hand_computed_with_ties():
    # predictions [0.5, 0.5, 0.9], labels [False, True, True].
    # Ranks (ascending): the two 0.5s tie for ranks 1,2 -> average 1.5 each; 0.9 is rank 3.
    # positive_rank_sum = 1.5 (the True at 0.5) + 3 (the True at 0.9) = 4.5
    # n_pos=2, n_neg=1 -> AUC = (4.5 - 2*3/2) / (2*1) = (4.5-3)/2 = 0.75
    result = roc_auc([0.5, 0.5, 0.9], [False, True, True])
    assert result == pytest.approx(0.75)


def test_roc_auc_all_one_class_is_none():
    assert roc_auc([0.1, 0.9], [True, True]) is None
    assert roc_auc([0.1, 0.9], [False, False]) is None


def test_roc_auc_empty_is_none():
    assert roc_auc([], []) is None


# ---------------------------------------------------------------------------
# expected_calibration_error
# ---------------------------------------------------------------------------


def test_ece_well_calibrated_bin_hand_computed():
    # bin index 8 (0.85*10=8.5 -> int 8) gets one True at 0.85: |0.85-1.0|=0.15, weight 0.5
    # bin index 1 (0.15*10=1.5 -> int 1) gets one False at 0.15: |0.15-0.0|=0.15, weight 0.5
    result = expected_calibration_error([0.85, 0.15], [True, False], n_bins=10)
    assert result == pytest.approx(0.15)


def test_ece_miscalibrated_bin_hand_computed():
    # Both predictions land in bin 9 (0.9*10=9.0 -> int min(9,9)=9): mean_predicted=0.9,
    # empirical_rate = 1/2 = 0.5 (one True, one False) -> |0.9-0.5| = 0.4, weight = 1.0 (all items)
    result = expected_calibration_error([0.9, 0.9], [True, False], n_bins=10)
    assert result == pytest.approx(0.4)


def test_ece_perfectly_calibrated_is_zero():
    # Four predictions at 0.5, exactly half True -> mean_predicted=0.5, empirical_rate=0.5
    result = expected_calibration_error([0.5, 0.5, 0.5, 0.5], [True, False, True, False], n_bins=10)
    assert result == pytest.approx(0.0, abs=1e-10)


def test_ece_empty_is_none():
    assert expected_calibration_error([], [], n_bins=10) is None


def test_ece_rejects_non_positive_bins():
    with pytest.raises(ValueError):
        expected_calibration_error([0.5], [True], n_bins=0)


# ---------------------------------------------------------------------------
# spearman_correlation
# ---------------------------------------------------------------------------


def test_spearman_perfect_positive():
    assert spearman_correlation([1, 2, 3], [1, 2, 3]) == pytest.approx(1.0)


def test_spearman_perfect_negative():
    assert spearman_correlation([1, 2, 3], [3, 2, 1]) == pytest.approx(-1.0)


def test_spearman_handles_ties_via_average_rank():
    # x has a tie at positions 0,1 (both value 1) -> ranks [1.5, 1.5, 3].
    # y = [1, 2, 3] -> ranks [1, 2, 3]. Not perfectly correlated because of the tie.
    result = spearman_correlation([1, 1, 2], [1, 2, 3])
    assert result is not None
    assert 0.0 < result < 1.0


def test_spearman_constant_sequence_is_none():
    assert spearman_correlation([5, 5, 5], [1, 2, 3]) is None


def test_spearman_fewer_than_two_points_is_none():
    assert spearman_correlation([1], [1]) is None
    assert spearman_correlation([], []) is None


def test_spearman_rejects_mismatched_lengths():
    with pytest.raises(ValueError):
        spearman_correlation([1, 2], [1])


# ---------------------------------------------------------------------------
# top_k_recall
# ---------------------------------------------------------------------------


def test_top_k_recall_perfect_set_wrong_order_is_still_perfect():
    # Order within the top-k does not matter, only set membership.
    result = top_k_recall(["b", "a", "d", "c"], ["a", "b", "c", "d"], k=2)
    assert result == pytest.approx(1.0)


def test_top_k_recall_hand_computed_partial_overlap():
    result = top_k_recall(["a", "b", "c", "d"], ["a", "b", "x", "y"], k=4)
    assert result == pytest.approx(2 / 4)


def test_top_k_recall_reduces_k_to_field_size():
    # Only 3 real teams exist; k=8 must not silently pretend there were 8.
    result = top_k_recall(["a", "b", "c"], ["a", "b", "c"], k=8)
    assert result == pytest.approx(1.0)


def test_top_k_recall_empty_ground_truth_is_none():
    assert top_k_recall(["a", "b"], [], k=8) is None


def test_top_k_recall_empty_predictions_is_none():
    assert top_k_recall([], ["a", "b"], k=8) is None


def test_top_k_recall_accepts_non_string_hashables():
    # Real callers pass team_number ints, not strings.
    result = top_k_recall([254, 1114, 33], [1114, 254, 99], k=2)
    assert result == pytest.approx(1.0)
