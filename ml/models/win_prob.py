"""Win-probability model, symmetric by construction.

Phase 4 Milestone 6 (docs/P4Milestones.md). The milestone's own brief offers
two structural ways to make alliance-order antisymmetry a guarantee rather
than an observation: "model on red-blue feature differences, or average
f(R,B) with 1-f(B,R)". This module takes the second option, deliberately,
for a concrete reason the first option cannot give here:

    A raw-difference approach only guarantees swap(red, blue) => p -> 1-p if
    the underlying regressor's *output* is an odd function of its input
    difference vector (f(-x) = -f(x)) -- true for a single linear term with
    no intercept (exactly why ml.models.baselines.EpaWinProbBaseline's
    single-parameter logistic gets symmetry for free), but NOT true in
    general for a gradient-boosted tree ensemble over a 16-wide feature
    difference vector. Trees are not odd functions of their input by
    construction, so training XGBoost on (red_vector - blue_vector) would
    only make symmetry an *empirical* property of the fitted trees, exactly
    the "merely observed" failure mode this milestone's own brief calls out
    by name.

    The average-of-two-evaluations construction is a guarantee for ANY base
    predictor, including an arbitrary tree ensemble, with no assumption
    about its internal symmetry at all:

        p(R, B) = ( raw(R, B) + (1 - raw(B, R)) ) / 2

    Expanding p(B, R) the same way and adding: p(R, B) + p(B, R) =
    ( raw(R,B) - raw(R,B) ) / 2 + ( raw(B,R) - raw(B,R) ) / 2 + 1 = 1,
    exactly, for any deterministic raw(). This is real algebra, not a claim
    about the model's own weights -- it holds even for a raw() that is a
    provably biased or asymmetric function of its two arguments, which is
    also exactly the property Milestone 8's audit needs a *deliberately-
    leaky* fixture model to exercise: this construction still forces the
    exposed p(R, B) to be exactly symmetric even when raw() itself is not.

raw() itself is one XGBoost regressor over the concatenation of both
alliances' aggregated feature vectors (red_vector, blue_vector), trained to
predict P(the first-named alliance wins) from real match outcomes -- so
"raw(B, R)" above is a real second call to the same fitted model with the
argument order swapped, not a different model. Each alliance's 16-wide
vector is ml.models.team_vector's team-level vector, summed across that
alliance's rostered teams (mirroring ml.models.baselines._alliance_epa_sum's
existing sum-across-alliance precedent) -- NaN, not 0.0, propagates through
plain floating-point addition whenever ANY team on that alliance lacks a
given feature, so an alliance-level feature is only ever a real number when
every rostered team's own value is real. This is per-feature, not a single
blanket "any team missing anything" check: a team missing only defense_score
still contributes fully to every other feature the alliance vector carries.

The model sees only alliance-aggregated team_metrics/EPA features -- no
field anywhere in this module's input encodes who proposed an alliance, a
coach's own strategy, or "AI recommendation" provenance, satisfying the
milestone's own "no-strategy-leakage" requirement structurally: there is
simply nothing in TeamFeatures/MatchFeatureRow for such a field to be.

Order-independence (same alliances, different call order -> identical
output) follows for free from predict_win_prob being a pure, stateless
function of its MatchFeatureRow argument -- there is no cache, counter, or
other mutable state anywhere in this class that could make repeated or
reordered calls diverge.

Known limitation, carried forward openly, same spirit as
ml.models.ranking_xgb's own documented one: this model's real, dated
beats-M4-baseline log-loss/Brier comparison (the milestone's actual
acceptance gate) needs real EPA data, currently blocked by the Statbotics
outage recorded in .agent/phase4/PHASE_STATUS.md. This module and its tests
are real, working code -- not a placeholder -- but the milestone is NOT
accepted until that real backtest runs.
"""

from __future__ import annotations

import base64
import json
from collections.abc import Sequence
from pathlib import Path
from typing import Self

import numpy as np
import xgboost as xgb

from ml.dataset.builder import LABEL_RED_WIN, LABEL_TIE, TrainingRow
from ml.features.assembler import MatchFeatureRow, TeamFeatures
from ml.models.team_vector import TEAM_FEATURE_NAMES, team_features_to_vector

__all__ = [
    "WIN_PROB_MODEL_VERSION",
    "WinProbXGBModel",
]

