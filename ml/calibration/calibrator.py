"""Probability calibration layer: fits a calibrator on a model's *raw*
win-probability outputs, never on the season it will be evaluated against.

Phase 4 Milestone 7 (docs/P4Milestones.md). The milestone's own done-means
target ("when it says 60%, that alliance historically wins 58-62% of the
time") is Phase 4's actual phase-level acceptance criterion
(docs/P4Milestones.md's own opening line), so this module's honesty matters
more than most: an isotonic or Platt calibrator fit on the same data it is
then judged against would trivially look well-calibrated on that data by
construction, telling a caller nothing about whether Milestone 6's model
generalizes. Every function here is built around keeping those two data
slices apart, structurally, not by caller discipline alone.

fit_calibrated_win_prob_model is the one function that enforces this
end-to-end: given a full training set for one backtest fold, it carves a
temporal validation slice (the fold's own train_rows, further split by
scheduled_time -- never touching the fold's separate, already-held-out
test_rows at all), fits the underlying win-prob model on the earlier
portion only, computes that model's RAW predictions on the later portion,
and fits the calibrator on those (raw_probability, label) pairs. The
held-out test season is a wholly separate argument this function never
receives -- it is evaluated later, by the caller, through
apply_calibrated_model, and the calibrator has structurally never seen it.

IsotonicCalibrator and PlattCalibrator both reuse scikit-learn's own
implementations (isotonic regression's PAV algorithm; Platt scaling is
plain single-feature logistic regression) rather than a hand-rolled PAV
implementation -- see requirements.txt's own comment for why. Both persist
to one small JSON envelope, matching every other model/baseline in this
codebase's save/load convention: IsotonicCalibrator stores
IsotonicRegression's own X_thresholds_/y_thresholds_ (its de-duplicated,
already-isotonic step-function knots) and reconstructs an identical
regressor from them on load, confirmed by a direct round-trip test rather
than assumed from sklearn's own docs.

compute_reliability_bins and check_calibration_band implement the
milestone's own named "small-bin honesty" requirement: a bin with fewer
than min_bin_count real examples is marked insufficient_sample=True and
never silently reported as passing or failing the 58-62% band -- there is
no reliable empirical rate to check in the first place, and hiding that
would misrepresent confidence exactly where CLAUDE.md's ML principles most
explicitly forbid it ("never exaggerate certainty").
"""

from __future__ import annotations

import base64
import json
import math
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol, Self, runtime_checkable

import numpy as np
from sklearn.isotonic import IsotonicRegression
from sklearn.linear_model import LogisticRegression

from ml.backtest.harness import Model
from ml.dataset.builder import LABEL_RED_WIN, LABEL_TIE, TrainingRow
from ml.features.assembler import MatchFeatureRow

__all__ = [
    "CALIBRATOR_VERSION",
    "BandCheckResult",
    "Calibrator",
    "IsotonicCalibrator",
    "PlattCalibrator",
    "ReliabilityBin",
    "apply_calibrated_model",
    "check_calibration_band",
    "compute_reliability_bins",
    "fit_calibrated_win_prob_model",
]

# Bumped whenever either calibrator's persisted representation changes --
# recorded in every save(), matching every other model in this codebase's
# identical *_VERSION convention.
CALIBRATOR_VERSION = "1.0.0"

# A bin with fewer real examples than this has no reliable empirical rate --
# chosen, not derived: large enough that a single-digit sample can't produce
# a spuriously exact-looking rate (5 examples landing 3-2 reads as "60%" from
# almost no evidence), small enough to still be reachable by a real held-out
# season's own bin sizes. Documented here, not buried in a magic number, so
# a future milestone can revisit it with real data in hand.
DEFAULT_MIN_BIN_COUNT = 30


def _sigmoid(x: float) -> float:
    """Numerically stable logistic function -- the same form
    ml.models.baselines._sigmoid already uses; kept as a local copy rather
    than a shared import since it is five lines of stable, unchanging math,
    not the kind of logic CLAUDE.md's "avoid duplicated logic" is aimed at.
    """
    if x >= 0:
        z = math.exp(-x)
        return 1.0 / (1.0 + z)
    z = math.exp(x)
    return z / (1.0 + z)


