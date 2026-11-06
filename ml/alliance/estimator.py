"""P11A A3: per-robot component estimates at one event, with their joint uncertainty and diagnostics.

docs/P11-RecommendationIntelligence.md A3 (PROPOSED). E2 evidence: docs/P11-E2-Benchmark-Report.md.

**The model, per event and component:**

    y_r = sum of x_t over the three robots t of alliance row r  +  e_r,    e_r ~ N(0, sigma^2)

- **Robots with an independent individual prior** (A3.2 (i)): x_t ~ N(m_t, v_t). Here m_t is the robot's estimate
  from its most recent earlier same-season event, and v_t is its posterior variance plus a drift variance.
- **Every other robot** gets the current-event population prior (A3.2 (iii)): x_t = mu + u_t, with u_t ~ N(0, tau^2),
  and mu estimated **jointly** in the same model (flat prior, integrated).
- **The plug-in** (a mean computed from the same rows, then treated as known) is **not offered**: spec A3.2 prohibits
  it.
- **sigma^2 and tau^2** are fitted by REML on the event's rows, evaluated exactly on the team matrix (Woodbury).
- **The posterior is exact** (Gaussian weighted least squares with prior pseudo-observations). Its full joint
  covariance is kept (A3.3, B5.2).

**Diagnostics** (A3.2, A3.7):
- per robot: n (rows), distinct partners, the largest |posterior correlation| with another robot, and the effective
  data weight w_eff = 1 − posterior variance / prior variance;
- per event fit (`NoiseDiagnostics`):
  - the **collapse screen** σ̂² / var(y) < 0.05 (E2 §21). It is **non-authoritative**: the 2026-11-06 investigation
    (research/p11a_hardening/collapse_check.py, docs/phase11.md "P11A hardening") showed it measures the residual
    share of the variance (about r²/(3 + r²) for r = σ/τ), so it fires on well-fitted high-signal events (100% false
    positives at r = 0.2 with 6-10 matches, where coverage was nominal) and cannot tell them from collapsed fits;
  - whether σ̂² sits on the optimizer's lower bound (a degenerate optimum, E2 §21 safeguard 2);
  - the profile-likelihood ratio for σ² = 0, and the residual degrees of freedom.
  - No data-only indicator tested detects short-schedule collapse (σ̂²/σ² < 0.25) reliably. That stays an open
    limitation, mitigated only by the per-robot labels and by every interval being `not_calibrated`.

**Labels** (candidate thresholds, NOT APPROVED, from E2 report §17; carried in every output as
`thresholds_status: candidate_unapproved`):
- `prior_dominated` when n < n_min or w_eff < w_min;
- `weakly_identified` when max |corr| > max_abs_corr or partners < min_partners;
- `fit_unreliable` (the whole component fit) only when σ̂² is on the optimizer bound (degenerate);
- `collapse_screen_flagged` (descriptive, non-authoritative) when the screen fires.

**Status.**
- Every estimate is `not_validated`. Individual estimates are never described as validated, because only aggregate
  alliance points are observed (E1b; no qualifying per-robot ground truth exists).
- Intervals are `not_calibrated`. In E2, nominal 80% intervals covered 68% of playoff alliance scores.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field

import numpy as np
from scipy.optimize import minimize

ROBOTS = 3
ESTIMATOR_VERSION = "p11a-a3-v1"


@dataclass(frozen=True)
class EstimatorPolicy:
    """The label thresholds. Candidate values from the E2 report; none is approved (spec §21.3, P11A-Q3)."""

    n_min: int = 4
    w_min: float = 0.4
    max_abs_corr: float = 0.5
    min_partners: int = 12
    collapse_ratio: float = 0.05
    status: str = "candidate_unapproved"


@dataclass(frozen=True)
class RobotDiagnostics:
    team: int
    n: int
    partners: int
    max_abs_corr: float
    w_eff: float
    prior_kind: str  # "prior_event_individual" | "current_event_joint"
    labels: tuple[str, ...]


@dataclass
class ComponentFit:
    component: str
    teams: list[int]
    mean: np.ndarray
    cov: np.ndarray
    sigma2: float
    tau2: float
    rows: int
    degenerate: bool  # sigma^2 on the optimizer bound: the only fit-level condition that withholds a plan
    noise: NoiseDiagnostics | None = None
    collapse_ratio: float | None = None  # sigma_hat^2 / var(y)
    screen_flagged: bool = False  # collapse_ratio < policy.collapse_ratio (non-authoritative)
    diagnostics: list[RobotDiagnostics] = field(default_factory=list)

    def index(self) -> dict[int, int]:
        return {t: i for i, t in enumerate(self.teams)}

    def vector(self, alliance: Sequence[int]) -> np.ndarray:
        idx = self.index()
        a = np.zeros(len(self.teams))
        for t in alliance:
            a[idx[t]] += 1.0
        return a


class EstimatorError(ValueError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


def design(rows: Sequence[Sequence[int]], teams: Sequence[int]) -> np.ndarray:
    index = {t: i for i, t in enumerate(teams)}
    A = np.zeros((len(rows), len(teams)))
    for r, alliance in enumerate(rows):
        for t in alliance:
            A[r, index[t]] += 1.0
    return A


LOG_BOUNDS = ((-12.0, 3.0), (-14.0, 3.0))  # log(sigma^2 / var(y)), log(tau^2 / var(y)) for the optimizer


def reml_objective(A: np.ndarray, y: np.ndarray):
    """(negll, scale): -2 log REML likelihood (up to a constant) as a function of (log sigma^2/scale,
    log tau^2/scale), and scale = var(y). Shared by `reml` and the diagnostics, so they judge the same likelihood."""
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
        zx = np.linalg.solve(Lk, AtX)
        xvx = (XX - float(zx @ zx)) / s2
        beta = ((Xy - float(zx @ np.linalg.solve(Lk, Aty))) / s2) / xvx
        rr = yy - 2 * beta * Xy + beta ** 2 * XX
        zr = np.linalg.solve(Lk, Aty - beta * AtX)
        return float(logdet + np.log(xvx) + (rr - float(zr @ zr)) / s2)

    return negll, scale


def _optimise(A: np.ndarray, y: np.ndarray):
    negll, scale = reml_objective(A, y)
    best = None
    for start in ((np.log(0.5), np.log(0.05)), (np.log(0.2), np.log(0.2))):
        res = minimize(negll, np.array(start), method="L-BFGS-B", bounds=list(LOG_BOUNDS))
        if best is None or res.fun < best.fun:
            best = res
    return best, negll, scale


def reml(A: np.ndarray, y: np.ndarray) -> tuple[float, float]:
    """(sigma^2, tau^2) maximizing the REML likelihood of y ~ N(3 mu 1, tau^2 A A' + sigma^2 I), with mu integrated.
    It is evaluated on the n x n team matrix by the Woodbury identity."""
    best, _, scale = _optimise(A, y)
    s2, t2 = np.exp(best.x) * scale
    return float(s2), float(t2)


@dataclass(frozen=True)
class NoiseDiagnostics:
    """Objective facts about the fitted sigma^2 (descriptive; none is an approved gate).

    - `sigma2_at_bound`: the REML optimum sits on the optimizer's lower bound for sigma^2, i.e. the likelihood is
      maximised by "no residual noise". That is degeneracy, not a threshold judgement.
    - `lr_zero`: -2 log REML at sigma^2 = the lower bound (tau^2 re-optimised) minus at the optimum. Below 3.84
      (chi-square 1 df, 95%) the data cannot distinguish sigma^2 from zero.
    - `residual_df`: alliance rows minus the rank of the design (teams' replication beyond the parameters)."""

    sigma2_at_bound: bool
    lr_zero: float
    residual_df: int


def noise_diagnostics(A: np.ndarray, y: np.ndarray, fitted=None) -> NoiseDiagnostics:
    """`fitted` is a `_optimise` result to reuse (fit_component passes its own)."""
    best, negll, _ = fitted or _optimise(A, y)
    low = LOG_BOUNDS[0][0]
    at_bound = bool(best.x[0] <= low + 0.5)
    if at_bound:
        lr = 0.0
    else:
        res = minimize(lambda t: negll(np.array([low, t[0]])), np.array([best.x[1]]), method="L-BFGS-B",
                       bounds=[LOG_BOUNDS[1]])
        lr = max(float(res.fun - best.fun), 0.0)
    return NoiseDiagnostics(at_bound, lr, int(A.shape[0] - np.linalg.matrix_rank(A)))


def posterior(A: np.ndarray, y: np.ndarray, teams: Sequence[int], sigma2: float, tau2: float,
              individual: Mapping[int, tuple[float, float]] | None = None) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """(mean, covariance, marginal prior variance) for the robots, with mu integrated when any robot uses the
    population prior. `individual` maps team -> (prior mean, prior variance)."""
    individual = dict(individual or {})
    n = len(teams)
    population = [i for i, t in enumerate(teams) if t not in individual]
    use_mu = bool(population)
    p = n + (1 if use_mu else 0)
    H = np.zeros((p, p))
    b = np.zeros(p)
    H[:n, :n] = (A.T @ A) / sigma2
    b[:n] = (A.T @ y) / sigma2
    prior_var = np.zeros(n)
    for i, t in enumerate(teams):
        if t in individual:
            m, v = individual[t]
            if not v > 0:
                raise EstimatorError("invalid_prior", f"team {t}: prior variance must be positive")
            H[i, i] += 1.0 / v
            b[i] += m / v
            prior_var[i] = v
        else:
            h = np.zeros(p)
            h[i], h[n] = 1.0, -1.0
            H += np.outer(h, h) / tau2
            prior_var[i] = tau2  # the between-team spread; mu itself is flat and integrated
    cov = np.linalg.inv(H)
    mean = cov @ b
    return mean[:n], cov[:n, :n], prior_var


def fit_component(component: str, rows: Sequence[Sequence[int]], y: Sequence[float], teams: Sequence[int], *,
                  individual: Mapping[int, tuple[float, float]] | None = None,
                  policy: EstimatorPolicy = EstimatorPolicy()) -> ComponentFit:
    """Fit one component at one event from its qualification alliance rows (each three teams) and their points."""
    teams = list(teams)
    if len(rows) != len(y):
        raise EstimatorError("invalid_input", "rows and points differ in length")
    if any(len(r) != ROBOTS for r in rows):
        raise EstimatorError("invalid_input", "every alliance row names exactly three robots")
    if len(rows) < 12:
        raise EstimatorError("insufficient_data", f"{component}: {len(rows)} alliance rows; at least 12 are needed")
    A = design(rows, teams)
    yv = np.asarray(y, dtype=float)
    fitted = _optimise(A, yv)
    s2, t2 = (float(v) for v in np.exp(fitted[0].x) * fitted[2])
    mean, cov, prior_var = posterior(A, yv, teams, s2, t2, individual)
    noise = noise_diagnostics(A, yv, fitted)
    ratio = s2 / max(float(np.var(yv)), 1e-9)
    fit = ComponentFit(component, teams, mean, cov, s2, t2, len(rows), noise.sigma2_at_bound, noise, ratio,
                       ratio < policy.collapse_ratio)
    sd = np.sqrt(np.diag(cov))
    corr = cov / np.outer(sd, sd)
    np.fill_diagonal(corr, 0.0)
    counts = A.sum(axis=0)
    for i, t in enumerate(teams):
        rows_t = A[:, i] > 0
        partners = int((A[rows_t].sum(axis=0) > 0).sum() - 1) if rows_t.any() else 0
        w = float(1.0 - cov[i, i] / prior_var[i])
        labels = []
        if counts[i] < policy.n_min or w < policy.w_min:
            labels.append("prior_dominated")
        if np.abs(corr[i]).max() > policy.max_abs_corr or partners < policy.min_partners:
            labels.append("weakly_identified")
        if fit.degenerate:
            labels.append("fit_unreliable")
        if fit.screen_flagged:
            labels.append("collapse_screen_flagged")
        fit.diagnostics.append(RobotDiagnostics(
            t, int(counts[i]), partners, float(np.abs(corr[i]).max()), w,
            "prior_event_individual" if individual and t in individual else "current_event_joint", tuple(labels)))
    return fit


def drift_variance(pairs: Sequence[tuple[float, float, float, float]], min_pairs: int = 30) -> float | None:
    """Method-of-moments variance of a team's true change between two consecutive events, from (mean1, var1, mean2,
    var2) estimate pairs. None with too few pairs (the robots then use the population prior)."""
    if len(pairs) < min_pairs:
        return None
    sq = np.mean([(m2 - m1) ** 2 for m1, _, m2, _ in pairs])
    noise = np.mean([v1 + v2 for _, v1, _, v2 in pairs])
    return max(float(sq - noise), 1e-6)


__all__ = ["ComponentFit", "ESTIMATOR_VERSION", "EstimatorError", "EstimatorPolicy", "LOG_BOUNDS", "NoiseDiagnostics",
           "RobotDiagnostics", "design", "drift_variance", "fit_component", "noise_diagnostics", "posterior", "reml",
           "reml_objective"]
