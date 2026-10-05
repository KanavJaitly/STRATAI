"""DIAGNOSTIC ONLY: does the P6-M10 under-confidence track the season of the teams' EPA sources, and does that
heterogeneity already exist in the 2024–2025 training seasons? This is a falsifiable check of one hypothesis.

    python -m scripts.phase6_m10_source_diagnostic     # DATABASE_URL = the isolated stratai_test copy (read-only)

**For each source category** (the six teams' EPA source events are all same-season, all prior-season, or mixed),
on the training seasons (2024, 2025) and on held-out 2026, it reports:
- the slope of the actual total normalized score difference on P6-M10's predicted mean (1 = unbiased scale);
- the residual SD around the *fitted* model.

Nothing is refitted for use, and nothing is served. Output: `.agent/phase6/diagnostics/p6_m10_source_diagnostic.json`.
"""

from __future__ import annotations

import json
import sys
import time
from collections import defaultdict
from pathlib import Path

import numpy as np

from scripts.phase6_common import P6_M10_VERSION_TAG, REGISTRY_DIR, isolated_database, load_frame, provenance, read_record

OUT = Path(".agent/phase6/diagnostics/p6_m10_source_diagnostic.json")
BREAKDOWN_SQL = """
SELECT r.source_object_id, r.payload_json->'score_breakdown'
FROM raw_source_payloads r
WHERE r.source = 'tba' AND r.source_object_type = 'match' AND r.is_current AND r.source_object_id = ANY(%s)
"""


def main() -> int:
    from ml.features.score_breakdown import ScoreBreakdownSchemaError, UnsupportedSeasonError
    from ml.features.score_components import score_components
    from ml.strategy.outcome import MatchContext, load_registered_strategy_model, missing_inputs, fit_sample
    from ml.strategy.representation import Strategy
    from scripts.phase6_m10_diagnostics import calibration_slope

    started = time.time()
    fit = read_record("p6_m10_fit.json")
    model = load_registered_strategy_model(REGISTRY_DIR, version_tag=P6_M10_VERSION_TAG,
                                           expected_sha256=fit["registry"]["model_sha256"])
    rows, frame_hash = load_frame()
    rows = [r for r in rows if r.comp_level == "qualification" and len(r.red_teams) == 3 and len(r.blue_teams) == 3
            and all(t.epa_total_present for t in (*r.red_teams, *r.blue_teams))
            and not missing_inputs(MatchContext(tuple(r.red_teams), tuple(r.blue_teams)))]
    database = isolated_database()
    breakdowns: dict[str, dict] = {}
    keys = [r.match_key for r in rows]
    with database.cursor() as cursor:
        for start in range(0, len(keys), 2000):
            cursor.execute(BREAKDOWN_SQL, (keys[start:start + 2000],))
            breakdowns.update(dict(cursor.fetchall()))
    beta = np.array([model.beta[c] for c in ("auto", "teleop", "endgame")])
    groups: dict[tuple[str, str], list[tuple[float, float]]] = defaultdict(list)
    joint: dict[str, list] = defaultdict(list)  # (delta vector, actual total, label) per split
    wins: dict[tuple[str, str], list[tuple[float, bool]]] = defaultdict(list)
    for row in rows:
        b = breakdowns.get(row.match_key)
        try:
            red, blue = score_components(row.season, b["red"]), score_components(row.season, b["blue"])
        except (TypeError, KeyError, ScoreBreakdownSchemaError, UnsupportedSeasonError):
            continue
        sample = fit_sample(row.red_teams, row.blue_teams, red, blue)
        predicted = float(np.dot(beta, [sample.delta[c] for c in ("auto", "teleop", "endgame")]))
        actual = sum(sample.d.values())
        prior = sum(1 for t in (*row.red_teams, *row.blue_teams) if t.epa_source_event_key[:4] != str(row.season))
        category = "all_same_season" if prior == 0 else ("all_prior_season" if prior == 6 else "mixed")
        split = "held_out_2026" if row.season == 2026 else "training_2024_2025"
        groups[(split, category)].append((predicted, actual))
        joint[split].append(([sample.delta[c] for c in ("auto", "teleop", "endgame")], actual, row.label))
        if row.label != "tie":
            e = model.evaluate(MatchContext(tuple(row.red_teams), tuple(row.blue_teams)),
                               Strategy.baseline([t.team_number for t in row.red_teams]),
                               Strategy.baseline([t.team_number for t in row.blue_teams]))
            for key in ((split, category), (split, "all")):
                wins[key].append((e.p_red, row.label == "red_win"))
    out = {}
    for (split, category), items in sorted(groups.items()):
        x = np.array([i[0] for i in items])
        y = np.array([i[1] for i in items])
        slope = float(np.dot(x, y) / np.dot(x, x))
        out.setdefault(split, {})[category] = {
            "n": len(items), "slope_actual_on_predicted_mean": slope,
            "residual_sd_around_fitted_mean": float(np.sqrt(np.mean((y - x) ** 2))),
            "predicted_mean_sd": float(np.std(x))}
    for (split, category), items in sorted(wins.items()):
        out.setdefault(split, {}).setdefault(category, {})["win_calibration_slope"] = calibration_slope(
            [i[0] for i in items], [i[1] for i in items])["slope"]
        out[split][category]["win_rows"] = len(items)
    # DIAGNOSTIC fit only (never a candidate model): total difference jointly on the three predicted component
    # differences, fitted on training rows; its in-sample and 2026 calibration slopes test whether discarding
    # cross-component information explains the under-confidence.
    from math import erfc, sqrt
    train = joint["training_2024_2025"]
    xt = np.array([j[0] for j in train]); yt = np.array([j[1] for j in train])
    coef = np.linalg.lstsq(xt, yt, rcond=None)[0]
    sigma_joint = float(np.sqrt(np.mean((yt - xt @ coef) ** 2)))
    joint_out = {"coefficients": dict(zip(("auto", "teleop", "endgame"), coef.tolist())), "sigma": sigma_joint}
    for split, items in joint.items():
        kept = [j for j in items if j[2] != "tie"]
        probs = [0.5 * erfc(-float(np.dot(coef, j[0])) / (sigma_joint * sqrt(2))) for j in kept]
        joint_out[f"{split}_win_calibration_slope"] = calibration_slope(probs, [j[2] == "red_win" for j in kept])["slope"]
    result = {"diagnostic_only": True, "joint_total_regression_diagnostic_only": joint_out, "frame_content_hash": frame_hash, "model_sigma": model.sigma, "groups": out,
              "minutes": round((time.time() - started) / 60, 1), "provenance": provenance()}
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(result, indent=1, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(out, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
