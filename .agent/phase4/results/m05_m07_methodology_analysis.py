"""Evidence for the M5/M7 methodology escalation (read-only; changes no methodology).

Run from the repository root:
    python .agent/phase4/results/m05_m07_methodology_analysis.py FRAME_DIR CHAIN_JSON OUT_JSON

Results are written to OUT_JSON after every section (atomically); a rerun skips
sections already present, so an interruption loses at most one section.

Discipline: nothing here is an acceptance gate and no methodology is changed.
M5 sections evaluate only on 2024/2025 (training seasons); 2026 appears only as
feature/target distributions. The M7 sections use the frozen M4 win-probability
baseline's own held-out predictions, rebuilt exactly and checked against the
frozen M4 metrics, to study the M7 band definition itself.
"""

from __future__ import annotations

import json
import math
import os
import random
import statistics
import sys
import time
from collections import defaultdict
from pathlib import Path

import numpy as np
import xgboost as xgb
from scipy.stats import ks_2samp, norm

sys.path.insert(0, ".")
from data.config import Settings  # noqa: E402
from data.rankings import read_final_ranks_for_season  # noqa: E402
from database.connection import DatabaseConfig  # noqa: E402
from database.readonly import ReadOnlySessionDatabase  # noqa: E402
from ml.backtest.harness import _match_features, _team_features_by_event, hold_out_season_split  # noqa: E402
from ml.backtest.metrics import (  # noqa: E402
    accuracy,
    brier_score,
    expected_calibration_error,
    log_loss,
    roc_auc,
    spearman_correlation,
)
from ml.calibration.calibrator import DEFAULT_MIN_BIN_COUNT, check_calibration_band, compute_reliability_bins  # noqa: E402
from ml.dataset.builder import LABEL_RED_WIN, LABEL_TIE  # noqa: E402
from ml.models import ranking_xgb as rx  # noqa: E402
from ml.models.baselines import EpaWinProbBaseline  # noqa: E402
from ml.models.team_vector import TEAM_FEATURE_NAMES, team_features_to_vector  # noqa: E402
from scripts.run_phase4_stratai import _folds, load_frame_rows  # noqa: E402

SEASONS = (2024, 2025, 2026)
BAND_TARGET, BAND_TOLERANCE = 0.60, 0.02  # check_calibration_band's defaults as M7 calls them
CONFIRMATION_TRIALS = 100
N_BINS = 10


# --- persistence -------------------------------------------------------------------


class Checkpoint:
    def __init__(self, path: Path) -> None:
        self.path = path
        self.state = json.loads(path.read_text()) if path.exists() else {"sections": {}}

    def run(self, name: str, fn) -> dict:
        if name in self.state["sections"]:
            print(f"[skip] {name} (already saved)")
            return self.state["sections"][name]
        started = time.time()
        result = fn()
        result["_seconds"] = round(time.time() - started, 1)
        self.state["sections"][name] = result
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(self.state, indent=2, default=str))
        os.replace(tmp, self.path)
        print(f"[saved] {name} in {result['_seconds']}s")
        return result


# --- vectorized descriptive helpers --------------------------------------------------


def describe(values: np.ndarray) -> dict:
    if values.size == 0:
        return {"n": 0}
    p10, p50, p90 = np.percentile(values, [10, 50, 90])
    return {"n": int(values.size), "mean": round(float(values.mean()), 3), "sd": round(float(values.std()), 3),
            "p10": round(float(p10), 3), "p50": round(float(p50), 3), "p90": round(float(p90), 3),
            "max": round(float(values.max()), 3)}


def shift(train: np.ndarray, test: np.ndarray) -> dict:
    if train.size == 0 or test.size == 0:
        return {}
    train_max = float(train.max())  # once, not per test value (the original script's bug)
    train_median = float(np.median(train))
    return {"ks_statistic": round(float(ks_2samp(train, test).statistic), 3),
            "median_ratio_test_over_train": round(float(np.median(test)) / train_median, 3) if train_median else None,
            "share_test_above_train_max": round(float((test > train_max).mean()), 4)}


