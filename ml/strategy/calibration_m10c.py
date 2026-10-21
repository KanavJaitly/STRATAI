"""P6-M10c: the upset-floor calibration of the frozen P6-M10 v1 base (frozen spec `.agent/phase6/P6_M10C_SPEC.md`,
blob f24a8d1c).

q_red = eps/2 + (1 - eps) * expit(a_g * z),  q_blue = eps/2 + (1 - eps) * expit(-a_g * z)

with z = log_ndtr(x) - log_ndtr(-x) (M10b §1, unchanged), a_g per M10b source group and eps pooled, in [0, 0.08].
The fit (§3) is L-BFGS-B followed by a bounded Newton polish, with every check frozen. The base, the groups, the
refusals and the evaluation path are M10b's (`ml.strategy.calibration`); only the link differs.

Nothing here registers or serves anything. The production fit, registration and serving each need Kanav's
separate authorization.
"""

from __future__ import annotations

import hashlib
import json
from collections import Counter
from pathlib import Path
from typing import Any, Sequence

import numpy as np
from scipy.optimize import minimize
from scipy.special import expit, log_expit

from ml.strategy.calibration import (GROUPS, MIN_GROUP_ROWS, CalibratedOutcomeModel, CalibrationFitRefused,
                                     stable_log_odds)

SPEC_PATH = ".agent/phase6/P6_M10C_SPEC.md"
SPEC_BLOB = "f24a8d1c129bde4f43d51e43ceeca7a20c7c716a"
V3_VERSION_TAG = "p6m10c-v1"
CALIBRATOR_MODEL_TYPE = "strategy_outcome_calibrator_m10c"

A_BOUNDS, EPS_BOUNDS = (0.05, 5.0), (0.0, 0.08)
X0_A, X0_EPS = 1.0, 0.02
LBFGS_OPTIONS = {"gtol": 1e-10, "ftol": 1e-15, "maxiter": 1000, "maxcor": 10}
POLISH_STEPS, POLISH_TOLERANCE, HESSIAN_STEP = 20, 1e-10, 1e-6
BOUND_TOLERANCE, NO_FLOOR_TOLERANCE, GRADIENT_TOLERANCE, HESSIAN_TOLERANCE = 1e-6, 1e-6, 1e-7, 1e-10


# --- §1: the link -----------------------------------------------------------------------------------------------


def floored(a: float, eps: float, x: float) -> tuple[float, float]:
    """(q_red, q_blue); q_blue computed directly, never as 1 - q_red. A non-finite x is refused (M10b §1)."""
    z = stable_log_odds(x)
    return float(eps / 2 + (1 - eps) * expit(a * z)), float(eps / 2 + (1 - eps) * expit(-a * z))


# --- §3: the objective -------------------------------------------------------------------------------------------


def _log_lik(t: np.ndarray, eps: float) -> np.ndarray:
    if eps == 0:
        return log_expit(t)
    return np.logaddexp(np.log(eps / 2), np.log1p(-eps) + log_expit(t))


class _Objective:
    """L(θ) and its analytic gradient. θ = (free slopes..., eps); rows of fixed groups use their fixed slope."""

    def __init__(self, z, s, slot, fixed):
        self.z, self.s, self.slot, self.fixed = z, s, slot, fixed  # slot: free-slope index per row, -1 if fixed
        self.k = int(slot.max()) + 1 if (slot >= 0).any() else 0

    def slopes(self, theta):
        return np.where(self.slot >= 0, theta[:self.k][np.maximum(self.slot, 0)] if self.k else 0.0, self.fixed)

    def value_and_grad(self, theta):
        eps = float(theta[-1])
        t = self.slopes(theta) * self.s * self.z
        ell = _log_lik(t, eps)
        n = t.size
        # d p / d a / p = (1 - eps) σ(t) σ(-t) s z / p, in log space; d p / d eps / p = (1/2 - σ(t)) / p
        ratio_a = np.exp(np.log1p(-eps) + log_expit(t) + log_expit(-t) - ell) * self.s * self.z
        grad = np.empty_like(theta)
        for j in range(self.k):
            grad[j] = -ratio_a[self.slot == j].sum() / n
        grad[-1] = -((0.5 - expit(t)) * np.exp(-ell)).sum() / n
        return float(-ell.mean()), grad

    def value(self, theta):
        return self.value_and_grad(theta)[0]

    def grad(self, theta):
        return self.value_and_grad(theta)[1]

    def hessian(self, theta):
        """Central differences of the analytic gradient (step 1e-6), symmetrized."""
        m = theta.size
        h = np.empty((m, m))
        for j in range(m):
            step = np.zeros(m)
            step[j] = HESSIAN_STEP
            h[:, j] = (self.grad(theta + step) - self.grad(theta - step)) / (2 * HESSIAN_STEP)
        return (h + h.T) / 2


