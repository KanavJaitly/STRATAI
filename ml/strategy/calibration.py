"""P6-M10b: the C-R calibration stage on the frozen P6-M10 v1 model (`.agent/phase6/P6_M10B_SPEC.md`, blob d699afaf,
frozen 2026-10-10).

- **Base:** the frozen `p6m10-v1`, never refit.
- **Probit index:** x = m / σ from the base evaluation. Stable log-odds: z(x) = log_ndtr(x) − log_ndtr(−x), with no
  probability clipping.
- **Calibrated output:** q_red = expit(a_g·z), q_blue = expit(−a_g·z), with one factor a_g per EPA-source group g
  (same / mixed / prior, from prediction-time information only).
- **Where it applies:** inside the single evaluation function (`CalibratedOutcomeModel.evaluate`), used identically by
  the AI and coach paths (P6-Q10).

The fit (§3) runs only on the calibration set (2026), and its refusal checks are never relaxed. Nothing here reads
a database; season lookups are injected.
"""

from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Callable, Sequence
from dataclasses import replace
from pathlib import Path
from typing import Any

import numpy as np
from scipy.optimize import minimize_scalar
from scipy.special import expit, log_ndtr

from ml.features.assembler import TeamFeatures
from ml.strategy.outcome import (INSUFFICIENT_DATA, NOT_VALIDATED, ComponentOutcomeModel, MatchContext,
                                 OutcomeEvaluation, display_odds)
from ml.strategy.representation import Strategy

SPEC_PATH = ".agent/phase6/P6_M10B_SPEC.md"
SPEC_BLOB = "d699afafc01d42904c7afc7c7e209f8007a6a207"
GROUPS = ("same", "mixed", "prior")
BOUNDS = (0.05, 5.0)  # §3
XATOL, MAXITER = 1e-10, 500
BOUND_TOLERANCE, STATIONARITY_TOLERANCE, CONVEXITY_TOLERANCE = 1e-6, 1e-8, 1e-12
MIN_GROUP_ROWS = 200
CALIBRATOR_MODEL_TYPE, CALIBRATOR_VERSION_TAG = "strategy_outcome_calibrator", "p6m10b-v1"
V2_VERSION_TAG = "p6m10b-v1"
REASON_NOT_ACCEPTED = "p6_m10b_not_accepted"
REASON_SEASON_ABSENT = "prediction_season_absent"
REASON_SOURCE_UNRESOLVABLE = "epa_source_unresolvable"
REASON_SOURCE_LATER = "epa_source_later_season"
REASON_INDEX_NOT_FINITE = "probit_index_not_finite"


class CalibrationInputError(ValueError):
    """A prediction the calibration stage cannot make (§1–§2). It becomes `insufficient_data`, never a guess."""

    def __init__(self, reason: str, detail: str = "") -> None:
        super().__init__(f"{reason}: {detail}" if detail else reason)
        self.reason = reason


class CalibrationFitRefused(ValueError):
    """A §3 check failed: no calibrator is registered, nothing is retried, and Kanav is told which check failed."""

    def __init__(self, check: str, details: dict[str, Any]) -> None:
        super().__init__(f"calibration fit refused ({check}): {details}")
        self.check, self.details = check, details


# --- §1: stable log-odds and the calibrated output --------------------------------------------------------------


def stable_log_odds(x: float) -> float:
    """z(x) = log Φ(x) − log Φ(−x) = logit(Φ(x)): finite for every finite x, strictly increasing, antisymmetric."""
    if not math.isfinite(x):
        raise CalibrationInputError(REASON_INDEX_NOT_FINITE, str(x))
    return float(log_ndtr(x) - log_ndtr(-x))


def calibrated(factor: float, x: float) -> tuple[float, float]:
    """(q_red, q_blue) = (expit(a·z(x)), expit(−a·z(x))). q_blue is computed directly, never as 1 − q_red."""
    z = stable_log_odds(x)
    return float(expit(factor * z)), float(expit(-factor * z))


# --- §2: prediction season and source groups --------------------------------------------------------------------


