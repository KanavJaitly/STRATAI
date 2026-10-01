"""Read-only diagnostics of the failed D16 M7 gate (changes nothing; not a re-run of the gate).

    python .agent/phase4/results/m07_failure_diagnostics.py FRAME_DIR OUT_JSON

Rebuilds the exact M7 model and calibrator (deterministic) and asks whether the
G2 failure is an implementation defect or a property of the data.
"""

from __future__ import annotations

import json
import sys
from collections import Counter
from pathlib import Path

import numpy as np

sys.path.insert(0, ".")
from ml.backtest.harness import _match_features  # noqa: E402
from ml.calibration.calibrator import SymmetricIsotonicCalibrator, _validation_split_index, fit_calibrated_win_prob_model  # noqa: E402
from ml.calibration.gate import bin_index, g2_bin_consistency  # noqa: E402
from ml.dataset.builder import LABEL_RED_WIN, LABEL_TIE  # noqa: E402
from ml.models.win_prob import WinProbXGBModel  # noqa: E402
from scripts.run_phase4_stratai import _folds, load_frame_rows  # noqa: E402


def main(frame_dir: Path, out: Path) -> None:
    rows = load_frame_rows(frame_dir)
    _, epa_fold, _, _ = _folds(rows)
    model, calibrator, _ = fit_calibrated_win_prob_model(
        WinProbXGBModel, epa_fold.train_rows, calibrator_factory=SymmetricIsotonicCalibrator)
    ordered = sorted(epa_fold.train_rows, key=lambda r: r.scheduled_time)
    split = _validation_split_index(len(ordered), 0.2)
    calibration_rows = [r for r in ordered[split:] if r.label != LABEL_TIE]
    test = [r for r in epa_fold.test_rows if r.label != LABEL_TIE]

    def predictions(rs):
        p = np.asarray([model.predict_win_prob(_match_features(r)) for r in rs])
        y = np.asarray([r.label == LABEL_RED_WIN for r in rs])
        return p, y

    p_cal, y_cal = predictions(calibration_rows)
    p_test, y_test = predictions(test)
    q_test = np.asarray([calibrator.calibrate(p) for p in p_test])
    q_cal = np.asarray([calibrator.calibrate(p) for p in p_cal])

    # 1. the served value matches the specified formula exactly (implementation check)
    g = calibrator._regressor  # noqa: SLF001
    formula = 0.5 * (g.predict(p_test) + 1 - g.predict(1 - p_test))
    formula_error = float(np.max(np.abs(formula - q_test)))

    # 2. the fitted step function near 0.5
    knots = [(round(float(x), 4), round(float(v), 4)) for x, v in zip(g.X_thresholds_, g.y_thresholds_) if 0.3 <= x <= 0.7]

    # 3. which raw predictions land in the rejected [0.5, 0.6) calibrated bin, and how they did
    in_bin = (q_test >= 0.5) & (q_test < 0.6)
    raw_in_bin = p_test[in_bin]
    raw_bands = {}
    for lo in np.arange(0.3, 0.8, 0.05):
        sel = in_bin & (p_test >= lo) & (p_test < lo + 0.05)
        if sel.sum():
            raw_bands[f"{lo:.2f}-{lo + 0.05:.2f}"] = {"n": int(sel.sum()), "calibrated_mean": round(float(q_test[sel].mean()), 4),
                                                      "observed": round(float(y_test[sel].mean()), 4)}

    # 4. the same bins on the calibration slice itself (in-sample for the calibrator)
    cal_g2 = g2_bin_consistency(q_cal.tolist(), y_cal.tolist())

    # 5. composition of calibration slice vs test season
    def composition(rs):
        return {"rows": len(rs), "first": str(rs[0].scheduled_time), "last": str(rs[-1].scheduled_time),
                "comp_level": dict(Counter(r.comp_level for r in rs)), "red_win_rate": round(float(np.mean([r.label == LABEL_RED_WIN for r in rs])), 4)}

    # 6. raw M6 reliability on the test season, for contrast
    raw_bins = {}
    for b in range(10):
        sel = np.asarray([bin_index(x) for x in p_test]) == b
        if sel.sum():
            raw_bins[str(b / 10)] = {"n": int(sel.sum()), "mean": round(float(p_test[sel].mean()), 4), "observed": round(float(y_test[sel].mean()), 4)}

    result = {
        "served_equals_formula_max_error": formula_error,
        "isotonic_knots_0.3_to_0.7": knots,
        "rejected_bin_0.5_0.6": {"n": int(in_bin.sum()), "raw_min": round(float(raw_in_bin.min()), 4),
                                 "raw_max": round(float(raw_in_bin.max()), 4), "by_raw_band": raw_bands},
        "calibration_slice_g2_in_sample": {"status": cal_g2.status, "rejected": cal_g2.rejected_bins},
        "composition": {"calibration_slice": composition(calibration_rows), "test_2026": composition(test)},
        "raw_m6_test_reliability": raw_bins,
    }
    out.write_text(json.dumps(result, indent=2))
    print(json.dumps(result, indent=1))


if __name__ == "__main__":
    main(Path(sys.argv[1]), Path(sys.argv[2]))
