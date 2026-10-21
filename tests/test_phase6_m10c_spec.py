"""P6-M10c DRAFT spec checks (`.agent/phase6/P6_M10C_SPEC_DRAFT.md`, PROPOSED): the proposed upset-floor link's
math only, implemented test-locally. There is no production code, nothing is fit, and no data is read."""

from __future__ import annotations

import numpy as np
import pytest
from scipy.special import expit, log_expit, log_ndtr

EPS_MAX = 0.08


def _z(x):
    return log_ndtr(x) - log_ndtr(-x)


def _q(a, eps, z):
    return eps / 2 + (1 - eps) * expit(a * z), eps / 2 + (1 - eps) * expit(-a * z)


def _loglik(a, eps, t):
    """The draft's stable log-likelihood of the observed outcome, t = a·s·z."""
    if eps == 0:
        return log_expit(t)
    return np.logaddexp(np.log(eps / 2), np.log1p(-eps) + log_expit(t))


Z = _z(np.linspace(-40, 40, 4001))


@pytest.mark.parametrize("a", [0.05, 0.9, 1.3, 5.0])
@pytest.mark.parametrize("eps", [0.0, 0.01, 0.06, EPS_MAX])
def test_the_link_is_symmetric_monotone_and_bounded(a, eps):
    q_red, q_blue = _q(a, eps, Z)
    assert np.max(np.abs(q_red + q_blue - 1.0)) <= 1e-12
    # bounded in real arithmetic; in floating point within one rounding where expit saturates
    assert np.all(np.diff(q_red) >= 0) and np.all(q_red >= eps / 2 - 1e-15) and np.all(q_red <= 1 - eps / 2 + 1e-15)
    inner = np.abs(a * Z) < 30  # strictly increasing wherever expit has not saturated
    assert np.all(np.diff(q_red[inner]) > 0)


def test_at_zero_floor_the_link_is_m10b():
    for a in (0.8, 1.32):
        assert np.array_equal(_q(a, 0.0, Z)[0], expit(a * Z))


def test_the_floor_keeps_the_low_odds_display_reachable():
    assert EPS_MAX / 2 < 0.05  # "<5%" (P6-A5) and the P6-M13 M7 low-odds check stay possible


@pytest.mark.parametrize("eps", [0.0, 0.02, EPS_MAX])
def test_the_stable_log_likelihood_matches_the_naive_form(eps):
    t = np.linspace(-30, 30, 601)
    naive = np.log(eps / 2 + (1 - eps) * expit(t))
    assert np.allclose(_loglik(1.0, eps, t), naive, rtol=0, atol=1e-12)
    assert np.all(np.isfinite(_loglik(1.0, eps, np.array([-1e4, 1e4]))))


def test_the_floor_bounds_tail_probabilities_where_the_scalar_form_does_not():
    """The diagnosed shape: sharpening (a > 1) moves the scalar form's tails toward 0 and 1; the floor holds them."""
    z_tail = _z(np.array([-2.5]))  # a v1 probability of about 0.006
    scalar = expit(1.32 * z_tail)[0]
    floored = _q(1.32, 0.06, z_tail)[0][0]
    assert scalar < 0.002 < 0.03 < floored


@pytest.mark.parametrize("eps", [0.0, 0.02, 0.06, EPS_MAX])
def test_the_unchanged_display_rule_stays_consistent_with_the_floor(eps):
    """P6-A5, unchanged: '<5%' below 0.05 and '>95%' above 0.95. With the floor, q never falls below eps/2, so the
    '<5%' bucket covers [eps/2, 0.05); it stays reachable for every eps <= 0.08. Reachable, not calibrated."""
    from ml.strategy.display import ABOVE_HIGH, BELOW_LOW, display_odds

    q_red, q_blue = _q(1.3, eps, Z)
    low = q_red[q_red < 0.05]
    assert low.size > 0 and {display_odds(float(q)) for q in low} == {BELOW_LOW}
    assert {display_odds(float(q)) for q in q_blue[q_blue > 0.95]} == {ABOVE_HIGH}
    assert float(q_red.min()) >= eps / 2 - 1e-15
