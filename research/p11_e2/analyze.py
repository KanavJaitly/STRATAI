"""P11A E2 research: metrics for the E2 records (PROTOCOL.json `metrics`, `delta_pi_grid`, `g2`).

    python -I research/p11_e2/analyze.py --results research/p11_e2/results [--budget-minutes 40]

Reads e2_records_<season>.json and writes analysis.json and analysis_tables.md (markdown tables for the report).
Everything here is computed from recorded outcomes and the models' pre-selection predictions. Nothing is refitted.
"""

from __future__ import annotations

import argparse
import json
import math
import sys
import time
from collections import defaultdict
from pathlib import Path

import numpy as np
from scipy.stats import norm

SEED = 20261105
BOOT = 1000
SEASONS = (2024, 2025, 2026)
TARGETS = ("auto", "teleop", "endgame", "no_foul", "total")
MODELS = ("M0_event_mean", "M1_team_average", "M2_prior_event", "M3_plain_opr", "AS1_joint", "AS1_joint_diag",
          "AS1_indep_prior", "AS1_plugin")
LEVELS = (0.5, 0.8, 0.9, 0.95)
DELTAS = (0, 2, 5, 10, 15, 20, 30)
DELTA_REL = (0.05, 0.1, 0.2, 0.3)
PIS = (0.6, 0.7, 0.8, 0.9, 0.95, 0.99)
BOUNDS = (2.0, 2.5, 3.0, 3.5, 4.0)


def accuracy(err: np.ndarray) -> dict:
    a = np.abs(err)
    return {"n": int(len(err)), "mae": float(a.mean()), "rmse": float(np.sqrt((err ** 2).mean())),
            "bias": float(err.mean()), "median_ae": float(np.median(a)),
            "ae_percentiles": {str(p): float(np.percentile(a, p)) for p in (50, 75, 90, 95, 99)}}


def coverage(err: np.ndarray, sd: np.ndarray) -> dict:
    out = {}
    for level in LEVELS:
        z = norm.ppf(0.5 + level / 2)
        out[str(level)] = {"coverage": float((np.abs(err) <= z * sd).mean()), "mean_width": float((2 * z * sd).mean())}
    return out


def cluster_boot(events: np.ndarray, per_row: np.ndarray, rng) -> tuple[float, float]:
    """Percentile 95% CI of the mean of `per_row`, resampling events (clusters) with replacement. Every statistic
    bootstrapped here is a mean of a per-row quantity, so it is computed from per-event sums and counts."""
    uniq, inverse = np.unique(events, return_inverse=True)
    sums = np.bincount(inverse, weights=per_row.astype(float))
    counts = np.bincount(inverse).astype(float)
    draws = rng.integers(0, len(uniq), size=(BOOT, len(uniq)))
    weights = np.stack([np.bincount(d, minlength=len(uniq)) for d in draws])
    stats = (weights @ sums) / (weights @ counts)
    return float(np.percentile(stats, 2.5)), float(np.percentile(stats, 97.5))


def classify(m: np.ndarray, s: np.ndarray, delta: float, pi: float) -> np.ndarray:
    s = np.maximum(s, 1e-9)
    p_a = 1 - norm.cdf((delta - m) / s)  # P(Delta > delta)
    p_b = norm.cdf((-delta - m) / s)  # P(Delta < -delta)
    p_eq = norm.cdf((delta - m) / s) - norm.cdf((-delta - m) / s) if delta > 0 else np.zeros_like(m)
    out = np.full(len(m), "unresolved", dtype=object)
    out[p_eq >= pi] = "practically_equivalent"
    out[p_b >= pi] = "B_preferred"
    out[p_a >= pi] = "A_preferred"
    return out


