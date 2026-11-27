"""Independent evaluation of the served win-probability model (D18 M6+M7) on the D18 frame (2026-11-26 audit).

Read-only: the frame cache and the registered artifact. Baselines are fit on 2024+2025 only (the D7 training seasons);
2026 is the already-consumed D7 hold-out (no 2027 data is read). Metrics on 2024/2025 are IN-SAMPLE for the served model
and are reported as such. Bootstrap CIs resample whole events (clustered), 1,000 replicates, seed 20261126.
"""
import gzip
import json
import math
import os
import random
import sys
from collections import defaultdict

sys.path.insert(0, "C:/Dev/StratAI")
os.chdir("C:/Dev/StratAI")
from scripts.local_test_env import PINS  # noqa: E402

os.environ.update({k: v for k, v in PINS.items() if k != "DATABASE_URL"})

import numpy as np  # noqa: E402
from sklearn.linear_model import LogisticRegression  # noqa: E402
from sklearn.metrics import roc_auc_score  # noqa: E402

from api.ml_loading import load_pinned_win_prob_model  # noqa: E402
from data.config import Settings  # noqa: E402
from ml.dataset.builder import TrainingRow  # noqa: E402

FRAME = "C:/Dev/StratAI-artifacts/phase4/frame_ab1adbf38b43c2f3/frame_rows.json.gz"
OUT = sys.argv[1]
rng = random.Random(20261126)

rows = [TrainingRow.model_validate(r) for r in json.loads(gzip.decompress(open(FRAME, "rb").read()))]
loaded = load_pinned_win_prob_model(Settings())
model = loaded.model if hasattr(loaded, "model") else loaded
print("rows", len(rows), "model", type(model).__name__)


def side_sum(teams, attr):
    vals = [getattr(t, attr) for t in teams]
    return None if any(v is None for v in vals) or len(vals) != 3 else sum(vals)


def info(r):
    teams = r.red_teams + r.blue_teams
    epa_complete = all(t.epa_total is not None for t in teams) and len(r.red_teams) == 3 and len(r.blue_teams) == 3
    scale = next((t.epa_scale for t in teams if getattr(t, "epa_scale", None)), None)
    sscale = next((t.score_scale for t in teams if getattr(t, "score_scale", None)), None)
    red_e, blue_e = side_sum(r.red_teams, "epa_total"), side_sum(r.blue_teams, "epa_total")
    red_a, blue_a = side_sum(r.red_teams, "average_score"), side_sum(r.blue_teams, "average_score")
    e_ok = red_e is not None and blue_e is not None
    a_ok = red_a is not None and blue_a is not None
    return {"epa_complete": epa_complete, "epa_diff": red_e - blue_e if e_ok else None,
            "epa_diff_n": (red_e - blue_e) / scale if e_ok and scale else None,
            "avg_diff_n": (red_a - blue_a) / (3 * sscale) if a_ok and sscale else None}


data = []
for r in rows:
    if r.label == "tie":
        continue
    i = info(r)
    i.update({"y": 1 if r.label == "red_win" else 0, "season": r.season, "event": r.event_key,
              "level": "qualification" if r.comp_level == "qm" or r.comp_level == "qualification" else "playoff",
              "time": r.scheduled_time, "row": r})
    data.append(i)
print("non-tie rows", len(data))

# Served model predictions (calibrated pair), every row.
for d in data:
    d["p_served"] = float(model.predict_win_prob(d["row"]))


def fit_logit(train, cols):
    X = np.array([[d[c] for c in cols] for d in train]); y = np.array([d["y"] for d in train])
    m = LogisticRegression(C=1e6, fit_intercept=False, max_iter=1000).fit(X, y)
    return lambda d: float(m.predict_proba(np.array([[d[c] for c in cols]]))[0, 1])


train = [d for d in data if d["season"] in (2024, 2025) and d["epa_complete"] and d["epa_diff_n"] is not None]
train_avg = [d for d in train if d["avg_diff_n"] is not None]
b_raw = fit_logit(train, ["epa_diff"])            # M4-style raw-point EPA logistic, no intercept
b_norm = fit_logit(train, ["epa_diff_n"])          # the same on the causal season scale
b_norm_avg = fit_logit([d for d in train_avg], ["epa_diff_n", "avg_diff_n"])
base_rate = sum(d["y"] for d in train) / len(train)