# --- shared inputs (loaded once per process) ------------------------------------------


class Inputs:
    def __init__(self, frame_dir: Path, chain_path: Path) -> None:
        self.frame_dir, self.chain_path = frame_dir, chain_path
        self._rows = None
        self._arrays = None
        self._database = None

    @property
    def rows(self):
        if self._rows is None:
            started = time.time()
            self._rows = load_frame_rows(self.frame_dir)
            print(f"loaded {len(self._rows)} frame rows in {time.time() - started:.0f}s")
        return self._rows

    @property
    def database(self):
        if self._database is None:
            self._database = ReadOnlySessionDatabase(DatabaseConfig(Settings().database_url))
        return self._database

    def by_season(self) -> dict[int, list]:
        out: dict[int, list] = defaultdict(list)
        for r in self.rows:
            out[r.season].append(r)
        return out

    def arrays(self) -> dict:
        """Per season: the feature matrix of every team appearance, and its target."""
        if self._arrays is None:
            matrices, targets = {}, {}
            for s, rows in self.by_season().items():
                vecs, ts = [], []
                for r in rows:
                    red_t, blue_t = rx._row_targets(r)
                    for team in r.red_teams:
                        vecs.append(team_features_to_vector(team))
                        ts.append(red_t)
                    for team in r.blue_teams:
                        vecs.append(team_features_to_vector(team))
                        ts.append(blue_t)
                matrices[s], targets[s] = np.vstack(vecs), np.asarray(ts)
            self._arrays = {"X": matrices, "y": targets}
        return self._arrays

    def feature(self, season: int, name: str) -> np.ndarray:
        column = self.arrays()["X"][season][:, TEAM_FEATURE_NAMES.index(name)]
        return column[~np.isnan(column)]

    def season_scale(self) -> dict:
        chain = json.loads(self.chain_path.read_text())
        out = {}
        for entry in chain["chain"]:
            report = json.loads((self.chain_path.parent / entry["directory"] / "execution_report.json").read_text())
            stats = report["year_stats"]
            out[entry["season"]] = {k: stats[k] for k in ("score_mean", "score_sd", "no_foul_mean", "week_one_matches")}
            out[entry["season"]]["week_one_complete_time"] = report["availability"]["week_one_complete_time"]
        return out


# --- M5 sections -----------------------------------------------------------------------


def section_distributions(inp: Inputs) -> dict:
    X, y = inp.arrays()["X"], inp.arrays()["y"]
    features = {}
    for i, name in enumerate(TEAM_FEATURE_NAMES):
        features[name] = {str(s): {**describe(inp.feature(s, name)),
                                   "present_share": round(float((~np.isnan(X[s][:, i])).mean()), 4)} for s in SEASONS}
    scores = {s: np.asarray([v for r in rows for v in (r.score_red, r.score_blue)], dtype=float)
              for s, rows in inp.by_season().items()}
    return {"season_scale_week_one": inp.season_scale(), "features": features,
            "target": {str(s): {**describe(y[s]), "abs_mean": round(float(np.abs(y[s]).mean()), 3)} for s in SEASONS},
            "alliance_score": {str(s): describe(scores[s]) for s in SEASONS}}


def section_shift(inp: Inputs) -> dict:
    y = inp.arrays()["y"]
    out = {}
    for name in TEAM_FEATURE_NAMES:
        train = np.concatenate([inp.feature(2024, name), inp.feature(2025, name)])
        out[name] = {"train_vs_2026": shift(train, inp.feature(2026, name)),
                     "2024_vs_2025": shift(inp.feature(2024, name), inp.feature(2025, name))}
    out["target"] = {"train_vs_2026": shift(np.concatenate([y[2024], y[2025]]), y[2026]),
                     "2024_vs_2025": shift(y[2024], y[2025])}
    return out


