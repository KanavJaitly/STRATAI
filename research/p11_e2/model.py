"""P11A E2 research: the estimators and baselines of PROTOCOL.json, as pure functions (numpy/scipy only).

The model (spec A3.2 / B5), per event and component:

    y_r = sum over robots t in alliance row r of x_t + e_r,   e_r ~ N(0, sigma^2)

Robot priors are one of:
- individual: x_t ~ N(m_t, v_t) (spec A3.2 (i));
- population: x_t = mu + u_t, u_t ~ N(0, tau^2), mu with a flat prior, estimated jointly (A3.2 (iii));
- plug-in (diagnostic only): x_t ~ N(mu_hat, tau^2), mu_hat = mean(y)/3 from the same rows, treated as known.

The posterior is exact, by weighted least squares with prior pseudo-observations: precision H, mean H^-1 b, covariance
H^-1. sigma^2 and tau^2 are fitted by REML on the event's qualification rows.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from scipy.optimize import minimize

ROBOTS = 3


def design(rows: list[list[int]], teams: list[int]) -> np.ndarray:
    index = {t: i for i, t in enumerate(teams)}
    A = np.zeros((len(rows), len(teams)))
    for r, alliance in enumerate(rows):
        for t in alliance:
            A[r, index[t]] += 1.0
    return A


def reml_objective(A: np.ndarray, y: np.ndarray):
    """(negll, scale): negll(log_params) is -2 x the REML log-likelihood (up to a constant) at
    (sigma^2, tau^2) = exp(log_params) * scale, with scale = var(y).

    It is evaluated exactly on the n x n team matrix, not the N x N row matrix, by the Woodbury identity:
    V = s2 I + t2 A A', log|V| = N log s2 + log|I + (t2/s2) A'A|, and V^-1 v = (v - A K^-1 A' v) / s2 with
    K = (s2/t2) I + A'A. It gives the same value as the direct form (tests: reml_direct)."""
    N, n = A.shape
    X = np.full(N, float(ROBOTS))
    AtA, Aty, AtX = A.T @ A, A.T @ y, A.T @ X
    yy, Xy, XX = float(y @ y), float(X @ y), float(X @ X)
    scale = max(float(np.var(y)), 1e-6)
    eye = np.eye(n)

    def negll(log_params: np.ndarray) -> float:
        s2, t2 = np.exp(log_params) * scale
        try:
            L = np.linalg.cholesky(eye + (t2 / s2) * AtA)
            Lk = np.linalg.cholesky((s2 / t2) * eye + AtA)
        except np.linalg.LinAlgError:
            return 1e12
        logdet = N * np.log(s2) + 2 * np.log(np.diag(L)).sum()

        def quad(u_dot_v: float, Atu: np.ndarray, Atv: np.ndarray) -> float:  # u' V^-1 v
            w = np.linalg.solve(Lk, Atv)
            z = np.linalg.solve(Lk, Atu)
            return (u_dot_v - float(z @ w)) / s2

        XtViX = quad(XX, AtX, AtX)
        beta = quad(Xy, AtX, Aty) / XtViX
        rr = yy - 2 * beta * Xy + beta ** 2 * XX
        Atr = Aty - beta * AtX
        rVr = (rr - float(np.linalg.solve(Lk, Atr) @ np.linalg.solve(Lk, Atr))) / s2
        return float(logdet + np.log(XtViX) + rVr)

    return negll, scale


def reml(A: np.ndarray, y: np.ndarray) -> tuple[float, float]:
    """(sigma^2, tau^2) maximizing the REML likelihood of y ~ N(3 mu 1, tau^2 A A' + sigma^2 I), mu integrated
    (the objective is `reml_objective`)."""
    negll, scale = reml_objective(A, y)
    best = None
    for start in ((np.log(0.5), np.log(0.05)), (np.log(0.2), np.log(0.2))):
        res = minimize(negll, np.array(start), method="L-BFGS-B", bounds=[(-12, 3), (-14, 3)])
        if best is None or res.fun < best.fun:
            best = res
    s2, t2 = np.exp(best.x) * scale
    return float(s2), float(t2)


def reml_tau_given_sigma(A: np.ndarray, y: np.ndarray, sigma2: float) -> float:
    """tau^2 maximizing the same REML likelihood with sigma^2 held fixed (follow-up F3 variant V3)."""
    negll, scale = reml_objective(A, y)
    log_s = np.log(sigma2 / scale)
    res = minimize(lambda v: negll(np.array([log_s, v[0]])), np.array([np.log(0.1)]), method="L-BFGS-B",
                   bounds=[(-14, 3)])
    return float(np.exp(res.x[0]) * scale)


def reml_direct(A: np.ndarray, y: np.ndarray) -> tuple[float, float]:
    """The direct N x N form of `reml`, kept as its reference. (sigma^2, tau^2) maximizing the REML likelihood of y ~ N(3 mu 1, tau^2 A A' + sigma^2 I), mu integrated."""
    N = len(y)
    X = np.full((N, 1), float(ROBOTS))
    AAt = A @ A.T
    scale = max(float(np.var(y)), 1e-6)

    def negll(log_params: np.ndarray) -> float:
        s2, t2 = np.exp(log_params) * scale
        V = t2 * AAt + s2 * np.eye(N)
        try:
            L = np.linalg.cholesky(V)
        except np.linalg.LinAlgError:
            return 1e12
        Vi_X = np.linalg.solve(L.T, np.linalg.solve(L, X))
        Vi_y = np.linalg.solve(L.T, np.linalg.solve(L, y))
        XtViX = (X.T @ Vi_X).item()
        beta = (X.T @ Vi_y).item() / XtViX
        resid = y - X[:, 0] * beta
        Vi_r = np.linalg.solve(L.T, np.linalg.solve(L, resid))
        return float(2 * np.log(np.diag(L)).sum() + np.log(XtViX) + resid @ Vi_r)

    best = None
    for start in ((np.log(0.5), np.log(0.05)), (np.log(0.2), np.log(0.2))):
        res = minimize(negll, np.array(start), method="L-BFGS-B", bounds=[(-12, 3), (-14, 3)])
        if best is None or res.fun < best.fun:
            best = res
    s2, t2 = np.exp(best.x) * scale
    return float(s2), float(t2)


@dataclass
class Posterior:
    teams: list[int]
    mean: np.ndarray  # robots only
    cov: np.ndarray  # robots only (mu integrated out)
    sigma2: float
    tau2: float
    kind: str
    prior_var: np.ndarray  # each robot's marginal prior variance (for w_eff)

    def predict(self, alliance: list[int]) -> tuple[float, float, float]:
        """(mean, estimation variance with full covariance, estimation variance with the diagonal only)."""
        a = self.vector(alliance)
        return float(a @ self.mean), float(a @ self.cov @ a), float((a * a) @ np.diag(self.cov))

    def vector(self, alliance: list[int]) -> np.ndarray:
        index = {t: i for i, t in enumerate(self.teams)}
        a = np.zeros(len(self.teams))
        for t in alliance:
            a[index[t]] += 1.0
        return a


def posterior(A: np.ndarray, y: np.ndarray, teams: list[int], sigma2: float, tau2: float, *,
              individual: dict[int, tuple[float, float]] | None = None, plugin: bool = False) -> Posterior:
    """The exact Gaussian posterior. `individual` maps team -> (prior mean, prior variance) for robots with an
    independent individual prior. Every other robot gets the population prior (mu flat and joint), or the plug-in."""
    individual = individual or {}
    n = len(teams)
    population = [i for i, t in enumerate(teams) if t not in individual]
    use_mu = bool(population) and not plugin
    p = n + (1 if use_mu else 0)
    H = (A.T @ A) / sigma2
    b = (A.T @ y) / sigma2
    if use_mu:
        H = np.pad(H, ((0, 1), (0, 1)))
        b = np.pad(b, (0, 1))
    mu_hat = float(np.mean(y)) / ROBOTS
    prior_var = np.zeros(n)
    for i, t in enumerate(teams):
        if t in individual:
            m, v = individual[t]
            H[i, i] += 1.0 / v
            b[i] += m / v
            prior_var[i] = v
        elif use_mu:  # pseudo-observation 0 = x_i - mu, precision 1/tau2
            h = np.zeros(p)
            h[i], h[n] = 1.0, -1.0
            H += np.outer(h, h) / tau2
            prior_var[i] = np.inf  # the marginal prior is improper (flat mu); w_eff uses tau2 below
        else:  # plug-in: x_i ~ N(mu_hat, tau2) treated as known
            H[i, i] += 1.0 / tau2
            b[i] += mu_hat / tau2
            prior_var[i] = tau2
    cov = np.linalg.inv(H)
    mean = cov @ b
    kind = "plugin" if plugin else ("individual+population" if individual and population else
                                    ("individual" if individual else "population_joint"))
    pv = np.where(np.isinf(prior_var), tau2, prior_var)
    return Posterior(list(teams), mean[:n], cov[:n, :n], sigma2, tau2, kind, pv)


def w_eff(post: Posterior) -> np.ndarray:
    """Effective data weight per robot: 1 - posterior variance / prior variance (spec A3.2)."""
    return 1.0 - np.diag(post.cov) / post.prior_var


def plain_opr(A: np.ndarray, y: np.ndarray, ridge: float = 1e-6) -> tuple[np.ndarray, np.ndarray, float]:
    """Least-squares OPR: (estimates, (A'A + ridge I)^-1, residual variance s^2)."""
    n = A.shape[1]
    G = np.linalg.inv(A.T @ A + ridge * np.eye(n))
    x = G @ (A.T @ y)
    resid = y - A @ x
    dof = max(len(y) - n, 1)
    return x, G, float(resid @ resid / dof)