def source_group(teams: Sequence[TeamFeatures], prediction_season: int | None,
                 season_of: Callable[[str], int | None]) -> str:
    """`same` (all six source seasons = the prediction season), `prior` (all six earlier) or `mixed`. The source is
    D18's prediction-time `epa_source_event_key`. A missing season, an unresolvable key or a later season is refused."""
    if prediction_season is None:
        raise CalibrationInputError(REASON_SEASON_ABSENT)
    if len(teams) != 6:
        raise CalibrationInputError(REASON_SOURCE_UNRESOLVABLE, f"{len(teams)} teams, not 6")
    seasons = []
    for t in teams:
        season = season_of(t.epa_source_event_key) if t.epa_source_event_key else None
        if season is None:
            raise CalibrationInputError(REASON_SOURCE_UNRESOLVABLE, f"team {t.team_number}")
        if season > prediction_season:
            raise CalibrationInputError(REASON_SOURCE_LATER, f"team {t.team_number}: {season} > {prediction_season}")
        seasons.append(season)
    if all(s == prediction_season for s in seasons):
        return "same"
    if all(s < prediction_season for s in seasons):
        return "prior"
    return "mixed"


# --- §3: the fit ------------------------------------------------------------------------------------------------


def _loss(a: float, z: np.ndarray, s: np.ndarray) -> float:
    return float(np.mean(np.logaddexp(0.0, -a * s * z)))


def _derivative(a: float, z: np.ndarray, s: np.ndarray) -> float:
    return float(-np.mean(s * z * expit(-a * s * z)))


def _curvature(a: float, z: np.ndarray, s: np.ndarray) -> float:
    return float(np.mean(z * z * expit(a * s * z) * expit(-a * s * z)))


def fit_factor(z: Sequence[float], s: Sequence[int], *, optimizer=minimize_scalar) -> dict[str, Any]:
    """a = argmin over [0.05, 5.0] of the mean softplus(−a·s·z) (§3), with every refusal check. `optimizer` is
    injectable only so the tests can simulate a failed optimizer."""
    z_arr, s_arr = np.asarray(z, dtype=np.float64), np.asarray(s, dtype=np.float64)
    if z_arr.size == 0 or not np.all(np.isin(s_arr, (-1.0, 1.0))):
        raise CalibrationFitRefused("invalid_input", {"n": int(z_arr.size)})
    result = optimizer(lambda a: _loss(a, z_arr, s_arr), bounds=BOUNDS, method="bounded",
                       options={"xatol": XATOL, "maxiter": MAXITER})
    a = float(result.x)
    report = {"a": a, "n": int(z_arr.size), "loss": _loss(a, z_arr, s_arr), "nit": int(getattr(result, "nit", -1)),
              "derivative": _derivative(a, z_arr, s_arr), "curvature": _curvature(a, z_arr, s_arr)}
    # §3: "every factor must pass all of them", so every check is evaluated and every failure is recorded; the
    # exception names the first one in the spec's order (a flat objective, for example, also lands near a bound).
    failed = [name for name, ok in (
        ("optimizer_failed", bool(getattr(result, "success", False)) and 0 <= report["nit"] < MAXITER),
        ("solution_at_bound", abs(a - BOUNDS[0]) > BOUND_TOLERANCE and abs(a - BOUNDS[1]) > BOUND_TOLERANCE),
        ("not_stationary", abs(report["derivative"]) <= STATIONARITY_TOLERANCE),
        ("not_unique", report["curvature"] > CONVEXITY_TOLERANCE)) if not ok]
    if failed:
        raise CalibrationFitRefused(failed[0], {**report, "failed_checks": failed})
    return report


class Calibrator:
    """The registered §3 artifact: a factor per group, the global factor, and how each was chosen."""

    def __init__(self, factors: dict[str, float], global_factor: float, counts: dict[str, int],
                 sources: dict[str, str], fits: dict[str, Any], *, base_sha256: str, fit_set_fingerprint: str,
                 spec_blob: str = SPEC_BLOB, artifact_sha256: str | None = None) -> None:
        if set(factors) != set(GROUPS) or set(sources) != set(GROUPS):
            raise ValueError("a calibrator needs a factor and a source for every group")
        self.factors, self.global_factor, self.counts = dict(factors), float(global_factor), dict(counts)
        self.sources, self.fits = dict(sources), dict(fits)
        self.base_sha256, self.fit_set_fingerprint, self.spec_blob = base_sha256, fit_set_fingerprint, spec_blob
        self.artifact_sha256 = artifact_sha256

    def factor(self, group: str) -> float:
        return self.factors[group]

    def to_dict(self) -> dict[str, Any]:
        return {"model_type": CALIBRATOR_MODEL_TYPE, "version_tag": CALIBRATOR_VERSION_TAG, "factors": self.factors,
                "global_factor": self.global_factor, "counts": self.counts, "sources": self.sources,
                "fits": self.fits, "base_sha256": self.base_sha256, "fit_set_fingerprint": self.fit_set_fingerprint,
                "spec_blob": self.spec_blob, "spec": SPEC_PATH}

    def save(self, path: Path) -> None:
        Path(path).write_text(json.dumps(self.to_dict(), indent=1, sort_keys=True) + "\n", encoding="utf-8")

    @classmethod
    def load(cls, path: Path) -> Calibrator:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        if data.get("model_type") != CALIBRATOR_MODEL_TYPE:
            raise ValueError(f"{path} is not a {CALIBRATOR_MODEL_TYPE} artifact")
        return cls(data["factors"], data["global_factor"], data["counts"], data["sources"], data["fits"],
                   base_sha256=data["base_sha256"], fit_set_fingerprint=data["fit_set_fingerprint"],
                   spec_blob=data["spec_blob"], artifact_sha256=hashlib.sha256(Path(path).read_bytes()).hexdigest())