def _bounds(k: int) -> list[tuple[float, float]]:
    return [A_BOUNDS] * k + [EPS_BOUNDS]


def _interior(theta, bounds, margin) -> bool:
    return all(lo + margin <= v <= hi - margin for v, (lo, hi) in zip(theta, bounds))


def _polish(objective: _Objective, theta: np.ndarray, bounds) -> tuple[np.ndarray, int]:
    """Up to 20 Newton steps; each accepted only inside the bounds and without increasing L (§3 step 2)."""
    steps = 0
    for _ in range(POLISH_STEPS):
        value, grad = objective.value_and_grad(theta)
        if np.max(np.abs(grad)) <= POLISH_TOLERANCE or not _interior(theta, bounds, HESSIAN_STEP):
            break
        try:
            step = np.linalg.solve(objective.hessian(theta), -grad)
        except np.linalg.LinAlgError:
            break
        candidate = theta + step
        if not all(lo <= v <= hi for v, (lo, hi) in zip(candidate, bounds)) or objective.value(candidate) > value:
            break
        theta, steps = candidate, steps + 1
    return theta, steps


def _fit(objective: _Objective, *, optimizer=minimize, raise_on_failure: bool = True) -> dict[str, Any]:
    """One §3 fit: L-BFGS-B, the polish, then the five checks in order. Returns the report; on a failed check it
    raises CalibrationFitRefused naming the first one (every check's result is in its details), unless
    raise_on_failure is false, when the report carries `failed_checks` instead."""
    bounds = _bounds(objective.k)
    x0 = np.array([X0_A] * objective.k + [X0_EPS])
    result = optimizer(objective.value_and_grad, x0, jac=True, method="L-BFGS-B", bounds=bounds,
                       options=dict(LBFGS_OPTIONS))
    theta, polish_steps = _polish(objective, np.asarray(result.x, dtype=np.float64), bounds)
    value, grad = objective.value_and_grad(theta)
    slopes, eps = theta[:-1], float(theta[-1])
    hessian_ok = _interior(theta, bounds, HESSIAN_STEP)
    eigenvalues = np.linalg.eigvalsh(objective.hessian(theta)).tolist() if hessian_ok else None
    checks = {
        "optimizer_failed": not (bool(getattr(result, "success", False)) and 0 <= int(getattr(result, "nit", -1))
                                 < LBFGS_OPTIONS["maxiter"]),
        "no_floor_identified": eps <= NO_FLOOR_TOLERANCE,
        "solution_at_bound": any(abs(a - b) <= BOUND_TOLERANCE for a in slopes for b in A_BOUNDS)
                             or abs(eps - EPS_BOUNDS[1]) <= BOUND_TOLERANCE,
        "not_stationary": not float(np.max(np.abs(grad))) <= GRADIENT_TOLERANCE,
        "not_unique": eigenvalues is None or not min(eigenvalues) > HESSIAN_TOLERANCE,
    }
    report = {"theta": theta.tolist(), "eps": eps, "nll": value, "nit": int(getattr(result, "nit", -1)),
              "lbfgs_success": bool(getattr(result, "success", False)), "polish_steps": polish_steps,
              "grad_inf": float(np.max(np.abs(grad))), "hessian_eigenvalues": eigenvalues, "checks": checks}
    failed = [name for name, bad in checks.items() if bad]
    if failed and raise_on_failure:
        raise CalibrationFitRefused(failed[0], {**report, "failed_checks": failed})
    return {**report, "failed_checks": failed}


