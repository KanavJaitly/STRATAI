"""Reproducible evaluation of the research candidates WP-NORM-EPA-v1 and RANK-BLEND-v1 (audit 2026-11-26, WS1/WS2).

    python -m scripts.evaluate_model_candidates --out results.json                 # 2026: retrospective evidence
    python -m scripts.evaluate_model_candidates --season 2027 --pre-registered-2027-run --out ...   # once, later

**What it reads (read-only):** the D18 frame cache (`--frame`), the served D18 models (their pins in
scripts/local_test_env.PINS, verified by sha256 at load), and, for rankings, TBA's final qualification ranks from an
isolated `stratai_test*` database (DATABASE_URL; the serving `stratai` is refused).

**What it reports:**
- **diagnosis:** per-season scoring scales, the share of matches mixing EPA from two seasons, and how the raw-point
  feature's spread changes across seasons (why the raw-point models fail on 2026);
- **win probability** on the season's EPA-complete, non-tie qualification matches (primary) and playoff matches:
  WP-NORM-EPA-v1 (fitted on 2024+2025), the served M6+M7 model, the raw-EPA logistic, and the training base rate.
  Log loss, Brier, AUC, ECE, the D6 calibration gate's G1 and G2, and event-clustered bootstrap CIs for the
  differences;
- **ranking** at the first, midpoint (primary) and last snapshots: RANK-BLEND-v1, served M5 v2, raw EPA, and the
  in-event average. Mean per-event Spearman, top-8 recall, and bootstrap CIs over events.

**2026 is retrospective evidence only:** it was examined repeatedly before these candidates existed. Its results
cannot validate either candidate. **2027** is each candidate's pre-registered evaluation. It is refused unless
`--pre-registered-2027-run` is given, which is to be done once, after the frozen specs' conditions are met.

**Time budget:** `--budget-minutes` (default 30). The run checks the budget between stages and writes what it has,
marked `partial`, when it runs out (CLAUDE.md's 45-minute verification limit). A full 2026 run takes a few minutes.
"""

from __future__ import annotations

import argparse
import gzip
import json
import math
import os
import random
import statistics
import sys
import time
from collections import defaultdict
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Any

from ml.backtest.metrics import brier_score, expected_calibration_error, log_loss, roc_auc
from ml.calibration.gate import ECE_THRESHOLD, g2_bin_consistency
from ml.candidates import ranking_blend
from ml.candidates.win_prob_norm_epa import (
    TRAINING_SEASONS,
    NormEpaLogistic,
    fit_coefficient,
    match_feature,
    outcome,
    raw_feature,
)
from ml.dataset.builder import TrainingRow

FRAME = Path("C:/Dev/StratAI-artifacts/phase4/frame_ab1adbf38b43c2f3/frame_rows.json.gz")
SEED = 20261126
HOLDOUT_SEASON = 2027
QUALIFICATION = "qualification"


class Budget:
    def __init__(self, minutes: float) -> None:
        self.deadline = time.monotonic() + minutes * 60
        self.started = time.monotonic()

    def exhausted(self) -> bool:
        return time.monotonic() > self.deadline

    def elapsed(self) -> float:
        return round(time.monotonic() - self.started, 1)


def check_season(season: int, pre_registered_2027_run: bool) -> str:
    """The label a run on this season carries; refuses the 2027 holdout unless that run is explicitly requested."""
    if season in TRAINING_SEASONS:
        raise SystemExit(f"{season} is a training season: an evaluation on it would be in-sample")
    if season >= HOLDOUT_SEASON and not pre_registered_2027_run:
        raise SystemExit(f"{season} is the untouched holdout. Its evaluation is pre-registered and run once: pass "
                         "--pre-registered-2027-run only for that run (see the frozen specs).")
    return "pre_registered_evaluation" if season >= HOLDOUT_SEASON else "retrospective_evidence_only"


def check_database_url(url: str) -> None:
    name = url.rsplit("/", 1)[-1].split("?", 1)[0]
    if not (name == "stratai_test" or name.startswith("stratai_test_")):
        raise SystemExit(f"refusing database {name!r}: rankings are read only from an isolated stratai_test* copy")


def load_frame(path: Path) -> list[TrainingRow]:
    return [TrainingRow.model_validate(r) for r in json.loads(gzip.decompress(path.read_bytes()))]


# --- metrics ---------------------------------------------------------------------------------------------------------


def probability_metrics(ps: Sequence[float], ys: Sequence[bool]) -> dict[str, Any]:
    g2 = g2_bin_consistency(list(ps), list(ys))
    ece = expected_calibration_error(ps, ys)
    return {"n": len(ps), "log_loss": _r(log_loss(ps, ys)), "brier": _r(brier_score(ps, ys)), "auc": _r(roc_auc(ps, ys)),
            "ece": _r(ece), "g1_ece_below_threshold": ece is not None and ece < ECE_THRESHOLD,
            "g2_status": g2.status, "g2_rejected_bins": g2.rejected_bins}


def _r(value: float | None) -> float | None:
    return None if value is None else round(value, 4)


