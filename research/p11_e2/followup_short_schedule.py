"""P11A E2 follow-up F3 (FOLLOWUP_PROTOCOL.json): why short schedules give overconfident intervals, and whether the
candidate n_min / identifiability criteria catch it. SIMULATION OUTPUT (synthetic truths on real schedules).

    python -I research/p11_e2/followup_short_schedule.py --sigma-over-tau 1.0 \
        --population research/p11_e2/cache/population --out research/p11_e2/results [--budget-minutes 40]

Variants on the same simulated data:
- V1, the REML plug-in (current method);
- V2, oracle hyperparameters;
- V3, sigma^2 known with tau^2 from REML;
- V4, hyperparameters integrated over a grid with REML-likelihood weights.

V4's interval uses a normal approximation of the mixture (its mean and variance), stated as such.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from collections import defaultdict
from pathlib import Path

import numpy as np
from scipy.stats import norm

sys.path.insert(0, str(Path(__file__).resolve().parent))
from model import design, posterior, reml, reml_objective, reml_tau_given_sigma, w_eff  # noqa: E402
from simulate import MU, TAU, sample_events, schedule  # noqa: E402

SEED_EVENTS, SEED = 20261105, 20261106
CAPS = (3, 6, None)
REPLICATES = 3
GRID = np.linspace(-7, 1, 15)
LEVELS = (0.5, 0.8, 0.95)
CRITERIA = {"lenient": {"n": 4, "corr": 0.5, "partners": 12, "w": 0.4},
            "strict": {"n": 6, "corr": 0.4, "partners": 12, "w": 0.5}}


def grid_posterior(A, y, teams):
    negll, scale = reml_objective(A, y)
    pts = [(a, b) for a in GRID for b in GRID]
    ll = np.array([-0.5 * negll(np.array(p)) for p in pts])
    w = np.exp(ll - ll.max())
    w /= w.sum()
    keep = w > 1e-6
    means, second = None, None
    for (a, b), wi in zip(np.array(pts)[keep], w[keep]):
        post = posterior(A, y, teams, float(np.exp(a) * scale), float(np.exp(b) * scale))
        m, v = post.mean, np.diag(post.cov)
        means = wi * m if means is None else means + wi * m
        second = wi * (v + m ** 2) if second is None else second + wi * (v + m ** 2)
    return means, np.sqrt(np.maximum(second - means ** 2, 1e-12))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--sigma-over-tau", type=float, required=True, choices=(1.0, 3.0))
    parser.add_argument("--population", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--budget-minutes", type=float, default=40.0)
    args = parser.parse_args(argv)
    if not 0 < args.budget_minutes <= 45:
        parser.error("--budget-minutes must be in (0, 45]")
    started = time.monotonic()
    deadline = started + args.budget_minutes * 60
    events = sample_events(args.population, np.random.default_rng(SEED_EVENTS))
    rng = np.random.default_rng([SEED, int(args.sigma_over_tau * 10)])
    sigma = args.sigma_over_tau * TAU
    acc = defaultdict(lambda: defaultdict(float))
    partial, sims = False, 0
    for cap in CAPS:
        key = f"cap={cap}"
        for event in events:
            for _ in range(REPLICATES):
                if time.monotonic() > deadline:
                    partial = True
                    break
                rows = schedule(event["rows"], cap, False, rng)
                teams = sorted({t for _, ts in rows for t in ts})
                if len(rows) < 12 or len(teams) < 6:
                    continue
                A = design([ts for _, ts in rows], teams)
                x = rng.normal(MU, TAU, len(teams))
                y = A @ x + rng.normal(0, sigma, len(rows))
                s2, t2 = reml(A, y)
                sims += 1
                a = acc[key]
                a["sims"] += 1
                a["collapse_true"] += int(s2 / sigma ** 2 < 0.25)
                a["collapse_flag"] += int(s2 / np.var(y) < 0.05)
                a["sigma_ratio_sum"] += s2 / sigma ** 2
                a["tau_ratio_sum"] += t2 / TAU ** 2
                v1 = posterior(A, y, teams, s2, t2)
                variants = {"V1_reml_plugin": (v1.mean, np.sqrt(np.diag(v1.cov))),
                            "V2_oracle": None, "V3_sigma_known": None, "V4_grid_integrated": grid_posterior(A, y, teams)}
                p2 = posterior(A, y, teams, sigma ** 2, TAU ** 2)
                variants["V2_oracle"] = (p2.mean, np.sqrt(np.diag(p2.cov)))
                p3 = posterior(A, y, teams, sigma ** 2, reml_tau_given_sigma(A, y, sigma ** 2))
                variants["V3_sigma_known"] = (p3.mean, np.sqrt(np.diag(p3.cov)))
                for name, (m, sd) in variants.items():
                    err = np.abs(m - x)
                    a[f"{name}|robots"] += len(teams)
                    for l in LEVELS:
                        a[f"{name}|cov{l}"] += int((err <= norm.ppf(0.5 + l / 2) * sd).sum())
                    a[f"{name}|width80"] += float((2 * norm.ppf(0.9) * sd).sum())
                    collapsed = s2 / np.var(y) < 0.05
                    a[f"{name}|flagged_robots"] += len(teams) * int(collapsed)
                    a[f"{name}|flagged_cov80"] += int((err <= norm.ppf(0.9) * sd).sum()) * int(collapsed)
                # Criteria are computed as a system would compute them, from V1's posterior.
                sd1 = np.sqrt(np.diag(v1.cov))
                corr = v1.cov / np.outer(sd1, sd1)
                np.fill_diagonal(corr, 0)
                maxcorr = np.abs(corr).max(axis=1)
                weights = w_eff(v1)
                counts = A.sum(axis=0)
                partners = np.zeros(len(teams))
                for j in range(len(teams)):
                    rows_j = A[:, j] > 0
                    partners[j] = int(((A[rows_j].sum(axis=0) > 0).sum()) - 1)
                collapsed = s2 / np.var(y) < 0.05
                for crit, c in CRITERIA.items():
                    passing = (counts >= c["n"]) & (maxcorr <= c["corr"]) & (partners >= c["partners"]) & (weights >= c["w"])
                    for with_flag in (False, True):
                        ok = passing & (not collapsed) if with_flag else passing
                        label = f"{crit}{'+collapse_flag' if with_flag else ''}"
                        a[f"crit|{label}|robots"] += len(teams)
                        a[f"crit|{label}|pass"] += int(ok.sum())
                        for name in ("V1_reml_plugin", "V4_grid_integrated"):
                            m, sd = variants[name]
                            cov = np.abs(m - x) <= norm.ppf(0.9) * sd
                            a[f"crit|{label}|{name}|pass_cov80"] += int(cov[ok].sum())
                            a[f"crit|{label}|{name}|fail_cov80"] += int(cov[~ok].sum())
            if partial:
                break
        if partial:
            break

    summary = {}
    for key, a in acc.items():
        out = {"sims": int(a["sims"]), "collapse_rate_true": a["collapse_true"] / a["sims"],
               "collapse_rate_flag": a["collapse_flag"] / a["sims"],
               "mean_sigma2_ratio": a["sigma_ratio_sum"] / a["sims"], "mean_tau2_ratio": a["tau_ratio_sum"] / a["sims"],
               "variants": {}, "criteria": {}}
        for name in ("V1_reml_plugin", "V2_oracle", "V3_sigma_known", "V4_grid_integrated"):
            n = a[f"{name}|robots"]
            out["variants"][name] = {**{f"cov{l}": a[f"{name}|cov{l}"] / n for l in LEVELS},
                                     "width80": a[f"{name}|width80"] / n,
                                     "cov80_when_collapse_flagged": (a[f"{name}|flagged_cov80"] / a[f"{name}|flagged_robots"]
                                                                     if a[f"{name}|flagged_robots"] else None)}
        for crit in CRITERIA:
            for label in (crit, f"{crit}+collapse_flag"):
                n, p = a[f"crit|{label}|robots"], a[f"crit|{label}|pass"]
                out["criteria"][label] = {"share_passing": p / n, **{
                    f"{name}_cov80_{side}": (a[f"crit|{label}|{name}|{side}_cov80"] / (p if side == "pass" else n - p)
                                             if (p if side == "pass" else n - p) else None)
                    for name in ("V1_reml_plugin", "V4_grid_integrated") for side in ("pass", "fail")}}
        summary[key] = out
    args.out.mkdir(parents=True, exist_ok=True)
    result = {"label": "SIMULATION OUTPUT", "sigma_over_tau": args.sigma_over_tau, "simulations": sims,
              "partial": partial, "seconds": round(time.monotonic() - started, 1), "by_cap": summary}
    (args.out / f"followup_f3_sigma_over_tau_{args.sigma_over_tau}.json").write_text(json.dumps(result, indent=1))
    print(json.dumps({"sigma_over_tau": args.sigma_over_tau, "simulations": sims, "partial": partial,
                      "seconds": result["seconds"]}))
    return 1 if partial else 0


if __name__ == "__main__":
    sys.exit(main())