@runtime_checkable
class Calibrator(Protocol):
    """The uniform interface both calibrators in this module conform to."""

    def fit(self, raw_probabilities: Sequence[float], labels: Sequence[bool]) -> None:
        """Fit on (raw_probability, label) pairs -- never on test-season data;
        see the module docstring for how that boundary is actually kept."""
        ...

    def calibrate(self, raw_probability: float) -> float:
        """The calibrated probability for one raw model output."""
        ...

    def save(self, path: Path) -> None: ...

    @classmethod
    def load(cls, path: Path) -> Self: ...


class IsotonicCalibrator:
    """Isotonic-regression calibration: a monotonic, non-parametric step
    function fit by scikit-learn's PAV implementation. Makes no assumption
    about the calibration curve's shape beyond monotonicity, at the cost of
    needing more data than Platt scaling to fit reliably.
    """

    def __init__(self) -> None:
        self._regressor: IsotonicRegression | None = None

    def fit(self, raw_probabilities: Sequence[float], labels: Sequence[bool]) -> None:
        if not raw_probabilities:
            raise ValueError("cannot fit IsotonicCalibrator on zero examples")
        if len(raw_probabilities) != len(labels):
            raise ValueError(f"raw_probabilities ({len(raw_probabilities)}) and labels ({len(labels)}) must match")
        X = np.asarray(raw_probabilities, dtype=np.float64)
        y = np.asarray([1.0 if label else 0.0 for label in labels], dtype=np.float64)
        regressor = IsotonicRegression(y_min=0.0, y_max=1.0, out_of_bounds="clip")
        regressor.fit(X, y)
        self._regressor = regressor

    def calibrate(self, raw_probability: float) -> float:
        if self._regressor is None:
            raise RuntimeError("calibrate called before fit()")
        return float(self._regressor.predict([raw_probability])[0])

    def save(self, path: Path) -> None:
        if self._regressor is None:
            raise RuntimeError("cannot save an unfit IsotonicCalibrator -- call fit() first")
        envelope = {
            "calibrator": "isotonic",
            "version": CALIBRATOR_VERSION,
            "x_thresholds": self._regressor.X_thresholds_.tolist(),
            "y_thresholds": self._regressor.y_thresholds_.tolist(),
        }
        path.write_text(json.dumps(envelope), encoding="utf-8")

    @classmethod
    def load(cls, path: Path) -> Self:
        data = json.loads(path.read_text(encoding="utf-8"))
        if data.get("calibrator") != "isotonic":
            raise ValueError(f"{path} does not contain an isotonic calibrator (found {data.get('calibrator')!r})")
        regressor = IsotonicRegression(y_min=0.0, y_max=1.0, out_of_bounds="clip")
        # Refitting on the saved (already-isotonic, de-duplicated) knots
        # reproduces an identical step function -- confirmed by a direct
        # round-trip test, not merely assumed from sklearn's own docs.
        regressor.fit(np.asarray(data["x_thresholds"]), np.asarray(data["y_thresholds"]))
        instance = cls()
        instance._regressor = regressor
        return instance


class PlattCalibrator:
    """Platt-scaling calibration: a single-feature logistic regression on
    the raw probability, sigmoid(coef * raw_probability + intercept). Needs
    less data than isotonic regression to fit reliably, at the cost of
    assuming the miscalibration itself has a sigmoid shape.
    """

    def __init__(self) -> None:
        self._coef: float | None = None
        self._intercept: float | None = None

    def fit(self, raw_probabilities: Sequence[float], labels: Sequence[bool]) -> None:
        if not raw_probabilities:
            raise ValueError("cannot fit PlattCalibrator on zero examples")
        if len(raw_probabilities) != len(labels):
            raise ValueError(f"raw_probabilities ({len(raw_probabilities)}) and labels ({len(labels)}) must match")
        if len(set(labels)) < 2:
            raise ValueError(
                "cannot fit PlattCalibrator: labels contain only one class -- logistic regression "
                "needs at least one example of each outcome"
            )
        X = np.asarray(raw_probabilities, dtype=np.float64).reshape(-1, 1)
        y = np.asarray([1.0 if label else 0.0 for label in labels], dtype=np.float64)
        classifier = LogisticRegression()
        classifier.fit(X, y)
        self._coef = float(classifier.coef_[0][0])
        self._intercept = float(classifier.intercept_[0])

    def calibrate(self, raw_probability: float) -> float:
        if self._coef is None or self._intercept is None:
            raise RuntimeError("calibrate called before fit()")
        return _sigmoid(self._coef * raw_probability + self._intercept)

    def save(self, path: Path) -> None:
        if self._coef is None or self._intercept is None:
            raise RuntimeError("cannot save an unfit PlattCalibrator -- call fit() first")
        envelope = {
            "calibrator": "platt", "version": CALIBRATOR_VERSION,
            "coef": self._coef, "intercept": self._intercept,
        }
        path.write_text(json.dumps(envelope), encoding="utf-8")

    @classmethod
    def load(cls, path: Path) -> Self:
        data = json.loads(path.read_text(encoding="utf-8"))
        if data.get("calibrator") != "platt":
            raise ValueError(f"{path} does not contain a platt calibrator (found {data.get('calibrator')!r})")
        instance = cls()
        instance._coef = data["coef"]
        instance._intercept = data["intercept"]
        return instance


