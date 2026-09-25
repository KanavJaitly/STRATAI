"""Team rating / ranking model: gradient-boosted regression on point-in-time
team features, trained purely from match outcomes.

Phase 4 Milestone 5 (docs/P4Milestones.md). "Using team_metrics + EPA
features (M1) to predict team-strength / final ranking" -- the milestone's
own wording -- but M3's Model protocol (already ACCEPTED, a hard interface
this module must conform to exactly, not renegotiate) hands fit() only
Sequence[TrainingRow]: match-level rows carrying both alliances' features
plus that match's own outcome and score margin. It never hands fit() a
team's real final event rank -- that is deliberately reserved for
ml.backtest.run_ranking_backtest's own final_ranks parameter, supplied
externally at BACKTEST time only (see ml.backtest.harness's module
docstring and data/rankings.py: no data source in this codebase has ever
landed a team's real final rank, and even now that data/rankings.py closes
that gap, the fix was to make final_ranks an external backtest input, not to
reopen or extend the already-accepted Model.fit() signature).

So this model cannot be trained directly against "final rank" -- there is no
such label available to it. It is trained against a signed, per-team-
appearance margin-contribution target instead, derived purely from each
TrainingRow's own outcome:

    for a team on the winning alliance:  +abs(score_margin)
    for a team on the losing alliance:   -abs(score_margin)
    for a team in a tied match:           0.0

This uses TrainingRow.label (not score_margin's own sign) to decide winner
vs loser, matching that model's own documented caution that label and
score_margin are independently sourced and may rarely diverge (a post-match
penalty adjustment changing the recorded winner without changing the posted
score) -- label is TBA's own authoritative winning_alliance-derived call, so
it is the one this module trusts for direction; score_margin only supplies
magnitude. This is an OPR/DPR-flavored proxy for "how much did this team's
alliance win or lose by", not literally an event ranking -- final ranking in
FRC is actually driven by ranking points, not raw margin, and that gap is a
real, documented limitation, not a hidden one (see this module's own
docstring below, "Known limitation").

Every optional TeamFeatures value (EPA, defense, feeding) is fed to XGBoost
as float("nan") when its presence flag is False, never 0.0 -- this is not a
manual imputation, it is XGBoost's own native missing-value handling
(DMatrix(..., missing=float("nan"))), which learns, from the training data
itself, which branch direction is better when a value is absent, instead of
this module asserting a specific stand-in number. That is the tree-model
-native way to honor CLAUDE.md's "insufficient_data propagates... never
silently 0" rule, not an exception to it.

Known limitation, carried forward openly: raw margin-contribution is a
proxy for team strength, not a model of FRC's actual ranking-point system
(wins/ties/RP tiebreakers). M5's own acceptance gate (beats the M4 raw-EPA
baseline on Spearman / top-8 recall against real final ranks, via
run_ranking_backtest) is the actual test of whether this proxy is good
enough -- and that gate cannot close until real EPA data unblocks M4's own
frozen baseline number (Statbotics has been down throughout this session;
see .agent/phase4/PHASE_STATUS.md). This module and its tests below are
real, working code, not a placeholder -- but the milestone is NOT accepted
until the real backtest runs and beats-baseline is checked against actual
numbers, per this codebase's standing rule against treating synthetic
fixtures as real evidence.
"""

from __future__ import annotations

import base64
import json
from collections.abc import Sequence
from pathlib import Path
from typing import Self

import numpy as np
import xgboost as xgb

from ml.dataset.builder import LABEL_BLUE_WIN, LABEL_RED_WIN, LABEL_TIE, TrainingRow
from ml.features.assembler import MatchFeatureRow, TeamFeatures
from ml.models.team_vector import TEAM_FEATURE_NAMES as FEATURE_NAMES
from ml.models.team_vector import team_features_to_vector as _team_features_to_vector

__all__ = [
    "RANKING_MODEL_VERSION",
    "RankingXGBModel",
]

# Bumped whenever this model's target formulation, feature list, or training
# procedure changes -- recorded in every save(), matching
# ml.models.baselines.BASELINE_VERSION's identical convention.
RANKING_MODEL_VERSION = "1.0.0"

# FEATURE_NAMES/_team_features_to_vector now live in ml.models.team_vector
# (shared with Milestone 6's win-prob model, to avoid duplicating this exact
# vector-construction logic) -- re-imported above under their original local
# names so this module's own tests and callers are unaffected by the move.

_DEFAULT_RANDOM_SEED = 42
_DEFAULT_NUM_BOOST_ROUND = 500
_DEFAULT_EARLY_STOPPING_ROUNDS = 20
_DEFAULT_VALIDATION_FRACTION = 0.2