def grid(pairs: list[dict], model: str, deltas_by_season: dict[int, list[float]], label: str) -> list[dict]:
    rows = []
    for season in (*SEASONS, "all"):
        sel = [p for p in pairs if season == "all" or p["season"] == season]
        if not sel:
            continue
        m = np.array([p["diff"]["no_foul"][model][0] for p in sel])
        s = np.array([p["diff"]["no_foul"][model][1] for p in sel])
        actual = np.array([p["actual_diff"]["no_foul"] for p in sel])
        deltas = deltas_by_season["all" if season == "all" else season]
        for d_i, delta in enumerate(deltas):
            for pi in PIS:
                cls = classify(m, s, delta, pi)
                n = len(cls)
                pref_a, pref_b = cls == "A_preferred", cls == "B_preferred"
                decided = (pref_a | pref_b) & (actual != 0)
                wrong = (pref_a & (actual < 0)) | (pref_b & (actual > 0))
                eq = cls == "practically_equivalent"
                rows.append({"season": season, "model": model, "delta_kind": label, "delta_index": d_i,
                             "delta": float(delta), "pi": pi, "n": n,
                             "A_preferred": int(pref_a.sum()), "B_preferred": int(pref_b.sum()),
                             "practically_equivalent": int(eq.sum()), "unresolved": int((cls == "unresolved").sum()),
                             "incorrect_preference_rate": float(wrong[decided].mean()) if decided.any() else None,
                             "n_decided_nontie": int(decided.sum()),
                             "equivalent_actual_abs_diff_median": float(np.median(np.abs(actual[eq]))) if eq.any()
                             else None, "classes": cls.tolist()})
    return rows


