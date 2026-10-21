"""HV-1: the PX historical validation study (`.agent/phase6/P6_PX_HISTORICAL_VALIDATION_SPEC_V1.md`, frozen at
7cf2ef7). Pure: walk-forward folds, their structural assertions, and the per-model and paired statistics.

Diagnostic only. It changes no frozen gate and cannot accept PX-1b (only FINAL-1 on 2027 can).
"""

from __future__ import annotations

import math
from collections import defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from ml.backtest.bootstrap import event_bootstrap_mean_ci
from ml.backtest.metrics import brier_score, expected_calibration_error, log_loss, roc_auc
from ml.playoffs.px1 import PlayoffRow

BOOTSTRAP_SEED = 20261010
CLIP = 1e-12


class FoldError(ValueError):
    """A fold violates walk-forward ordering or event disjointness: HV-1 refuses it."""


@dataclass(frozen=True)
class Fold:
    name: str
    train: tuple[PlayoffRow, ...]
    test: tuple[PlayoffRow, ...]
    excluded: int
    cutoff: datetime | None = None


def season_fold(name: str, rows: Sequence[PlayoffRow], train_seasons: Sequence[int], test_season: int) -> Fold:
    """F1/F2 (spec §2): every row of the training seasons; every row of the test season."""
    return Fold(name, tuple(r for r in rows if r.season in train_seasons),
                tuple(r for r in rows if r.season == test_season), 0)


def within_season_fold(name: str, rows: Sequence[PlayoffRow], season: int,
                       selection: Mapping[str, datetime]) -> Fold:
    """F0 (spec §2): T = the selection moment of the event at index n//2 of the season's events sorted by
    (selection moment, event_key). Train: rows before T. Test: rows of events selected at or after T. The rows of
    earlier-selected events at or after T are excluded and counted."""
    season_rows = [r for r in rows if r.season == season]
    events = sorted({r.event_key for r in season_rows}, key=lambda e: (selection[e], e))
    cutoff = selection[events[len(events) // 2]]
    test_events = {e for e in events if selection[e] >= cutoff}
    train = tuple(r for r in season_rows if r.scheduled_time < cutoff and r.event_key not in test_events)
    test = tuple(r for r in season_rows if r.event_key in test_events)
    return Fold(name, train, test, len(season_rows) - len(train) - len(test), cutoff)


def fold_assertions(fold: Fold, selection: Mapping[str, datetime]) -> dict[str, Any]:
    """Spec §2: every training row precedes every test event's selection moment, and the events are disjoint."""
    if not fold.train or not fold.test:
        raise FoldError(f"{fold.name}: empty train or test")
    latest_train = max(r.scheduled_time for r in fold.train)
    earliest_test_selection = min(selection[r.event_key] for r in fold.test)
    shared = {r.event_key for r in fold.train} & {r.event_key for r in fold.test}
    report = {"latest_train_row": latest_train.isoformat(),
              "earliest_test_selection": earliest_test_selection.isoformat(),
              "time_ordered": latest_train < earliest_test_selection, "shared_events": sorted(shared)}
    if not report["time_ordered"] or shared:
        raise FoldError(f"{fold.name}: not walk-forward ({report})")
    return report


def _logit(p: float) -> float:
    p = min(max(p, CLIP), 1 - CLIP)
    return math.log(p / (1 - p))


def calibration_slope(predictions: Sequence[float], labels: Sequence[bool]) -> dict[str, float | None]:
    """Spec §4: an unpenalized logistic regression of the outcome on logit(p). A slope below 1 means overconfident."""
    from sklearn.linear_model import LogisticRegression

    if len(set(labels)) < 2:
        return {"slope": None, "intercept": None, "reason": "a single outcome class"}
    x = [[_logit(p)] for p in predictions]
    model = LogisticRegression(penalty=None, solver="lbfgs", max_iter=10000).fit(x, [bool(y) for y in labels])
    return {"slope": float(model.coef_[0][0]), "intercept": float(model.intercept_[0])}


def model_summary(predictions: Sequence[float], labels: Sequence[bool], events: Sequence[str], *,
                  train_abs_logit: float | None = None) -> dict[str, Any]:
    """Spec §4's per-model statistics on one fold's test rows."""
    from scripts.phase6_playoff_track import reliability_bins

    test_abs_logit = sum(abs(_logit(p)) for p in predictions) / len(predictions)
    auc = roc_auc(list(predictions), list(labels)) if len(set(labels)) > 1 else None
    return {"rows": len(predictions), "events": len(set(events)),
            "log_loss": log_loss(list(predictions), list(labels)), "brier": brier_score(list(predictions), list(labels)),
            "roc_auc": auc, **({"roc_auc_reason": "a single outcome class"} if auc is None else {}),
            "ece_10": expected_calibration_error(list(predictions), list(labels), n_bins=10),
            "reliability_bins": reliability_bins(list(predictions), list(labels)),
            "calibration": calibration_slope(predictions, labels),
            "mean_abs_logit_test": test_abs_logit, "mean_abs_logit_train": train_abs_logit,
            "abs_logit_ratio": (test_abs_logit / train_abs_logit) if train_abs_logit else None,
            "share_extreme": sum(1 for p in predictions if p < 0.1 or p > 0.9) / len(predictions)}


def paired(candidate: Sequence[float], comparator: Sequence[float], labels: Sequence[bool],
           events: Sequence[str]) -> dict[str, Any]:
    """Spec §4: per-match log-loss and Brier differences (candidate − comparator) with the event-bootstrap CI, and
    the §5 reading of the log-loss CI."""
    ll: dict[str, list[float]] = defaultdict(list)
    br: dict[str, list[float]] = defaultdict(list)
    for p, q, y, e in zip(candidate, comparator, labels, events):
        ll[e].append(log_loss([p], [y]) - log_loss([q], [y]))
        br[e].append((p - y) ** 2 - (q - y) ** 2)
    log_ci = event_bootstrap_mean_ci(ll, seed=BOOTSTRAP_SEED)
    brier_ci = event_bootstrap_mean_ci(br, seed=BOOTSTRAP_SEED)
    reading = ("statistically supported" if log_ci["ci_high"] < 0
               else "point estimate only" if log_ci["mean"] < 0 else "not better")
    better_events = sum(1 for e in ll if sum(ll[e]) < 0)
    return {"log_loss_difference": log_ci, "brier_difference": brier_ci, "reading": reading,
            "frozen_p6_q3_form_ci_below_zero": log_ci["ci_high"] < 0,
            "events_candidate_better": better_events, "events": len(ll),
            "share_events_candidate_better": better_events / len(ll)}


def per_event(predictions: Mapping[str, Sequence[float]], labels: Sequence[bool], events: Sequence[str]
              ) -> dict[str, dict[str, Any]]:
    """Spec §4: each model's log-loss and n per test event."""
    out: dict[str, dict[str, Any]] = {}
    index: dict[str, list[int]] = defaultdict(list)
    for i, e in enumerate(events):
        index[e].append(i)
    for e in sorted(index):
        ys = [labels[i] for i in index[e]]
        out[e] = {"n": len(ys), **{m: log_loss([p[i] for i in index[e]], ys) for m, p in predictions.items()}}
    return out
