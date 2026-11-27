"""The served ranking model (M5 v2, d18 artifact) against unfitted simple baselines at the D16 midpoint snapshot,
2026 held-out (already consumed by D7), final qualification ranks as truth. Read-only (frame cache, registry, and the
stratai_test ranks). Audit 2026-11-26."""
import gzip
import json
import os
import random
import statistics
import sys

sys.path.insert(0, "C:/Dev/StratAI")
os.chdir("C:/Dev/StratAI")
from scripts.local_test_env import PINS  # noqa: E402
from data.config import Settings  # noqa: E402
from urllib.parse import urlparse  # noqa: E402

os.environ.update({k: v for k, v in PINS.items() if k != "DATABASE_URL"})
u = urlparse(str(Settings().database_url))
os.environ["DATABASE_URL"] = u._replace(path="/stratai_test").geturl()

from api.ml_loading import load_pinned_ranking_model  # noqa: E402
from data.rankings import read_final_ranks_for_season  # noqa: E402
from database.connection import Database, DatabaseConfig  # noqa: E402
from ml.backtest.ranking_midpoint import FIRST, LAST, MIDPOINT, decision_snapshots, evaluate_ranking  # noqa: E402
from ml.dataset.builder import TrainingRow  # noqa: E402

rows = [TrainingRow.model_validate(r) for r in json.loads(gzip.decompress(open(
    "C:/Dev/StratAI-artifacts/phase4/frame_ab1adbf38b43c2f3/frame_rows.json.gz", "rb").read()))]
test = [r for r in rows if r.season == 2026]
ranks = read_final_ranks_for_season(Database(DatabaseConfig(os.environ["DATABASE_URL"])), 2026)
served = load_pinned_ranking_model(Settings())
model = served.model if hasattr(served, "model") else served
NEG = -1e9


def raw_epa(f):
    return f.epa_total if f.epa_total is not None else NEG


def avg(f):
    return f.average_score / 3 if f.average_score is not None else NEG


def blend(f):
    vals = [v for v in (f.epa_total, None if f.average_score is None else f.average_score / 3) if v is not None]
    return statistics.fmean(vals) if vals else NEG


out = {}
rng = random.Random(20261126)
for name, rule in (("first", FIRST), ("midpoint", MIDPOINT), ("last", LAST)):
    snaps = decision_snapshots(test, rule)
    evals = {k: evaluate_ranking(fn, snaps, ranks) for k, fn in
             (("m5v2_served", model.predict_rating), ("raw_epa", raw_epa), ("in_event_avg", avg), ("blend", blend))}
    res = {k: {"spearman": round(v.spearman, 4), "top8_recall": round(v.top_k_recall, 4), "events": v.events_scored}
           for k, v in evals.items()}
    events = sorted(set.intersection(*[set(v.per_event) for v in evals.values()]))
    for other in ("raw_epa", "in_event_avg", "blend"):
        d = [evals["m5v2_served"].per_event[e]["spearman"] - evals[other].per_event[e]["spearman"] for e in events
             if evals["m5v2_served"].per_event[e]["spearman"] is not None and evals[other].per_event[e]["spearman"] is not None]
        boots = sorted(statistics.fmean(rng.choice(d) for _ in d) for _ in range(2000))
        res[f"m5v2_minus_{other}"] = {"mean": round(statistics.fmean(d), 4), "ci95": [round(boots[49], 4), round(boots[1949], 4)],
                                      "m5v2_better_events": sum(x > 0 for x in d), "events": len(d)}
    out[name] = res
    print(name, json.dumps(res))
json.dump(out, open(sys.argv[1], "w"), indent=1)