def _row_targets(row: TrainingRow) -> tuple[float, float]:
    """(red_target, blue_target) for one TrainingRow -- see the module
    docstring for the signed-margin-contribution rule. Direction comes from
    `label` (TBA's own authoritative winner), magnitude from
    abs(score_margin); the two are independently sourced upstream and may
    rarely diverge, so neither is trusted for both direction and magnitude.
    """
    magnitude = abs(row.score_margin)
    if row.label == LABEL_RED_WIN:
        return magnitude, -magnitude
    if row.label == LABEL_BLUE_WIN:
        return -magnitude, magnitude
    if row.label == LABEL_TIE:
        return 0.0, 0.0
    raise ValueError(f"unrecognized label {row.label!r} on row {row.match_key!r}")  # pragma: no cover -- TrainingRow already validates this


def _rows_to_matrix(rows: Sequence[TrainingRow]) -> tuple[np.ndarray, np.ndarray]:
    """Every team-appearance across `rows` as one training sample apiece --
    a row with a 3-robot red alliance and a 3-robot blue alliance contributes
    6 samples, one per rostered team (fewer for a documented short/empty
    alliance, per Milestone 1's own frc0-placeholder case; never padded).
    """
    feature_rows: list[np.ndarray] = []
    targets: list[float] = []
    for row in rows:
        red_target, blue_target = _row_targets(row)
        for team in row.red_teams:
            feature_rows.append(_team_features_to_vector(team))
            targets.append(red_target)
        for team in row.blue_teams:
            feature_rows.append(_team_features_to_vector(team))
            targets.append(blue_target)

    if not feature_rows:
        return np.empty((0, len(FEATURE_NAMES)), dtype=np.float64), np.empty((0,), dtype=np.float64)
    return np.vstack(feature_rows), np.array(targets, dtype=np.float64)


def _validation_split_index(row_count: int, validation_fraction: float) -> int:
    """Index splitting temporally-sorted rows into (train, validation).

    Fewer than 2 rows cannot support a validation fold at all -- returns
    row_count (everything trains, nothing validates) rather than raising,
    since a caller with a genuinely tiny training set should still get a
    fitted model, just without early stopping; fit() documents this
    tradeoff via fit_validation_row_count == 0 rather than hiding it.
    """
    if row_count < 2:
        return row_count
    split_index = int(round(row_count * (1.0 - validation_fraction)))
    split_index = max(1, min(row_count - 1, split_index))
    return split_index


