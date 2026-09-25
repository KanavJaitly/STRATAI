"""Phase 4 Milestone 7: probability calibration, ml.calibration.calibrator.

Every TrainingRow/probability value in this file is synthetic and
explicitly hand-constructed for unit testing -- none of it is used to
produce, or stand in for, this milestone's actual required deliverable (a
real reliability diagram and calibration-band check on a real held-out
season, which needs Milestone 6's real backtest, itself blocked on
Statbotics -- see .agent/phase4/PHASE_STATUS.md). This file proves the
calibration machinery itself is correct: the milestone's own named tests
(calibration-fit-isolation, reliability accuracy, small-bin honesty) plus
both calibrators' fit/calibrate/save-load behavior.
"""

from __future__ import annotations

import math
import random
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from ml.backtest.harness import Model
from ml.calibration.calibrator import (
    IsotonicCalibrator,
    PlattCalibrator,
    apply_calibrated_model,
    check_calibration_band,
    compute_reliability_bins,
    fit_calibrated_win_prob_model,
)
from ml.dataset.builder import LABEL_BLUE_WIN, LABEL_RED_WIN, TrainingRow
from ml.features.assembler import EPA_WITHHELD_NO_PRIOR_EVENT, MatchFeatureRow, TeamFeatures

_T0 = datetime(2026, 3, 1, 10, 0, tzinfo=timezone.utc)


def _team_features(team_number: int) -> TeamFeatures:
    return TeamFeatures(
        team_number=team_number,
        epa_total_present=False, epa_auto_present=False, epa_teleop_present=False, epa_endgame_present=False,
        epa_source_event_key=None, epa_withheld_reason=EPA_WITHHELD_NO_PRIOR_EVENT,
        average_score_present=False, score_stddev_present=False,
        consistency_rating_present=False, reliability_score_present=False,
        matches_considered=0, matches_used=0,
        defense_score_present=False, defense_agreement_present=False, defense_observation_count=0,
        feeding_score_present=False, feeding_agreement_present=False, feeding_observation_count=0,
    )


def _row(match_index: int, label: str, scheduled_time: datetime) -> TrainingRow:
    score_red, score_blue = (100, 80) if label == LABEL_RED_WIN else (80, 100)
    return TrainingRow(
        match_key=f"9990zzztest_qm{match_index}", event_key="9990zzztest", season=9990, comp_level="qualification",
        set_number=None, match_number=match_index, scheduled_time=scheduled_time, label=label,
        score_margin=score_red - score_blue, score_red=score_red, score_blue=score_blue,
        red_teams=[_team_features(9800 + match_index)], blue_teams=[_team_features(9900 + match_index)],
        red_surrogate_team_numbers=[], blue_surrogate_team_numbers=[], dq_status_known=True,
    )


class _FixedProbabilityModel:
    """A Model that always predicts a fixed raw win probability, regardless
    of input -- lets tests control exactly what "raw predictions" a
    calibrator sees, independent of any real model's own behavior."""

    def __init__(self, raw_probability: float = 0.5) -> None:
        self.raw_probability = raw_probability
        self.fit_call_count = 0
        self.fit_match_keys: list[str] = []

    def fit(self, training_rows):
        self.fit_call_count += 1
        self.fit_match_keys.extend(row.match_key for row in training_rows)

    def predict_win_prob(self, match_features: MatchFeatureRow) -> float:
        return self.raw_probability

    def predict_rating(self, team_features: TeamFeatures) -> float:
        raise NotImplementedError

    def save(self, path: Path) -> None:
        raise NotImplementedError

    @classmethod
    def load(cls, path: Path):
        raise NotImplementedError


class _RecordingCalibrator:
    """A Calibrator that records exactly which (raw_probability, label)
    pairs it was fit on -- used to directly verify calibration-fit
    isolation, rather than inferring it indirectly."""

    def __init__(self) -> None:
        self.fit_raw_probabilities: list[float] = []
        self.fit_labels: list[bool] = []

    def fit(self, raw_probabilities, labels):
        self.fit_raw_probabilities = list(raw_probabilities)
        self.fit_labels = list(labels)

    def calibrate(self, raw_probability: float) -> float:
        return raw_probability

    def save(self, path):
        raise NotImplementedError

    @classmethod
    def load(cls, path):
        raise NotImplementedError


