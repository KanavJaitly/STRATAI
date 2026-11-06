"""P11A hardening (2026-11-06): what does the estimator's collapse check measure?

Pre-declared before running (nothing here is tuned to results):
- Simulated events: 30 robots, true contributions x ~ N(20, tau^2) with tau = 8, a random balanced schedule with m
  matches per robot, alliance points y = sum of three x + N(0, sigma^2), sigma = r * tau.
- Grid: r in {0.2, 0.35, 0.5, 1.0, 2.0} x m in {3, 4, 6, 10}; 60 seeded replicates per cell.
- Truth (simulation only): a fit has **collapsed** when sigma_hat^2 / sigma^2 < 0.25 (the E2 report's definition).
- Indicators compared (all computable from data):
  1. `ratio`: sigma_hat^2 / var(y) < 0.05 (the implemented check, ml/alliance/estimator.py);
  2. `bound`: sigma_hat^2 on the optimizer's lower bound (`noise_diagnostics.sigma2_at_bound`);
  3. `lr_zero`: sigma^2 = 0 not rejected by the profile REML likelihood ratio (< 3.84).
- Reported per cell and indicator: flag rate, sensitivity (flagged | collapsed), false-positive rate
  (flagged | not collapsed), and per-robot 80% posterior coverage of the true x in flagged/unflagged fits.
- Time budget: 20 minutes; it stops and reports partial cells if reached.

Run: python -m research.p11a_hardening.collapse_check  -> research/p11a_hardening/results/collapse_check.json
"""

from __future__ import annotations

import json
import time
from pathlib import Path

import numpy as np

from ml.alliance.estimator import design, noise_diagnostics, posterior, reml

OUT = Path(__file__).with_name("results") / "collapse_check.json"
TEAMS, TAU, MU, REPS, BUDGET_S = 30, 8.0, 20.0, 60, 20 * 60
RATIOS = (0.2, 0.35, 0.5, 1.0, 2.0)
MATCHES = (3, 4, 6, 10)
Z80 = 1.2815515655446004


def schedule(rng: np.random.Generator, m: int) -> list[list[int]]:
    """Rows of three distinct robots; every robot plays m times (random partners)."""
    rows: list[list[int]] = []
    for _ in range(m):
        order = rng.permutation(TEAMS)
        rows.extend(order[i:i + 3].tolist() for i in range(0, TEAMS, 3))
    return rows


def one_fit(rng: np.random.Generator, r: float, m: int) -> dict:
    x = rng.normal(MU, TAU, TEAMS)
    rows = schedule(rng, m)
    A = design(rows, list(range(TEAMS)))
    sigma = r * TAU
    y = A @ x + rng.normal(0, sigma, len(rows))
    s2, t2 = reml(A, y)
    mean, cov, _ = posterior(A, y, list(range(TEAMS)), s2, t2, None)
    sd = np.sqrt(np.diag(cov))
    covered = float(np.mean(np.abs(x - mean) <= Z80 * sd))
    nd = noise_diagnostics(A, y)
    return {"collapsed": s2 / sigma ** 2 < 0.25, "s2_over_true": s2 / sigma ** 2,
            "ratio": s2 / max(float(np.var(y)), 1e-9) < 0.05, "bound": nd.sigma2_at_bound,
            "lr_zero": nd.lr_zero < 3.84, "coverage": covered, "residual_df": nd.residual_df}


def summarise(fits: list[dict]) -> dict:
    out = {"fits": len(fits), "collapse_rate": float(np.mean([f["collapsed"] for f in fits])),
           "coverage_all": float(np.mean([f["coverage"] for f in fits])),
           "median_s2_over_true": float(np.median([f["s2_over_true"] for f in fits]))}
    col = [f for f in fits if f["collapsed"]]
    ok = [f for f in fits if not f["collapsed"]]
    for key in ("ratio", "bound", "lr_zero"):
        flagged = [f for f in fits if f[key]]
        out[key] = {
            "flag_rate": len(flagged) / len(fits),
            "sensitivity": None if not col else float(np.mean([f[key] for f in col])),
            "false_positive_rate": None if not ok else float(np.mean([f[key] for f in ok])),
            "coverage_flagged": None if not flagged else float(np.mean([f["coverage"] for f in flagged])),
            "coverage_flagged_not_collapsed": (None if not [f for f in flagged if not f["collapsed"]] else
                                               float(np.mean([f["coverage"] for f in flagged if not f["collapsed"]]))),
            "coverage_unflagged": (None if len(flagged) == len(fits) else
                                   float(np.mean([f["coverage"] for f in fits if not f[key]]))),
        }
    return out


def main() -> None:
    started = time.monotonic()
    cells, stopped = [], False
    for r in RATIOS:
        for m in MATCHES:
            if time.monotonic() - started > BUDGET_S:
                stopped = True
                break
            rng = np.random.default_rng([int(r * 100), m, 20261106])
            fits = [one_fit(rng, r, m) for _ in range(REPS)]
            cells.append({"sigma_over_tau": r, "matches_per_robot": m, **summarise(fits)})
            print(f"r={r} m={m}: collapse {cells[-1]['collapse_rate']:.2f} ratio-flag "
                  f"{cells[-1]['ratio']['flag_rate']:.2f} FP {cells[-1]['ratio']['false_positive_rate']}", flush=True)
        if stopped:
            break
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps({"protocol": __doc__, "complete": not stopped, "seconds": time.monotonic() - started,
                               "cells": cells}, indent=1))
    print(f"wrote {OUT} ({time.monotonic() - started:.0f} s, complete={not stopped})")


if __name__ == "__main__":
    main()