def section_candidates(inp: Inputs) -> dict:
    scale = inp.season_scale()
    by_season = inp.by_season()
    y = inp.arrays()["y"]
    out = {}
    for name in ("epa_total", "average_score", "average_auto_points"):
        raw = {s: inp.feature(s, name) for s in SEASONS}
        own = {s: raw[s] / scale[s]["score_sd"] for s in SEASONS}
        prior = {s: raw[s] / scale[s - 1]["score_sd"] for s in (2025, 2026)}
        out[name] = {
            "raw": shift(np.concatenate([raw[2024], raw[2025]]), raw[2026]),
            "divided_by_own_season_week_one_score_sd": shift(np.concatenate([own[2024], own[2025]]), own[2026]),
            "divided_by_prior_season_week_one_score_sd (train = 2025 only; 2024 has no prior)":
                shift(prior[2025], prior[2026]),
        }

    def event_percentiles(season: int, name: str) -> np.ndarray:
        values = []
        for teams in _team_features_by_event(by_season[season]).values():
            vals = np.asarray([getattr(tf, name) for tf in teams.values() if getattr(tf, f"{name}_present")], float)
            if vals.size < 2:
                continue
            ranks = vals.argsort().argsort()
            values.append(ranks / (vals.size - 1))
        return np.concatenate(values) if values else np.empty(0)

    for name in ("epa_total", "average_score"):
        p = {s: event_percentiles(s, name) for s in SEASONS}
        out[name]["event_percentile"] = shift(np.concatenate([p[2024], p[2025]]), p[2026])
    t = {s: y[s] / scale[s]["score_sd"] for s in SEASONS}
    out["target"] = {"raw": shift(np.concatenate([y[2024], y[2025]]), y[2026]),
                     "divided_by_own_season_week_one_score_sd": shift(np.concatenate([t[2024], t[2025]]), t[2026])}
    return out


def section_early_stopping(inp: Inputs) -> dict:
    fold = hold_out_season_split(inp.rows, held_out_season=2026)
    ordered = sorted(fold.train_rows, key=lambda r: r.scheduled_time)
    split = rx._validation_split_index(len(ordered), rx._DEFAULT_VALIDATION_FRACTION)
    fit_rows, val_rows = ordered[:split], ordered[split:]
    X_fit, y_fit = rx._rows_to_matrix(fit_rows)
    X_val, y_val = rx._rows_to_matrix(val_rows)
    params = {"objective": "reg:squarederror", "seed": 42, "max_depth": 6, "eta": 0.1, "subsample": 1.0,
              "colsample_bytree": 1.0, "nthread": 1}  # exactly RankingXGBModel.fit's parameters
    names = list(TEAM_FEATURE_NAMES)
    d_fit = xgb.DMatrix(X_fit, label=y_fit, feature_names=names, missing=np.nan)
    d_val = xgb.DMatrix(X_val, label=y_val, feature_names=names, missing=np.nan)
    curve: dict = {}
    booster = xgb.train(params, d_fit, num_boost_round=100, evals=[(d_fit, "fit"), (d_val, "validation")],
                        evals_result=curve, verbose_eval=False)
    ranks_2025 = read_final_ranks_for_season(inp.database, 2025)
    val_events = _team_features_by_event(val_rows)

    def event_spearman(score) -> float | None:
        values = []
        for event, teams in val_events.items():
            actual = ranks_2025.get(event)
            numbers = [t for t in teams if actual and t in actual]
            if len(numbers) < 2:
                continue
            rho = spearman_correlation(score(teams, numbers), [-actual[t] for t in numbers])
            if rho is not None:
                values.append(rho)
        return round(statistics.mean(values), 4) if values else None

    def model_score(rounds):
        def score(teams, numbers):
            m = np.vstack([team_features_to_vector(teams[t]) for t in numbers])
            return list(map(float, booster.predict(xgb.DMatrix(m, feature_names=names, missing=np.nan),
                                                   iteration_range=(0, rounds))))
        return score

    def raw_epa(teams, numbers):
        return [teams[t].epa_total if teams[t].epa_total_present else float("-inf") for t in numbers]

    fit_seasons = np.asarray([r.season for r in fit_rows for _ in (*r.red_teams, *r.blue_teams)])
    return {
        "fit_rows": len(fit_rows), "validation_rows": len(val_rows),
        "fit_period": [str(fit_rows[0].scheduled_time), str(fit_rows[-1].scheduled_time)],
        "validation_period": [str(val_rows[0].scheduled_time), str(val_rows[-1].scheduled_time)],
        "fit_target": describe(y_fit), "validation_target": describe(y_val),
        "fit_target_by_season": {str(s): describe(y_fit[fit_seasons == s]) for s in (2024, 2025)},
        "fit_rmse_by_round": [round(v, 3) for v in curve["fit"]["rmse"][:30]],
        "validation_rmse_by_round": [round(v, 3) for v in curve["validation"]["rmse"][:30]],
        "best_round_index_by_validation_rmse": int(np.argmin(curve["validation"]["rmse"])),
        "validation_rmse_constant_prediction": round(float(np.sqrt(np.mean((y_val - y_fit.mean()) ** 2))), 3),
        "validation_event_spearman_by_rounds": {str(k): event_spearman(model_score(k)) for k in (1, 3, 5, 10, 20, 50, 100)},
        "validation_event_spearman_raw_epa": event_spearman(raw_epa),
        "validation_events_with_ranks": sum(1 for e in val_events if e in ranks_2025),
    }


