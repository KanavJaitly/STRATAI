"""The served win-probability model: M6 plus its D16 symmetric isotonic calibrator.

This is exactly the pair Phase 4 evaluated under D18 M7: ``fit`` calls
``ml.calibration.calibrator.fit_calibrated_win_prob_model(WinProbXGBModel, rows,
calibrator_factory=SymmetricIsotonicCalibrator)``, the same call
scripts/run_phase4_stratai.run_m07 makes (M6 fit on the temporal first 80%,
the calibrator on the last 20%). It changes neither model; it only packages
the evaluated pair as one ``Model`` so the registry can store and serve it.

Why serve the pair, not raw M6: the qualification calibration evidence
(.agent/phase4/D18_M07_DIAGNOSTIC.md: qualification ECE 0.015) was measured
on these calibrated probabilities. M7 itself FAILED (playoffs are not
calibrated), so the API labels and gates what it serves accordingly
(api.routes.predictions).

Symmetric: M6 gives p(B, R) = 1 - p(R, B) exactly and the calibrator gives
q(1 - p) = 1 - q(p), so swapping alliances returns 1 - q.
"""

from __future__ import annotations

import json
import tempfile
from collections.abc import Sequence
from pathlib import Path
from typing import Self

from ml.calibration.calibrator import SymmetricIsotonicCalibrator, fit_calibrated_win_prob_model
from ml.dataset.builder import TrainingRow
from ml.features.assembler import MatchFeatureRow, TeamFeatures
from ml.models.win_prob import FEATURE_NAMES, WinProbXGBModel

CALIBRATED_WIN_PROB_MODEL_TYPE = "win_prob_xgb_calibrated"
CALIBRATED_WIN_PROB_MODEL_VERSION = "1.0.0"

__all__ = ["CALIBRATED_WIN_PROB_MODEL_TYPE", "CALIBRATED_WIN_PROB_MODEL_VERSION", "CalibratedWinProbModel",
           "FEATURE_NAMES"]


class CalibratedWinProbModel:
    """``Model``-protocol wrapper of (WinProbXGBModel, SymmetricIsotonicCalibrator)."""

    def __init__(self) -> None:
        self.win_prob: WinProbXGBModel | None = None
        self.calibrator: SymmetricIsotonicCalibrator | None = None
        self.fit_diagnostics: dict[str, int] = {}

    def fit(self, rows: Sequence[TrainingRow]) -> None:
        self.win_prob, self.calibrator, self.fit_diagnostics = fit_calibrated_win_prob_model(
            WinProbXGBModel, rows, calibrator_factory=SymmetricIsotonicCalibrator)

    def raw_win_prob(self, match_features: MatchFeatureRow) -> float:
        """M6's uncalibrated output (for audit; not what is served)."""
        if self.win_prob is None:
            raise RuntimeError("raw_win_prob called before fit() or load()")
        return self.win_prob.predict_win_prob(match_features)

    def predict_win_prob(self, match_features: MatchFeatureRow) -> float:
        if self.calibrator is None:
            raise RuntimeError("predict_win_prob called before fit() or load()")
        return self.calibrator.calibrate(self.raw_win_prob(match_features))

    def predict_rating(self, team_features: TeamFeatures) -> float:
        raise NotImplementedError("CalibratedWinProbModel predicts match win probabilities, not team ratings")

    def save(self, path: Path) -> None:
        """One JSON file holding both components' own saved envelopes, unchanged."""
        if self.win_prob is None or self.calibrator is None:
            raise RuntimeError("cannot save an unfit CalibratedWinProbModel")
        with tempfile.TemporaryDirectory() as directory:
            model_path, calibrator_path = Path(directory) / "m6.json", Path(directory) / "m7.json"
            self.win_prob.save(model_path)
            self.calibrator.save(calibrator_path)
            envelope = {
                "model": CALIBRATED_WIN_PROB_MODEL_TYPE, "version": CALIBRATED_WIN_PROB_MODEL_VERSION,
                "feature_names": list(FEATURE_NAMES), "fit_diagnostics": self.fit_diagnostics,
                "win_prob": json.loads(model_path.read_text(encoding="utf-8")),
                "calibrator": json.loads(calibrator_path.read_text(encoding="utf-8")),
            }
        path.write_text(json.dumps(envelope), encoding="utf-8")

    @classmethod
    def load(cls, path: Path) -> Self:
        data = json.loads(path.read_text(encoding="utf-8"))
        if data.get("model") != CALIBRATED_WIN_PROB_MODEL_TYPE:
            raise ValueError(f"{path} does not contain a {CALIBRATED_WIN_PROB_MODEL_TYPE} model "
                             f"(found {data.get('model')!r})")
        if data.get("feature_names") != list(FEATURE_NAMES):
            raise ValueError("saved feature list does not match the current win-probability FEATURE_NAMES")
        instance = cls()
        with tempfile.TemporaryDirectory() as directory:
            model_path, calibrator_path = Path(directory) / "m6.json", Path(directory) / "m7.json"
            model_path.write_text(json.dumps(data["win_prob"]), encoding="utf-8")
            calibrator_path.write_text(json.dumps(data["calibrator"]), encoding="utf-8")
            instance.win_prob = WinProbXGBModel.load(model_path)
            instance.calibrator = SymmetricIsotonicCalibrator.load(calibrator_path)
        instance.fit_diagnostics = data.get("fit_diagnostics", {})
        return instance