def clustered_difference(rows: Sequence[dict], key_a: str, key_b: str, metric: Callable, reps: int,
                         rng: random.Random) -> dict[str, Any]:
    """metric(a) − metric(b), with a 95% CI from resampling whole events."""
    by_event: dict[str, list[dict]] = defaultdict(list)
    for r in rows:
        by_event[r["event"]].append(r)
    events = sorted(by_event)

    def diff(sample: Sequence[dict]) -> float:
        ys = [r["y"] for r in sample]
        return metric([r[key_a] for r in sample], ys) - metric([r[key_b] for r in sample], ys)

    point = diff(rows)
    boots = sorted(diff([r for e in (rng.choice(events) for _ in events) for r in by_event[e]]) for _ in range(reps))
    lo, hi = boots[int(0.025 * reps)], boots[int(0.975 * reps) - 1]
    return {"difference": round(point, 4), "ci95": [round(lo, 4), round(hi, 4)], "events": len(events), "reps": reps}


# --- stages ----------------------------------------------------------------------------------------------------------


def diagnosis(rows: Sequence[TrainingRow]) -> dict[str, Any]:
    by_season: dict[int, dict[str, list[float]]] = defaultdict(lambda: defaultdict(list))
    mixed: dict[int, list[int]] = defaultdict(lambda: [0, 0])
    for r in rows:
        teams = (*r.red_teams, *r.blue_teams)
        scales = {round(t.epa_scale, 6) for t in teams if t.epa_scale}
        mixed[r.season][0] += len(scales) > 1
        mixed[r.season][1] += 1
        for t in teams:
            for name in ("score_scale", "epa_scale", "epa_total"):
                value = getattr(t, name)
                if value is not None:
                    by_season[r.season][name].append(value)
        raw = raw_feature(r)
        if raw is not None:
            by_season[r.season]["abs_raw_difference"].append(abs(raw))
        x = match_feature(r)
        if x is not None:
            by_season[r.season]["abs_normalized_difference"].append(abs(x))
    out = {}
    for season in sorted(by_season):
        values = by_season[season]
        out[str(season)] = {f"median_{k}": round(statistics.median(v), 3) for k, v in sorted(values.items())}
        out[str(season)]["share_of_matches_mixing_epa_seasons"] = round(mixed[season][0] / mixed[season][1], 4)
    train = [s for s in sorted(by_season) if s in TRAINING_SEASONS]
    if train:
        base = statistics.fmean(statistics.median(by_season[s]["score_scale"]) for s in train)
        for season in sorted(by_season):
            out[str(season)]["score_scale_vs_training_mean"] = round(
                statistics.median(by_season[season]["score_scale"]) / base, 2)
    return out


def win_probability(rows: Sequence[TrainingRow], season: int, served_predict: Callable[[TrainingRow], float] | None,
                    reps: int, rng: random.Random) -> dict[str, Any]:
    candidate = NormEpaLogistic.fit(rows)
    train_raw = [r for r in rows if r.season in TRAINING_SEASONS and outcome(r) is not None
                 and raw_feature(r) is not None and match_feature(r) is not None]
    raw_b = fit_coefficient([raw_feature(r) for r in train_raw], [outcome(r) for r in train_raw])  # type: ignore[misc]
    base_rate = statistics.fmean(1.0 if outcome(r) else 0.0 for r in train_raw)


    out: dict[str, Any] = {"candidate_coefficient": round(candidate.coefficient, 6), "raw_epa_coefficient": round(raw_b, 8),
                           "training_rows": len(train_raw), "training_base_rate": round(base_rate, 4)}
    for level in (QUALIFICATION, "playoff"):
        evaluated = []
        for r in rows:
            if r.season != season or outcome(r) is None or (r.comp_level == QUALIFICATION) != (level == QUALIFICATION):
                continue
            p = candidate.predict(r)
            raw = raw_feature(r)
            if p is None or raw is None:
                continue  # EPA-complete only: the population the served label covers
            entry = {"event": r.event_key, "y": bool(outcome(r)), "candidate": p,
                     "raw_epa_logistic": 1 / (1 + math.exp(-raw_b * raw)), "base_rate": base_rate}
            if served_predict is not None:
                entry["served_m6m7"] = float(served_predict(r))
            evaluated.append(entry)
        keys = [k for k in ("candidate", "served_m6m7", "raw_epa_logistic", "base_rate") if evaluated and k in evaluated[0]]
        result = {k: probability_metrics([e[k] for e in evaluated], [e["y"] for e in evaluated]) for k in keys}
        if level == QUALIFICATION and evaluated:
            comparisons = {}
            for other in [k for k in keys if k != "candidate"]:
                comparisons[f"candidate_minus_{other}_log_loss"] = clustered_difference(
                    evaluated, "candidate", other, log_loss, reps, rng)
                comparisons[f"candidate_minus_{other}_brier"] = clustered_difference(
                    evaluated, "candidate", other, brier_score, reps, rng)
            result["comparisons"] = comparisons
        out[level] = result
    return out