def stability(rows: list[dict]) -> dict:
    """Share of comparisons whose class changes when delta or pi moves one grid step (same season, model, kind)."""
    keyed = {(r["season"], r["model"], r["delta_kind"], r["delta_index"], r["pi"]): r["classes"] for r in rows}
    out = defaultdict(list)
    for (season, model, kind, di, pi), classes in keyed.items():
        c = np.array(classes)
        nxt_d = keyed.get((season, model, kind, di + 1, pi))
        nxt_p = PIS[PIS.index(pi) + 1] if PIS.index(pi) + 1 < len(PIS) else None
        nxt_pi = keyed.get((season, model, kind, di, nxt_p)) if nxt_p else None
        if nxt_d is not None:
            out[f"{season}|{model}|{kind}|delta_step"].append(float((c != np.array(nxt_d)).mean()))
        if nxt_pi is not None:
            out[f"{season}|{model}|{kind}|pi_step"].append(float((c != np.array(nxt_pi)).mean()))
    return {k: {"mean_changed": float(np.mean(v)), "max_changed": float(np.max(v))} for k, v in out.items()}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--results", type=Path, required=True)
    parser.add_argument("--budget-minutes", type=float, default=40.0)
    args = parser.parse_args(argv)
    if not 0 < args.budget_minutes <= 45:
        parser.error("--budget-minutes must be in (0, 45]")
    started = time.monotonic()
    rng = np.random.default_rng(SEED)
    alliances, pairs, hyper, metas = [], [], [], []
    for season in SEASONS:
        path = args.results / f"e2_records_{season}.json"
        if not path.exists():
            continue
        data = json.loads(path.read_text())
        alliances += data["alliances"]
        pairs += data["pairs"]
        hyper += [{**h, "season": season} for h in data["hyper"]]
        metas.append(data["meta"])
    out: dict = {"meta": metas, "accuracy": {}, "coverage": {}, "boot": {}, "event_coverage": {}, "pairwise": {},
                 "g2": {}, "independence": {}, "hyper": {}}

    # --- accuracy and coverage ------------------------------------------------------------------------------------
    for season in (*SEASONS, "all"):
        sel = [a for a in alliances if season == "all" or a["season"] == season]
        if not sel:
            continue
        events = np.array([a["event"] for a in sel])
        for target in TARGETS:
            actual = np.array([a["actual"][target] for a in sel], dtype=float)
            for model in MODELS:
                pred = np.array([a["pred"][target][model][0] for a in sel])
                sd = np.array([a["pred"][target][model][1] for a in sel])
                err = pred - actual
                key = f"{season}|{target}|{model}"
                out["accuracy"][key] = accuracy(err)
                out["coverage"][key] = coverage(err, sd)
                if target in ("no_foul", "total") and model in ("M0_event_mean", "M1_team_average", "M2_prior_event",
                                                                 "M3_plain_opr", "AS1_joint", "AS1_indep_prior"):
                    out["boot"][key] = {
                        "mae_ci": cluster_boot(events, np.abs(err), rng),
                        "cov80_ci": cluster_boot(events, (np.abs(err) <= norm.ppf(0.9) * sd).astype(float), rng)}
                if target == "no_foul" and model in ("AS1_joint", "AS1_joint_diag", "AS1_plugin", "AS1_indep_prior",
                                                     "M3_plain_opr"):
                    per_event = defaultdict(list)
                    for e, er, s in zip(events, err, sd):
                        per_event[e].append(abs(er) <= norm.ppf(0.9) * s)
                    covs = np.array([np.mean(v) for v in per_event.values() if len(v) >= 10])
                    out["event_coverage"][key] = {"events": int(len(covs)),
                                                  "quantiles": {str(q): float(np.quantile(covs, q))
                                                                for q in (0.1, 0.25, 0.5, 0.75, 0.9)},
                                                  "share_below_0.7": float((covs < 0.7).mean()),
                                                  "share_above_0.9": float((covs > 0.9).mean())}
        # paired MAE difference vs AS1_joint (no_foul), event-cluster bootstrap
        actual = np.array([a["actual"]["no_foul"] for a in sel], dtype=float)
        joint_ae = np.abs(np.array([a["pred"]["no_foul"]["AS1_joint"][0] for a in sel]) - actual)
        for model in ("M0_event_mean", "M1_team_average", "M2_prior_event", "M3_plain_opr", "AS1_indep_prior"):
            other = np.abs(np.array([a["pred"]["no_foul"][model][0] for a in sel]) - actual)
            d = other - joint_ae
            out["boot"][f"{season}|no_foul|{model}-AS1_joint|mae_diff"] = {
                "point": float(d.mean()), "ci": cluster_boot(events, d, rng)}
        if time.monotonic() - started > args.budget_minutes * 60:
            out["partial"] = True
            break

    # --- pairwise -----------------------------------------------------------------------------------------------
    pair_models = ("AS1_joint", "AS1_joint_diag", "AS1_indep_prior", "AS1_plugin", "M3_plain_opr", "M1_team_average",
                   "M2_prior_event")
    sigma2 = {(h["event"], h["component"]): h["sigma2"] for h in hyper}
    for season in (*SEASONS, "all"):
        sel = [p for p in pairs if season == "all" or p["season"] == season]
        if not sel:
            continue
        actual = np.array([p["actual_diff"]["no_foul"] for p in sel], dtype=float)
        nontie = actual != 0
        for model in pair_models:
            m = np.array([p["diff"]["no_foul"][model][0] for p in sel])
            sign_ok = (np.sign(m) == np.sign(actual)) & nontie
            wrong = (np.sign(m) != np.sign(actual)) & nontie
            slope = float(np.polyfit(m, actual, 1)[0])
            entry = {"n": int(len(sel)), "n_nontie": int(nontie.sum()),
                     "sign_accuracy": float(sign_ok.sum() / nontie.sum()),
                     "diff_mae": float(np.abs(m - actual).mean()), "corr": float(np.corrcoef(m, actual)[0, 1]),
                     "calibration_slope": slope,
                     "wrong_actual_abs_diff_median": float(np.median(np.abs(actual[wrong]))) if wrong.any() else None,
                     "wrong_pred_abs_diff_median": float(np.median(np.abs(m[wrong]))) if wrong.any() else None}
            if model in ("AS1_joint", "AS1_joint_diag", "AS1_indep_prior", "AS1_plugin"):
                s = np.array([p["diff"]["no_foul"][model][1] for p in sel])
                noise = np.array([2 * sigma2[(p["event"], "no_foul")] for p in sel])
                z90 = norm.ppf(0.9)
                entry["est_sd_median"] = float(np.median(s))
                entry["coverage80_of_actual_diff_with_match_noise"] = float(
                    (np.abs(actual - m) <= z90 * np.sqrt(s ** 2 + noise)).mean())
            out["pairwise"][f"{season}|{model}"] = entry

    # --- delta / pi grid ------------------------------------------------------------------------------------------
    season_sd = {}
    for season in SEASONS:
        vals = [a["actual"]["no_foul"] for a in alliances if a["season"] == season]
        if vals:
            season_sd[season] = float(np.std(vals, ddof=1))
    out["season_playoff_alliance_sd"] = season_sd
    abs_deltas = {s: list(DELTAS) for s in (*SEASONS, "all")}
    rel_deltas = {s: [r * season_sd[s] for r in DELTA_REL] for s in season_sd}
    rel_deltas["all"] = [r * float(np.mean(list(season_sd.values()))) for r in DELTA_REL]
    grid_rows = []
    for model in ("AS1_joint", "AS1_joint_diag", "AS1_indep_prior"):
        grid_rows += grid(pairs, model, abs_deltas, "absolute")
        grid_rows += grid(pairs, model, rel_deltas, "relative")
    out["delta_pi_stability"] = stability(grid_rows)
    # event-level spread of class shares (sensitivity to event), AS1_joint absolute grid, all seasons
    by_event = defaultdict(list)
    for i, p in enumerate(pairs):
        by_event[p["event"]].append(i)
    event_sens = []
    for r in grid_rows:
        if r["model"] != "AS1_joint" or r["delta_kind"] != "absolute" or r["season"] != "all":
            continue
        cls = np.array(r["classes"])
        shares = [float((cls[idx] == "unresolved").mean()) for idx in by_event.values() if len(idx) >= 8]
        event_sens.append({"delta": r["delta"], "pi": r["pi"], "events": len(shares),
                           "unresolved_share_event_p10": float(np.percentile(shares, 10)),
                           "unresolved_share_event_p50": float(np.percentile(shares, 50)),
                           "unresolved_share_event_p90": float(np.percentile(shares, 90))})
    out["delta_pi_event_sensitivity"] = event_sens
    for r in grid_rows:
        r.pop("classes")
    out["delta_pi_grid"] = grid_rows

    # --- G2: standardized residuals -----------------------------------------------------------------------------
    for season in (*SEASONS, "all"):
        sel = [a for a in alliances if season == "all" or a["season"] == season]
        if not sel:
            continue
        for target in ("auto", "teleop", "endgame", "no_foul", "total"):
            z = np.array([(a["actual"][target] - a["pred"][target]["AS1_joint"][0]) / a["pred"][target]["AS1_joint"][1]
                          for a in sel])
            entry = {"n": int(len(z)), "mean": float(z.mean()), "sd": float(z.std(ddof=1)),
                     "quantiles": {str(q): float(np.quantile(z, q)) for q in (0.001, 0.01, 0.05, 0.5, 0.95, 0.99, 0.999)},
                     "bounds": {}}
            for b in BOUNDS:
                entry["bounds"][str(b)] = {"observed_share": float((np.abs(z) > b).mean()),
                                           "nominal_share": float(2 * (1 - norm.cdf(b))),
                                           "low_share": float((z < -b).mean()), "high_share": float((z > b).mean())}
            out["g2"][f"{season}|{target}"] = entry
    # G2 by event size and playoff round (no_foul, all seasons)
    sizes = defaultdict(list)
    for a in alliances:
        z = (a["actual"]["no_foul"] - a["pred"]["no_foul"]["AS1_joint"][0]) / a["pred"]["no_foul"]["AS1_joint"][1]
        sizes[f"comp_level={a['comp_level']}"].append(z)
        sizes[f"event_type={a['event_type']}"].append(z)
    out["g2"]["by_group_no_foul"] = {k: {"n": len(v), "sd": float(np.std(v, ddof=1)),
                                         "share_abs_z_gt_3": float((np.abs(v) > 3).mean())}
                                     for k, v in sizes.items() if len(v) >= 30}

    # --- independence on real data ---------------------------------------------------------------------------------
    for season in (*SEASONS, "all"):
        sel = [a for a in alliances if season == "all" or a["season"] == season]
        if not sel:
            continue
        full = np.array([a["pred"]["no_foul"]["AS1_joint"][2] for a in sel])
        diag = np.array([a["pred"]["no_foul"]["AS1_joint_diag"][2] for a in sel])
        pfull = np.array([a["pred"]["no_foul"]["AS1_joint"][1] for a in sel])
        pdiag = np.array([a["pred"]["no_foul"]["AS1_joint_diag"][1] for a in sel])
        psel = [p for p in pairs if season == "all" or p["season"] == season]
        dfull = np.array([p["diff"]["no_foul"]["AS1_joint"][1] for p in psel])
        ddiag = np.array([p["diff"]["no_foul"]["AS1_joint_diag"][1] for p in psel])
        out["independence"][str(season)] = {
            "alliance_est_sd_ratio_diag_over_full": {"median": float(np.median(diag / full)),
                                                     "p10": float(np.percentile(diag / full, 10)),
                                                     "p90": float(np.percentile(diag / full, 90))},
            "alliance_pred_sd_ratio_diag_over_full": {"median": float(np.median(pdiag / pfull)),
                                                      "p10": float(np.percentile(pdiag / pfull, 10)),
                                                      "p90": float(np.percentile(pdiag / pfull, 90))},
            "pair_diff_est_sd_ratio_diag_over_full": {"median": float(np.median(ddiag / dfull)),
                                                      "p10": float(np.percentile(ddiag / dfull, 10)),
                                                      "p90": float(np.percentile(ddiag / dfull, 90))}}
    # classification disagreement full vs diag at each grid point (absolute deltas, all seasons)
    disagree = []
    m_full = np.array([p["diff"]["no_foul"]["AS1_joint"][0] for p in pairs])
    s_full = np.array([p["diff"]["no_foul"]["AS1_joint"][1] for p in pairs])
    s_diag = np.array([p["diff"]["no_foul"]["AS1_joint_diag"][1] for p in pairs])
    for delta in DELTAS:
        for pi in PIS:
            a, b = classify(m_full, s_full, delta, pi), classify(m_full, s_diag, delta, pi)
            disagree.append({"delta": delta, "pi": pi, "share_class_changed": float((a != b).mean())})
    out["independence"]["classification_change_full_vs_diag"] = disagree

    # --- hyperparameters --------------------------------------------------------------------------------------------
    for season in SEASONS:
        hs = [h for h in hyper if h["season"] == season and h["component"] == "no_foul"]
        if not hs:
            continue
        out["hyper"][str(season)] = {
            "events": len(hs),
            "sigma_median": float(np.median([math.sqrt(h["sigma2"]) for h in hs])),
            "tau_median": float(np.median([math.sqrt(h["tau2"]) for h in hs])),
            "events_with_drift_prior": int(sum(1 for h in hs if h["tau_drift2"] is not None)),
            "tau_drift_median": float(np.median([math.sqrt(h["tau_drift2"]) for h in hs if h["tau_drift2"]]))
            if any(h["tau_drift2"] for h in hs) else None,
            "share_robots_with_prior_event": float(sum(h["robots_with_prior_event"] for h in hs)
                                                   / sum(h["n_teams"] for h in hs))}
    out["seconds"] = round(time.monotonic() - started, 1)
    (args.results / "analysis.json").write_text(json.dumps(out, indent=1))
    write_tables(out, args.results / "analysis_tables.md")
    print(json.dumps({"seconds": out["seconds"], "partial": out.get("partial", False),
                      "alliances": len(alliances), "pairs": len(pairs)}))
    return 0