class RankingXGBModel:
    """Milestone 5's ranking model. Implements ml.backtest.harness.Model --
    predict_rating only; predict_win_prob raises NotImplementedError,
    mirroring ml.models.baselines.RawEpaRankingBaseline's identical split.
    """

    def __init__(
        self,
        *,
        random_seed: int = _DEFAULT_RANDOM_SEED,
        num_boost_round: int = _DEFAULT_NUM_BOOST_ROUND,
        early_stopping_rounds: int = _DEFAULT_EARLY_STOPPING_ROUNDS,
        validation_fraction: float = _DEFAULT_VALIDATION_FRACTION,
    ) -> None:
        self._booster: xgb.Booster | None = None
        self._random_seed = random_seed
        self._num_boost_round = num_boost_round
        self._early_stopping_rounds = early_stopping_rounds
        self._validation_fraction = validation_fraction
        # Diagnostic state from the most recent fit() -- not part of the
        # Model protocol, but real inspectable state, matching
        # EpaWinProbBaseline's identical fit_row_count/fit_excluded_count
        # precedent for auditability.
        self.best_iteration: int | None = None
        self.fit_train_row_count: int | None = None
        self.fit_validation_row_count: int | None = None

    def fit(self, training_rows: Sequence[TrainingRow]) -> None:
        """Fit on every team-appearance in training_rows, holding out the
        temporally-last validation_fraction of rows (by scheduled_time, not
        randomly shuffled) as an internal early-stopping fold -- exactly the
        "early stopping on a temporal validation fold" this milestone's own
        brief names, carved out of training_rows since fit() receives no
        separate validation set from the caller.

        Raises ValueError if training_rows is empty or contains zero
        team-appearances (e.g. every row has empty alliances) -- fitting a
        model from no data is a caller error to surface loudly, matching
        EpaWinProbBaseline's identical guarantee.
        """
        if not training_rows:
            raise ValueError("cannot fit RankingXGBModel on zero training rows")

        sorted_rows = sorted(training_rows, key=lambda row: row.scheduled_time)
        split_index = _validation_split_index(len(sorted_rows), self._validation_fraction)
        train_rows, validation_rows = sorted_rows[:split_index], sorted_rows[split_index:]

        X_train, y_train = _rows_to_matrix(train_rows)
        if X_train.shape[0] == 0:
            raise ValueError(
                "cannot fit RankingXGBModel: zero team-appearance samples across every training row "
                "(every alliance in training_rows is empty)"
            )

        params = {
            "objective": "reg:squarederror",
            "seed": self._random_seed,
            "max_depth": 6,
            "eta": 0.1,
            "subsample": 1.0,
            "colsample_bytree": 1.0,
            # Pinned to one thread so retraining the same data is bit-for-bit
            # reproducible (this milestone's own named reproducibility test),
            # not merely reproducible up to floating-point summation-order
            # noise across worker threads.
            "nthread": 1,
        }
        dtrain = xgb.DMatrix(X_train, label=y_train, feature_names=list(FEATURE_NAMES), missing=np.nan)
        evals = [(dtrain, "train")]

        X_val, y_val = _rows_to_matrix(validation_rows)
        if X_val.shape[0] > 0:
            dval = xgb.DMatrix(X_val, label=y_val, feature_names=list(FEATURE_NAMES), missing=np.nan)
            evals.append((dval, "validation"))
            booster = xgb.train(
                params, dtrain, num_boost_round=self._num_boost_round, evals=evals,
                early_stopping_rounds=self._early_stopping_rounds, verbose_eval=False,
            )
            self.best_iteration = booster.best_iteration
        else:
            # Too little temporally-ordered data to carve out a validation
            # fold at all (see _validation_split_index) -- trains for the
            # full requested rounds with no early stopping, documented via
            # fit_validation_row_count == 0 rather than silently pretending
            # early stopping happened.
            booster = xgb.train(params, dtrain, num_boost_round=self._num_boost_round, evals=evals, verbose_eval=False)
            self.best_iteration = None

        self._booster = booster
        self.fit_train_row_count = int(X_train.shape[0])
        self.fit_validation_row_count = int(X_val.shape[0])

    def predict_rating(self, team_features: TeamFeatures) -> float:
        """This team's predicted signed margin-contribution -- higher is
        stronger. Only meaningful as a within-event ordering (per
        ml.backtest.harness.run_ranking_backtest's own contract), not as an
        absolute, cross-event-comparable number.
        """
        if self._booster is None:
            raise RuntimeError("predict_rating called before fit()")
        vector = _team_features_to_vector(team_features).reshape(1, -1)
        dmatrix = xgb.DMatrix(vector, feature_names=list(FEATURE_NAMES), missing=np.nan)
        if self.best_iteration is not None:
            prediction = self._booster.predict(dmatrix, iteration_range=(0, self.best_iteration + 1))
        else:
            prediction = self._booster.predict(dmatrix)
        return float(prediction[0])

    def predict_win_prob(self, match_features: MatchFeatureRow) -> float:
        raise NotImplementedError(
            "RankingXGBModel predicts team ratings, not match win probabilities -- "
            "use a win-probability model (Milestone 6) for that evaluation mode"
        )

    def save(self, path: Path) -> None:
        """Persists the fitted booster (as XGBoost's own JSON model format,
        base64-embedded) plus a metadata envelope -- one file, matching
        ml.models.baselines's single-JSON-file convention rather than a
        second sidecar file this codebase's registry (Milestone 10) would
        otherwise have to track alongside it.
        """
        if self._booster is None:
            raise RuntimeError("cannot save an unfit RankingXGBModel -- call fit() first")
        booster_bytes = bytes(self._booster.save_raw(raw_format="json"))
        envelope = {
            "model": "ranking_xgb",
            "version": RANKING_MODEL_VERSION,
            "feature_names": list(FEATURE_NAMES),
            "random_seed": self._random_seed,
            "best_iteration": self.best_iteration,
            "fit_train_row_count": self.fit_train_row_count,
            "fit_validation_row_count": self.fit_validation_row_count,
            "booster_json_base64": base64.b64encode(booster_bytes).decode("ascii"),
        }
        path.write_text(json.dumps(envelope), encoding="utf-8")

    @classmethod
    def load(cls, path: Path) -> Self:
        data = json.loads(path.read_text(encoding="utf-8"))
        if data.get("model") != "ranking_xgb":
            raise ValueError(f"{path} does not contain a ranking_xgb model (found {data.get('model')!r})")
        saved_feature_names = data.get("feature_names")
        if saved_feature_names != list(FEATURE_NAMES):
            raise ValueError(
                f"{path} was saved with feature list {saved_feature_names!r}, which does not match "
                f"the current assembler's feature list {list(FEATURE_NAMES)!r} -- refusing to load a "
                "model whose features no longer match what this code computes"
            )

        instance = cls(random_seed=data["random_seed"])
        booster = xgb.Booster()
        booster_bytes = base64.b64decode(data["booster_json_base64"])
        booster.load_model(bytearray(booster_bytes))
        instance._booster = booster
        instance.best_iteration = data.get("best_iteration")
        instance.fit_train_row_count = data.get("fit_train_row_count")
        instance.fit_validation_row_count = data.get("fit_validation_row_count")
        return instance
