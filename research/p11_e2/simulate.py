"""P11A E2 research: controlled simulations for the prior, independence and identifiability questions
(PROTOCOL.json `simulations`). One task per sigma/tau value, so each run stays well inside 45 minutes.

    python -I research/p11_e2/simulate.py --sigma-over-tau 1.0 --population research/p11_e2/cache/population \
        --out research/p11_e2/results [--budget-minutes 40]

Schedules are the real qualification team lists of 24 seeded, size-stratified events. Truths and noise are
synthetic. Every number this script writes is SIMULATION OUTPUT, not evidence about any real team.
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
from model import design, posterior, reml, w_eff  # noqa: E402

SEED = 20261105
MU, TAU = 30.0, 10.0
CAPS = (3, 6, 9, None)
UNEQUAL = (False, True)
NOISE = ("none", "shared_match_effect_rho_0.5", "robot_specific_heteroscedastic")
SCENARIOS = ("indep_individual", "indep_population", "current_event_joint", "current_event_plugin")
REPLICATES = 3
LEVELS = (0.5, 0.8, 0.95)
N_ALLIANCES, N_PAIRS = 30, 30
DELTA_FRAC, PI = 0.2, 0.8  # a fixed illustrative classification for the full-vs-diagonal comparison


def sample_events(population_dir: Path, rng: np.random.Generator) -> list[dict]:
    chosen = []
    for season in (2024, 2025, 2026):
        events = json.loads((population_dir / f"population_{season}.json").read_text())["events"]
        strata = {"small": [e for e in events if len(e["teams"]) <= 36],
                  "medium": [e for e in events if 37 <= len(e["teams"]) <= 50],
                  "large": [e for e in events if len(e["teams"]) > 50]}
        quota = {"small": 3, "medium": 3, "large": 2}
        for name, pool in strata.items():
            pool = sorted(pool, key=lambda e: e["key"])
            for i in rng.choice(len(pool), size=min(quota[name], len(pool)), replace=False):
                e = pool[int(i)]
                chosen.append({"key": e["key"], "stratum": name,
                               "rows": [(r["match"], r["teams"]) for r in e["quals"]]})
    return chosen


def schedule(rows: list, cap: int | None, unequal: bool, rng) -> list:
    out, count = [], defaultdict(int)
    for match, teams in rows:
        if unequal and rng.random() < 0.25:
            continue
        if cap is not None and any(count[t] >= cap for t in teams):
            continue
        out.append((match, teams))
        for t in teams:
            count[t] += 1
    return out


def bin_of(value: float, edges: list[float]) -> str:
    for lo, hi in zip(edges, edges[1:]):
        if lo <= value < hi:
            return f"[{lo},{hi})"
    return f">={edges[-1]}"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--sigma-over-tau", type=float, required=True, choices=(0.5, 1.0, 2.0, 3.0))
    parser.add_argument("--population", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--budget-minutes", type=float, default=40.0)
    parser.add_argument("--caps", default="all", choices=("all", "low", "high", "cap9", "nocap"),
                        help="all: every cap (the original single task); low: caps 3 and 6; high: cap 9 and no cap. "
                             "cap9 / nocap: one cap each (high split further). Splitting keeps each task inside 45 minutes; each part "
                             "has its own seeded stream")
    args = parser.parse_args(argv)
    if not 0 < args.budget_minutes <= 45:
        parser.error("--budget-minutes must be in (0, 45]")
    caps = {"all": CAPS, "low": CAPS[:2], "high": CAPS[2:], "cap9": CAPS[2:3], "nocap": CAPS[3:]}[args.caps]
    started = time.monotonic()
    deadline = started + args.budget_minutes * 60
    rng = np.random.default_rng(SEED)
    events = sample_events(args.population, rng)  # the same 24 schedules for every task (same seed)
    sigma = args.sigma_over_tau * TAU
    stream = [SEED, int(args.sigma_over_tau * 10)] + ([] if args.caps == "all" else [{"low": 1, "high": 2, "cap9": 3, "nocap": 4}[args.caps]])
    task_rng = np.random.default_rng(stream)

    cells: dict[str, dict] = {}
    bins: dict[str, dict] = defaultdict(lambda: {"n": 0, "cov80": 0, "sq": 0.0, "width80": 0.0, "bias": 0.0})
    partial, sims = False, 0
    z80 = norm.ppf(0.9)
    for cap in caps:
        for unequal in UNEQUAL:
            for noise in NOISE:
                cell = f"cap={cap}|unequal={unequal}|noise={noise}"
                acc = {s: {"robots": 0, **{f"cov{l}": 0 for l in LEVELS}, "width80": 0.0, "bias": 0.0, "sq": 0.0,
                           "alliances": 0, "alliance_cov80": 0} for s in SCENARIOS}
                acc["covariance"] = {"alliances": 0, "full_cov80": 0, "diag_cov80": 0, "full_width80": 0.0,
                                     "diag_width80": 0.0, "pairs": 0, "pair_full_cov80": 0, "pair_diag_cov80": 0,
                                     "pair_class_changed": 0, "pair_full_wrong": 0, "pair_diag_wrong": 0,
                                     "pair_full_decided": 0, "pair_diag_decided": 0}
                for event in events:
                    for rep in range(REPLICATES):
                        if time.monotonic() > deadline:
                            partial = True
                            break
                        rows = schedule(event["rows"], cap, unequal, task_rng)
                        teams = sorted({t for _, ts in rows for t in ts})
                        if len(rows) < 12 or len(teams) < 6:
                            continue
                        truth = {t: task_rng.normal(MU, TAU) for t in teams}
                        A = design([ts for _, ts in rows], teams)
                        x = np.array([truth[t] for t in teams])
                        if noise == "none":
                            e = task_rng.normal(0, sigma, len(rows))
                        elif noise.startswith("shared"):
                            shared = {m: task_rng.normal(0, sigma * np.sqrt(0.5)) for m, _ in rows}
                            e = np.array([shared[m] for m, _ in rows]) + task_rng.normal(0, sigma * np.sqrt(0.5), len(rows))
                        else:
                            scale = {t: task_rng.uniform(0.5, 1.5) for t in teams}
                            e = np.array([task_rng.normal(0, sigma * np.sqrt(np.mean([scale[t] ** 2 for t in ts])))
                                          for _, ts in rows])
                        y = A @ x + e
                        s2, t2 = reml(A, y)
                        d = 0.5 * TAU
                        indiv = {t: (truth[t] + task_rng.normal(0, d), d ** 2) for t in teams}
                        v_mu = TAU ** 2 / 50
                        mu_noisy = MU + task_rng.normal(0, np.sqrt(v_mu))
                        pop = {t: (mu_noisy, TAU ** 2 + v_mu) for t in teams}
                        posts = {"indep_individual": posterior(A, y, teams, s2, TAU ** 2, individual=indiv),
                                 "indep_population": posterior(A, y, teams, s2, TAU ** 2, individual=pop),
                                 "current_event_joint": posterior(A, y, teams, s2, t2),
                                 "current_event_plugin": posterior(A, y, teams, s2, t2, plugin=True)}
                        sims += 1
                        triples = [task_rng.choice(len(teams), 3, replace=False) for _ in range(N_ALLIANCES)]
                        for name, post in posts.items():
                            sd = np.sqrt(np.diag(post.cov))
                            err = post.mean - x
                            a = acc[name]
                            a["robots"] += len(teams)
                            for l in LEVELS:
                                a[f"cov{l}"] += int((np.abs(err) <= norm.ppf(0.5 + l / 2) * sd).sum())
                            a["width80"] += float((2 * z80 * sd).sum())
                            a["bias"] += float(err.sum())
                            a["sq"] += float((err ** 2).sum())
                            for tri in triples:
                                v = np.zeros(len(teams))
                                v[tri] = 1
                                a["alliances"] += 1
                                a["alliance_cov80"] += int(abs(v @ post.mean - v @ x) <= z80 * np.sqrt(v @ post.cov @ v))
                        joint = posts["current_event_joint"]
                        cv = acc["covariance"]
                        for tri in triples:
                            v = np.zeros(len(teams))
                            v[tri] = 1
                            err = v @ joint.mean - v @ x
                            sf, sdg = np.sqrt(v @ joint.cov @ v), np.sqrt((v * v) @ np.diag(joint.cov))
                            cv["alliances"] += 1
                            cv["full_cov80"] += int(abs(err) <= z80 * sf)
                            cv["diag_cov80"] += int(abs(err) <= z80 * sdg)
                            cv["full_width80"] += float(2 * z80 * sf)
                            cv["diag_width80"] += float(2 * z80 * sdg)
                        for _ in range(N_PAIRS):
                            pick = task_rng.choice(len(teams), 6, replace=False)
                            v = np.zeros(len(teams))
                            v[pick[:3]], v[pick[3:]] = 1, -1
                            m, true_d = float(v @ joint.mean), float(v @ x)
                            sf, sdg = np.sqrt(v @ joint.cov @ v), np.sqrt((v * v) @ np.diag(joint.cov))
                            cv["pairs"] += 1
                            cv["pair_full_cov80"] += int(abs(m - true_d) <= z80 * sf)
                            cv["pair_diag_cov80"] += int(abs(m - true_d) <= z80 * sdg)
                            delta = DELTA_FRAC * TAU
                            cls = []
                            for s_ in (sf, sdg):
                                pa, pb = 1 - norm.cdf((delta - m) / s_), norm.cdf((-delta - m) / s_)
                                cls.append("A" if pa >= PI else ("B" if pb >= PI else "other"))
                            cv["pair_class_changed"] += int(cls[0] != cls[1])
                            for which, c in zip(("full", "diag"), cls):
                                if c in ("A", "B"):
                                    cv[f"pair_{which}_decided"] += 1
                                    cv[f"pair_{which}_wrong"] += int((c == "A") != (true_d > 0))
                        # per-robot identifiability bins (joint and individual-prior scenarios)
                        partners = defaultdict(set)
                        for _, ts in rows:
                            for t in ts:
                                partners[t].update(u for u in ts if u != t)
                        counts = A.sum(axis=0)
                        for name in ("current_event_joint", "indep_individual"):
                            post = posts[name]
                            sd = np.sqrt(np.diag(post.cov))
                            corr = post.cov / np.outer(sd, sd)
                            np.fill_diagonal(corr, 0)
                            maxcorr = np.abs(corr).max(axis=1)
                            weights = w_eff(post)
                            err = post.mean - x
                            for i, t in enumerate(teams):
                                keys = [f"{name}|n={int(counts[i]) if counts[i] < 12 else '12+'}",
                                        f"{name}|w_eff={bin_of(weights[i], [-1, 0.2, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9])}",
                                        f"{name}|maxcorr={bin_of(maxcorr[i], [0, 0.1, 0.2, 0.3, 0.4, 0.5, 0.6])}",
                                        f"{name}|partners={bin_of(len(partners[t]), [0, 6, 12, 18, 24, 30])}"]
                                for k in keys:
                                    b = bins[k]
                                    b["n"] += 1
                                    b["cov80"] += int(abs(err[i]) <= z80 * sd[i])
                                    b["sq"] += float(err[i] ** 2)
                                    b["width80"] += float(2 * z80 * sd[i])
                                    b["bias"] += float(err[i])
                    if partial:
                        break
                cells[cell] = acc
                if partial:
                    break
            if partial:
                break
        if partial:
            break

    summary = {}
    for cell, acc in cells.items():
        summary[cell] = {}
        for name in SCENARIOS:
            a = acc[name]
            if a["robots"]:
                summary[cell][name] = {"robots": a["robots"], **{f"cov{l}": a[f"cov{l}"] / a["robots"] for l in LEVELS},
                                       "width80": a["width80"] / a["robots"], "bias": a["bias"] / a["robots"],
                                       "rmse": float(np.sqrt(a["sq"] / a["robots"])),
                                       "alliance_cov80": a["alliance_cov80"] / max(a["alliances"], 1)}
        cv = acc["covariance"]
        if cv["alliances"]:
            summary[cell]["covariance"] = {
                "alliance_full_cov80": cv["full_cov80"] / cv["alliances"],
                "alliance_diag_cov80": cv["diag_cov80"] / cv["alliances"],
                "alliance_width_ratio_diag_over_full": cv["diag_width80"] / cv["full_width80"],
                "pair_full_cov80": cv["pair_full_cov80"] / cv["pairs"],
                "pair_diag_cov80": cv["pair_diag_cov80"] / cv["pairs"],
                "pair_class_changed": cv["pair_class_changed"] / cv["pairs"],
                "pair_full_wrong_rate": cv["pair_full_wrong"] / max(cv["pair_full_decided"], 1),
                "pair_diag_wrong_rate": cv["pair_diag_wrong"] / max(cv["pair_diag_decided"], 1),
                "pair_full_decided_share": cv["pair_full_decided"] / cv["pairs"],
                "pair_diag_decided_share": cv["pair_diag_decided"] / cv["pairs"]}
    bin_summary = {k: {"n": b["n"], "cov80": b["cov80"] / b["n"], "rmse": float(np.sqrt(b["sq"] / b["n"])),
                       "width80": b["width80"] / b["n"], "bias": b["bias"] / b["n"]} for k, b in sorted(bins.items())}
    args.out.mkdir(parents=True, exist_ok=True)
    out = {"label": "SIMULATION OUTPUT (synthetic truths on real schedules)", "sigma_over_tau": args.sigma_over_tau,
           "caps": args.caps, "stream": stream,
           "mu": MU, "tau": TAU, "sigma": sigma, "events": [(e["key"], e["stratum"]) for e in events],
           "simulations": sims, "partial": partial, "seconds": round(time.monotonic() - started, 1),
           "cells": summary, "identifiability_bins": bin_summary}
    suffix = "" if args.caps == "all" else f"_caps_{args.caps}"
    (args.out / f"sim_sigma_over_tau_{args.sigma_over_tau}{suffix}.json").write_text(json.dumps(out, indent=1))
    print(json.dumps({"sigma_over_tau": args.sigma_over_tau, "simulations": sims, "partial": partial,
                      "seconds": out["seconds"]}))
    return 1 if partial else 0


if __name__ == "__main__":
    sys.exit(main())
