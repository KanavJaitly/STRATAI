"""DIAGNOSTIC ONLY: a forensic analysis of the P6-M10 gate failure. It is not an evaluation and not a fix.

    python -m scripts.phase6_m10_diagnostics     # DATABASE_URL = the isolated stratai_test copy (read-only)

**What it does not do:**
- It does not change the model, its parameters, the evaluation population, the gate or any record.
- It reads the registered `p6m10-v1` artifact, the D18 frame, the registered M6/M7 pair and the 2026 score
  breakdowns (read-only).
- It writes `.agent/phase6/diagnostics/p6_m10_diagnostics.json`, outside `results/`, so it is never confused with
  the authoritative failed run (`p6_m10_outcome_model.json`).

**Post-hoc 2026 fits.** Every quantity fitted on 2026 data here, such as a calibration slope or 2026 component
coefficients, is **descriptive evidence about the failure only**. None is a candidate model or a recalibration, and
none may be served.
"""

from __future__ import annotations

import json
import math
import random
import sys
import time
from collections import Counter, defaultdict
from pathlib import Path

import numpy as np

from scripts.phase6_common import (HELD_OUT_SEASON, P6_M10_VERSION_TAG, REGISTRY_DIR, isolated_database, load_frame,
                                   load_m6m7, provenance, read_record)

OUT = Path(".agent/phase6/diagnostics/p6_m10_diagnostics.json")
COLLAPSE_SAMPLE, COLLAPSE_SEED = 25, 20261012
BREAKDOWN_SQL = """
SELECT r.source_object_id, r.payload_json->'score_breakdown'
FROM raw_source_payloads r
WHERE r.source = 'tba' AND r.source_object_type = 'match' AND r.is_current AND r.source_object_id = ANY(%s)
"""
WEEK_SQL = """
SELECT DISTINCT ON (r.source_object_id) r.source_object_id, (r.payload_json->>'week')::int
FROM raw_source_payloads r
WHERE r.source = 'tba' AND r.source_object_type = 'event' AND r.is_current AND r.source_object_id = ANY(%s)
ORDER BY r.source_object_id, r.id DESC
"""


def _logit(p: float) -> float:
    p = min(max(p, 1e-12), 1 - 1e-12)
    return math.log(p / (1 - p))


def calibration_slope(p: list[float], y: list[bool]) -> dict[str, float]:
    """Logistic recalibration y ~ a + b·logit(p), by Newton–Raphson (diagnostic only). b > 1 means the predictions
    are under-confident."""
    x = np.array([_logit(v) for v in p])
    t = np.array(y, dtype=float)
    a = b = 0.0
    b = 1.0
    for _ in range(50):
        z = a + b * x
        q = 1 / (1 + np.exp(-z))
        w = q * (1 - q)
        g = np.array([np.sum(t - q), np.sum((t - q) * x)])
        h = np.array([[np.sum(w), np.sum(w * x)], [np.sum(w * x), np.sum(w * x * x)]])
        step = np.linalg.solve(h, g)
        a, b = a + step[0], b + step[1]
        if np.max(np.abs(step)) < 1e-12:
            break
    return {"intercept": float(a), "slope": float(b)}


def brier_decomposition(p: list[float], y: list[bool], bins: int = 10) -> dict[str, float]:
    """Murphy: Brier = reliability - resolution + uncertainty (10 fixed bins, as G1/G2 use)."""
    p_arr, y_arr = np.array(p), np.array(y, dtype=float)
    base = y_arr.mean()
    reliability = resolution = 0.0
    for k in range(bins):
        mask = np.minimum((p_arr * bins).astype(int), bins - 1) == k
        if mask.any():
            n_k = mask.sum()
            reliability += n_k * (p_arr[mask].mean() - y_arr[mask].mean()) ** 2
            resolution += n_k * (y_arr[mask].mean() - base) ** 2
    n = len(p)
    return {"reliability": reliability / n, "resolution": resolution / n, "uncertainty": base * (1 - base),
            "brier": float(np.mean((p_arr - y_arr) ** 2))}


def auc(p: list[float], y: list[bool]) -> float:
    from ml.backtest.metrics import roc_auc

    return roc_auc(p, y)