class FlooredCalibrator:
    """M10c's calibrator: a slope per group, the pooled eps, how each slope was chosen, and the global fit."""

    def __init__(self, slopes: dict[str, float], eps: float, counts: dict[str, int], sources: dict[str, str],
                 fits: dict[str, Any], *, base_sha256: str, fit_set_fingerprint: str, spec_blob: str = SPEC_BLOB,
                 artifact_sha256: str | None = None) -> None:
        if set(slopes) != set(GROUPS) or set(sources) != set(GROUPS):
            raise ValueError("an M10c calibrator needs a slope and a source for every group")
        self.slopes, self.eps, self.counts = dict(slopes), float(eps), dict(counts)
        self.sources, self.fits = dict(sources), dict(fits)
        self.base_sha256, self.fit_set_fingerprint, self.spec_blob = base_sha256, fit_set_fingerprint, spec_blob
        self.artifact_sha256 = artifact_sha256

    def to_dict(self) -> dict[str, Any]:
        return {"model_type": CALIBRATOR_MODEL_TYPE, "version_tag": V3_VERSION_TAG, "slopes": self.slopes,
                "eps": self.eps, "counts": self.counts, "sources": self.sources, "fits": self.fits,
                "base_sha256": self.base_sha256, "fit_set_fingerprint": self.fit_set_fingerprint,
                "spec_blob": self.spec_blob, "spec": SPEC_PATH}

    def save(self, path: Path) -> None:
        Path(path).write_text(json.dumps(self.to_dict(), indent=1, sort_keys=True) + "\n", encoding="utf-8")

    @classmethod
    def load(cls, path: Path) -> FlooredCalibrator:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        if data.get("model_type") != CALIBRATOR_MODEL_TYPE:
            raise ValueError(f"{path} is not a {CALIBRATOR_MODEL_TYPE} artifact")
        return cls(data["slopes"], data["eps"], data["counts"], data["sources"], data["fits"],
                   base_sha256=data["base_sha256"], fit_set_fingerprint=data["fit_set_fingerprint"],
                   spec_blob=data["spec_blob"], artifact_sha256=hashlib.sha256(Path(path).read_bytes()).hexdigest())


def fit_floored(groups: Sequence[str], z: Sequence[float], s: Sequence[int], *, base_sha256: str,
                fit_set_fingerprint: str, optimizer=minimize) -> FlooredCalibrator:
    """§3: the global fit (a_G, eps_G), always; then the joint fit of the slopes of groups with n >= 200 and the pooled
    eps, smaller groups fixed at a_G. Refuses (CalibrationFitRefused) on any failed check; nothing is retried."""
    z_arr, s_arr = np.asarray(z, dtype=np.float64), np.asarray(s, dtype=np.float64)
    groups = list(groups)
    if z_arr.size == 0 or z_arr.size != s_arr.size or len(groups) != z_arr.size \
            or not np.all(np.isin(s_arr, (-1.0, 1.0))) or not np.all(np.isfinite(z_arr)):
        raise CalibrationFitRefused("invalid_input", {"n": int(z_arr.size)})
    unknown = set(groups) - set(GROUPS)
    if unknown:
        raise CalibrationFitRefused("invalid_input", {"unknown_groups": sorted(unknown)})
    counts = Counter(groups)
    # §3: the global fit is always computed and recorded with every check. Its checks gate the result only when its
    # a_G is used, for a group with n < 200; §3's checks table is written for θ (the joint fit). This reading of
    # §3 was fixed on 2026-10-11, before any M10c fit on real data.
    global_report = _fit(_Objective(z_arr, s_arr, np.zeros(z_arr.size, dtype=int), np.zeros(z_arr.size)),
                         optimizer=optimizer, raise_on_failure=False)
    a_global = global_report["theta"][0]
    free = [g for g in GROUPS if counts.get(g, 0) >= MIN_GROUP_ROWS]
    if len(free) < len(GROUPS) and global_report["failed_checks"]:
        raise CalibrationFitRefused("global_fit_refused", {"global": global_report,
                                                           "small_groups": sorted(set(GROUPS) - set(free))})
    index = {g: i for i, g in enumerate(free)}
    slot = np.array([index.get(g, -1) for g in groups], dtype=int)
    fixed = np.where(slot >= 0, 0.0, a_global)
    joint = _fit(_Objective(z_arr, s_arr, slot, fixed), optimizer=optimizer)
    slopes = {g: (joint["theta"][index[g]] if g in index else a_global) for g in GROUPS}
    sources = {g: ("joint" if g in index else "global_fallback") for g in GROUPS}
    return FlooredCalibrator(slopes, joint["eps"], {g: counts.get(g, 0) for g in GROUPS}, sources,
                             {"global": global_report, "joint": {**joint, "free_groups": free}},
                             base_sha256=base_sha256, fit_set_fingerprint=fit_set_fingerprint)


class FlooredOutcomeModel(CalibratedOutcomeModel):
    """v1's evaluation, then the M10c link, inside the one function both strategy paths use (M10b's path)."""

    version_tag_out = V3_VERSION_TAG

    def _link(self, group: str, x: float) -> tuple[float, float, dict[str, Any]]:
        a = self.calibrator.slopes[group]
        q_red, q_blue = floored(a, self.calibrator.eps, x)
        return q_red, q_blue, {"group": group, "slope": a, "eps": self.calibrator.eps, "probit_index": x,
                               "calibrator_sha256": self.calibrator.artifact_sha256}