def write_tables(out: dict, path: Path) -> None:
    lines = []
    f = lambda x, d=1: "—" if x is None else f"{x:.{d}f}"  # noqa: E731
    lines.append("## Accuracy and 80% coverage (no_foul)\n")
    lines.append("| Season | Model | n | MAE [95% CI] | RMSE | Bias | Median AE | 80% cov [95% CI] | 80% width |")
    lines.append("|---|---|---|---|---|---|---|---|---|")
    for season in (*SEASONS, "all"):
        for model in MODELS:
            k = f"{season}|no_foul|{model}"
            if k not in out["accuracy"]:
                continue
            a, c, b = out["accuracy"][k], out["coverage"][k]["0.8"], out["boot"].get(k, {})
            mae_ci = f" [{f(b['mae_ci'][0])}, {f(b['mae_ci'][1])}]" if "mae_ci" in b else ""
            cov_ci = f" [{f(b['cov80_ci'][0], 3)}, {f(b['cov80_ci'][1], 3)}]" if "cov80_ci" in b else ""
            lines.append(f"| {season} | {model} | {a['n']} | {f(a['mae'])}{mae_ci} | {f(a['rmse'])} | {f(a['bias'])} | "
                         f"{f(a['median_ae'])} | {f(c['coverage'], 3)}{cov_ci} | {f(c['mean_width'])} |")
    lines.append("\n## Coverage at every nominal level (AS1_joint)\n")
    lines.append("| Season | Target | 50% | 80% | 90% | 95% |")
    lines.append("|---|---|---|---|---|---|")
    for season in (*SEASONS, "all"):
        for target in TARGETS:
            k = f"{season}|{target}|AS1_joint"
            if k in out["coverage"]:
                c = out["coverage"][k]
                lines.append(f"| {season} | {target} | " + " | ".join(f(c[str(l)]["coverage"], 3) for l in LEVELS) + " |")
    lines.append("\n## Component accuracy (AS1_joint vs M0)\n")
    lines.append("| Season | Target | AS1 MAE | M0 MAE | AS1 bias |")
    lines.append("|---|---|---|---|---|")
    for season in (*SEASONS, "all"):
        for target in TARGETS:
            k1, k0 = f"{season}|{target}|AS1_joint", f"{season}|{target}|M0_event_mean"
            if k1 in out["accuracy"]:
                lines.append(f"| {season} | {target} | {f(out['accuracy'][k1]['mae'])} | {f(out['accuracy'][k0]['mae'])}"
                             f" | {f(out['accuracy'][k1]['bias'])} |")
    lines.append("\n## Paired MAE difference vs AS1_joint (no_foul; positive = AS1_joint better)\n")
    lines.append("| Season | Comparator | MAE diff [95% CI] |")
    lines.append("|---|---|---|")
    for k, v in out["boot"].items():
        if k.endswith("mae_diff"):
            season, _, comp, _ = k.split("|")
            lines.append(f"| {season} | {comp} | {f(v['point'], 2)} [{f(v['ci'][0], 2)}, {f(v['ci'][1], 2)}] |")
    lines.append("\n## Pairwise (red vs blue, no_foul)\n")
    lines.append("| Season | Model | n (non-tie) | Sign accuracy | Diff MAE | Corr | Slope | Median |actual| when wrong |")
    lines.append("|---|---|---|---|---|---|---|---|")
    for k, v in out["pairwise"].items():
        season, model = k.split("|")
        lines.append(f"| {season} | {model} | {v['n_nontie']} | {f(v['sign_accuracy'], 3)} | {f(v['diff_mae'])} | "
                     f"{f(v['corr'], 3)} | {f(v['calibration_slope'], 2)} | {f(v['wrong_actual_abs_diff_median'])} |")
    path.write_text("\n".join(lines) + "\n")


if __name__ == "__main__":
    sys.exit(main())