def section_snapshot_timing(inp: Inputs) -> dict:
    out = {}
    by_season = inp.by_season()
    for s in (2024, 2025):
        ranks = read_final_ranks_for_season(inp.database, s)
        last_qual: dict[str, object] = {}
        latest: dict[str, dict[int, tuple]] = {}
        for r in by_season[s]:
            if r.comp_level == "qualification":
                last_qual[r.event_key] = max(last_qual.get(r.event_key, r.scheduled_time), r.scheduled_time)
            for tf in (*r.red_teams, *r.blue_teams):
                prev = latest.setdefault(r.event_key, {}).get(tf.team_number)
                if prev is None or r.scheduled_time > prev[0]:
                    latest[r.event_key][tf.team_number] = (r.scheduled_time, tf)
        after = total = 0
        rho_avg, rho_epa = [], []
        for event, teams in latest.items():
            for when, _ in teams.values():
                total += 1
                after += int(event in last_qual and when > last_qual[event])
            actual = ranks.get(event)
            numbers = [t for t in teams if actual and t in actual]
            if len(numbers) < 2:
                continue
            truth = [-actual[t] for t in numbers]
            a = spearman_correlation([teams[t][1].average_score if teams[t][1].average_score_present else float("-inf")
                                      for t in numbers], truth)
            e = spearman_correlation([teams[t][1].epa_total if teams[t][1].epa_total_present else float("-inf")
                                      for t in numbers], truth)
            if a is not None:
                rho_avg.append(a)
            if e is not None:
                rho_epa.append(e)
        out[str(s)] = {"team_event_snapshots": total, "snapshot_after_last_qualification_match": after,
                       "share_after_quals": round(after / total, 4), "events": len(rho_avg),
                       "event_spearman_in_event_average_score_vs_final_rank": round(statistics.mean(rho_avg), 4),
                       "event_spearman_prior_event_epa_vs_final_rank": round(statistics.mean(rho_epa), 4)}
    return out


# --- M7 sections -----------------------------------------------------------------------


def m4_held_out_predictions(inp: Inputs) -> tuple[np.ndarray, np.ndarray]:
    """The frozen M4 win-prob baseline's held-out predictions, rebuilt exactly as
    run_win_prob_backtest produces them (EPA-complete fold, ties excluded)."""
    _, epa_fold, _, _ = _folds(inp.rows)
    model = EpaWinProbBaseline()
    model.fit(epa_fold.train_rows)
    p, y = [], []
    for row in epa_fold.test_rows:
        if row.label == LABEL_TIE:
            continue
        p.append(model.predict_win_prob(_match_features(row)))
        y.append(row.label == LABEL_RED_WIN)
    return np.asarray(p), np.asarray(y)