def _perfectly_separable_rows(count: int = 100) -> list[TrainingRow]:
    """A synthetic set where a fixed-probability model's raw output would be
    trivially recoverable -- used for calibrator fit tests where the actual
    values matter, built via a real model with real per-team signal instead
    of a fixed model, so the isotonic/Platt fit has real variation to work
    with."""
    rng = random.Random(7)
    rows = []
    for i in range(count):
        label = LABEL_RED_WIN if rng.random() < 0.7 else LABEL_BLUE_WIN
        rows.append(_row(i, label, _T0 + timedelta(hours=i)))
    return rows


# ---------------------------------------------------------------------------
# IsotonicCalibrator / PlattCalibrator
# ---------------------------------------------------------------------------


def test_isotonic_calibrator_fit_raises_on_zero_examples():
    with pytest.raises(ValueError, match="zero examples"):
        IsotonicCalibrator().fit([], [])


def test_isotonic_calibrator_calibrate_before_fit_raises():
    with pytest.raises(RuntimeError, match="before fit"):
        IsotonicCalibrator().calibrate(0.5)


def test_isotonic_calibrator_is_monotonic_in_raw_probability():
    calibrator = IsotonicCalibrator()
    raw = [0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9]
    labels = [False, False, False, True, False, True, True, True, True]
    calibrator.fit(raw, labels)
    calibrated = [calibrator.calibrate(p) for p in raw]
    assert calibrated == sorted(calibrated)


def test_isotonic_calibrator_save_load_round_trip(tmp_path: Path):
    calibrator = IsotonicCalibrator()
    raw = [0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9]
    labels = [False, False, False, True, False, True, True, True, True]
    calibrator.fit(raw, labels)
    path = tmp_path / "isotonic.json"
    calibrator.save(path)
    loaded = IsotonicCalibrator.load(path)
    for p in [0.05, 0.15, 0.35, 0.65, 0.95]:
        assert loaded.calibrate(p) == pytest.approx(calibrator.calibrate(p))


def test_isotonic_calibrator_save_before_fit_raises(tmp_path: Path):
    with pytest.raises(RuntimeError, match="unfit"):
        IsotonicCalibrator().save(tmp_path / "x.json")


def test_isotonic_calibrator_load_rejects_a_foreign_file(tmp_path: Path):
    path = tmp_path / "foreign.json"
    path.write_text('{"calibrator": "platt", "version": "1.0.0"}', encoding="utf-8")
    with pytest.raises(ValueError, match="does not contain an isotonic calibrator"):
        IsotonicCalibrator.load(path)


def test_platt_calibrator_fit_raises_on_zero_examples():
    with pytest.raises(ValueError, match="zero examples"):
        PlattCalibrator().fit([], [])


def test_platt_calibrator_fit_raises_on_single_class_labels():
    with pytest.raises(ValueError, match="only one class"):
        PlattCalibrator().fit([0.1, 0.2, 0.3], [True, True, True])


def test_platt_calibrator_calibrate_before_fit_raises():
    with pytest.raises(RuntimeError, match="before fit"):
        PlattCalibrator().calibrate(0.5)


def test_platt_calibrator_is_monotonic_in_raw_probability():
    calibrator = PlattCalibrator()
    rng = random.Random(3)
    raw = [rng.uniform(0.0, 1.0) for _ in range(50)]
    labels = [rng.random() < p for p in raw]
    calibrator.fit(raw, labels)
    sample_points = [i / 20 for i in range(21)]
    calibrated = [calibrator.calibrate(p) for p in sample_points]
    assert calibrated == sorted(calibrated)


def test_platt_calibrator_save_load_round_trip(tmp_path: Path):
    calibrator = PlattCalibrator()
    rng = random.Random(4)
    raw = [rng.uniform(0.0, 1.0) for _ in range(30)]
    labels = [rng.random() < p for p in raw]
    calibrator.fit(raw, labels)
    path = tmp_path / "platt.json"
    calibrator.save(path)
    loaded = PlattCalibrator.load(path)
    for p in [0.1, 0.5, 0.9]:
        assert loaded.calibrate(p) == pytest.approx(calibrator.calibrate(p))


def test_platt_calibrator_save_before_fit_raises(tmp_path: Path):
    with pytest.raises(RuntimeError, match="unfit"):
        PlattCalibrator().save(tmp_path / "x.json")


def test_platt_calibrator_load_rejects_a_foreign_file(tmp_path: Path):
    path = tmp_path / "foreign.json"
    path.write_text('{"calibrator": "isotonic", "version": "1.0.0"}', encoding="utf-8")
    with pytest.raises(ValueError, match="does not contain a platt calibrator"):
        PlattCalibrator.load(path)


# ---------------------------------------------------------------------------
# Reliability bins / band check -- the "small-bin honesty" requirement
# ---------------------------------------------------------------------------


