"""Locked naive baselines: raw Statbotics EPA (ranking) and a logistic
win-probability model fit on EPA-sum difference alone (win-prob).

Phase 4 Milestone 4 (docs/P4Milestones.md). "Locked" means exactly what it
says: once this milestone's real, dated backtest numbers are recorded in
RUNNING_NOTES.md, these two models and whatever parameters get fit into them
must not change without a new, separately-dated entry -- they are the
documented bar every later Phase 4 model (M5's ranking model, M6's win-prob
model) is required to beat, not a moving target.

Both classes implement ml.backtest.harness.Model, each supporting exactly
one of predict_rating/predict_win_prob -- per that protocol's own design,
raising NotImplementedError for the capability it does not have.

RawEpaRankingBaseline
=====================
"Raw Statbotics EPA" per the milestone's own wording -- read directly from
TeamFeatures.epa_total, never fit, never adjusted. fit() is therefore a
genuine no-op: there is nothing to learn, by design, for a baseline whose
entire point is being the simplest possible reference point. A team with no
EPA (TeamFeatures.epa_total_present=False -- a real, expected case for a
team's first eligible event, per Milestone 1's EPA_WITHHELD_NO_PRIOR_EVENT)
is given float("-inf") rather than a fabricated number: -inf sorts below
every real EPA value, so an un-rated team is never mistaken for a weak-but-
measured one and never wins a ranking comparison it has no evidence for.

EpaWinProbBaseline
==================
"Logistic on EPA-sum difference" -- literally, not "the standard EPA
win-prob formula" alternative the milestone also offers. That alternative
was considered and rejected here: Statbotics does not publish one fixed,
citable win-probability formula in their own documentation or source that
this project could verify and cite, and inventing one under that name would
be exactly the kind of unverified-external-formula mistake this codebase
has already been burned by once (RUNNING_NOTES.md, 2026-07-24, "Rejected:
checking epa_total against epa_auto+epa_teleop+epa_endgame -- any tolerance
would be invented statistics"). A genuine, fit, single-parameter logistic
is auditable on its own terms instead: fit() maximizes the likelihood of
p = sigmoid(scale * (red_epa_sum - blue_epa_sum)) over every eligible
training row via Newton-Raphson (concave in one parameter, converges in a
handful of iterations, no numpy/scipy needed).

Deliberately no intercept term. An intercept would let the model predict
something other than exactly 0.5 when both alliances have identical EPA,
and more importantly would break "symmetric by construction": swapping red
and blue negates the one feature (the difference) and sigmoid(-x) = 1 -
sigmoid(x) is an exact identity regardless of what scale turns out to be --
an intercept term would not cancel the same way. This is what makes the
milestone's own named symmetry test hold structurally, not just empirically.

A match where either alliance has any team with epa_total_present=False has
no well-defined EPA-sum and is excluded from both fitting and prediction --
never treated as contributing 0 EPA. Treating an absent value as 0 is
exactly the imputation CLAUDE.md's ML principles and P4Milestones.md's own
standing rule ("insufficient_data propagates -- a missing defense/feeding
value is never silently 0") forbid, applied here to EPA instead of defense/
feeding. predict_win_prob raises ValueError rather than guess when called on
an EPA-incomplete match; the caller (Milestone 4's own backtest runner, not
this module) is responsible for filtering to EPA-complete rows before
running this baseline through Milestone 3's harness, and the excluded count
must be reported, never silently dropped.
"""

from __future__ import annotations

import json
import math
from collections.abc import Sequence
from pathlib import Path
from typing import Self

from ml.dataset.builder import LABEL_RED_WIN, LABEL_TIE, TrainingRow
from ml.features.assembler import MatchFeatureRow, TeamFeatures

__all__ = [
    "BASELINE_VERSION",
    "EpaWinProbBaseline",
    "RawEpaRankingBaseline",
]

# Bumped whenever either baseline's behavior changes -- recorded in every
# save() so a loaded model's provenance is inspectable, matching Milestone
# 2's DATASET_BUILDER_VERSION convention.
BASELINE_VERSION = "1.0.0"


def _sigmoid(x: float) -> float:
    """Numerically stable logistic function -- avoids overflow in exp() for
    large |x| in either direction, unlike the textbook 1/(1+exp(-x)) alone.
    """
    if x >= 0:
        z = math.exp(-x)
        return 1.0 / (1.0 + z)
    z = math.exp(x)
    return z / (1.0 + z)


