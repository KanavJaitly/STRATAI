"""M5 v2: team ranking model with an attributed contribution target (decision D16 §1).

Frozen specification: .agent/phase4/M05_M07_REDESIGN_SPEC.md §1. M5 v1
(ml.models.ranking_xgb) is kept unchanged as the failed result's record.

Target (§1.1). For each training event e, over its retained qualification
rows Q_e:
- the margin d_m = S_red(m) - S_blue(m);
- a design row a_m with +1 for each red team, -1 for each blue team;
- ridge least squares with lambda = 1: c_e = (A^T A + I)^-1 A^T d;
- sigma_e = population SD of the event's qualification alliance scores;
- y_{i,e} = c_{e,i} / sigma_e, defined only when team i has n_i >= 3 rows in Q_e
  and sigma_e > 0.
Every qualification-row appearance of team i at e is a training sample with
label y_{i,e}. Playoff rows are never samples.

Features (§1.2). The game-point features are divided by the snapshot's causal
scales (TeamFeatures.score_scale / epa_scale): EPA by epa_scale, in-event
scores by score_scale. The scale-free fields are used as they are. A value is
NaN when it or its scale is absent; nothing is imputed.

XGBoost parameters, rounds, early stopping and the temporal validation split
are exactly v1's (§1.4). Nothing is tuned.
"""

from __future__ import annotations

import base64
import json
import statistics
from collections import defaultdict
from collections.abc import Sequence
from pathlib import Path
from typing import Self

import numpy as np
import xgboost as xgb

from ml.dataset.builder import TrainingRow
from ml.features.assembler import MatchFeatureRow, TeamFeatures
from ml.models import ranking_xgb as v1

__all__ = ["FEATURE_NAMES_V2", "RANKING_MODEL_V2_VERSION", "RankingXGBModelV2", "event_contribution_targets"]

RANKING_MODEL_V2_VERSION = "2.0.0"
QUALIFICATION = "qualification"
RIDGE_LAMBDA = 1.0
MIN_QUAL_MATCHES = 3

FEATURE_NAMES_V2: tuple[str, ...] = (
    "epa_total_norm", "epa_auto_norm", "epa_teleop_norm", "epa_endgame_norm",
    "average_score_norm", "score_stddev_norm", "consistency_rating", "reliability_score",
    "average_auto_points_norm",
    "matches_considered", "matches_used",
    "defense_score", "defense_agreement", "defense_observation_count",
    "feeding_score", "feeding_agreement", "feeding_observation_count",
)


def _scaled(value: float | None, present: bool, scale: float | None) -> float:
    return value / scale if present and value is not None and scale is not None else float("nan")


def team_vector_v2(tf: TeamFeatures) -> np.ndarray:
    epa_scale = tf.epa_scale if tf.epa_scale_present else None
    score_scale = tf.score_scale if tf.score_scale_present else None
    nan = float("nan")
    return np.array([
        _scaled(tf.epa_total, tf.epa_total_present, epa_scale),
        _scaled(tf.epa_auto, tf.epa_auto_present, epa_scale),
        _scaled(tf.epa_teleop, tf.epa_teleop_present, epa_scale),
        _scaled(tf.epa_endgame, tf.epa_endgame_present, epa_scale),
        _scaled(tf.average_score, tf.average_score_present, score_scale),
        _scaled(tf.score_stddev, tf.score_stddev_present, score_scale),
        tf.consistency_rating if tf.consistency_rating_present else nan,
        tf.reliability_score if tf.reliability_score_present else nan,
        _scaled(tf.average_auto_points, tf.average_auto_points_present, score_scale),
        float(tf.matches_considered),
        float(tf.matches_used),
        tf.defense_score if tf.defense_score_present else nan,
        tf.defense_agreement if tf.defense_agreement_present else nan,
        float(tf.defense_observation_count),
        tf.feeding_score if tf.feeding_score_present else nan,
        tf.feeding_agreement if tf.feeding_agreement_present else nan,
        float(tf.feeding_observation_count),
    ], dtype=np.float64)


def event_contribution_targets(rows: Sequence[TrainingRow]) -> tuple[dict[tuple[int, str], float], dict[str, int]]:
    """y_{i,e} for every (team, event) with a defined label, plus counts of what was excluded."""
    by_event: dict[str, list[TrainingRow]] = defaultdict(list)
    for row in rows:
        if row.comp_level == QUALIFICATION:
            by_event[row.event_key].append(row)
    targets: dict[tuple[int, str], float] = {}
    excluded = {"events_zero_sigma": 0, "team_events_below_min_matches": 0}
    for event_key in sorted(by_event):
        event_rows = sorted(by_event[event_key], key=lambda r: (r.scheduled_time, r.match_key))
        teams = sorted({t.team_number for r in event_rows for t in (*r.red_teams, *r.blue_teams)})
        index = {team: k for k, team in enumerate(teams)}
        A = np.zeros((len(event_rows), len(teams)))
        d = np.zeros(len(event_rows))
        appearances = np.zeros(len(teams), dtype=int)
        scores: list[int] = []
        for m, r in enumerate(event_rows):
            for t in r.red_teams:
                A[m, index[t.team_number]] += 1.0
                appearances[index[t.team_number]] += 1
            for t in r.blue_teams:
                A[m, index[t.team_number]] -= 1.0
                appearances[index[t.team_number]] += 1
            d[m] = r.score_red - r.score_blue
            scores += [r.score_red, r.score_blue]
        sigma = statistics.pstdev(scores)
        if sigma <= 0:
            excluded["events_zero_sigma"] += 1
            continue
        c = np.linalg.solve(A.T @ A + RIDGE_LAMBDA * np.eye(len(teams)), A.T @ d)
        for team, k in index.items():
            if appearances[k] >= MIN_QUAL_MATCHES:
                targets[(team, event_key)] = float(c[k] / sigma)
            else:
                excluded["team_events_below_min_matches"] += 1
    return targets, excluded


