"""Pure statistical metric functions for backtesting -- no model, no database,
no StratAI-specific vocabulary (no "red"/"blue", no "tie", no TrainingRow).

Phase 4 Milestone 3 (authoritative plan, docs/P4Milestones.md). Deliberately a
sibling of ml.backtest.harness, not folded into it: these functions operate on
plain (prediction, label) / (value, value) sequences, so Milestone 7
(probability calibration) can reuse expected_calibration_error directly for
its reliability diagrams without importing anything about matches, alliances,
or TrainingRow -- the same "pure function, reused unmodified" discipline
Milestone 1 already established for data.metrics.statistics/aggregation.

Every function here is total: given well-formed input it never raises, and
returns None (never a fabricated 0.0 or NaN) exactly when the statistic is
mathematically undefined for that input -- accuracy/log-loss/Brier/ECE need
at least one sample; ROC-AUC and calibration additionally need at least one
positive AND one negative label to be meaningful (an AUC computed over an
all-one-class sample is not "an AUC", it is undefined, and reporting a number
anyway would be exactly the fabricated-confidence failure mode
data.metrics.statistics's own docstrings already reject once for
consistency_rating/reliability_score). Spearman needs at least two points.
No numpy/scipy: Phase 4's own plan defers those dependencies to Milestone 5,
and every metric here is a small, well-known closed-form computation over
lists no larger than one event's or one season's row count.
"""

from __future__ import annotations

import math
from collections.abc import Hashable, Sequence

__all__ = [
    "accuracy",
    "brier_score",
    "expected_calibration_error",
    "log_loss",
    "roc_auc",
    "spearman_correlation",
    "top_k_recall",
]

# log(0) and log(1) are undefined/infinite; a model that is ever asked to
# score a probability of exactly 0.0 or 1.0 is clamped to this epsilon before
# taking a log, the standard convention for binary cross-entropy (sklearn's
# log_loss does the same, via its own `eps` parameter). This is a numerical
# floor, not a statistical claim -- it never changes which side of 0.5 a
# prediction falls on, only prevents -inf.
_LOG_LOSS_EPS = 1e-15


def _clamp_probability(p: float) -> float:
    return min(max(p, _LOG_LOSS_EPS), 1.0 - _LOG_LOSS_EPS)


def accuracy(predictions: Sequence[float], labels: Sequence[bool]) -> float | None:
    """Fraction of predictions on the correct side of 0.5.

    predictions are P(positive) in [0, 1]; labels are the true binary
    outcome. A prediction of exactly 0.5 is scored as incorrect regardless of
    the true label -- there is no principled way to credit a coin-flip
    prediction with "correct", and silently rounding it either direction
    would inflate accuracy on a model that is honestly reporting maximum
    uncertainty.
    """
    if len(predictions) != len(labels):
        raise ValueError(f"predictions ({len(predictions)}) and labels ({len(labels)}) must be the same length")
    if not predictions:
        return None
    # p == 0.5 is excluded from the (p > 0.5) == bool(y) comparison on
    # purpose: that comparison alone would silently score p=0.5 as "predicted
    # False" (since 0.5 > 0.5 is False), crediting a coin-flip prediction as
    # correct whenever the true label happened to be False -- exactly the
    # asymmetric accident this function's own docstring promises does not
    # happen.
    correct = sum(1 for p, y in zip(predictions, labels) if p != 0.5 and (p > 0.5) == bool(y))
    return correct / len(predictions)


def log_loss(predictions: Sequence[float], labels: Sequence[bool]) -> float | None:
    """Binary cross-entropy: mean of -[y*log(p) + (1-y)*log(1-p)].

    Lower is better, 0 is a perfect, fully-confident-and-correct prediction.
    Predictions are clamped to [_LOG_LOSS_EPS, 1-_LOG_LOSS_EPS] before the log
    -- see the module-level constant's own docstring.
    """
    if len(predictions) != len(labels):
        raise ValueError(f"predictions ({len(predictions)}) and labels ({len(labels)}) must be the same length")
    if not predictions:
        return None
    total = 0.0
    for p, y in zip(predictions, labels):
        p_clamped = _clamp_probability(p)
        total += -(math.log(p_clamped) if y else math.log(1.0 - p_clamped))
    return total / len(predictions)


