"""Read-only diagnostic of the D18 M07 failure (D16 gate on frame ab1adbf3).

    python .agent/phase4/results/d18/m07_diagnostics.py FRAME_DIR SNAPSHOT_DIR OUT_JSON

Refits the D18 M7 model exactly as scripts/run_phase4_stratai.run_m07 does
(deterministic) and first checks that it reproduces the recorded D18 result
bit-for-bit. It then analyses those same predictions. It changes no model,
calibrator, bin, threshold or gate. It is not an acceptance input: the
recorded D18 M07 result stands as recorded.

Sections: reproduction; practical magnitude (per-bin deviations with
Clopper-Pearson intervals, an ECE noise floor under perfect calibration,
an event-cluster bootstrap, finer and equal-mass bins, favourite-perspective
reliability, calibrator plateaus); localisation (comp level, week, event
type, EPA-source season, month); the raw M6 shift; a cross-season
diagnostic fold (2024 -> 2025); and use-case impact (expected qualification
wins per team, playoff series).
"""

from __future__ import annotations

import gzip
import json
import sys
from collections import defaultdict
from pathlib import Path

import numpy as np
from scipy.stats import beta

sys.path.insert(0, str(Path(__file__).resolve().parents[4]))

from ml.backtest.harness import _match_features, hold_out_season_split  # noqa: E402
from ml.backtest.metrics import brier_score, expected_calibration_error, log_loss  # noqa: E402
from ml.calibration.calibrator import SymmetricIsotonicCalibrator, fit_calibrated_win_prob_model  # noqa: E402
from ml.calibration.gate import evaluate_calibration_gate  # noqa: E402
from ml.dataset.builder import LABEL_RED_WIN, LABEL_TIE  # noqa: E402
from ml.models.win_prob import WinProbXGBModel  # noqa: E402
from scripts.run_m4_baseline_backtest import _split_epa_complete  # noqa: E402
from scripts.run_phase4_stratai import _folds, load_frame_rows  # noqa: E402

RECORD = Path(".agent/phase4/results/d18/m07_result.json")
SEED = 20261002


def cp_interval(k: int, n: int) -> list[float]:
    lo = 0.0 if k == 0 else float(beta.ppf(0.025, k, n - k + 1))
    hi = 1.0 if k == n else float(beta.ppf(0.975, k + 1, n - k))
    return [round(lo, 4), round(hi, 4)]


def bins(q: np.ndarray, y: np.ndarray, edges: np.ndarray) -> list[dict]:
    index = np.clip(np.searchsorted(edges, q, side="right") - 1, 0, len(edges) - 2)
    out = []
    for b in range(len(edges) - 1):
        mask = index == b
        n = int(mask.sum())
        if n == 0:
            out.append({"lower": round(float(edges[b]), 4), "upper": round(float(edges[b + 1]), 4), "n": 0})
            continue
        k = int(y[mask].sum())
        out.append({"lower": round(float(edges[b]), 4), "upper": round(float(edges[b + 1]), 4), "n": n,
                    "mean_q": round(float(q[mask].mean()), 4), "observed": round(k / n, 4),
                    "observed_minus_predicted": round(k / n - float(q[mask].mean()), 4),
                    "observed_95ci": cp_interval(k, n)})
    return out


def _ece(q, y, edges):
    index = np.clip(np.searchsorted(edges, q, side="right") - 1, 0, len(edges) - 2)
    total = 0.0
    for b in range(len(edges) - 1):
        mask = index == b
        if mask.any():
            total += mask.sum() * abs(y[mask].mean() - q[mask].mean())
    return float(total / len(q))


def ece_equal_mass(q, y, n_bins=10):
    order = np.argsort(q, kind="stable")
    total = 0.0
    for chunk in np.array_split(order, n_bins):
        total += len(chunk) * abs(y[chunk].mean() - q[chunk].mean())
    return float(total / len(q))


