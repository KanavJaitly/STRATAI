"""The D16 M7 calibration gate (ml.calibration.gate) and the symmetric calibrator."""

from __future__ import annotations

import itertools
import random
from pathlib import Path

import numpy as np
import pytest
from scipy.stats import binomtest

from ml.calibration.calibrator import SymmetricIsotonicCalibrator
from ml.calibration.gate import (
    G2_FAIL,
    G2_PASS,
    G2_UNEVALUABLE,
    bin_index,
    central_interval,
    evaluate_calibration_gate,
    g2_bin_consistency,
    holm,
    poisson_binomial_pmf,
    two_sided_p_value,
)


def test_pmf_by_hand_and_brute_force() -> None:
    assert poisson_binomial_pmf([0.5, 0.5]).tolist() == [0.25, 0.5, 0.25]
    rng = random.Random(3)
    for n in range(1, 9):
        p = [rng.random() for _ in range(n)]
        brute = np.zeros(n + 1)
        for outcome in itertools.product((0, 1), repeat=n):
            brute[sum(outcome)] += np.prod([q if o else 1 - q for q, o in zip(p, outcome)])
        assert np.max(np.abs(poisson_binomial_pmf(p) - brute)) < 1e-12


@pytest.mark.parametrize(("n", "p", "k"), [(30, 0.3, 13), (100, 0.65, 55), (500, 0.9, 461)])
def test_p_value_equals_the_exact_binomial_test_for_equal_probabilities(n: int, p: float, k: int) -> None:
    ours = two_sided_p_value(poisson_binomial_pmf([p] * n), k)
    assert ours == pytest.approx(binomtest(k, n, p, alternative="two-sided").pvalue, abs=1e-9)


def test_central_interval_brackets_the_mean() -> None:
    lo, hi = central_interval(poisson_binomial_pmf([0.5] * 100))
    assert (lo, hi) == (40, 60)


def test_holm_by_hand() -> None:
    # sorted 0.005 (<= .05/4), 0.01 (<= .05/3), 0.03 (> .05/2) stop
    assert [r for _, r in holm([0.01, 0.04, 0.03, 0.005])] == [True, False, False, True]
    assert [r for _, r in holm([0.2, 0.001])] == [False, True]
    assert [r for _, r in holm([0.04, 0.03])] == [False, False]  # 0.03 > 0.05/2: nothing rejected


def test_holm_rejects_the_smallest_when_below_its_threshold() -> None:
    assert [r for _, r in holm([0.02, 0.03])] == [True, True]  # 0.02 <= 0.025, then 0.03 <= 0.05


def test_bins_are_fixed_and_match_ece() -> None:
    assert [bin_index(q) for q in (0.0, 0.0999, 0.1, 0.6, 0.6999, 0.9, 1.0)] == [0, 0, 1, 6, 6, 9, 9]


def _calibrated(n: int, seed: int):
    rng = np.random.default_rng(seed)
    p = rng.beta(0.5, 0.5, size=n)
    return p.tolist(), (rng.random(n) < p).tolist()


def test_g2_passes_a_calibrated_sample_and_fails_a_miscalibrated_one() -> None:
    p, y = _calibrated(15000, 11)
    result = g2_bin_consistency(p, y)
    assert result.status == G2_PASS and result.eligible_bins == 10
    rng = np.random.default_rng(12)
    shifted = (rng.random(len(p)) < np.clip(np.asarray(p) + 0.05, 0, 1)).tolist()
    assert g2_bin_consistency(p, shifted).status == G2_FAIL


def test_g2_unevaluable_with_fewer_than_two_eligible_bins_is_not_a_pass() -> None:
    p = [0.62] * 100 + [0.15] * 10  # one eligible bin, one under-populated
    y = [True] * 62 + [False] * 38 + [False] * 10
    result = g2_bin_consistency(p, y)
    assert result.status == G2_UNEVALUABLE and result.eligible_bins == 1
    assert [b.tested for b in result.bins if b.count] == [False, True]
    gate = evaluate_calibration_gate(p, y, symmetry_errors=[0.0], order_independent=True, fit_isolated=True)
    assert not gate.passed  # even if G1 were to pass, unevaluable G2 blocks acceptance


def test_untested_bins_are_reported_not_passed() -> None:
    p, y = _calibrated(2000, 5)
    p += [0.55] * 5
    y += [True] * 5
    result = g2_bin_consistency(p, y)
    assert all(b.p_value is None and b.rejected is None for b in result.bins if not b.tested)


def test_gate_requires_all_four() -> None:
    p, y = _calibrated(15000, 11)
    ok = dict(symmetry_errors=[1e-16], order_independent=True, fit_isolated=True)
    assert evaluate_calibration_gate(p, y, **ok).passed
    assert not evaluate_calibration_gate(p, y, **{**ok, "symmetry_errors": [1e-9]}).passed
    assert not evaluate_calibration_gate(p, y, **{**ok, "order_independent": False}).passed
    assert not evaluate_calibration_gate(p, y, **{**ok, "fit_isolated": False}).passed


# --- symmetric calibrator ------------------------------------------------------------


def _fitted(seed: int = 1) -> SymmetricIsotonicCalibrator:
    rng = random.Random(seed)
    p = [rng.random() for _ in range(3000)]
    y = [rng.random() < min(1.0, 0.1 + 0.8 * q) for q in p]  # deliberately red-biased and compressed
    calibrator = SymmetricIsotonicCalibrator()
    calibrator.fit(p, y)
    return calibrator


def test_symmetric_calibrator_is_exactly_symmetric_and_monotone() -> None:
    calibrator = _fitted()
    rng = random.Random(9)
    points = [rng.random() for _ in range(20000)] + [0.0, 0.5, 1.0]
    assert max(abs(calibrator.calibrate(p) + calibrator.calibrate(1 - p) - 1) for p in points) <= 1e-12
    grid = [i / 1000 for i in range(1001)]
    values = [calibrator.calibrate(p) for p in grid]
    assert all(a <= b + 1e-15 for a, b in zip(values, values[1:]))
    assert calibrator.calibrate(0.5) == pytest.approx(0.5, abs=1e-15)
    assert all(0.0 <= v <= 1.0 for v in values)


def test_symmetric_calibrator_round_trip_and_errors(tmp_path: Path) -> None:
    calibrator = _fitted()
    path = tmp_path / "c.json"
    calibrator.save(path)
    loaded = SymmetricIsotonicCalibrator.load(path)
    assert all(loaded.calibrate(p) == calibrator.calibrate(p) for p in (0.01, 0.3, 0.77))
    with pytest.raises(ValueError):
        SymmetricIsotonicCalibrator().fit([], [])
    with pytest.raises(RuntimeError):
        SymmetricIsotonicCalibrator().calibrate(0.3)
    path.write_text('{"calibrator": "isotonic"}')
    with pytest.raises(ValueError):
        SymmetricIsotonicCalibrator.load(path)