def brier_score(predictions: Sequence[float], labels: Sequence[bool]) -> float | None:
    """Mean squared error between predicted probability and the 0/1 outcome.

    Lower is better, 0 is perfect. Unlike log_loss, well-defined at p=0/p=1
    with no clamping needed -- (1-1)**2 and (0-0)**2 are both exactly 0, not
    a singularity.
    """
    if len(predictions) != len(labels):
        raise ValueError(f"predictions ({len(predictions)}) and labels ({len(labels)}) must be the same length")
    if not predictions:
        return None
    total = sum((p - (1.0 if y else 0.0)) ** 2 for p, y in zip(predictions, labels))
    return total / len(predictions)


def roc_auc(predictions: Sequence[float], labels: Sequence[bool]) -> float | None:
    """Area under the ROC curve, via the rank-sum (Mann-Whitney U) identity:

        AUC = (sum of ranks assigned to positive-class predictions - n_pos*(n_pos+1)/2)
              / (n_pos * n_neg)

    Avoids numpy/sklearn entirely and avoids the O(n^2) direct pairwise-
    comparison definition -- this is the same statistic, computed in one
    sort. Tied predicted values are given the average rank of the tied
    block (the standard treatment; an untied implementation would silently
    over- or under-credit whichever tied example happened to sort first).

    None (not 0.5, not 1.0) when every label is the same class -- with no
    negative examples, or no positive examples, "how well does this model
    separate the two classes" has no answer, and 0.5 in particular would
    misrepresent a genuinely perfect model tested on an all-positive sample
    as merely "as good as chance".
    """
    if len(predictions) != len(labels):
        raise ValueError(f"predictions ({len(predictions)}) and labels ({len(labels)}) must be the same length")
    n = len(predictions)
    if n == 0:
        return None
    n_pos = sum(1 for y in labels if y)
    n_neg = n - n_pos
    if n_pos == 0 or n_neg == 0:
        return None

    order = sorted(range(n), key=lambda i: predictions[i])
    ranks = [0.0] * n
    i = 0
    while i < n:
        j = i
        while j + 1 < n and predictions[order[j + 1]] == predictions[order[i]]:
            j += 1
        # Ranks are 1-indexed by convention; every index in a tied block
        # [i, j] gets the average of ranks i+1..j+1.
        average_rank = (i + 1 + j + 1) / 2.0
        for k in range(i, j + 1):
            ranks[order[k]] = average_rank
        i = j + 1

    positive_rank_sum = sum(ranks[idx] for idx, y in enumerate(labels) if y)
    return (positive_rank_sum - n_pos * (n_pos + 1) / 2.0) / (n_pos * n_neg)


def expected_calibration_error(
    predictions: Sequence[float], labels: Sequence[bool], *, n_bins: int = 10,
) -> float | None:
    """ECE: bin predictions into n_bins equal-width bins over [0, 1], and
    return the bin-size-weighted mean absolute gap between each bin's average
    predicted probability and its empirical positive rate.

    A perfectly calibrated model (its own "when it says 60%, that alliance
    wins 58-62% of the time" definition of done) has ECE near 0. Empty bins
    contribute nothing and are not treated as zero-error -- a bin with no
    predictions in it says nothing about calibration in that range, honest
    silence rather than a fabricated perfect score for a range the model was
    never actually asked to predict in.
    """
    if len(predictions) != len(labels):
        raise ValueError(f"predictions ({len(predictions)}) and labels ({len(labels)}) must be the same length")
    if not predictions:
        return None
    if n_bins < 1:
        raise ValueError(f"n_bins must be >= 1, got {n_bins}")

    bins: list[list[tuple[float, bool]]] = [[] for _ in range(n_bins)]
    for p, y in zip(predictions, labels):
        # A prediction of exactly 1.0 would compute to bin index n_bins,
        # one past the end -- clamped into the last bin, same convention
        # as a closed-on-the-right final interval.
        index = min(int(p * n_bins), n_bins - 1)
        bins[index].append((p, y))

    total = len(predictions)
    weighted_error = 0.0
    for bin_items in bins:
        if not bin_items:
            continue
        bin_predictions = [p for p, _ in bin_items]
        bin_labels = [y for _, y in bin_items]
        mean_predicted = sum(bin_predictions) / len(bin_predictions)
        empirical_rate = sum(1 for y in bin_labels if y) / len(bin_labels)
        weighted_error += (len(bin_items) / total) * abs(mean_predicted - empirical_rate)
    return weighted_error