# Bumped whenever this model's feature list or training procedure changes --
# recorded in every save(), matching ml.models.baselines.BASELINE_VERSION
# and ml.models.ranking_xgb.RANKING_MODEL_VERSION's identical convention.
WIN_PROB_MODEL_VERSION = "1.0.0"

# One alliance's vector is TEAM_FEATURE_NAMES summed across its rostered
# teams; the model's actual input is (red_alliance_vector, blue_alliance_
# vector) concatenated, so its own feature list is twice as wide, distinctly
# named per alliance side so a saved model's feature list is unambiguous
# about which half is which -- refused at load time if it doesn't match,
# same guard ml.models.ranking_xgb.RankingXGBModel.load already applies.
FEATURE_NAMES: tuple[str, ...] = tuple(f"red_{name}" for name in TEAM_FEATURE_NAMES) + tuple(
    f"blue_{name}" for name in TEAM_FEATURE_NAMES
)

_DEFAULT_RANDOM_SEED = 42
_DEFAULT_NUM_BOOST_ROUND = 500
_DEFAULT_EARLY_STOPPING_ROUNDS = 20
_DEFAULT_VALIDATION_FRACTION = 0.2


def _alliance_vector(teams: Sequence[TeamFeatures]) -> np.ndarray:
    """One alliance's aggregated feature vector: TEAM_FEATURE_NAMES summed
    across every rostered team. An empty alliance (Milestone 1's documented
    frc0-placeholder case) gives an all-NaN vector, not a fabricated all-zero
    one -- there is no rostered team to have summed anything from.
    """
    if not teams:
        return np.full(len(TEAM_FEATURE_NAMES), np.nan, dtype=np.float64)
    return np.sum(np.vstack([team_features_to_vector(team) for team in teams]), axis=0)


def _match_input_vector(red_teams: Sequence[TeamFeatures], blue_teams: Sequence[TeamFeatures]) -> np.ndarray:
    """The model's real input for one (red, blue) argument order: the two
    alliance vectors concatenated, red first. Swapping the two arguments
    (calling with (blue_teams, red_teams)) is exactly "raw(B, R)" in the
    module docstring's algebra.
    """
    return np.concatenate([_alliance_vector(red_teams), _alliance_vector(blue_teams)])


def _validation_split_index(row_count: int, validation_fraction: float) -> int:
    """Identical rule to ml.models.ranking_xgb's own helper -- not imported
    from there to keep this module's temporal-split policy independently
    readable and changeable without coupling the two models' training
    procedures together; the logic is three lines, not worth a shared
    dependency for.
    """
    if row_count < 2:
        return row_count
    split_index = int(round(row_count * (1.0 - validation_fraction)))
    split_index = max(1, min(row_count - 1, split_index))
    return split_index


def _rows_to_matrix(rows: Sequence[TrainingRow]) -> tuple[np.ndarray, np.ndarray]:
    """Every non-tie TrainingRow becomes one training sample: the
    concatenated (red, blue) alliance vectors as input, 1.0 if red won and
    0.0 if blue won as the target. Ties are excluded from fitting -- there
    is no well-defined "which alliance won" label to regress a probability
    toward, the same exclusion ml.models.baselines.EpaWinProbBaseline.fit
    already applies for the identical reason.
    """
    feature_rows: list[np.ndarray] = []
    targets: list[float] = []
    for row in rows:
        if row.label == LABEL_TIE:
            continue
        feature_rows.append(_match_input_vector(row.red_teams, row.blue_teams))
        targets.append(1.0 if row.label == LABEL_RED_WIN else 0.0)

    if not feature_rows:
        return np.empty((0, len(FEATURE_NAMES)), dtype=np.float64), np.empty((0,), dtype=np.float64)
    return np.vstack(feature_rows), np.array(targets, dtype=np.float64)