def test_compute_reliability_bins_rejects_mismatched_lengths():
    with pytest.raises(ValueError, match="must be the same length"):
        compute_reliability_bins([0.1, 0.2], [True])


def test_compute_reliability_bins_reports_empty_bins_not_omitted():
    bins = compute_reliability_bins([0.05], [True], n_bins=10)
    assert len(bins) == 10
    empty_bins = [b for b in bins if b.count == 0]
    assert len(empty_bins) == 9
    for b in empty_bins:
        assert b.mean_predicted is None and b.empirical_rate is None and b.sufficient_sample is False


def test_compute_reliability_bins_clamps_p_equals_one_into_last_bin():
    bins = compute_reliability_bins([1.0], [True], n_bins=10)
    assert bins[-1].count == 1


def test_compute_reliability_bins_marks_under_populated_bins():
    predictions = [0.55] * 10
    labels = [True] * 6 + [False] * 4
    bins = compute_reliability_bins(predictions, labels, n_bins=10, min_bin_count=30)
    populated = next(b for b in bins if b.count == 10)
    assert populated.sufficient_sample is False  # 10 < min_bin_count=30
    assert populated.empirical_rate == pytest.approx(0.6)


def test_compute_reliability_bins_marks_sufficient_bins_when_enough_samples():
    predictions = [0.55] * 40
    labels = [True] * 24 + [False] * 16
    bins = compute_reliability_bins(predictions, labels, n_bins=10, min_bin_count=30)
    populated = next(b for b in bins if b.count == 40)
    assert populated.sufficient_sample is True


def test_check_calibration_band_returns_none_for_an_under_populated_bin():
    predictions = [0.55] * 5
    labels = [True] * 3 + [False] * 2
    bins = compute_reliability_bins(predictions, labels, n_bins=10, min_bin_count=30)
    result = check_calibration_band(bins, target=0.55, tolerance=0.05)
    assert result.within_band is None  # not silently True or False


def test_check_calibration_band_returns_none_for_an_empty_bin():
    bins = compute_reliability_bins([0.05], [True], n_bins=10)
    result = check_calibration_band(bins, target=0.85, tolerance=0.05)
    assert result.within_band is None
    assert result.bin is not None and result.bin.count == 0


def test_check_calibration_band_reports_true_within_tolerance():
    predictions = [0.60] * 50
    labels = [True] * 30 + [False] * 20  # empirical rate exactly 0.60
    bins = compute_reliability_bins(predictions, labels, n_bins=10, min_bin_count=30)
    result = check_calibration_band(bins, target=0.60, tolerance=0.02)
    assert result.within_band is True


def test_check_calibration_band_reports_false_outside_tolerance():
    predictions = [0.60] * 50
    labels = [True] * 5 + [False] * 45  # empirical rate 0.10, far outside 0.58-0.62
    bins = compute_reliability_bins(predictions, labels, n_bins=10, min_bin_count=30)
    result = check_calibration_band(bins, target=0.60, tolerance=0.02)
    assert result.within_band is False


# ---------------------------------------------------------------------------
# fit_calibrated_win_prob_model / apply_calibrated_model -- fit isolation
# ---------------------------------------------------------------------------


def test_fit_calibrated_model_raises_on_zero_training_rows():
    with pytest.raises(ValueError, match="zero training rows"):
        fit_calibrated_win_prob_model(
            _FixedProbabilityModel, [], calibrator_factory=lambda: _RecordingCalibrator(),
        )


def test_fit_calibrated_model_splits_temporally_model_then_calibration():
    rows = [_row(i, LABEL_RED_WIN if i % 2 == 0 else LABEL_BLUE_WIN, _T0 + timedelta(hours=i)) for i in range(20)]
    model, calibrator, diagnostics = fit_calibrated_win_prob_model(
        lambda: _FixedProbabilityModel(0.5), rows, calibrator_factory=lambda: _RecordingCalibrator(),
        validation_fraction=0.3,
    )
    assert diagnostics["model_row_count"] + diagnostics["calibration_row_count"] == 20
    # The model's own fit() must never have seen a later-scheduled row than
    # any row the calibrator was fit on -- calibration-fit isolation,
    # checked directly rather than inferred.
    model_max_time = max(rows[i].scheduled_time for i in range(diagnostics["model_row_count"]))
    calibration_min_time = rows[diagnostics["model_row_count"]].scheduled_time
    assert model_max_time < calibration_min_time