def group_summary(groups: dict[str, list[tuple[float, bool]]], min_n: int = 1) -> dict[str, dict]:
    from ml.backtest.metrics import expected_calibration_error

    out = {}
    for key, items in sorted(groups.items()):
        if len(items) < min_n:
            continue
        p = [i[0] for i in items]
        y = [i[1] for i in items]
        out[key] = {"n": len(items), "mean_predicted": float(np.mean(p)), "observed": float(np.mean(y)),
                    "ece": expected_calibration_error(p, y), "slope": calibration_slope(p, y)["slope"]
                    if len(items) >= 200 else None,
                    # signed mean (observed - predicted) on the favourite side: positive = under-confident
                    "favourite_gap": float(np.mean([(yy if pp >= 0.5 else 1 - yy) - (pp if pp >= 0.5 else 1 - pp)
                                                    for pp, yy in items]))}
    return out


def main() -> int:
    from ml.backtest.harness import _match_features
    from ml.backtest.metrics import log_loss
    from ml.calibration.gate import evaluate_calibration_gate, g2_bin_consistency
    from ml.dataset.builder import LABEL_RED_WIN, LABEL_TIE
    from ml.features.score_breakdown import ScoreBreakdownSchemaError, UnsupportedSeasonError
    from ml.features.score_components import score_components
    from ml.strategy.engine import candidate_strategies
    from ml.strategy.outcome import (MatchContext, alliance_means, load_registered_strategy_model,
                                     normalized_difference)
    from ml.strategy.representation import RobotPlan, Strategy

    started = time.time()
    fit = read_record("p6_m10_fit.json")
    record = read_record("p6_m10_outcome_model.json")
    model = load_registered_strategy_model(REGISTRY_DIR, version_tag=P6_M10_VERSION_TAG,
                                           expected_sha256=fit["registry"]["model_sha256"])
    m6m7 = load_m6m7()
    rows, frame_hash = load_frame()
    database = isolated_database()

    # --- the exact evaluated population (identical filters to scripts/phase6_m10_evaluate.py) ----------------
    population = []
    for row in rows:
        if row.season != HELD_OUT_SEASON or row.comp_level != "qualification":
            continue
        teams = [*row.red_teams, *row.blue_teams]
        if len(teams) != 6 or not all(t.epa_total_present for t in teams) or row.label == LABEL_TIE:
            continue
        context = MatchContext(tuple(row.red_teams), tuple(row.blue_teams))
        e = model.evaluate(context, Strategy.baseline([t.team_number for t in row.red_teams]),
                           Strategy.baseline([t.team_number for t in row.blue_teams]))
        if e.p_red is None:
            continue
        population.append((row, e))
    p = [e.p_red for _, e in population]
    y = [row.label == LABEL_RED_WIN for row, _ in population]
    q = [m6m7.predict_win_prob(_match_features(row)) for row, _ in population]
    g2_now = g2_bin_consistency(p, y)
    recorded_bins = [(b["count"], b.get("rejected")) for b in record["gate"]["g2"]["bins"]]
    reproduced = [(b.count, b.rejected) for b in g2_now.bins] == recorded_bins and len(p) == record["population"]["evaluated"]

    # --- 1-2 / 6-7: calibration shape and the comparison on the same rows ----------------------------------------
    m6m7_gate = evaluate_calibration_gate(q, y, symmetry_errors=[0.0], order_independent=True, fit_isolated=True)
    comparison = {
        "p6_m10": {"log_loss": log_loss(p, y), "auc": auc(p, y), "calibration": calibration_slope(p, y),
                   "brier": brier_decomposition(p, y), "g2_rejected_bins": g2_now.rejected_bins},
        "m6m7": {"log_loss": log_loss(q, y), "auc": auc(q, y), "calibration": calibration_slope(q, y),
                 "brier": brier_decomposition(q, y), "g1_ece": m6m7_gate.ece, "g2_status": m6m7_gate.g2.status,
                 "g2_rejected_bins": m6m7_gate.g2.rejected_bins,
                 "g2_bins": [{"lower": b.lower, "count": b.count, "mean_predicted": b.mean_predicted,
                              "observed_rate": b.observed_rate, "p_value": b.p_value, "rejected": b.rejected}
                             for b in m6m7_gate.g2.bins]},
    }

    # --- 3: concentration ----------------------------------------------------------------------------------------
    with database.cursor() as cursor:
        cursor.execute(WEEK_SQL, (sorted({row.event_key for row, _ in population}),))
        weeks = dict(cursor.fetchall())
    by_week, by_source, by_fallback, by_position, by_event, by_range = (defaultdict(list) for _ in range(6))
    order_in_event: dict[str, list] = defaultdict(list)
    for row, e in population:
        order_in_event[row.event_key].append(row.scheduled_time)
    for row, e in population:
        item = (e.p_red, row.label == LABEL_RED_WIN)
        week = weeks.get(row.event_key)
        by_week["champs/none" if week is None else f"week_{week}"].append(item)
        sources = [t.epa_source_event_key[:4] for t in (*row.red_teams, *row.blue_teams)]
        prior = sum(1 for s in sources if s != str(HELD_OUT_SEASON))
        by_source["all_2026_sources" if prior == 0 else ("all_prior_season" if prior == 6 else "mixed")].append(item)
        fallback = any(t.epa_value_source == "stratai_fallback" for t in (*row.red_teams, *row.blue_teams))
        by_fallback["stratai_fallback" if fallback else "statbotics_only"].append(item)
        times = sorted(order_in_event[row.event_key])
        tercile = min(2, 3 * times.index(row.scheduled_time) // max(1, len(times)))
        by_position[["early", "middle", "late"][tercile] + "_in_event"].append(item)
        by_event[row.event_key].append(item)
        by_range[f"{min(int(e.p_red * 10), 9) / 10:.1f}"].append(item)
    event_gaps = sorted(((k, float(np.mean([yy for _, yy in v]) - np.mean([pp for pp, _ in v])), len(v))
                         for k, v in by_event.items()), key=lambda t: t[1])
    # leave-one-week-out: does G2 still fail without any single week?
    lowo = {}
    for week_key in sorted(by_week):
        keep = [(pp, yy) for (row, e), pp, yy in zip(population, p, y)
                if (("champs/none" if weeks.get(row.event_key) is None else f"week_{weeks.get(row.event_key)}")
                    != week_key)]
        g = g2_bin_consistency([a for a, _ in keep], [b for _, b in keep])
        lowo[f"without_{week_key}"] = {"n": len(keep), "g2": g.status, "rejected_bins": g.rejected_bins}
    concentration = {"week": group_summary(by_week), "epa_source_season": group_summary(by_source),
                     "fallback": group_summary(by_fallback), "position_in_event": group_summary(by_position),
                     "probability_range": group_summary(by_range),
                     "events_most_overpredicted": event_gaps[:5], "events_most_underpredicted": event_gaps[-5:],
                     "event_count": len(by_event), "leave_one_week_out_g2": lowo}

    # --- 5 / score components: the fitted component model against 2026 outcomes -------------------------------
    keys = [row.match_key for row, _ in population]
    breakdowns: dict[str, dict] = {}
    with database.cursor() as cursor:
        for start in range(0, len(keys), 2000):
            cursor.execute(BREAKDOWN_SQL, (keys[start:start + 2000],))
            breakdowns.update(dict(cursor.fetchall()))
    deltas, actuals, skipped = [], [], 0
    for row, e in population:
        b = breakdowns.get(row.match_key)
        try:
            red, blue = score_components(2026, b["red"]), score_components(2026, b["blue"])
        except (TypeError, KeyError, ScoreBreakdownSchemaError, UnsupportedSeasonError):
            skipped += 1
            continue
        scale = row.red_teams[0].score_scale
        mu_r = alliance_means(row.red_teams, Strategy.baseline([t.team_number for t in row.red_teams]), ())
        mu_b = alliance_means(row.blue_teams, Strategy.baseline([t.team_number for t in row.blue_teams]), ())
        deltas.append([mu_r[c] - mu_b[c] for c in ("auto", "teleop", "endgame")])
        d = normalized_difference(red, blue, scale)
        actuals.append([d[c] for c in ("auto", "teleop", "endgame", "other")])
    deltas_a, actual_a = np.array(deltas), np.array(actuals)
    beta_fit = np.array([model.beta[c] for c in ("auto", "teleop", "endgame")])
    beta_2026 = (deltas_a * actual_a[:, :3]).sum(axis=0) / (deltas_a ** 2).sum(axis=0)
    residual_fit = actual_a - np.column_stack([deltas_a * beta_fit, np.zeros(len(deltas_a))])
    sigma_2026_under_fitted_beta = float(math.sqrt((residual_fit.T @ residual_fit / len(residual_fit)).sum()))
    predicted_mean = (deltas_a * beta_fit).sum(axis=1)
    actual_total = actual_a.sum(axis=1)
    total_slope = float(np.dot(predicted_mean, actual_total) / np.dot(predicted_mean, predicted_mean))
    components = {
        "rows": len(deltas), "skipped_no_breakdown": skipped,
        "beta_fitted_2024_2025": dict(zip(("auto", "teleop", "endgame"), beta_fit.tolist())),
        "beta_2026_diagnostic_only": dict(zip(("auto", "teleop", "endgame"), beta_2026.tolist())),
        "sigma_fitted_2024_2025": model.sigma,
        "sigma_2026_residual_under_fitted_beta_diagnostic_only": sigma_2026_under_fitted_beta,
        "component_residual_sd_fitted": np.sqrt(np.diag(model.sigma_matrix)).tolist(),
        "component_residual_sd_2026": np.sqrt(np.diag(residual_fit.T @ residual_fit / len(residual_fit))).tolist(),
        "actual_total_on_predicted_mean_slope_2026": total_slope,
        "signal_to_noise_fitted": float(np.std(predicted_mean) / model.sigma),
        "signal_to_noise_2026": float(np.std(predicted_mean) / sigma_2026_under_fitted_beta),
    }

    # --- 8-10: strategy space and defense/feeding ----------------------------------------------------------------
    rng = random.Random(COLLAPSE_SEED)
    collapse = []
    for row, _ in rng.sample(population, COLLAPSE_SAMPLE):
        context = MatchContext(tuple(row.red_teams), tuple(row.blue_teams))
        own = [t.team_number for t in row.red_teams]
        opp = [t.team_number for t in row.blue_teams]
        inputs, probs = set(), set()
        for s in candidate_strategies(own, opp):
            mu = alliance_means(row.red_teams, s, ())
            inputs.add(tuple(round(mu[c], 15) for c in ("auto", "teleop", "endgame")))
            probs.add(model.evaluate(context, s, Strategy.baseline(opp)).p_red)
        zero_caps = sum(1 for t in row.red_teams for v in (t.epa_auto, t.epa_teleop, t.epa_endgame) if v <= 0)
        collapse.append({"distinct_model_inputs": len(inputs), "distinct_probabilities": len(probs),
                         "zero_capability_components": zero_caps})
    # identities that must hold if defense/feeding contribute nothing: same withheld components => same odds
    row = population[0][0]
    context = MatchContext(tuple(row.red_teams), tuple(row.blue_teams))
    a, b, c = (t.team_number for t in row.red_teams)
    opp = [t.team_number for t in row.blue_teams]
    rest = (RobotPlan(team_number=b), RobotPlan(team_number=c))
    variants = [Strategy(robots=(RobotPlan(team_number=a, components=("auto", "endgame")), *rest))]
    variants += [Strategy(robots=(RobotPlan(team_number=a, role="defense", components=("auto", "endgame"),
                                            defense_target=t), *rest)) for t in opp]
    variants += [Strategy(robots=(RobotPlan(team_number=a, role="feeding", components=("auto", "endgame"),
                                            feed_target=t), *rest)) for t in (b, c)]
    odds = {model.evaluate(context, s, Strategy.baseline(opp)).p_red for s in variants}
    # scouting values are never read: planting a defense/feeding score on every team changes nothing
    planted = tuple(t.model_copy(update={"defense_score": 5.0, "defense_score_present": True, "feeding_score": 5.0,
                                         "feeding_score_present": True}) for t in row.red_teams)
    unchanged = (model.evaluate(MatchContext(planted, tuple(row.blue_teams)), Strategy.baseline([a, b, c]),
                                Strategy.baseline(opp)).p_red
                 == model.evaluate(context, Strategy.baseline([a, b, c]), Strategy.baseline(opp)).p_red)
    defense_feeding_rows = sum(1 for r in rows if r.season == 2026 for t in (*r.red_teams, *r.blue_teams)
                               if t.defense_score_present or t.feeding_score_present)
    strategy_space = {
        "candidates_per_context": 21952,
        "theoretical_distinct_inputs_per_context": 8 ** 3,
        "sampled_contexts": collapse,
        "defense_feeding_identity": {"variants": len(variants), "distinct_odds": len(odds)},
        "planted_scouting_values_change_odds": not unchanged,
        "frame_2026_team_appearances_with_defense_or_feeding": defense_feeding_rows,
        "evaluated_population_strategies": "baseline only for both alliances (the P6-Q9 gate population)",
    }

    result = {"diagnostic_only": True, "not_an_evaluation_or_fix": True, "authoritative_record": "p6_m10_outcome_model.json",
              "frame_content_hash": frame_hash, "model_sha256": model.artifact_sha256,
              "population": len(p), "recorded_gate_reproduced": reproduced, "comparison_same_rows": comparison,
              "concentration": concentration, "components": components, "strategy_space": strategy_space,
              "minutes": round((time.time() - started) / 60, 1), "provenance": provenance()}
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(result, indent=1, sort_keys=True, default=str) + "\n", encoding="utf-8")
    print("reproduced:", reproduced, "minutes:", result["minutes"], "->", OUT)
    return 0


if __name__ == "__main__":
    sys.exit(main())