class WinProbXGBModel:
    """Milestone 6's win-probability model. Implements
    ml.backtest.harness.Model -- predict_win_prob only; predict_rating
    raises NotImplementedError, mirroring
    ml.models.baselines.EpaWinProbBaseline's identical split.
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
        self.best_iteration: int | None = None
        self.fit_train_row_count: int | None = None
        self.fit_validation_row_count: int | None = None
        self.fit_excluded_tie_count: int | None = None

    def fit(self, training_rows: Sequence[TrainingRow]) -> None:
        """Fit on every non-tie row, holding out the temporally-last
        validation_fraction (by scheduled_time) as an internal early-stopping
        fold -- identical procedure and rationale to
        ml.models.ranking_xgb.RankingXGBModel.fit, applied to this model's
        own (concatenated-alliance-vector, red-won) samples instead.

        Raises ValueError if training_rows is empty or every row is a tie
        (zero eligible samples) -- fitting from no data is a caller error to
        surface loudly, matching every other model in this codebase.
        """
        if not training_rows:
            raise ValueError("cannot fit WinProbXGBModel on zero training rows")

        sorted_rows = sorted(training_rows, key=lambda row: row.scheduled_time)
        tie_count = sum(1 for row in sorted_rows if row.label == LABEL_TIE)
        split_index = _validation_split_index(len(sorted_rows), self._validation_fraction)
        train_rows, validation_rows = sorted_rows[:split_index], sorted_rows[split_index:]

        X_train, y_train = _rows_to_matrix(train_rows)
        if X_train.shape[0] == 0:
            raise ValueError(
                "cannot fit WinProbXGBModel: zero non-tie training rows (every row is a tie)"
            )

        params = {
            "objective": "binary:logistic",
            "seed": self._random_seed,
            "max_depth": 6,
            "eta": 0.1,
            "subsample": 1.0,
            "colsample_bytree": 1.0,
            # Single-threaded for bit-for-bit reproducibility, same
            # rationale as RankingXGBModel's identical setting.
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
            booster = xgb.train(params, dtrain, num_boost_round=self._num_boost_round, evals=evals, verbose_eval=False)
            self.best_iteration = None

        self._booster = booster
        self.fit_train_row_count = int(X_train.shape[0])
        self.fit_validation_row_count = int(X_val.shape[0])
        self.fit_excluded_tie_count = tie_count

    def _raw_predict(self, red_teams: Sequence[TeamFeatures], blue_teams: Sequence[TeamFeatures]) -> float:
        """One real evaluation of the underlying (asymmetric-by-default)
        booster: P(the alliance passed first wins), as this model was
        literally trained. Never called directly by predict_win_prob's own
        callers -- see the module docstring for why this alone would not be
        a symmetry guarantee.
        """
        if self._booster is None:
            raise RuntimeError("predict_win_prob called before fit()")
        vector = _match_input_vector(red_teams, blue_teams).reshape(1, -1)
        dmatrix = xgb.DMatrix(vector, feature_names=list(FEATURE_NAMES), missing=np.nan)
        if self.best_iteration is not None:
            prediction = self._booster.predict(dmatrix, iteration_range=(0, self.best_iteration + 1))
        else:
            prediction = self._booster.predict(dmatrix)
        return float(prediction[0])

    def predict_win_prob(self, match_features: MatchFeatureRow) -> float:
        """P(red wins), exactly symmetric by construction -- see the module
        docstring's algebra. Two real evaluations of the same fitted
        booster, forward and swapped, averaged per that algebra.
        """
        forward = self._raw_predict(match_features.red_teams, match_features.blue_teams)
        swapped = self._raw_predict(match_features.blue_teams, match_features.red_teams)
        return 0.5 * (forward + (1.0 - swapped))

    def predict_rating(self, team_features: TeamFeatures) -> float:
        raise NotImplementedError(
            "WinProbXGBModel predicts match win probabilities, not team ratings -- "
            "use RankingXGBModel (Milestone 5) for that evaluation mode"
        )

    def save(self, path: Path) -> None:
        if self._booster is None:
            raise RuntimeError("cannot save an unfit WinProbXGBModel -- call fit() first")
        booster_bytes = bytes(self._booster.save_raw(raw_format="json"))
        envelope = {
            "model": "win_prob_xgb",
            "version": WIN_PROB_MODEL_VERSION,
            "feature_names": list(FEATURE_NAMES),
            "random_seed": self._random_seed,
            "best_iteration": self.best_iteration,
            "fit_train_row_count": self.fit_train_row_count,
            "fit_validation_row_count": self.fit_validation_row_count,
            "fit_excluded_tie_count": self.fit_excluded_tie_count,
            "booster_json_base64": base64.b64encode(booster_bytes).decode("ascii"),
        }
        path.write_text(json.dumps(envelope), encoding="utf-8")

    @classmethod
    def load(cls, path: Path) -> Self:
        data = json.loads(path.read_text(encoding="utf-8"))
        if data.get("model") != "win_prob_xgb":
            raise ValueError(f"{path} does not contain a win_prob_xgb model (found {data.get('model')!r})")
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
        instance.fit_excluded_tie_count = data.get("fit_excluded_tie_count")
        return instance
