"""CalibratedWinProbModel packages exactly the D18 M7 pair (synthetic data; no quality claim)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from ml.backtest.harness import _match_features
from ml.calibration.calibrator import SymmetricIsotonicCalibrator, fit_calibrated_win_prob_model
from ml.models.calibrated_win_prob import CALIBRATED_WIN_PROB_MODEL_TYPE, CalibratedWinProbModel
from ml.models.win_prob import WinProbXGBModel
from scripts.ml_bias_audit import _synthetic_win_prob_rows


@pytest.fixture(scope="module")
def rows():
    return _synthetic_win_prob_rows(count=120)


@pytest.fixture(scope="module")
def fitted(rows):
    model = CalibratedWinProbModel()
    model.fit(rows)
    return model


def test_serves_the_same_probabilities_as_the_evaluated_pipeline(rows, fitted):
    model, calibrator, diagnostics = fit_calibrated_win_prob_model(
        WinProbXGBModel, rows, calibrator_factory=SymmetricIsotonicCalibrator)
    assert fitted.fit_diagnostics == diagnostics
    for row in rows:
        features = _match_features(row)
        assert fitted.predict_win_prob(features) == calibrator.calibrate(model.predict_win_prob(features))


def test_save_load_round_trip_is_exact(tmp_path: Path, rows, fitted):
    path = tmp_path / "model.json"
    fitted.save(path)
    loaded = CalibratedWinProbModel.load(path)
    for row in rows:
        features = _match_features(row)
        assert loaded.predict_win_prob(features) == fitted.predict_win_prob(features)
        assert loaded.raw_win_prob(features) == fitted.raw_win_prob(features)


def test_swapping_alliances_gives_the_complement(rows, fitted):
    for row in rows[:40]:
        features = _match_features(row)
        swapped = features.model_copy(update={"red_teams": features.blue_teams, "blue_teams": features.red_teams})
        assert abs(fitted.predict_win_prob(features) + fitted.predict_win_prob(swapped) - 1.0) <= 1e-12


def test_load_refuses_another_model_type(tmp_path: Path, fitted):
    path = tmp_path / "model.json"
    fitted.save(path)
    data = json.loads(path.read_text(encoding="utf-8"))
    data["model"] = "win_prob_xgb"
    path.write_text(json.dumps(data), encoding="utf-8")
    with pytest.raises(ValueError, match=CALIBRATED_WIN_PROB_MODEL_TYPE):
        CalibratedWinProbModel.load(path)


def test_unfit_model_refuses_to_predict_or_save(tmp_path: Path, rows):
    model = CalibratedWinProbModel()
    with pytest.raises(RuntimeError):
        model.predict_win_prob(_match_features(rows[0]))
    with pytest.raises(RuntimeError):
        model.save(tmp_path / "x.json")
