"""P11A A3: the estimator (REML, posterior with joint covariance, priors, diagnostics, labels). Synthetic data only."""

from __future__ import annotations

import numpy as np
import pytest
from scipy.optimize import minimize

from ml.alliance.estimator import (
    EstimatorError,
    EstimatorPolicy,
    design,
    drift_variance,
    fit_component,
    posterior,
    reml,
)
from tests.p11a_support import snapshot, truths


def reml_direct(A, y):
    """An independent reference: the same REML likelihood on the N x N row covariance."""
    N = len(y)
    X = np.full((N, 1), 3.0)
    AAt = A @ A.T
    scale = max(float(np.var(y)), 1e-6)

    def negll(lp):
        s2, t2 = np.exp(lp) * scale
        V = t2 * AAt + s2 * np.eye(N)
        L = np.linalg.cholesky(V)
        solve = lambda v: np.linalg.solve(L.T, np.linalg.solve(L, v))  # noqa: E731
        xvx = (X.T @ solve(X)).item()
        beta = (X.T @ solve(y)).item() / xvx
        r = y - X[:, 0] * beta
        return float(2 * np.log(np.diag(L)).sum() + np.log(xvx) + r @ solve(r))

    best = min((minimize(negll, np.array(s), method="L-BFGS-B", bounds=[(-12, 3), (-14, 3)])
                for s in ((np.log(0.5), np.log(0.05)), (np.log(0.2), np.log(0.2)))), key=lambda r: r.fun)
    return tuple(np.exp(best.x) * scale)


def _event(seed=3, noise=4.0, matches_per_team=10):
    snap = snapshot(seed=seed, noise=noise, matches_per_team=matches_per_team)
    rows = [list(r.teams) for r in snap.qual_rows]
    return snap, rows


def test_reml_matches_an_independent_direct_computation():
    snap, rows = _event()
    A = design(rows, snap.teams())
    y = np.array([r.teleop for r in snap.qual_rows])
    a, b = reml(A, y), reml_direct(A, y)
    assert a[0] == pytest.approx(b[0], rel=1e-4) and a[1] == pytest.approx(b[1], rel=1e-4)


def test_the_estimates_recover_synthetic_truths_with_honest_intervals():
    """Across many synthetic events at real-schedule sizes, 80% posterior intervals cover about 80% of the truths."""
    covered, total = 0, 0
    for seed in range(12):
        truth = truths(24, seed + 100)
        snap = snapshot(seed=seed + 100, truth=truth, noise=6.0)
        fit = fit_component("teleop", [list(r.teams) for r in snap.qual_rows],
                            [r.teleop for r in snap.qual_rows], snap.teams())
        sd = np.sqrt(np.diag(fit.cov))
        x = np.array([truth[t]["teleop"] for t in fit.teams])
        covered += int((np.abs(fit.mean - x) <= 1.2816 * sd).sum())
        total += len(x)
    assert 0.72 <= covered / total <= 0.88, covered / total


def test_the_joint_covariance_is_kept_and_partners_are_correlated():
    snap, rows = _event()
    fit = fit_component("auto", rows, [r.auto for r in snap.qual_rows], snap.teams())
    assert fit.cov.shape == (24, 24)
    off = fit.cov[~np.eye(24, dtype=bool)]
    assert (off != 0).any()
    assert np.allclose(fit.cov, fit.cov.T)
    assert np.all(np.linalg.eigvalsh(fit.cov) > 0)


def test_individual_priors_shrink_toward_the_prior_and_report_their_kind():
    snap, rows = _event(matches_per_team=4)
    teams = snap.teams()
    prior = {teams[0]: (100.0, 1e-4)}  # an extremely confident (deliberately wrong) prior
    fit = fit_component("teleop", rows, [r.teleop for r in snap.qual_rows], teams, individual=prior)
    assert fit.mean[0] == pytest.approx(100.0, abs=0.5)
    kinds = {d.team: d.prior_kind for d in fit.diagnostics}
    assert kinds[teams[0]] == "prior_event_individual" and kinds[teams[1]] == "current_event_joint"
    with pytest.raises(EstimatorError):
        posterior(design(rows, teams), np.ones(len(rows)), teams, 1.0, 1.0, {teams[0]: (1.0, 0.0)})