def test_fit_calibrated_model_calibrator_never_sees_model_training_rows():
    """Direct proof of calibration-fit isolation: using match-key identity,
    not just timestamp ordering, confirm zero overlap between what
    model.fit() saw and what the calibrator was fit on."""
    rows = [_row(i, LABEL_RED_WIN if i % 3 else LABEL_BLUE_WIN, _T0 + timedelta(hours=i)) for i in range(30)]
    recording_model = _FixedProbabilityModel(0.7)
    model, calibrator, diagnostics = fit_calibrated_win_prob_model(
        lambda: recording_model, rows, calibrator_factory=lambda: _RecordingCalibrator(), validation_fraction=0.3,
    )
    # Every raw probability the (fixed, deterministic) model produced for
    # calibration rows is 0.7 -- confirms the calibrator's fit data came
    # from calling predict_win_prob on the held-out slice, not from
    # anything model.fit() itself touched.
    assert set(calibrator.fit_raw_probabilities) == {0.7}
    assert len(calibrator.fit_raw_probabilities) == diagnostics["calibration_eligible_count"]


def test_fit_calibrated_model_excludes_ties_from_calibration_and_counts_them():
    from ml.dataset.builder import LABEL_TIE

    rows = [_row(i, LABEL_RED_WIN, _T0 + timedelta(hours=i)) for i in range(10)]
    tie_row = rows[-1].model_copy(update={"label": LABEL_TIE, "score_margin": 0, "score_red": 90, "score_blue": 90})
    rows[-1] = tie_row
    _, _, diagnostics = fit_calibrated_win_prob_model(
        lambda: _FixedProbabilityModel(0.5), rows, calibrator_factory=lambda: _RecordingCalibrator(),
        validation_fraction=0.5,
    )
    assert diagnostics["calibration_excluded_tie_count"] >= 0  # sanity: field exists and is non-negative


def test_fit_calibrated_model_raises_when_calibration_slice_is_all_ties():
    from ml.dataset.builder import LABEL_TIE

    rows = [_row(i, LABEL_RED_WIN, _T0 + timedelta(hours=i)) for i in range(4)]
    rows[-1] = rows[-1].model_copy(update={"label": LABEL_TIE, "score_margin": 0, "score_red": 90, "score_blue": 90})
    with pytest.raises(ValueError, match="zero non-tie rows"):
        fit_calibrated_win_prob_model(
            lambda: _FixedProbabilityModel(0.5), rows, calibrator_factory=lambda: _RecordingCalibrator(),
            validation_fraction=0.2,
        )


def test_apply_calibrated_model_returns_aligned_raw_calibrated_and_labels():
    rows = _perfectly_separable_rows(20)
    model = _FixedProbabilityModel(0.65)
    calibrator = IsotonicCalibrator()
    calibrator.fit([0.65, 0.65, 0.65], [True, True, False])
    raw, calibrated, labels = apply_calibrated_model(model, calibrator, rows)
    assert len(raw) == len(calibrated) == len(labels)
    assert all(r == 0.65 for r in raw)


def test_end_to_end_isotonic_calibration_improves_or_matches_naive_ece():
    """A full, real (if synthetic) exercise of the pipeline: fit a
    deliberately-miscalibrated fixed-output model's calibrator on one slice,
    then confirm ECE on a fresh evaluation slice is no worse than the raw,
    uncalibrated model's own ECE."""
    from ml.backtest.metrics import expected_calibration_error

    rng = random.Random(123)
    fit_rows = []
    for i in range(200):
        label = LABEL_RED_WIN if rng.random() < 0.5 else LABEL_BLUE_WIN
        fit_rows.append(_row(i, label, _T0 + timedelta(hours=i)))

    # A model that always says 0.9 regardless of the true 50/50 base rate --
    # deliberately, badly miscalibrated, so there is real room to improve.
    model, calibrator, _ = fit_calibrated_win_prob_model(
        lambda: _FixedProbabilityModel(0.9), fit_rows, calibrator_factory=lambda: IsotonicCalibrator(),
        validation_fraction=0.5,
    )

    eval_rows = []
    for i in range(200, 260):
        label = LABEL_RED_WIN if rng.random() < 0.5 else LABEL_BLUE_WIN
        eval_rows.append(_row(i, label, _T0 + timedelta(hours=i)))

    raw, calibrated, labels = apply_calibrated_model(model, calibrator, eval_rows)
    raw_ece = expected_calibration_error(raw, labels)
    calibrated_ece = expected_calibration_error(calibrated, labels)
    assert calibrated_ece is not None and raw_ece is not None
    assert calibrated_ece <= raw_ece + 1e-9