def metrics(ds, key):
    y = np.array([d["y"] for d in ds]); p = np.clip(np.array([d[key] for d in ds]), 1e-6, 1 - 1e-6)
    ll = float(-np.mean(y * np.log(p) + (1 - y) * np.log(1 - p)))
    brier = float(np.mean((p - y) ** 2)); acc = float(np.mean((p >= 0.5) == (y == 1)))
    auc = float(roc_auc_score(y, p)) if len(set(y)) > 1 else None
    bins = np.minimum((p * 10).astype(int), 9); ece = 0.0; rel = []
    for b in range(10):
        m = bins == b
        if m.sum():
            ece += m.sum() / len(p) * abs(p[m].mean() - y[m].mean())
            rel.append({"bin": b, "n": int(m.sum()), "mean_p": round(float(p[m].mean()), 4),
                        "observed": round(float(y[m].mean()), 4)})
    return {"n": len(ds), "log_loss": round(ll, 4), "brier": round(brier, 4), "accuracy": round(acc, 4),
            "auc": None if auc is None else round(auc, 4), "ece": round(ece, 4), "reliability": rel}


def cluster_ci(ds, key_a, key_b, metric="log_loss", reps=1000):
    by_event = defaultdict(list)
    for d in ds:
        by_event[d["event"]].append(d)
    events = list(by_event)
    diffs = []
    for _ in range(reps):
        sample = [d for e in (rng.choice(events) for _ in events) for d in by_event[e]]
        diffs.append(metrics(sample, key_a)[metric] - metrics(sample, key_b)[metric])
    diffs.sort()
    return {"mean": round(float(np.mean(diffs)), 4), "ci95": [round(diffs[24], 4), round(diffs[974], 4)]}


for d in data:
    ok = d["epa_complete"] and d["epa_diff_n"] is not None
    d["p_raw"] = b_raw(d) if d["epa_diff"] is not None else None
    d["p_norm"] = b_norm(d) if ok else None
    d["p_norm_avg"] = b_norm_avg(d) if ok and d["avg_diff_n"] is not None else None
    d["p_base"] = base_rate

result = {"frame": "ab1adbf3", "baselines_fit_on": "2024+2025 EPA-complete non-tie rows", "base_rate": round(base_rate, 4)}
for season in (2024, 2025, 2026):
    for level in ("qualification", "playoff"):
        ds = [d for d in data if d["season"] == season and d["level"] == level and d["epa_complete"]
              and d["p_norm"] is not None]
        key = f"{season}_{level}_epa_complete" + ("_IN_SAMPLE" if season < 2026 else "_HELD_OUT")
        result[key] = {k: metrics(ds, k) for k in ("p_served", "p_raw", "p_norm", "p_base")}
        both = [d for d in ds if d["p_norm_avg"] is not None]
        result[key]["p_norm_avg_subset"] = {"served": metrics(both, "p_served"), "norm_avg": metrics(both, "p_norm_avg")}
# The served-label population: 2026 qualification, EPA-complete (approximately_calibrated_qualification).
q26 = [d for d in data if d["season"] == 2026 and d["level"] == "qualification" and d["epa_complete"]
       and d["p_norm"] is not None]
result["2026_qual_ci"] = {
    "served_minus_norm_logloss": cluster_ci(q26, "p_served", "p_norm"),
    "served_minus_raw_logloss": cluster_ci(q26, "p_served", "p_raw"),
    "served_minus_norm_brier": cluster_ci(q26, "p_served", "p_norm", "brier"),
}
q26b = [d for d in q26 if d["p_norm_avg"] is not None]
result["2026_qual_ci"]["served_minus_norm_avg_logloss"] = cluster_ci(q26b, "p_served", "p_norm_avg")
# By week of season (2026 quals): early-season calibration.
start = min(d["time"] for d in q26)
byweek = defaultdict(list)
for d in q26:
    byweek[min((d["time"] - start).days // 7, 7)].append(d)
result["2026_qual_by_week_served"] = {w: {k: v for k, v in metrics(ds, "p_served").items() if k != "reliability"}
                                      for w, ds in sorted(byweek.items())}
# Not EPA-complete rows (the served label withholds the probability there).
nc = [d for d in data if d["season"] == 2026 and d["level"] == "qualification" and not d["epa_complete"]]
result["2026_qual_not_epa_complete_served"] = metrics(nc, "p_served")
# Negative controls on 2026 quals.
perm = [dict(d) for d in q26]
ys = [d["y"] for d in perm]; rng.shuffle(ys)
for d, y in zip(perm, ys):
    d["y"] = y
result["negative_control_label_permutation"] = {k: v for k, v in metrics(perm, "p_served").items() if k != "reliability"}
with open(OUT, "w") as f:
    json.dump(result, f, indent=1, default=str)
for k, v in result.items():
    if isinstance(v, dict) and "p_served" in v:
        print(k, {m: {x: v[m][x] for x in ("n", "log_loss", "brier", "accuracy", "auc", "ece")} for m in ("p_served", "p_raw", "p_norm")})
print("CI", json.dumps(result["2026_qual_ci"]))
print("by week", json.dumps(result["2026_qual_by_week_served"]))
print("not EPA-complete", {k: v for k, v in result["2026_qual_not_epa_complete_served"].items() if k != "reliability"})
print("permutation", result["negative_control_label_permutation"])