@dataclass(frozen=True)
class ReliabilityBin:
    """One bin of a reliability diagram, over [lower, upper) of predicted
    probability (the final bin is closed on both ends, matching
    ml.backtest.metrics.expected_calibration_error's own clamp-into-last-bin
    convention for a prediction of exactly 1.0).
    """

    lower: float
    upper: float
    count: int
    mean_predicted: float | None
    empirical_rate: float | None
    sufficient_sample: bool


def compute_reliability_bins(
    predictions: Sequence[float], labels: Sequence[bool], *,
    n_bins: int = 10, min_bin_count: int = DEFAULT_MIN_BIN_COUNT,
) -> list[ReliabilityBin]:
    """Every bin over [0, 1], including empty ones -- an empty or
    under-populated bin is still a real bin in the diagram, reported with
    sufficient_sample=False, mean_predicted/empirical_rate=None rather than
    silently omitted (an omitted bin looks identical to "this range never
    came up", which is a different, stronger claim than "it came up too
    rarely to trust").
    """
    if len(predictions) != len(labels):
        raise ValueError(f"predictions ({len(predictions)}) and labels ({len(labels)}) must be the same length")
    if n_bins < 1:
        raise ValueError(f"n_bins must be >= 1, got {n_bins}")

    bin_items: list[list[tuple[float, bool]]] = [[] for _ in range(n_bins)]
    for p, y in zip(predictions, labels):
        index = min(int(p * n_bins), n_bins - 1)
        bin_items[index].append((p, y))

    bins: list[ReliabilityBin] = []
    for index, items in enumerate(bin_items):
        lower, upper = index / n_bins, (index + 1) / n_bins
        count = len(items)
        if count == 0:
            bins.append(ReliabilityBin(lower, upper, 0, None, None, False))
            continue
        mean_predicted = sum(p for p, _ in items) / count
        empirical_rate = sum(1 for _, y in items if y) / count
        bins.append(ReliabilityBin(lower, upper, count, mean_predicted, empirical_rate, count >= min_bin_count))
    return bins


@dataclass(frozen=True)
class BandCheckResult:
    """Whether one target probability's own bin holds the phase-level
    done-means band (e.g. 0.60 -> 0.58-0.62)."""

    target: float
    bin: ReliabilityBin | None
    within_band: bool | None
    lower_bound: float
    upper_bound: float


def check_calibration_band(
    bins: Sequence[ReliabilityBin], *, target: float, tolerance: float = 0.02,
) -> BandCheckResult:
    """Finds the bin containing `target` and checks whether its empirical
    rate falls within [target - tolerance, target + tolerance].

    within_band is None, not True or False, whenever the bin is
    under-populated (sufficient_sample=False) or empty -- there is no
    reliable empirical rate to check, and reporting a boolean either way
    would be exactly the "silently passing" failure mode this milestone's
    own brief names by name ("under-populated bins are flagged, not
    silently passing").
    """
    lower_bound, upper_bound = target - tolerance, target + tolerance
    matching_bin = next((b for b in bins if b.lower <= target < b.upper), None)
    if matching_bin is None or not matching_bin.sufficient_sample or matching_bin.empirical_rate is None:
        return BandCheckResult(target, matching_bin, None, lower_bound, upper_bound)
    within_band = lower_bound <= matching_bin.empirical_rate <= upper_bound
    return BandCheckResult(target, matching_bin, within_band, lower_bound, upper_bound)


