"""The reference's rounding behaviours, reproduced exactly (spec §8).

Every expected value below is worked by hand from the definition
r(x, n) = int(x * 10**n + 0.5) / 10**n, where int() truncates toward zero.
The negative-value results are the reference's, not correct rounding; they
are asserted as-is because Level A parity needs the stored values.
"""

from __future__ import annotations

import pytest

from ml.ratings.epa.aggregate import unitless_epa
from ml.ratings.epa.rounding import numpy_round, python_round, reference_round as r


@pytest.mark.parametrize(
    ("x", "n", "expected"),
    [
        (1.234, 2, 1.23),  # 123.4 + 0.5 = 123.9 -> 123
        (1.235, 2, 1.24),  # 1.235*100 = 123.50000000000001 -> 124.00000000000001 -> 124
        (1.236, 2, 1.24),
        (49.22, 2, 49.22),
        (2.5, 0, 3.0),  # half rounds up, not to even
        (0.5, 0, 1.0),
        (1919.4, 0, 1919.0),
        (1919.5, 0, 1920.0),
    ],
)
def test_positive_values(x: float, n: int, expected: float) -> None:
    assert r(x, n) == expected


@pytest.mark.parametrize(("x", "n"), [(0.0, 0), (0.0, 2), (-0.0, 2), (0.004999, 2)])
def test_zero_and_values_that_round_to_zero(x: float, n: int) -> None:
    assert r(x, n) == 0.0


@pytest.mark.parametrize(
    ("x", "n", "expected", "correct"),
    [
        (-1.234, 2, -1.22, -1.23),  # -123.4 + 0.5 = -122.9 -> int -> -122
        (-1.236, 2, -1.23, -1.24),  # -123.6 + 0.5 = -123.1 -> -123
        (-1.5, 0, -1.0, -2.0),  # -1.0 -> -1
        (-2.5, 0, -2.0, -2.0),  # -2.0 -> -2 (agrees by coincidence)
        (-0.6, 0, 0.0, -1.0),  # -0.1 truncates to 0
        (-0.5, 0, 0.0, -0.0),
        (-0.004, 2, 0.0, -0.0),  # -0.4 + 0.5 = 0.1 -> 0
    ],
)
def test_negative_values_reproduce_truncation(x: float, n: int, expected: float, correct: float) -> None:
    assert r(x, n) == expected
    assert numpy_round(x, n) == correct  # the reference is NOT correct rounding here, by design


def test_values_near_rounding_boundaries() -> None:
    # 1.005 is stored as 1.00499999999999989..., so it rounds down
    assert r(1.005, 2) == 1.0
    # 0.125 is exact in binary: r() rounds the half up, np.round rounds to even
    assert r(0.125, 2) == 0.13
    assert numpy_round(0.125, 2) == 0.12
    assert python_round(0.125, 2) == 0.12
    assert numpy_round(0.375, 2) == 0.38
    # -0.125: r() gives int(-12.5 + 0.5) = -12 -> -0.12, the same as half-to-even
    assert r(-0.125, 2) == -0.12


def test_repeated_application_is_idempotent_for_positive_values() -> None:
    for x in (1.234, 1.235, 49.22, 0.125, 1919.5):
        once = r(x, 2)
        assert r(once, 2) == once
        assert r(r(once, 2), 2) == once
        assert numpy_round(numpy_round(x, 2), 2) == numpy_round(x, 2)


def test_repeated_application_drifts_negative_values_upward() -> None:
    # -1.22 is already at 2 decimals, yet r() moves it: -122.0 + 0.5 = -121.5 -> -121
    assert r(-1.22, 2) == -1.21
    assert r(r(-1.22, 2), 2) == -1.2
    # np.round is idempotent, so the drift is specific to r()
    assert numpy_round(numpy_round(-1.22, 2), 2) == -1.22


def test_team_event_start_applies_r_to_an_np_rounded_value() -> None:
    """te.epa_start = r(np.round(pre_epa, 2), 2) (agg.py:175): a negative pre-match
    EPA is stored one cent high. aggregate.py reproduces that composition."""
    pre_epa = -1.2203
    assert numpy_round(pre_epa, 2) == -1.22
    assert r(numpy_round(pre_epa, 2), 2) == -1.21


def test_unitless_rounds_with_r() -> None:
    from ml.ratings.epa.year_stats import YearStats

    stats = YearStats(2024, 10, 60.0, 30.0, 55.0, 5.0, 10, 30, 15, 0.2, 0.1, 0, 0.1, (0,) * 10)
    assert unitless_epa(20.0, stats) == 1500  # epa == score_mean / 3
    # 1500 + 250 * (26.0 - 20) / 30 = 1550
    assert unitless_epa(26.0, stats) == 1550
    # 1500 + 250 * (-10.0 - 20) / 30 = 1250; r() of an exact integer is exact
    assert unitless_epa(-10.0, stats) == 1250
    # 1500 + 250 * (20.0012 - 20) / 30 = 1500.01 -> 1500
    assert unitless_epa(20.0012, stats) == 1500
