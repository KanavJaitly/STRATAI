"""P11A E2 follow-up F1 (bias decomposition) and F2 (correction candidates), per FOLLOWUP_PROTOCOL.json.

    python -I research/p11_e2/analyze_followup.py --results research/p11_e2/results \
        --population research/p11_e2/cache/population

Reads the original E2 records (never modified), the F1c refit rows and the populations. Writes
followup_analysis.json and followup_tables.md. OBSERVED results vs MODEL PREDICTIONS; F2 corrections are research
candidates evaluated on held-out events only.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from pathlib import Path

import numpy as np
from scipy.stats import norm

SEASONS = (2024, 2025, 2026)
COMPONENTS = ("auto", "teleop", "endgame", "no_foul")
LEVELS = (0.5, 0.8, 0.9, 0.95)
BOOT, SEED = 1000, 20261106


def cluster_ci(events: np.ndarray, per_row: np.ndarray, rng) -> tuple[float, float]:
    uniq, inverse = np.unique(events, return_inverse=True)
    sums = np.bincount(inverse, weights=per_row.astype(float))
    counts = np.bincount(inverse).astype(float)
    draws = rng.integers(0, len(uniq), size=(BOOT, len(uniq)))
    w = np.stack([np.bincount(d, minlength=len(uniq)) for d in draws])
    stats = (w @ sums) / (w @ counts)
    return float(np.percentile(stats, 2.5)), float(np.percentile(stats, 97.5))


def metrics(actual, pred, sd) -> dict:
    err = pred - actual
    out = {"n": int(len(err)), "mae": float(np.abs(err).mean()), "rmse": float(np.sqrt((err ** 2).mean())),
           "bias": float(err.mean())}
    for l in LEVELS:
        out[f"cov{l}"] = float((np.abs(err) <= norm.ppf(0.5 + l / 2) * sd).mean())
    out["width80"] = float((2 * norm.ppf(0.9) * sd).mean())
    return out


def fit_correction(form: str, actual, pred, sd) -> dict:
    if form == "C1_multiplicative":
        m = float(actual.sum() / pred.sum())
        k = float(np.sqrt(np.mean(((actual - m * pred) / sd) ** 2)))
        return {"m": m, "k": k}
    c = float(np.mean((actual - pred) / sd))
    k = float(np.sqrt(np.mean(((actual - (pred + c * sd)) / sd) ** 2)))
    return {"c": c, "k": k}


def apply_correction(form: str, params: dict, pred, sd):
    if form == "C1_multiplicative":
        return params["m"] * pred, params["k"] * sd
    return pred + params["c"] * sd, params["k"] * sd


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--results", type=Path, required=True)
    parser.add_argument("--population", type=Path, required=True)
    args = parser.parse_args(argv)
    rng = np.random.default_rng(SEED)
    alliances, f1c, events_meta, qual_means = [], [], {}, {}
    for season in SEASONS:
        alliances += json.loads((args.results / f"e2_records_{season}.json").read_text())["alliances"]
        f1c += json.loads((args.results / f"followup_f1c_{season}.json").read_text())["rows"]
        pop = json.loads((args.population / f"population_{season}.json").read_text())
        for e in pop["events"]:
            events_meta[e["key"]] = {"season": season, "type": e["type"], "week": e["week"],
                                     "start": e["start_date"], "end": e["end_date"], "teams": len(e["teams"])}
            qual_means[e["key"]] = {c: float(np.mean([r[c] for r in e["quals"]])) for c in COMPONENTS}
    out: dict = {}

    # --- F1a: qualification vs playoff distributions ----------------------------------------------------------
    f1a = {}
    for season in (*SEASONS, "all"):
        sel = [a for a in alliances if season == "all" or a["season"] == season]
        by_event = defaultdict(list)
        for a in sel:
            by_event[a["event"]].append(a)
        rows = []
        for ev, rs in by_event.items():
            rows.append({c: (np.mean([r["actual"][c] for r in rs]), qual_means[ev][c],
                             np.mean([r["pred"][c]["AS1_joint"][0] for r in rs])) for c in COMPONENTS})
        f1a[str(season)] = {c: {"playoff_mean": float(np.mean([r[c][0] for r in rows])),
                                "qual_mean": float(np.mean([r[c][1] for r in rows])),
                                "playoff_pred_mean": float(np.mean([r[c][2] for r in rows])),
                                "events": len(rows)} for c in COMPONENTS}
    out["F1a"] = f1a

    # --- F1b: by event --------------------------------------------------------------------------------------------
    f1b = {}
    resid = defaultdict(list)
    for a in alliances:
        resid[a["event"]].append(a["actual"]["no_foul"] - a["pred"]["no_foul"]["AS1_joint"][0])
    ev_mean = {e: float(np.mean(v)) for e, v in resid.items()}
    for season in (*SEASONS, "all"):
        keys = [e for e in ev_mean if season == "all" or events_meta[e]["season"] == season]
        v = np.array([ev_mean[e] for e in keys])
        rows = np.concatenate([resid[e] for e in keys])
        n_drop = max(1, int(round(0.05 * len(keys))))
        drop = set(sorted(keys, key=lambda e: -abs(ev_mean[e]))[:n_drop])
        kept = np.concatenate([resid[e] for e in keys if e not in drop])
        trimmed = np.sort(v)[int(0.1 * len(v)):len(v) - int(0.1 * len(v))]
        f1b[str(season)] = {"events": len(keys), "row_mean_resid": float(rows.mean()),
                            "event_mean_resid_median": float(np.median(v)),
                            "event_mean_resid_trimmed10": float(trimmed.mean()),
                            "share_events_resid_positive": float((v > 0).mean()),
                            "row_mean_resid_without_top5pct_events": float(kept.mean()),
                            "event_resid_p10_p90": [float(np.percentile(v, 10)), float(np.percentile(v, 90))]}
    groups = defaultdict(list)
    for a in alliances:
        meta = events_meta[a["event"]]
        r = a["actual"]["no_foul"] - a["pred"]["no_foul"]["AS1_joint"][0]
        sd = a["pred"]["no_foul"]["AS1_joint"][1]
        size = "<=36" if meta["teams"] <= 36 else ("37-50" if meta["teams"] <= 50 else ">50")
        wk = meta["week"] if meta["week"] is not None else "?"
        for g in (f"type={meta['type']}", f"size={size}", f"week={wk}"):
            groups[(meta["season"], g)].append((r, r / sd))
    f1b["groups"] = {f"{s}|{g}": {"n": len(v), "mean_resid": float(np.mean([x[0] for x in v])),
                                  "mean_z": float(np.mean([x[1] for x in v]))}
                     for (s, g), v in sorted(groups.items(), key=lambda kv: (kv[0][0], str(kv[0][1]))) if len(v) >= 50}
    out["F1b"] = f1b

    # --- F1c: within-qualification trend ----------------------------------------------------------------------------
    f1c_out = {}
    orig = {(a["event"], a["match"], a["color"]): a for a in alliances}
    for season in (*SEASONS, "all"):
        for c in COMPONENTS:
            late = [r for r in f1c if r["kind"] == "late_qual" and r["component"] == c and (season == "all" or r["season"] == season)]
            po = [r for r in f1c if r["kind"] == "playoff_from_early" and r["component"] == c and (season == "all" or r["season"] == season)]
            full = [orig[(r["event"], r["match"], r["color"])] for r in po if (r["event"], r["match"], r["color"]) in orig]
            f1c_out[f"{season}|{c}"] = {
                "late_qual_resid_mean": float(np.mean([r["actual"] - r["pred"] for r in late])),
                "late_qual_z_sd": float(np.std([(r["actual"] - r["pred"]) / r["sd"] for r in late], ddof=1)),
                "late_qual_cov80": float(np.mean([abs(r["actual"] - r["pred"]) <= norm.ppf(0.9) * r["sd"] for r in late])),
                "playoff_from_early_resid_mean": float(np.mean([r["actual"] - r["pred"] for r in po])),
                "playoff_from_full_resid_mean": float(np.mean([a["actual"][c] - a["pred"][c]["AS1_joint"][0] for a in full])),
                "n_late": len(late), "n_playoff": len(po)}
    out["F1c"] = f1c_out

    # --- F1d: strength terciles --------------------------------------------------------------------------------------
    f1d = {}
    by_event = defaultdict(list)
    for a in alliances:
        by_event[a["event"]].append(a)
    terc = defaultdict(list)
    for ev, rs in by_event.items():
        preds = np.array([r["pred"]["no_foul"]["AS1_joint"][0] for r in rs])
        cuts = np.quantile(preds, [1 / 3, 2 / 3])
        for r, p in zip(rs, preds):
            t = 0 if p <= cuts[0] else (1 if p <= cuts[1] else 2)
            terc[(r["season"], t)].append(r["actual"]["no_foul"] - p)
    f1d["playoff_by_pred_tercile"] = {f"{s}|T{t + 1}": {"n": len(v), "mean_resid": float(np.mean(v))}
                                      for (s, t), v in sorted(terc.items())}
    late_terc = defaultdict(list)
    late_by_event = defaultdict(list)
    for r in f1c:
        if r["kind"] == "late_qual" and r["component"] == "no_foul":
            late_by_event[r["event"]].append(r)
    for ev, rs in late_by_event.items():
        preds = np.array([r["pred"] for r in rs])
        cuts = np.quantile(preds, [1 / 3, 2 / 3])
        for r, p in zip(rs, preds):
            t = 0 if p <= cuts[0] else (1 if p <= cuts[1] else 2)
            late_terc[(r["season"], t)].append(r["actual"] - p)
    f1d["late_qual_by_pred_tercile"] = {f"{s}|T{t + 1}": {"n": len(v), "mean_resid": float(np.mean(v))}
                                        for (s, t), v in sorted(late_terc.items())}
    out["F1d"] = f1d

    # --- F1e: round and appearance order ---------------------------------------------------------------------------
    f1e = defaultdict(list)
    seen = defaultdict(int)
    for a in sorted(alliances, key=lambda a: (a["event"], a["time"])):
        k = (a["event"], tuple(sorted(a["teams"])))
        seen[k] += 1
        order = str(min(seen[k], 3)) + ("+" if seen[k] >= 3 else "")
        r = a["actual"]["no_foul"] - a["pred"]["no_foul"]["AS1_joint"][0]
        f1e[(a["season"], f"comp_level={a['comp_level']}")].append(r)
        f1e[(a["season"], f"appearance={order}")].append(r)
    out["F1e"] = {f"{s}|{g}": {"n": len(v), "mean_resid": float(np.mean(v))} for (s, g), v in sorted(f1e.items())}

    # --- F1f: components and fouls --------------------------------------------------------------------------------
    f1f = {}
    for season in (*SEASONS, "all"):
        sel = [a for a in alliances if season == "all" or a["season"] == season]
        f1f[str(season)] = {c: float(np.mean([a["actual"][c] - a["pred"][c]["AS1_joint"][0] for a in sel]))
                            for c in (*COMPONENTS, "total")}
    out["F1f"] = f1f

    # --- F2: correction candidates on held-out events ---------------------------------------------------------------
    def arrays(rows):
        return (np.array([r["actual"]["no_foul"] for r in rows], float),
                np.array([r["pred"]["no_foul"]["AS1_joint"][0] for r in rows]),
                np.array([r["pred"]["no_foul"]["AS1_joint"][1] for r in rows]),
                np.array([r["event"] for r in rows]))

    designs = {}
    for season in SEASONS:
        starts = sorted(m["start"] for e, m in events_meta.items() if m["season"] == season)
        median_start = starts[len(starts) // 2]
        train = [a for a in alliances if a["season"] == season and events_meta[a["event"]]["end"] < median_start]
        test = [a for a in alliances if a["season"] == season and events_meta[a["event"]]["start"] >= median_start]
        designs[f"W_within_season_{season}"] = (train, test, median_start)
    designs["X_cross_season"] = ([a for a in alliances if a["season"] in (2024, 2025)],
                                 [a for a in alliances if a["season"] == 2026], None)
    f2 = {}
    for name, (train, test, split) in designs.items():
        ya, yp, ys, _ = arrays(train)
        ta, tp, ts, te = arrays(test)
        entry = {"split_date": split, "train_rows": len(train), "test_rows": len(test),
                 "train_events": len({r["event"] for r in train}), "test_events": len({r["event"] for r in test}),
                 "uncorrected": metrics(ta, tp, ts), "forms": {}}
        for form in ("C1_multiplicative", "C2_z_shift"):
            params = fit_correction(form, ya, yp, ys)
            cp, cs = apply_correction(form, params, tp, ts)
            d = np.abs(tp - ta) - np.abs(cp - ta)  # positive = correction more accurate
            cov_gain = ((np.abs(cp - ta) <= norm.ppf(0.9) * cs).astype(float)
                        - (np.abs(tp - ta) <= norm.ppf(0.9) * ts).astype(float))
            entry["forms"][form] = {"params": params, "test": metrics(ta, cp, cs),
                                    "mae_gain": float(d.mean()), "mae_gain_ci": cluster_ci(te, d, rng),
                                    "cov80_gain": float(cov_gain.mean()), "cov80_gain_ci": cluster_ci(te, cov_gain, rng)}
        f2[name] = entry
    out["F2"] = f2

    (args.results / "followup_analysis.json").write_text(json.dumps(out, indent=1))
    write_tables(out, args.results / "followup_tables.md")
    print("wrote followup_analysis.json and followup_tables.md")
    return 0


def write_tables(out: dict, path: Path) -> None:
    f = lambda x, d=1: "—" if x is None else f"{x:.{d}f}"  # noqa: E731
    L = ["## F1a qualification vs playoff means (no_foul; event-averaged)\n",
         "| Season | Qual mean | Playoff mean (observed) | Playoff mean (AS1 pred) |", "|---|---|---|---|"]
    for s, v in out["F1a"].items():
        c = v["no_foul"]
        L.append(f"| {s} | {f(c['qual_mean'])} | {f(c['playoff_mean'])} | {f(c['playoff_pred_mean'])} |")
    L += ["\n## F1b event-level residual (observed − AS1_joint, no_foul)\n",
          "| Season | Events | Row mean | Event median | Trimmed 10% | Share events > 0 | Without top 5% events | Event p10–p90 |",
          "|---|---|---|---|---|---|---|---|"]
    for s in ("2024", "2025", "2026", "all"):
        v = out["F1b"][s]
        L.append(f"| {s} | {v['events']} | {f(v['row_mean_resid'])} | {f(v['event_mean_resid_median'])} | "
                 f"{f(v['event_mean_resid_trimmed10'])} | {f(v['share_events_resid_positive'], 3)} | "
                 f"{f(v['row_mean_resid_without_top5pct_events'])} | {f(v['event_resid_p10_p90'][0])} – "
                 f"{f(v['event_resid_p10_p90'][1])} |")
    L += ["\n### F1b groups (mean residual, mean z)\n", "| Season | Group | n | Mean resid | Mean z |", "|---|---|---|---|---|"]
    for k, v in out["F1b"]["groups"].items():
        s, g = k.split("|")
        L.append(f"| {s} | {g} | {v['n']} | {f(v['mean_resid'])} | {f(v['mean_z'], 2)} |")
    L += ["\n## F1c within-qualification trend (fit on first 2/3 of qualifications)\n",
          "| Season | Component | Late-qual resid | Late-qual z SD | Late-qual cov80 | Playoff resid (early fit) | Playoff resid (full fit) |",
          "|---|---|---|---|---|---|---|"]
    for k, v in out["F1c"].items():
        s, c = k.split("|")
        L.append(f"| {s} | {c} | {f(v['late_qual_resid_mean'])} | {f(v['late_qual_z_sd'], 2)} | {f(v['late_qual_cov80'], 3)} | "
                 f"{f(v['playoff_from_early_resid_mean'])} | {f(v['playoff_from_full_resid_mean'])} |")
    L += ["\n## F1d residual by predicted-strength tercile (T1 weakest)\n", "| Season | Tercile | Playoff resid | Late-qual resid |",
          "|---|---|---|---|"]
    for k, v in out["F1d"]["playoff_by_pred_tercile"].items():
        lq = out["F1d"]["late_qual_by_pred_tercile"].get(k, {})
        s, t = k.split("|")
        L.append(f"| {s} | {t} | {f(v['mean_resid'])} (n {v['n']}) | {f(lq.get('mean_resid'))} (n {lq.get('n')}) |")
    L += ["\n## F1e round and appearance order\n", "| Season | Group | n | Mean resid |", "|---|---|---|---|"]
    for k, v in out["F1e"].items():
        s, g = k.split("|")
        L.append(f"| {s} | {g} | {v['n']} | {f(v['mean_resid'])} |")
    L += ["\n## F1f mean residual by component (observed − AS1_joint)\n", "| Season | Auto | Teleop | Endgame | No-foul | Total |",
          "|---|---|---|---|---|---|"]
    for s, v in out["F1f"].items():
        L.append(f"| {s} | {f(v['auto'])} | {f(v['teleop'])} | {f(v['endgame'])} | {f(v['no_foul'])} | {f(v['total'])} |")
    L += ["\n## F2 correction candidates (held-out test events only)\n",
          "| Design | Train/test events | Form | Params | Test MAE (uncorr → corr) | MAE gain [95% CI] | Test bias | Cov80 (uncorr → corr) [gain CI] | Cov50/90/95 corr | Width80 |",
          "|---|---|---|---|---|---|---|---|---|---|"]
    for name, e in out["F2"].items():
        u = e["uncorrected"]
        for form, r in e["forms"].items():
            t = r["test"]
            params = ", ".join(f"{k}={v:.3f}" for k, v in r["params"].items())
            L.append(f"| {name} | {e['train_events']}/{e['test_events']} | {form} | {params} | {f(u['mae'])} → {f(t['mae'])} | "
                     f"{f(r['mae_gain'], 2)} [{f(r['mae_gain_ci'][0], 2)}, {f(r['mae_gain_ci'][1], 2)}] | {f(u['bias'])} → {f(t['bias'])} | "
                     f"{f(u['cov0.8'], 3)} → {f(t['cov0.8'], 3)} [{f(r['cov80_gain_ci'][0], 3)}, {f(r['cov80_gain_ci'][1], 3)}] | "
                     f"{f(t['cov0.5'], 3)}/{f(t['cov0.9'], 3)}/{f(t['cov0.95'], 3)} | {f(u['width80'])} → {f(t['width80'])} |")
    path.write_text("\n".join(L) + "\n")


if __name__ == "__main__":
    sys.exit(main())
