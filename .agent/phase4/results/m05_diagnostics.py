"""Scratch diagnostics for the M5 failure. Changes nothing M5 defines; explains it."""
import json
import statistics
import sys
from pathlib import Path

sys.path.insert(0, r"C:\Dev\StratAI")
import numpy as np  # noqa: E402
import xgboost as xgb  # noqa: E402

from ml.backtest.harness import Fold, run_ranking_backtest  # noqa: E402
from ml.models import ranking_xgb as rx  # noqa: E402
from scripts.run_phase4_stratai import _final_ranks, _folds, _labels_shuffled, load_frame_rows  # noqa: E402

FRAME = Path(r"C:\Dev\StratAI-artifacts\phase4\frame_54e9d54b5ebe6b11")
rows = load_frame_rows(FRAME)
fold, _, _, _ = _folds(rows)
ranks = _final_ranks(2026)
out = {}

# 1. label shuffle across seeds
shuffle = []
for seed in range(1, 9):
    f = Fold(label=f"shuffle {seed}", train_rows=_labels_shuffled(fold.train_rows, seed), test_rows=fold.test_rows,
             split_strategy=fold.split_strategy)
    shuffle.append(run_ranking_backtest(rx.RankingXGBModel, [f], ranks).aggregate.spearman)
out["label_shuffle_spearman_by_seed"] = shuffle
out["label_shuffle_mean"] = statistics.mean(shuffle)

# 2. the early-stopping validation curve, reproduced with M5's own split and parameters
sorted_rows = sorted(fold.train_rows, key=lambda r: r.scheduled_time)
split = rx._validation_split_index(len(sorted_rows), rx._DEFAULT_VALIDATION_FRACTION)
tr, va = sorted_rows[:split], sorted_rows[split:]
X_tr, y_tr = rx._rows_to_matrix(tr)
X_va, y_va = rx._rows_to_matrix(va)
params = {"objective": "reg:squarederror", "seed": 42, "max_depth": 6, "eta": 0.1, "subsample": 1.0,
          "colsample_bytree": 1.0, "nthread": 1}
d_tr = xgb.DMatrix(X_tr, label=y_tr, feature_names=list(rx.FEATURE_NAMES), missing=np.nan)
d_va = xgb.DMatrix(X_va, label=y_va, feature_names=list(rx.FEATURE_NAMES), missing=np.nan)
curve = {}
xgb.train(params, d_tr, num_boost_round=40, evals=[(d_tr, "train"), (d_va, "validation")], evals_result=curve,
          verbose_eval=False)
out["validation_rows"] = {"first": str(va[0].scheduled_time), "seasons": sorted({r.season for r in va})}
out["rmse_by_round"] = {k: [round(x, 3) for x in v["rmse"][:25]] for k, v in curve.items()}
out["target_abs_mean_by_season"] = {
    s: round(statistics.mean(abs(r.score_margin) for r in rows if r.season == s), 2) for s in (2024, 2025, 2026)}

# 3. feature scale across seasons
def epa_values(season):
    return [t.epa_total for r in rows if r.season == season for t in (*r.red_teams, *r.blue_teams) if t.epa_total_present]

train_max = max(epa_values(2024) + epa_values(2025))
test = epa_values(2026)
out["epa_total"] = {s: {"median": round(statistics.median(epa_values(s)), 2), "p90": round(float(np.percentile(epa_values(s), 90)), 2)}
                    for s in (2024, 2025, 2026)}
out["epa_total_train_max"] = round(train_max, 2)
out["share_2026_epa_above_train_max"] = round(sum(v > train_max for v in test) / len(test), 4)
print(json.dumps(out, indent=1))
(FRAME / "m05_failure_diagnostics.json").write_text(json.dumps(out, indent=2))
