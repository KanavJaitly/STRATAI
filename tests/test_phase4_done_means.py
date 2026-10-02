"""M13's done-means gate (scripts/phase4_done_means.py): it can only report MET when both
recorded conditions passed, and it reflects the real D18 records exactly."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts.phase4_done_means import RESULTS_DIR, evaluate_done_means, main

PROJECT_ROOT = Path(__file__).resolve().parents[1]


def _write(directory: Path, ranking_passed: bool, calibration_passed: bool) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "m05v2_result.json").write_text(json.dumps({
        "passed": ranking_passed,
        "primary": {"model": {"spearman": 0.6}, "baseline_same_protocol": {"spearman": 0.5}}}))
    (directory / "m07_result.json").write_text(json.dumps({
        "passed": calibration_passed,
        "gate": {"ece": 0.02, "g2": {"status": "pass" if calibration_passed else "fail", "rejected_bins": 0,
                                     "eligible_bins": 9, "bins": [{"lower": 0.6, "count": 100,
                                                                   "mean_predicted": 0.64, "observed_rate": 0.65}]}}}))
    return directory


@pytest.mark.parametrize(("ranking", "calibration", "met"), [
    (True, True, True), (True, False, False), (False, True, False), (False, False, False)])
def test_met_only_when_both_conditions_passed(tmp_path, ranking, calibration, met):
    assert evaluate_done_means(_write(tmp_path / "r", ranking, calibration)).met is met
    assert main(["--results", str(tmp_path / "r")]) == (0 if met else 1)


def test_a_missing_record_is_an_error_not_a_pass(tmp_path):
    with pytest.raises(FileNotFoundError):
        evaluate_done_means(tmp_path)


def test_real_d18_records_ranking_met_calibration_not_met():
    result = evaluate_done_means(PROJECT_ROOT / RESULTS_DIR)
    assert result.ranking_beats_baseline is True
    assert result.win_prob_calibrated is False  # D18 M07 FAILED (G2); recorded, never re-judged
    assert result.met is False