def _alliance_epa_sum(teams: Sequence[TeamFeatures]) -> float | None:
    """The sum of epa_total across an alliance, or None if the alliance is
    empty or any team's EPA is absent.

    An empty alliance (Milestone 1's documented frc0-placeholder case) is
    None, not 0.0 -- a real absence of any rostered team is not the same
    claim as "this alliance measurably has zero EPA", and conflating the two
    would silently assert something about a roster this function was never
    told exists.
    """
    if not teams:
        return None
    total = 0.0
    for team in teams:
        if not team.epa_total_present:
            return None
        assert team.epa_total is not None  # guaranteed by TeamFeatures' own presence-flag invariant
        total += team.epa_total
    return total


class RawEpaRankingBaseline:
    """Milestone 4's ranking baseline: a team's predicted rating is exactly
    its own Statbotics EPA, nothing else. Implements ml.backtest.harness.Model.
    """

    def fit(self, training_rows: Sequence[TrainingRow]) -> None:
        """A documented no-op. There is nothing to learn: this baseline is
        defined as reading a value directly off TeamFeatures, not as a model
        whose parameters are estimated from data. Milestone 3's harness
        still calls fit() once per fold (its own contract, so every model
        looks identical to the harness), so this must accept the call
        without error -- it just does nothing with it.
        """
        return

    def predict_rating(self, team_features: TeamFeatures) -> float:
        """This team's raw epa_total, or float("-inf") if absent -- see the
        module docstring for why -inf and not a fabricated number.
        """
        if not team_features.epa_total_present:
            return float("-inf")
        assert team_features.epa_total is not None
        return team_features.epa_total

    def predict_win_prob(self, match_features: MatchFeatureRow) -> float:
        raise NotImplementedError(
            "RawEpaRankingBaseline predicts team ratings, not match win probabilities -- "
            "use EpaWinProbBaseline for that evaluation mode"
        )

    def save(self, path: Path) -> None:
        """Writes a version marker, not fitted state -- there is none to
        persist. Still a real file (not a no-op) so a future model registry
        (Milestone 10) can load and version-check this baseline the same
        uniform way it will load a real trained model.
        """
        path.write_text(json.dumps({"baseline": "raw_epa_ranking", "version": BASELINE_VERSION}), encoding="utf-8")

    @classmethod
    def load(cls, path: Path) -> Self:
        data = json.loads(path.read_text(encoding="utf-8"))
        if data.get("baseline") != "raw_epa_ranking":
            raise ValueError(f"{path} does not contain a raw_epa_ranking baseline (found {data.get('baseline')!r})")
        return cls()


