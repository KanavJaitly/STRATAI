"""Synthetic verification of the D16 M7 gate (spec §2.5, criteria V1-V4 fixed before running).

Entirely synthetic; reads no database and no real outcome. V5 (regression) is
the test suite: tests/test_ml_calibration.py and tests/test_ml_calibration_gate.py.
Results are saved after every section; a rerun skips saved sections.

    python -m scripts.verify_m07_gate --out .agent/phase4/results/m07_synthetic_verification.json
"""

from __future__ import annotations

import argparse
import itertools
import json
import math
import os
import random
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import numpy as np
from scipy.stats import beta as beta_dist
from scipy.stats import binomtest

from ml.calibration.calibrator import SymmetricIsotonicCalibrator, fit_calibrated_win_prob_model
from ml.calibration.gate import G2_FAIL, G2_UNEVALUABLE, g2_bin_consistency, poisson_binomial_pmf, two_sided_p_value

N_PREDICTIONS = 15_000
V2_DATASETS = 1_000
V3_DATASETS = 200


def _save(path: Path, state: dict) -> None:
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(state, indent=2, default=str))
    os.replace(tmp, path)


def v1() -> dict:
    rng = random.Random(1)
    worst, worst_sum = 0.0, 0.0
    for trial in range(200):
        n = trial % 12 + 1
        p = [rng.random() for _ in range(n)]
        brute = np.zeros(n + 1)
        for outcome in itertools.product((0, 1), repeat=n):
            brute[sum(outcome)] += math.prod(q if o else 1 - q for q, o in zip(p, outcome))
        pmf = poisson_binomial_pmf(p)
        worst = max(worst, float(np.max(np.abs(pmf - brute))))
        worst_sum = max(worst_sum, abs(float(pmf.sum()) - 1.0))
    a = {"max_abs_difference": worst, "max_sum_error": worst_sum, "pass": worst <= 1e-12 and worst_sum <= 1e-12}

    nrng = np.random.default_rng(2)
    p = nrng.random(300)
    draws = (nrng.random((200_000, 300)) < p).sum(axis=1)
    empirical = np.bincount(draws, minlength=301) / draws.size
    pmf = poisson_binomial_pmf(p)
    tv = 0.5 * float(np.abs(empirical - pmf).sum())
    mean_error = abs(draws.mean() - p.sum()) / p.sum()
    var_error = abs(draws.var() - (p * (1 - p)).sum()) / (p * (1 - p)).sum()
    b = {"total_variation": tv, "relative_mean_error": float(mean_error), "relative_variance_error": float(var_error),
         "pass": bool(tv <= 0.01 and mean_error <= 0.01 and var_error <= 0.01)}

    worst_c = 0.0
    for n in (30, 100, 500):
        for q in (0.1, 0.35, 0.6, 0.92):
            for f in (0.7, 0.9, 1.0, 1.1, 1.3):
                k = min(n, max(0, round(n * q * f)))
                ours = two_sided_p_value(poisson_binomial_pmf([q] * n), k)
                worst_c = max(worst_c, abs(ours - binomtest(k, n, q, alternative="two-sided").pvalue))
    c = {"max_abs_difference_vs_scipy_binomtest": float(worst_c), "pass": bool(worst_c <= 1e-9)}
    return {"a_brute_force": a, "b_simulation": b, "c_equal_probability": c,
            "pass": bool(a["pass"] and b["pass"] and c["pass"])}


def _rates(scenario, datasets: int, seed: int) -> dict:
    rng = np.random.default_rng(seed)
    statuses = {"pass": 0, "fail": 0, "unevaluable": 0}
    for _ in range(datasets):
        q = rng.beta(0.5, 0.5, size=N_PREDICTIONS)
        y = rng.random(N_PREDICTIONS) < scenario(q)
        statuses[g2_bin_consistency(q.tolist(), y.tolist()).status] += 1
    return statuses


def _logit(x):
    x = np.clip(x, 1e-12, 1 - 1e-12)
    return np.log(x / (1 - x))


def v2() -> dict:
    statuses = _rates(lambda q: q, V2_DATASETS, 20260930)
    failures = statuses[G2_FAIL]
    rate = failures / V2_DATASETS
    lower = float(beta_dist.ppf(0.025, failures, V2_DATASETS - failures + 1)) if failures else 0.0
    upper = float(beta_dist.ppf(0.975, failures + 1, V2_DATASETS - failures))
    return {"datasets": V2_DATASETS, "statuses": statuses, "false_failure_rate": rate,
            "clopper_pearson_95": [lower, upper],
            "pass": lower <= 0.05 and statuses[G2_UNEVALUABLE] == 0}


def v3() -> dict:
    scenarios = {
        "i_overconfidence_logit_x0.8": (lambda q: 1 / (1 + np.exp(-0.8 * _logit(q))), True),
        "ii_shift_plus_0.03": (lambda q: np.clip(q + 0.03, 0, 1), True),
        "iii_shift_plus_0.01_information_only": (lambda q: np.clip(q + 0.01, 0, 1), False),
    }
    out = {}
    for seed, (name, (fn, gating)) in enumerate(scenarios.items(), start=31):
        statuses = _rates(fn, V3_DATASETS, seed)
        rate = statuses[G2_FAIL] / V3_DATASETS
        out[name] = {"statuses": statuses, "rejection_rate": rate, "gating": gating,
                     "pass": (rate >= 0.80) if gating else None}
    out["pass"] = all(v["pass"] for v in out.values() if isinstance(v, dict) and v["gating"])
    return out