def ranking(rows: Sequence[TrainingRow], season: int, final_ranks: dict, served_rating: Callable | None, reps: int,
            rng: random.Random) -> dict[str, Any]:
    from ml.backtest.ranking_midpoint import FIRST, LAST, MIDPOINT, decision_snapshots, evaluate_ranking

    neg = ranking_blend.MISSING
    rules = {"candidate_blend": ranking_blend.blend_rating_for_evaluation,
             "raw_epa": lambda f: f.epa_total if f.epa_total is not None else neg,
             "in_event_average": lambda f: f.average_score / 3 if f.average_score is not None else neg}
    if served_rating is not None:
        rules["served_m5v2"] = served_rating
    season_rows = [r for r in rows if r.season == season]
    out: dict[str, Any] = {}
    for name, rule in (("first", FIRST), ("midpoint", MIDPOINT), ("last", LAST)):
        snapshots = decision_snapshots(season_rows, rule)
        evaluations = {k: evaluate_ranking(fn, snapshots, final_ranks) for k, fn in rules.items()}
        res: dict[str, Any] = {k: {"spearman": _r(v.spearman), "top8_recall": _r(v.top_k_recall),
                                   "events": v.events_scored} for k, v in evaluations.items()}
        events = sorted(set.intersection(*[set(v.per_event) for v in evaluations.values()]))
        for other in [k for k in rules if k != "candidate_blend"]:
            diffs = [evaluations["candidate_blend"].per_event[e]["spearman"] - evaluations[other].per_event[e]["spearman"]
                     for e in events if evaluations["candidate_blend"].per_event[e]["spearman"] is not None
                     and evaluations[other].per_event[e]["spearman"] is not None]
            if not diffs:
                continue
            boots = sorted(statistics.fmean(rng.choice(diffs) for _ in diffs) for _ in range(reps))
            res[f"candidate_minus_{other}"] = {"mean": round(statistics.fmean(diffs), 4),
                                               "ci95": [round(boots[int(0.025 * reps)], 4),
                                                        round(boots[int(0.975 * reps) - 1], 4)],
                                               "candidate_better_events": sum(d > 0 for d in diffs),
                                               "events": len(diffs)}
        out[name] = res
    return out


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--frame", type=Path, default=FRAME)
    parser.add_argument("--season", type=int, default=2026)
    parser.add_argument("--pre-registered-2027-run", action="store_true")
    parser.add_argument("--reps", type=int, default=1000)
    parser.add_argument("--budget-minutes", type=float, default=30.0)
    parser.add_argument("--skip-served", action="store_true", help="do not load the served models")
    parser.add_argument("--skip-ranking", action="store_true", help="no database: win probability and diagnosis only")
    args = parser.parse_args(argv)

    label = check_season(args.season, args.pre_registered_2027_run)
    budget = Budget(args.budget_minutes)
    rng = random.Random(SEED)
    result: dict[str, Any] = {"candidates": ["WP-NORM-EPA-v1", "RANK-BLEND-v1"], "season": args.season,
                              "label": label, "frame": str(args.frame), "seed": SEED, "reps": args.reps,
                              "partial": False}

    def finish() -> int:
        result["elapsed_seconds"] = budget.elapsed()
        args.out.write_text(json.dumps(result, indent=1, default=str), encoding="utf-8")
        print(f"wrote {args.out} ({'PARTIAL' if result['partial'] else 'complete'}, {result['elapsed_seconds']} s)")
        return 0

    rows = load_frame(args.frame)
    result["frame_rows"] = len(rows)
    if not any(r.season == args.season for r in rows):
        raise SystemExit(f"the frame has no {args.season} rows")
    result["diagnosis"] = diagnosis(rows)

    served_win = served_rank = None
    if not args.skip_served:
        from scripts.local_test_env import PINS

        os.environ.update({k: v for k, v in PINS.items() if k != "DATABASE_URL"})
        from api.ml_loading import load_pinned_ranking_model, load_pinned_win_prob_model
        from data.config import Settings

        settings = Settings()
        win_model, rank_model = load_pinned_win_prob_model(settings), load_pinned_ranking_model(settings)
        served_win = getattr(win_model, "model", win_model).predict_win_prob if win_model else None
        served_rank = getattr(rank_model, "model", rank_model).predict_rating if rank_model else None
        result["served_models_loaded"] = {"win_probability": served_win is not None, "ranking": served_rank is not None}

    if budget.exhausted():
        result["partial"] = True
        return finish()
    result["win_probability"] = win_probability(rows, args.season, served_win, args.reps, rng)

    if not args.skip_ranking:
        if budget.exhausted():
            result["partial"] = True
            return finish()
        from data.config import Settings
        from data.rankings import read_final_ranks_for_season
        from database.connection import Database, DatabaseConfig

        url = str(Settings().database_url)
        check_database_url(url)
        final_ranks = read_final_ranks_for_season(Database(DatabaseConfig(url)), args.season)
        result["ranking"] = ranking(rows, args.season, final_ranks, served_rank, args.reps, rng)
    return finish()


if __name__ == "__main__":
    sys.exit(main())