def poisson_binomial_pmf(p: np.ndarray) -> np.ndarray:
    """Exact distribution of the number of wins when win i has probability p[i]."""
    pmf = np.zeros(p.size + 1)
    pmf[0] = 1.0
    for i, q in enumerate(p, start=1):
        pmf[1:i + 1] = pmf[1:i + 1] * (1 - q) + pmf[0:i] * q
        pmf[0] *= 1 - q
    return pmf


def band_pass_probability(pmf: np.ndarray, n: int, low: float, high: float) -> float:
    rates = np.arange(n + 1) / n
    return float(pmf[(rates >= low) & (rates <= high)].sum())  # inclusive, as check_calibration_band compares


def section_m7_analytic(inp: Inputs, frozen_m04: dict) -> dict:
    p, y = m4_held_out_predictions(inp)
    preds, labels = p.tolist(), y.tolist()
    frozen = frozen_m04["result"]["win_prob"]["aggregate"]
    reproduced = {"row_count": len(preds), "accuracy": accuracy(preds, labels), "log_loss": log_loss(preds, labels),
                  "brier_score": brier_score(preds, labels), "roc_auc": roc_auc(preds, labels),
                  "calibration_error": expected_calibration_error(preds, labels)}
    matches_frozen = all(reproduced[k] == frozen[k] for k in reproduced)

    index = np.minimum((p * N_BINS).astype(int), N_BINS - 1)  # the binning rule both modules use
    bins = compute_reliability_bins(preds, labels)
    band = check_calibration_band(bins, target=BAND_TARGET, tolerance=BAND_TOLERANCE)
    low, high = band.lower_bound, band.upper_bound
    total = p.size
    table = []
    for b in range(N_BINS):
        pb, yb = p[index == b], y[index == b]
        n = int(pb.size)
        if n == 0:
            table.append({"bin": [b / N_BINS, (b + 1) / N_BINS], "count": 0})
            continue
        var = float((pb * (1 - pb)).sum())
        pmf = poisson_binomial_pmf(pb)
        rates = np.arange(n + 1) / n
        m = float(pb.mean())
        table.append({
            "bin": [b / N_BINS, (b + 1) / N_BINS], "count": n, "mean_predicted": round(m, 5),
            "expected_wins_if_calibrated": round(float(pb.sum()), 2),
            "se_of_rate_if_calibrated": round(math.sqrt(var) / n, 5),
            "observed_wins": int(yb.sum()), "observed_rate": round(float(yb.mean()), 5),
            "ece_contribution_observed": round(n / total * abs(m - float(yb.mean())), 5),
            "expected_ece_contribution_if_calibrated": round(n / total * float((pmf * np.abs(rates - m)).sum()), 5),
        })

    target = next(t for t in table if t["bin"][0] <= BAND_TARGET < t["bin"][1])
    pb = p[index == int(BAND_TARGET * N_BINS)]
    n, m = int(pb.size), float(pb.mean())
    pmf = poisson_binomial_pmf(pb)
    se = target["se_of_rate_if_calibrated"]
    observed_ece = reproduced["calibration_error"]
    centred = p[(p >= 0.55) & (p < 0.65)]
    centred_pmf = poisson_binomial_pmf(centred)
    return {
        "reproduced_m4_metrics": reproduced, "matches_frozen_m04_exactly": matches_frozen,
        "band_rule": {"bin": [band.bin.lower, band.bin.upper], "required_rate": [low, high],
                      "min_bin_count": DEFAULT_MIN_BIN_COUNT,
                      "rule": "check_calibration_band: bin with lower <= 0.60 < upper; pass iff lower_bound <= rate <= upper_bound"},
        "target_bin": {
            "count": n, "mean_predicted": round(m, 5),
            "expected_wins_if_calibrated": target["expected_wins_if_calibrated"],
            "expected_rate_if_calibrated": round(m, 5), "se_of_rate_if_calibrated": se,
            "p_pass_exact_if_calibrated": round(band_pass_probability(pmf, n, low, high), 6),
            "p_pass_normal_approximation": round(float(norm.cdf((high - m) / se) - norm.cdf((low - m) / se)), 6),
            "z_of_upper_bound": round((high - m) / se, 3),
            "observed_wins": target["observed_wins"], "observed_rate": target["observed_rate"],
            "observed_band_check": band.within_band,
            "ece_contribution_observed": target["ece_contribution_observed"],
            "share_of_observed_ece": round(target["ece_contribution_observed"] / observed_ece, 4),
            "expected_ece_contribution_if_calibrated": target["expected_ece_contribution_if_calibrated"],
        },
        "bins": table,
        "expected_total_ece_if_calibrated": round(sum(t.get("expected_ece_contribution_if_calibrated", 0) for t in table), 5),
        "alternatives_analysis_only": {
            "same_bin_rate_within_0.02_of_its_own_mean_prediction":
                round(band_pass_probability(pmf, n, m - BAND_TOLERANCE, m + BAND_TOLERANCE), 6),
            "bin_centred_on_0.60_[0.55,0.65)": {
                "count": int(centred.size), "mean_predicted": round(float(centred.mean()), 5),
                "p_pass_0.58_0.62_if_calibrated": round(band_pass_probability(centred_pmf, centred.size, low, high), 6)},
        },
    }