def _synthetic_rows(count: int, seed: int):
    from ml.dataset.builder import LABEL_BLUE_WIN, LABEL_RED_WIN, TrainingRow
    from ml.features.assembler import EPA_WITHHELD_NO_PRIOR_EVENT, TeamFeatures

    rng = random.Random(seed)
    start = datetime(9990, 3, 1, tzinfo=timezone.utc)

    def team(number: int) -> TeamFeatures:
        return TeamFeatures(
            team_number=number, epa_total=rng.uniform(5, 60), epa_total_present=True,
            epa_auto=rng.uniform(1, 15), epa_auto_present=True, epa_teleop=rng.uniform(2, 40), epa_teleop_present=True,
            epa_endgame=rng.uniform(0, 10), epa_endgame_present=True, epa_source_event_key="9989zzzprior",
            average_score=rng.uniform(20, 120), average_score_present=True, score_stddev_present=False,
            consistency_rating_present=False, reliability_score_present=False, matches_considered=6, matches_used=6,
            average_auto_points_present=False, auto_points_matches_used=0, defense_score_present=False,
            defense_agreement_present=False, defense_observation_count=0, feeding_score_present=False,
            feeding_agreement_present=False, feeding_observation_count=0,
        )

    rows = []
    for i in range(count):
        red = [team(10_000 + 6 * i + k) for k in range(3)]
        blue = [team(10_000 + 6 * i + 3 + k) for k in range(3)]
        diff = sum(t.epa_total for t in red) - sum(t.epa_total for t in blue)
        red_wins = rng.random() < 1 / (1 + math.exp(-diff / 25))
        score_red, score_blue = (100, 80) if red_wins else (80, 100)
        rows.append(TrainingRow(
            match_key=f"9990zzzv4_qm{i}", event_key="9990zzzv4", season=9990, comp_level="qualification",
            match_number=i, scheduled_time=start + timedelta(minutes=10 * i),
            label=LABEL_RED_WIN if red_wins else LABEL_BLUE_WIN, score_margin=score_red - score_blue,
            score_red=score_red, score_blue=score_blue, red_teams=red, blue_teams=blue, dq_status_known=True,
        ))
    return rows


def v4() -> dict:
    from ml.backtest.harness import _match_features
    from ml.models.win_prob import WinProbXGBModel

    rng = random.Random(4)
    p = [rng.random() for _ in range(3000)]
    y = [rng.random() < min(1.0, 0.1 + 0.8 * q) for q in p]
    calibrator = SymmetricIsotonicCalibrator()
    calibrator.fit(p, y)
    points = [rng.random() for _ in range(100_000)] + [0.0, 0.5, 1.0]
    a_error = max(abs(calibrator.calibrate(x) + calibrator.calibrate(1 - x) - 1) for x in points)
    grid = sorted(points)
    values = [calibrator.calibrate(x) for x in grid]
    monotone = all(u <= v + 1e-15 for u, v in zip(values, values[1:]))
    a = {"max_symmetry_error": a_error, "monotone": monotone, "pass": a_error <= 1e-12 and monotone}

    model, fitted, diagnostics = fit_calibrated_win_prob_model(
        WinProbXGBModel, _synthetic_rows(2000, 5), calibrator_factory=SymmetricIsotonicCalibrator)
    evaluation = _synthetic_rows(1000, 6)
    forward, worst = [], 0.0
    for row in evaluation:
        features = _match_features(row)
        swapped = features.model_copy(update={"red_teams": features.blue_teams, "blue_teams": features.red_teams})
        q_rb = fitted.calibrate(model.predict_win_prob(features))
        q_br = fitted.calibrate(model.predict_win_prob(swapped))
        worst = max(worst, abs(q_rb + q_br - 1))
        forward.append(q_rb)
    backward = [fitted.calibrate(model.predict_win_prob(_match_features(r))) for r in reversed(evaluation)]
    order = forward == list(reversed(backward))
    b = {"matches": len(evaluation), "max_symmetry_error": worst, "order_independent": order,
         "fit_diagnostics": diagnostics, "pass": worst <= 1e-12 and order}
    return {"a_calibrator": a, "b_end_to_end": b, "pass": a["pass"] and b["pass"]}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args(argv)
    state = json.loads(args.out.read_text()) if args.out.exists() else {"spec": "M05_M07_REDESIGN_SPEC.md §2.5 (D16)"}
    for name, fn in (("V1", v1), ("V2", v2), ("V3", v3), ("V4", v4)):
        if name in state:
            print(f"[skip] {name}: pass={state[name]['pass']}")
            continue
        started = time.time()
        state[name] = {**fn(), "_seconds": round(time.time() - started, 1)}
        _save(args.out, state)
        print(f"[saved] {name}: pass={state[name]['pass']} ({state[name]['_seconds']}s)")
    state["all_pass"] = all(state[n]["pass"] is True for n in ("V1", "V2", "V3", "V4"))
    _save(args.out, state)
    print(f"V1-V4 all pass: {state['all_pass']}")
    return 0 if state["all_pass"] else 1


if __name__ == "__main__":
    sys.exit(main())