def spearman_correlation(x: Sequence[float], y: Sequence[float]) -> float | None:
    """Spearman rank correlation: Pearson correlation of the rank-transformed
    sequences. Tied values share the average rank of their tied block, the
    same treatment roc_auc gives tied predictions, for the same reason (an
    untied tiebreak would silently reward or penalize whichever value
    happened to sort first).

    None when fewer than 2 points (correlation is undefined for a single
    point) or when either sequence is constant (every value identical) --
    a constant sequence has zero variance, so "correlation with it" is
    undefined, not 0.
    """
    if len(x) != len(y):
        raise ValueError(f"x ({len(x)}) and y ({len(y)}) must be the same length")
    n = len(x)
    if n < 2:
        return None

    rx = _average_ranks(x)
    ry = _average_ranks(y)

    mean_rx = sum(rx) / n
    mean_ry = sum(ry) / n
    cov = sum((a - mean_rx) * (b - mean_ry) for a, b in zip(rx, ry))
    var_x = sum((a - mean_rx) ** 2 for a in rx)
    var_y = sum((b - mean_ry) ** 2 for b in ry)
    if var_x == 0.0 or var_y == 0.0:
        return None
    return cov / math.sqrt(var_x * var_y)


def _average_ranks(values: Sequence[float]) -> list[float]:
    """1-indexed ranks, tied values receiving the average rank of their block."""
    n = len(values)
    order = sorted(range(n), key=lambda i: values[i])
    ranks = [0.0] * n
    i = 0
    while i < n:
        j = i
        while j + 1 < n and values[order[j + 1]] == values[order[i]]:
            j += 1
        average_rank = (i + 1 + j + 1) / 2.0
        for k in range(i, j + 1):
            ranks[order[k]] = average_rank
        i = j + 1
    return ranks


def top_k_recall(
    predicted_order: Sequence[Hashable], actual_order: Sequence[Hashable], *, k: int = 8,
) -> float | None:
    """Fraction of the true top-k identities that also appear in the
    predicted top-k, by identity (e.g. a team_number int, or any hashable
    label) -- not by position, so a model that gets the right 8 teams in the
    wrong order still scores a perfect 1.0. That is deliberate: "top-8
    recall" asks whether the model identified the right *set* of contenders,
    which is what alliance-selection/playoff-contention questions actually
    need; a model does not need to also get seed order right to have found
    the right 8 teams.

    k is reduced to len(actual_order) when the field is smaller than k (a
    real case for a small off-season event) -- rather than raising or
    silently returning a number computed against a k the event never had.
    None if actual_order is empty (no ground truth to recall against) or if
    predicted_order is empty (a model that named zero teams recalled none of
    them, but reporting recall=0.0 for "the model was never actually asked"
    would misrepresent a caller error as a real finding).
    """
    if not actual_order:
        return None
    if not predicted_order:
        return None
    effective_k = min(k, len(actual_order))
    true_top_k = set(actual_order[:effective_k])
    predicted_top_k = set(predicted_order[:effective_k])
    return len(true_top_k & predicted_top_k) / len(true_top_k)