def section_m7_confirmation(inp: Inputs) -> dict:
    """At most 100 trials: the actual M4 predictions held fixed, labels drawn so the
    predictions are perfectly calibrated by construction, scored by the real M7/D6 code."""
    p, _ = m4_held_out_predictions(inp)
    preds = p.tolist()
    rng = np.random.default_rng(20260930)
    passes, eces, rates, counts = 0, [], [], []
    for _ in range(CONFIRMATION_TRIALS):
        labels = (rng.random(p.size) < p).tolist()
        bins = compute_reliability_bins(preds, labels)
        band = check_calibration_band(bins, target=BAND_TARGET, tolerance=BAND_TOLERANCE)
        passes += int(bool(band.within_band))
        rates.append(band.bin.empirical_rate)
        counts.append(band.bin.count)
        eces.append(expected_calibration_error(preds, labels))
    r, e = np.asarray(rates), np.asarray(eces)
    return {"trials": CONFIRMATION_TRIALS, "seed": 20260930, "band_passes": passes,
            "band_pass_rate": passes / CONFIRMATION_TRIALS,
            "rule_of_three_95pct_upper_bound": round(3 / CONFIRMATION_TRIALS, 3) if passes == 0 else None,
            "target_bin_count": int(counts[0]),
            "target_bin_rate": {"mean": round(float(r.mean()), 5), "sd": round(float(r.std()), 5),
                                "min": round(float(r.min()), 5), "max": round(float(r.max()), 5)},
            "ece": {"mean": round(float(e.mean()), 5), "sd": round(float(e.std()), 5),
                    "p95": round(float(np.percentile(e, 95)), 5), "max": round(float(e.max()), 5),
                    "share_below_0.05": float((e < 0.05).mean())}}


def main(frame_dir: Path, chain_path: Path, out_path: Path) -> None:
    inp = Inputs(frame_dir, chain_path)
    checkpoint = Checkpoint(out_path)
    frozen_m04 = json.loads(Path(".agent/phase4/results/m04_result.json").read_text())
    checkpoint.run("m7_analytic", lambda: section_m7_analytic(inp, frozen_m04))
    checkpoint.run("m7_confirmation", lambda: section_m7_confirmation(inp))
    checkpoint.run("m5_distributions", lambda: section_distributions(inp))
    checkpoint.run("m5_shift", lambda: section_shift(inp))
    checkpoint.run("m5_candidate_normalizations", lambda: section_candidates(inp))
    checkpoint.run("m5_early_stopping", lambda: section_early_stopping(inp))
    checkpoint.run("m5_snapshot_timing", lambda: section_snapshot_timing(inp))
    print(f"all sections saved -> {out_path}")


if __name__ == "__main__":
    main(Path(sys.argv[1]), Path(sys.argv[2]), Path(sys.argv[3]))