def _match_features(row: TrainingRow) -> MatchFeatureRow:
    """The point-in-time feature view of a TrainingRow -- exactly what a
    model's predict_win_prob may see, mirroring ml.backtest.harness's own
    identical (private, so not imported directly) helper."""
    return MatchFeatureRow(
        match_key=row.match_key, as_of=row.scheduled_time, event_key=row.event_key, season=row.season,
        red_teams=row.red_teams, blue_teams=row.blue_teams,
    )


def _raw_predictions_and_labels(model: Model, rows: Sequence[TrainingRow]) -> tuple[list[float], list[bool]]:
    """Non-tie rows only -- a tie has no well-defined "did red win" label to
    calibrate against, the same exclusion every win-prob model and metric in
    this codebase already applies."""
    predictions: list[float] = []
    labels: list[bool] = []
    for row in rows:
        if row.label == LABEL_TIE:
            continue
        predictions.append(model.predict_win_prob(_match_features(row)))
        labels.append(row.label == LABEL_RED_WIN)
    return predictions, labels


def _validation_split_index(row_count: int, validation_fraction: float) -> int:
    """Identical rule to ml.models.ranking_xgb/win_prob's own helpers -- see
    either module's docstring for why each keeps its own copy rather than
    sharing one for three lines of logic."""
    if row_count < 2:
        return row_count
    split_index = int(round(row_count * (1.0 - validation_fraction)))
    split_index = max(1, min(row_count - 1, split_index))
    return split_index


def fit_calibrated_win_prob_model(
    model_factory: Callable[[], Model], training_rows: Sequence[TrainingRow], *,
    calibrator_factory: Callable[[], Calibrator], validation_fraction: float = 0.2,
) -> tuple[Model, Calibrator, dict[str, int]]:
    """Fit a win-prob model AND its calibrator from one training set,
    keeping the calibrator's own fitting data strictly separate from
    whatever model.fit() saw -- see the module docstring for the full
    rationale.

    training_rows is meant to be exactly one backtest Fold's own
    `train_rows` -- this function never receives, and therefore cannot
    touch, that fold's separate `test_rows`. Splits training_rows further,
    temporally (by scheduled_time, not randomly), into a model-fitting
    portion and a later calibration-fitting portion.

    Returns (fitted_model, fitted_calibrator, diagnostics) where diagnostics
    reports how many rows went to each stage and how many ties were
    excluded from calibration fitting, for auditability.
    """
    if not training_rows:
        raise ValueError("cannot fit a calibrated model on zero training rows")

    sorted_rows = sorted(training_rows, key=lambda row: row.scheduled_time)
    split_index = _validation_split_index(len(sorted_rows), validation_fraction)
    model_rows, calibration_rows = sorted_rows[:split_index], sorted_rows[split_index:]

    if not model_rows:
        raise ValueError("cannot fit a calibrated model: zero rows available to fit the underlying model")

    model = model_factory()
    model.fit(model_rows)

    raw_predictions, calibration_labels = _raw_predictions_and_labels(model, calibration_rows)
    if not raw_predictions:
        raise ValueError(
            "cannot fit the calibrator: zero non-tie rows in the temporal validation slice -- "
            "increase validation_fraction or supply more training_rows"
        )

    calibrator = calibrator_factory()
    calibrator.fit(raw_predictions, calibration_labels)

    diagnostics = {
        "model_row_count": len(model_rows),
        "calibration_row_count": len(calibration_rows),
        "calibration_eligible_count": len(raw_predictions),
        "calibration_excluded_tie_count": len(calibration_rows) - len(raw_predictions),
    }
    return model, calibrator, diagnostics


def apply_calibrated_model(
    model: Model, calibrator: Calibrator, rows: Sequence[TrainingRow],
) -> tuple[list[float], list[float], list[bool]]:
    """Evaluate (model, calibrator) against `rows` -- meant to be exactly
    the held-out fold's own `test_rows`, never seen by either fit() call
    above. Returns (raw_predictions, calibrated_predictions, labels), all
    aligned, non-tie rows only -- the three inputs
    compute_reliability_bins/check_calibration_band and
    ml.backtest.metrics' own functions expect.
    """
    raw_predictions, labels = _raw_predictions_and_labels(model, rows)
    calibrated_predictions = [calibrator.calibrate(p) for p in raw_predictions]
    return raw_predictions, calibrated_predictions, labels