def summary(q, y, label=""):
    if len(q) == 0:
        return {"n": 0}
    gate = evaluate_calibration_gate(list(q), list(y.astype(bool)), symmetry_errors=[0.0] * len(q),
                                     order_independent=True, fit_isolated=True).to_dict()
    g2 = gate["g2"]
    return {"n": int(len(q)), "red_win_rate": round(float(y.mean()), 4), "mean_q": round(float(q.mean()), 4),
            "observed_minus_predicted": round(float(y.mean() - q.mean()), 4),
            "ece": round(_ece(q, y, np.linspace(0, 1, 11)), 4),
            "log_loss": round(float(log_loss(list(q), list(y.astype(bool)))), 4),
            "brier": round(float(brier_score(list(q), list(y.astype(bool)))), 4),
            "g2_status": g2["status"], "g2_eligible_bins": g2["eligible_bins"], "g2_rejected_bins": g2["rejected_bins"],
            "bins": bins(q, y, np.linspace(0, 1, 11))}


def brier_decomposition(q, y, edges):
    index = np.clip(np.searchsorted(edges, q, side="right") - 1, 0, len(edges) - 2)
    base = y.mean()
    rel = res = 0.0
    for b in range(len(edges) - 1):
        mask = index == b
        if mask.any():
            rel += mask.sum() * (q[mask].mean() - y[mask].mean()) ** 2
            res += mask.sum() * (y[mask].mean() - base) ** 2
    n = len(q)
    return {"reliability": round(rel / n, 5), "resolution": round(res / n, 5),
            "uncertainty": round(float(base * (1 - base)), 5)}


def by_comp_level(rows, q, y):
    out = {}
    for level in ("qualification", "playoff"):
        idx = np.asarray([i for i, r in enumerate(rows) if (r.comp_level == "qualification") == (level == "qualification")])
        out[level] = summary(q[idx], y[idx]) if len(idx) else {"n": 0}
    return out


def predict(model, calibrator, rows):
    raw, q, y = [], [], []
    for row in rows:
        p = model.predict_win_prob(_match_features(row))
        raw.append(p)
        q.append(calibrator.calibrate(p))
        y.append(row.label == LABEL_RED_WIN)
    return np.asarray(raw), np.asarray(q), np.asarray(y, dtype=float)


def event_meta(snapshot: Path) -> dict[str, dict]:
    meta = {}
    for f in (snapshot / "raw").glob("*.json.gz"):
        for r in json.loads(gzip.decompress(f.read_bytes())):
            meta[r["event"]] = {"type": r["type"], "week": r["week"], "status": r["status"]}
    return meta