class EpaWinProbBaseline:
    """Milestone 4's win-probability baseline: P(red wins) = sigmoid(scale *
    (red_epa_sum - blue_epa_sum)), scale fit by maximum likelihood on
    training data, no intercept. Implements ml.backtest.harness.Model.
    """

    def __init__(self) -> None:
        self._scale: float | None = None
        # Diagnostic counts from the most recent fit() -- not part of the
        # Model protocol, but real, inspectable state for anyone auditing a
        # "locked" baseline's own reproducibility, since a caller cannot
        # otherwise tell how much of their training data actually
        # contributed to the fitted scale.
        self.fit_row_count: int | None = None
        self.fit_excluded_count: int | None = None

    def fit(self, training_rows: Sequence[TrainingRow]) -> None:
        """Fit the single scale parameter by Newton-Raphson maximum
        likelihood over every non-tie, EPA-complete row in training_rows.

        Ties and EPA-incomplete rows are excluded from fitting, counted
        (fit_excluded_count), and never silently dropped without a trace --
        the same discipline ml.backtest.harness.run_win_prob_backtest
        already applies to ties at evaluation time, extended here to
        fitting time and to missing EPA specifically.

        Raises ValueError if zero rows are eligible -- fitting a baseline
        from no data is a caller error to surface loudly, not a silent
        scale=0.0 default that would look like a real, if uninformative, fit.
        """
        diffs: list[float] = []
        labels: list[bool] = []
        for row in training_rows:
            if row.label == LABEL_TIE:
                continue
            red_sum = _alliance_epa_sum(row.red_teams)
            blue_sum = _alliance_epa_sum(row.blue_teams)
            if red_sum is None or blue_sum is None:
                continue
            diffs.append(red_sum - blue_sum)
            labels.append(row.label == LABEL_RED_WIN)

        if not diffs:
            raise ValueError(
                "cannot fit EpaWinProbBaseline: zero rows have both a non-tie label and "
                "complete EPA on both alliances"
            )

        self._scale = _fit_logistic_scale(diffs, labels)
        self.fit_row_count = len(diffs)
        self.fit_excluded_count = len(training_rows) - len(diffs)

    def predict_win_prob(self, match_features: MatchFeatureRow) -> float:
        """P(red wins), symmetric by construction: swapping red_teams and
        blue_teams negates the one feature this model reads, and sigmoid(-x)
        = 1 - sigmoid(x) is an exact identity -- true for any fitted scale,
        not merely observed to hold on test data.

        Raises RuntimeError if called before fit(). Raises ValueError if
        either alliance's EPA is incomplete -- this model never imputes a
        missing EPA to 0; see the module docstring for why. The caller is
        responsible for pre-filtering to EPA-complete matches, exactly as
        fit() itself does internally.
        """
        if self._scale is None:
            raise RuntimeError("predict_win_prob called before fit()")
        red_sum = _alliance_epa_sum(match_features.red_teams)
        blue_sum = _alliance_epa_sum(match_features.blue_teams)
        if red_sum is None or blue_sum is None:
            raise ValueError(
                "cannot predict win probability: at least one alliance's EPA is incomplete "
                "or empty for this match -- callers must filter to EPA-complete matches "
                "before evaluating this baseline, the same way fit() does internally"
            )
        return _sigmoid(self._scale * (red_sum - blue_sum))

    def predict_rating(self, team_features: TeamFeatures) -> float:
        raise NotImplementedError(
            "EpaWinProbBaseline predicts match win probabilities, not team ratings -- "
            "use RawEpaRankingBaseline for that evaluation mode"
        )

    def save(self, path: Path) -> None:
        if self._scale is None:
            raise RuntimeError("cannot save an unfit EpaWinProbBaseline -- call fit() first")
        path.write_text(json.dumps({
            "baseline": "epa_win_prob", "version": BASELINE_VERSION, "scale": self._scale,
            "fit_row_count": self.fit_row_count, "fit_excluded_count": self.fit_excluded_count,
        }), encoding="utf-8")

    @classmethod
    def load(cls, path: Path) -> Self:
        data = json.loads(path.read_text(encoding="utf-8"))
        if data.get("baseline") != "epa_win_prob":
            raise ValueError(f"{path} does not contain an epa_win_prob baseline (found {data.get('baseline')!r})")
        instance = cls()
        instance._scale = data["scale"]
        instance.fit_row_count = data.get("fit_row_count")
        instance.fit_excluded_count = data.get("fit_excluded_count")
        return instance


def _fit_logistic_scale(
    diffs: Sequence[float], labels: Sequence[bool], *, max_iterations: int = 100, tolerance: float = 1e-10,
) -> float:
    """Newton-Raphson maximum-likelihood fit of the single coefficient k in
    p_i = sigmoid(k * diffs[i]), no intercept.

    The log-likelihood sum[y*log(p) + (1-y)*log(1-p)] is concave in k for a
    single feature, so Newton's method converges in a handful of iterations
    from k=0 for any well-behaved (non-perfectly-separable) input -- no
    numpy/scipy optimizer needed for one scalar parameter.

    Perfectly separable input (every positive diff a red win and every
    negative diff a red loss, or similar) has no finite maximum-likelihood
    k -- the true MLE is +/-infinity. This function does not special-case
    that: max_iterations bounds how large a k it can return in practice, a
    documented limitation of a deliberately simple baseline fit rather than
    a case worth adding regularization for before real data ever exhibits it.
    """
    scale = 0.0
    for _ in range(max_iterations):
        gradient = 0.0
        hessian = 0.0
        for x, y in zip(diffs, labels):
            p = _sigmoid(scale * x)
            gradient += x * ((1.0 if y else 0.0) - p)
            hessian -= (x * x) * p * (1.0 - p)
        if hessian == 0.0:
            break
        step = gradient / hessian
        scale -= step
        if abs(step) < tolerance:
            break
    return scale