def fit_calibrator(groups: Sequence[str], z: Sequence[float], s: Sequence[int], *, base_sha256: str,
                   fit_set_fingerprint: str, optimizer=minimize_scalar) -> Calibrator:
    """§3. a_G is always fit on all rows. Each group with ≥ 200 rows gets its own factor; a smaller group uses a_G.
    The choice depends only on the calibration set's counts. Any refusal propagates and no calibrator is made."""
    unknown = set(groups) - set(GROUPS)
    if unknown:
        raise CalibrationFitRefused("invalid_input", {"unknown_groups": sorted(unknown)})
    global_fit = fit_factor(z, s, optimizer=optimizer)
    factors, counts, sources, fits = {}, {}, {}, {"global": global_fit}
    g_arr, z_arr, s_arr = np.asarray(groups), np.asarray(z, dtype=np.float64), np.asarray(s)
    for group in GROUPS:
        mask = g_arr == group
        counts[group] = int(mask.sum())
        if counts[group] >= MIN_GROUP_ROWS:
            fit = fit_factor(z_arr[mask], s_arr[mask], optimizer=optimizer)
            factors[group], sources[group], fits[group] = fit["a"], "group", fit
        else:
            factors[group], sources[group] = global_fit["a"], "global_fallback"
    return Calibrator(factors, global_fit["a"], counts, sources, fits, base_sha256=base_sha256,
                      fit_set_fingerprint=fit_set_fingerprint)


# --- the single evaluation function (§1, P6-Q10) -----------------------------------------------------------------


class CalibratedOutcomeModel:
    """P6-M10b: v1's evaluation, then the C-R calibration, inside the one function both strategy paths use."""

    version_tag_out = V2_VERSION_TAG

    def __init__(self, base: ComponentOutcomeModel, calibrator: Calibrator, season_of: Callable[[str], int | None],
                 *, baseline_status: tuple[str, str | None] = (NOT_VALIDATED, REASON_NOT_ACCEPTED)) -> None:
        if base.artifact_sha256 is not None and base.artifact_sha256 != calibrator.base_sha256:
            raise ValueError("the calibrator was not fit on this base model")
        self.base = base.with_status(version_tag=base.version_tag or "p6m10-v1", baseline_status=baseline_status)
        self.calibrator, self.season_of = calibrator, season_of
        self.baseline_status = baseline_status

    def evaluate(self, context: MatchContext, strategy_red: Strategy, strategy_blue: Strategy) -> OutcomeEvaluation:
        base = self.base.evaluate(context, strategy_red, strategy_blue)
        identity = {"model_version_tag": self.version_tag_out, "model_sha256": self.base.artifact_sha256}
        if base.p_red is None:
            return replace(base, **identity)
        try:
            group = source_group((*context.red_teams, *context.blue_teams), context.prediction_season,
                                 self.season_of)
            x = base.mean_difference / base.sigma
            q_red, q_blue, calibration = self._link(group, x)
        except CalibrationInputError as exc:
            return OutcomeEvaluation(None, None, None, None, INSUFFICIENT_DATA, (f"missing_input:{exc.reason}",),
                                     **identity)
        return replace(base, p_red=q_red, p_blue=q_blue, display_red=display_odds(q_red),
                       display_blue=display_odds(q_blue), **identity, calibration=calibration)

    def _link(self, group: str, x: float) -> tuple[float, float, dict[str, Any]]:
        """M10b's link (§1). P6-M10c's model overrides only this; everything else in `evaluate` is shared."""
        factor = self.calibrator.factor(group)
        q_red, q_blue = calibrated(factor, x)
        return q_red, q_blue, {"group": group, "factor": factor, "probit_index": x,
                               "calibrator_sha256": self.calibrator.artifact_sha256}