def main(frame_dir: Path, snapshot: Path, out: Path) -> None:
    rows = load_frame_rows(frame_dir)
    _, epa_fold, _, _ = _folds(rows)
    model, calibrator, diag = fit_calibrated_win_prob_model(
        WinProbXGBModel, epa_fold.train_rows, calibrator_factory=SymmetricIsotonicCalibrator)
    evaluated = [r for r in epa_fold.test_rows if r.label != LABEL_TIE]
    raw, q, y = predict(model, calibrator, evaluated)
    record = json.loads(RECORD.read_text(encoding="utf-8"))
    gate_now = evaluate_calibration_gate(q.tolist(), [bool(v) for v in y], symmetry_errors=[0.0] * len(q),
                                         order_independent=True, fit_isolated=True).to_dict()
    recorded_bins = [(b["count"], b.get("observed_wins")) for b in record["gate"]["g2"]["bins"]]
    reproduced = {
        "ece_recorded": record["calibrated"]["ece"], "ece_now_gate_path": gate_now["ece"],
        "rows_recorded": record["held_out_rows"], "rows_now": len(q),
        "fit_diagnostics_equal": diag == record["fit_diagnostics"],
        "g2_bin_counts_and_wins_equal": recorded_bins == [(b["count"], b.get("observed_wins")) for b in gate_now["g2"]["bins"]],
        "g2_p_values_equal": [b["p_value"] for b in record["gate"]["g2"]["bins"]] == [b["p_value"] for b in gate_now["g2"]["bins"]],
    }
    reproduced["identical"] = (reproduced["ece_recorded"] == reproduced["ece_now_gate_path"] and
                               reproduced["rows_recorded"] == reproduced["rows_now"] and reproduced["fit_diagnostics_equal"]
                               and reproduced["g2_bin_counts_and_wins_equal"] and reproduced["g2_p_values_equal"])
    if not reproduced["identical"]:
        raise SystemExit(f"does not reproduce the recorded D18 M7 run: {reproduced}")

    rng = np.random.default_rng(SEED)
    result: dict = {"reproduction": reproduced}

    # --- practical magnitude ---------------------------------------------------------
    sims = np.array([_ece(q, (rng.random(len(q)) < q).astype(float), np.linspace(0, 1, 11)) for _ in range(2000)])
    events = np.array([r.event_key for r in evaluated])
    unique_events = np.unique(events)
    by_event = {e: np.flatnonzero(events == e) for e in unique_events}
    boot = []
    for _ in range(1000):
        idx = np.concatenate([by_event[e] for e in rng.choice(unique_events, len(unique_events))])
        boot.append(_ece(q[idx], y[idx], np.linspace(0, 1, 11)))
    fav_q = np.maximum(q, 1 - q)
    fav_y = np.where(q >= 0.5, y, 1 - y)
    values, counts = np.unique(np.round(q, 6), return_counts=True)
    top = np.argsort(-counts)[:12]
    result["magnitude"] = {
        "overall": summary(q, y),
        "ece_10_equal_width": round(_ece(q, y, np.linspace(0, 1, 11)), 4),
        "ece_20_equal_width": round(_ece(q, y, np.linspace(0, 1, 21)), 4),
        "ece_10_equal_mass": round(ece_equal_mass(q, y, 10), 4),
        "ece_noise_floor_perfect_calibration": {"mean": round(float(sims.mean()), 4),
                                                "p95": round(float(np.quantile(sims, 0.95)), 4),
                                                "p99": round(float(np.quantile(sims, 0.99)), 4)},
        "ece_event_bootstrap_95ci": [round(float(np.quantile(boot, 0.025)), 4), round(float(np.quantile(boot, 0.975)), 4)],
        "reliability_20_bins": bins(q, y, np.linspace(0, 1, 21)),
        "favourite_perspective": {"mean_favourite_q": round(float(fav_q.mean()), 4),
                                  "favourite_win_rate": round(float(fav_y.mean()), 4),
                                  "bins": bins(fav_q, fav_y, np.linspace(0.5, 1, 6))},
        "brier_decomposition_10_bins": brier_decomposition(q, y, np.linspace(0, 1, 11)),
        "calibrator_plateaus": [{"q": float(values[i]), "n": int(counts[i]),
                                 "observed": round(float(y[np.round(q, 6) == values[i]].mean()), 4)} for i in top],
        "distinct_q_values": int(len(values)),
    }

    # --- localisation ------------------------------------------------------------------
    meta = event_meta(snapshot)
    groups: dict[str, dict[str, list[int]]] = defaultdict(lambda: defaultdict(list))
    for i, r in enumerate(evaluated):
        groups["comp_level"]["qualification" if r.comp_level == "qualification" else "playoff"].append(i)
        m = meta.get(r.event_key, {"type": "no_statbotics_record", "week": None})
        groups["event_type"][m["type"]].append(i)
        groups["statbotics_week"][str(m["week"])].append(i)
        groups["month"][r.scheduled_time.strftime("%Y-%m")].append(i)
        prior = sum(1 for t in (*r.red_teams, *r.blue_teams)
                    if t.epa_source_event_key is not None and t.epa_source_event_key[:4] != str(r.season))
        groups["teams_with_prior_season_epa"]["0" if prior == 0 else ("1-3" if prior <= 3 else "4-6")].append(i)
        groups["value_source"]["any_stratai_fallback" if any(
            t.epa_value_source == "stratai_fallback" for t in (*r.red_teams, *r.blue_teams)) else "statbotics_only"].append(i)
        groups["comp_level_x_favourite"][("qual" if r.comp_level == "qualification" else "playoff")
                                          + ("_red_favoured" if q[i] >= 0.5 else "_blue_favoured")].append(i)
    result["localisation"] = {
        name: {key: {k: v for k, v in summary(q[idx], y[idx]).items() if name != "month" or k != "bins"}
               for key, idx in sorted(members.items()) for idx in [np.asarray(idx)]}
        for name, members in groups.items()
    }

    # --- playoff seeding: the higher seed (its best member's final qualification rank is
    # better; seed k's captain is the best-ranked team not on alliances 1..k-1) ---------------
    from scripts.run_phase4_stratai import _final_ranks

    ranks = _final_ranks(2026)
    hs_q, hs_y, hs_red = [], [], []
    for i, r in enumerate(evaluated):
        if r.comp_level == "qualification" or r.event_key not in ranks:
            continue
        rk = ranks[r.event_key]
        red = min((rk.get(t.team_number, 10**6) for t in r.red_teams), default=10**6)
        blue = min((rk.get(t.team_number, 10**6) for t in r.blue_teams), default=10**6)
        if red == blue or 10**6 in (red, blue):
            continue
        red_higher = red < blue
        hs_q.append(q[i] if red_higher else 1 - q[i])
        hs_y.append(y[i] if red_higher else 1 - y[i])
        hs_red.append(red_higher)
    hs_q, hs_y, hs_red = np.asarray(hs_q), np.asarray(hs_y), np.asarray(hs_red)
    result["playoff_higher_seed_perspective"] = {
        "all": summary(hs_q, hs_y), "higher_seed_is_red": summary(hs_q[hs_red], hs_y[hs_red]),
        "higher_seed_is_blue": summary(hs_q[~hs_red], hs_y[~hs_red]),
    }
    for level in ("qualification", "playoff"):
        idx = np.asarray([i for i, r in enumerate(evaluated) if (r.comp_level == "qualification") == (level == "qualification")])
        result["magnitude"][f"favourite_perspective_{level}"] = summary(fav_q[idx], fav_y[idx])

    # --- raw M6 shift: calibration slice (2025, in-sample for the calibrator) vs 2026 ---------
    sorted_train = sorted(epa_fold.train_rows, key=lambda r: r.scheduled_time)
    cal_rows = [r for r in sorted_train[len(sorted_train) - diag["calibration_row_count"]:] if r.label != LABEL_TIE]
    cal_raw, cal_q, cal_y = predict(model, calibrator, cal_rows)
    result["raw_m6_shift"] = {
        "calibration_slice": {"window": [cal_rows[0].scheduled_time.isoformat(), cal_rows[-1].scheduled_time.isoformat()],
                              "raw": summary(cal_raw, cal_y), "calibrated_in_sample": summary(cal_q, cal_y),
                              "calibrated_in_sample_by_comp_level": by_comp_level(cal_rows, cal_q, cal_y)},
        "held_out_2026_raw": summary(raw, y),
    }

    # --- cross-season diagnostic fold: 2024 -> 2025 (same pipeline; not a D7 split) ----------
    fold_2025 = hold_out_season_split([r for r in rows if r.season in (2024, 2025)], held_out_season=2025)
    epa_2025, _, _ = _split_epa_complete(fold_2025)
    m25, c25, d25 = fit_calibrated_win_prob_model(WinProbXGBModel, epa_2025.train_rows,
                                                  calibrator_factory=SymmetricIsotonicCalibrator)
    eval25 = [r for r in epa_2025.test_rows if r.label != LABEL_TIE]
    raw25, q25, y25 = predict(m25, c25, eval25)
    result["cross_season_fold_2024_to_2025"] = {"fit": d25, "raw": summary(raw25, y25), "calibrated": summary(q25, y25),
                                                "calibrated_by_comp_level": by_comp_level(eval25, q25, y25)}
    result["red_share_of_decided_matches"] = {
        f"{season}_{level}": round(float(np.mean([r.label == LABEL_RED_WIN for r in rows if r.season == season
                                                  and r.label != LABEL_TIE and
                                                  (r.comp_level == "qualification") == (level == "qualification")])), 4)
        for season in (2024, 2025, 2026) for level in ("qualification", "playoff")}

    # --- use-case impact ---------------------------------------------------------------
    expected, actual, played = defaultdict(float), defaultdict(float), defaultdict(int)
    for i, r in enumerate(evaluated):
        if r.comp_level != "qualification":
            continue
        for t in r.red_teams:
            expected[(r.event_key, t.team_number)] += q[i]
            actual[(r.event_key, t.team_number)] += y[i]
            played[(r.event_key, t.team_number)] += 1
        for t in r.blue_teams:
            expected[(r.event_key, t.team_number)] += 1 - q[i]
            actual[(r.event_key, t.team_number)] += 1 - y[i]
            played[(r.event_key, t.team_number)] += 1
    keys = sorted(expected)
    e_arr = np.array([expected[k] for k in keys])
    a_arr = np.array([actual[k] for k in keys])
    n_arr = np.array([played[k] for k in keys])
    qual_idx = np.flatnonzero([r.comp_level == "qualification" for r in evaluated])
    sim_abs = []
    for _ in range(500):
        draw = (rng.random(len(q)) < q).astype(float)
        sim_a = defaultdict(float)
        for i in qual_idx:
            r = evaluated[i]
            for t in r.red_teams:
                sim_a[(r.event_key, t.team_number)] += draw[i]
            for t in r.blue_teams:
                sim_a[(r.event_key, t.team_number)] += 1 - draw[i]
        sim_abs.append(np.mean(np.abs(np.array([sim_a[k] for k in keys]) - e_arr)))
    strong = e_arr / n_arr >= 0.6
    weak = e_arr / n_arr <= 0.4
    playoff = np.flatnonzero([r.comp_level != "qualification" for r in evaluated])

    def series(p):  # best of three
        return p * p * (3 - 2 * p)

    shift = float(y[playoff].mean() - q[playoff].mean())
    result["use_case_impact"] = {
        "qualification_expected_wins_per_team_event": {
            "team_events": len(keys), "mean_matches_in_population": round(float(n_arr.mean()), 2),
            "mean_actual_minus_expected": round(float((a_arr - e_arr).mean()), 4),
            "mean_abs_actual_minus_expected": round(float(np.abs(a_arr - e_arr).mean()), 4),
            "mean_abs_under_perfect_calibration": round(float(np.mean(sim_abs)), 4),
            "predicted_strong_teams_actual_minus_expected": round(float((a_arr - e_arr)[strong].mean()), 4),
            "predicted_weak_teams_actual_minus_expected": round(float((a_arr - e_arr)[weak].mean()), 4),
        },
        "playoff": {"matches": int(len(playoff)), "red_win_rate": round(float(y[playoff].mean()), 4),
                    "mean_q_red": round(float(q[playoff].mean()), 4), "red_underestimate": round(shift, 4),
                    "best_of_3_red_series_if_match_q_0.60": round(series(0.60), 4),
                    "best_of_3_red_series_if_match_q_0.60_plus_shift": round(series(min(0.60 + shift, 1)), 4)},
    }
    out.write_text(json.dumps(result, indent=1, default=str) + "\n", encoding="utf-8")
    print(json.dumps({"reproduction": reproduced, "ece_noise_floor": result["magnitude"]["ece_noise_floor_perfect_calibration"],
                      "ece_bootstrap": result["magnitude"]["ece_event_bootstrap_95ci"]}, indent=1))


if __name__ == "__main__":
    main(Path(sys.argv[1]), Path(sys.argv[2]), Path(sys.argv[3]))