def test_one_extreme_match_cannot_set_a_robots_capability():
    snap, rows = _event()
    y = np.array([r.teleop for r in snap.qual_rows], dtype=float)
    teams = snap.teams()
    target = teams[0]
    first = next(i for i, r in enumerate(rows) if target in r)
    base = fit_component("teleop", rows, y, teams)
    y2 = y.copy()
    y2[first] += 200.0
    spiked = fit_component("teleop", rows, y2, teams)
    i = teams.index(target)
    assert spiked.mean[i] - base.mean[i] < 200.0 / 3  # far less than the whole jump


def test_labels_follow_the_candidate_policy_and_say_it_is_unapproved():
    snap, rows = _event(matches_per_team=3)
    fit = fit_component("auto", rows, [r.auto for r in snap.qual_rows], snap.teams(), policy=EstimatorPolicy())
    assert EstimatorPolicy().status == "candidate_unapproved"
    assert all("prior_dominated" in d.labels for d in fit.diagnostics if d.n < 4)
    assert all("weakly_identified" in d.labels for d in fit.diagnostics if d.partners < 12)


def test_a_degenerate_fit_is_flagged_unreliable():
    snap, rows = _event()
    teams = snap.teams()
    x = {t: float(i) for i, t in enumerate(teams)}
    y = [sum(x[t] for t in r) for r in rows]  # no noise at all: the REML optimum is sigma^2 = 0 (on the bound)
    fit = fit_component("auto", rows, y, teams)
    assert fit.degenerate and fit.noise.sigma2_at_bound
    assert all("fit_unreliable" in d.labels for d in fit.diagnostics)


def test_the_collapse_screen_is_descriptive_and_does_not_mark_a_good_high_signal_fit_unreliable():
    """The 2026-11-06 investigation's case: low noise (sigma/tau = 0.2) and 10 matches per robot. The screen fires,
    but the fit is accurate and not degenerate, so nothing is marked unreliable."""
    rng = np.random.default_rng(5)
    teams = list(range(1, 31))
    x = dict(zip(teams, rng.normal(20, 8, 30)))
    rows = [list(rng.permutation(teams)[i:i + 3]) for _ in range(10) for i in range(0, 30, 3)]
    rows = [r for k in range(10) for r in [rows[k * 10 + j] for j in range(10)]]
    y = [sum(x[t] for t in r) + rng.normal(0, 1.6) for r in rows]
    fit = fit_component("auto", rows, y, teams)
    assert fit.screen_flagged and not fit.degenerate
    assert 0.25 < fit.sigma2 / 1.6 ** 2 < 4  # sigma^2 is estimated, not collapsed
    assert all("collapse_screen_flagged" in d.labels and "fit_unreliable" not in d.labels for d in fit.diagnostics)
    assert fit.noise.lr_zero > 3.84 and fit.noise.residual_df > 0


def test_too_few_rows_or_malformed_rows_are_refused():
    with pytest.raises(EstimatorError) as refused:
        fit_component("auto", [[1, 2, 3]] * 5, [1.0] * 5, [1, 2, 3])
    assert refused.value.code == "insufficient_data"
    with pytest.raises(EstimatorError):
        fit_component("auto", [[1, 2]] * 20, [1.0] * 20, [1, 2])


def test_drift_variance_needs_enough_pairs_and_removes_estimation_noise():
    assert drift_variance([(1, 1, 2, 1)] * 10) is None
    rng = np.random.default_rng(0)
    pairs = []
    for _ in range(4000):
        true1 = rng.normal(0, 5)
        true2 = true1 + rng.normal(0, 2)  # true drift variance 4
        pairs.append((true1 + rng.normal(0, 1), 1.0, true2 + rng.normal(0, 1), 1.0))
    assert drift_variance(pairs) == pytest.approx(4.0, rel=0.15)