def _samples(rows: Sequence[TrainingRow], targets: dict[tuple[int, str], float]) -> tuple[np.ndarray, np.ndarray]:
    X, y = [], []
    for row in rows:
        if row.comp_level != QUALIFICATION:
            continue
        for t in (*row.red_teams, *row.blue_teams):
            label = targets.get((t.team_number, row.event_key))
            if label is not None:
                X.append(team_vector_v2(t))
                y.append(label)
    if not X:
        return np.empty((0, len(FEATURE_NAMES_V2))), np.empty((0,))
    return np.vstack(X), np.asarray(y)


class RankingXGBModelV2:
    """Implements ml.backtest.harness.Model: predict_rating only."""

    def __init__(self, *, random_seed: int = v1._DEFAULT_RANDOM_SEED,
                 num_boost_round: int = v1._DEFAULT_NUM_BOOST_ROUND,
                 early_stopping_rounds: int = v1._DEFAULT_EARLY_STOPPING_ROUNDS,
                 validation_fraction: float = v1._DEFAULT_VALIDATION_FRACTION) -> None:
        self._booster: xgb.Booster | None = None
        self._random_seed = random_seed
        self._num_boost_round = num_boost_round
        self._early_stopping_rounds = early_stopping_rounds
        self._validation_fraction = validation_fraction
        self.best_iteration: int | None = None
        self.fit_train_sample_count: int | None = None
        self.fit_validation_sample_count: int | None = None
        self.target_exclusions: dict[str, int] = {}
        self.labelled_team_events: int = 0

    def fit(self, training_rows: Sequence[TrainingRow]) -> None:
        if not training_rows:
            raise ValueError("cannot fit RankingXGBModelV2 on zero training rows")
        targets, self.target_exclusions = event_contribution_targets(training_rows)
        self.labelled_team_events = len(targets)
        # §1.4: the temporal last 20% of samples by scheduled_time, using v1's split-index rule
        rows = sorted((r for r in training_rows if r.comp_level == QUALIFICATION),
                      key=lambda r: (r.scheduled_time, r.match_key))
        X_all, y_all = _samples(rows, targets)
        split = v1._validation_split_index(X_all.shape[0], self._validation_fraction)
        X_train, y_train = X_all[:split], y_all[:split]
        X_val, y_val = X_all[split:], y_all[split:]
        if X_train.shape[0] == 0:
            raise ValueError("cannot fit RankingXGBModelV2: no labelled qualification samples")
        params = {"objective": "reg:squarederror", "seed": self._random_seed, "max_depth": 6, "eta": 0.1,
                  "subsample": 1.0, "colsample_bytree": 1.0, "nthread": 1}  # exactly v1's
        names = list(FEATURE_NAMES_V2)
        dtrain = xgb.DMatrix(X_train, label=y_train, feature_names=names, missing=np.nan)
        if X_val.shape[0] > 0:
            dval = xgb.DMatrix(X_val, label=y_val, feature_names=names, missing=np.nan)
            booster = xgb.train(params, dtrain, num_boost_round=self._num_boost_round,
                                evals=[(dtrain, "train"), (dval, "validation")],
                                early_stopping_rounds=self._early_stopping_rounds, verbose_eval=False)
            self.best_iteration = booster.best_iteration
        else:
            booster = xgb.train(params, dtrain, num_boost_round=self._num_boost_round, verbose_eval=False)
            self.best_iteration = None
        self._booster = booster
        self.fit_train_sample_count = int(X_train.shape[0])
        self.fit_validation_sample_count = int(X_val.shape[0])

    def predict_rating(self, team_features: TeamFeatures) -> float:
        if self._booster is None:
            raise RuntimeError("predict_rating called before fit()")
        dmatrix = xgb.DMatrix(team_vector_v2(team_features).reshape(1, -1), feature_names=list(FEATURE_NAMES_V2),
                              missing=np.nan)
        if self.best_iteration is not None:
            return float(self._booster.predict(dmatrix, iteration_range=(0, self.best_iteration + 1))[0])
        return float(self._booster.predict(dmatrix)[0])

    def predict_win_prob(self, match_features: MatchFeatureRow) -> float:
        raise NotImplementedError("RankingXGBModelV2 predicts team ratings, not match win probabilities")

    def feature_gain(self) -> dict[str, float]:
        if self._booster is None:
            raise RuntimeError("feature_gain called before fit()")
        return self._booster.get_score(importance_type="gain")

    def save(self, path: Path) -> None:
        if self._booster is None:
            raise RuntimeError("cannot save an unfit RankingXGBModelV2")
        path.write_text(json.dumps({
            "model": "ranking_xgb_v2", "version": RANKING_MODEL_V2_VERSION, "feature_names": list(FEATURE_NAMES_V2),
            "best_iteration": self.best_iteration,
            "booster": base64.b64encode(bytes(self._booster.save_raw("json"))).decode("ascii"),
        }), encoding="utf-8")

    @classmethod
    def load(cls, path: Path) -> Self:
        data = json.loads(path.read_text(encoding="utf-8"))
        if data.get("model") != "ranking_xgb_v2":
            raise ValueError(f"{path} does not contain a ranking_xgb_v2 model (found {data.get('model')!r})")
        if data.get("feature_names") != list(FEATURE_NAMES_V2):
            raise ValueError("saved feature list does not match FEATURE_NAMES_V2")
        instance = cls()
        booster = xgb.Booster()
        booster.load_model(bytearray(base64.b64decode(data["booster"])))
        instance._booster = booster
        instance.best_iteration = data["best_iteration"]
        return instance
