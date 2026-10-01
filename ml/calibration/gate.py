"""The M7 calibration gate, decision D16 (.agent/phase4/M05_M07_REDESIGN_SPEC.md §2.3).

G1 is D6's ECE < 0.05 (ml.backtest.metrics.expected_calibration_error).
G2 tests each sufficiently populated fixed bin's observed win count against
the exact Poisson-binomial distribution implied by that bin's own individual
predicted probabilities, two-sided, with Holm-Bonferroni across the eligible
bins at alpha = 0.05. With fewer than 2 eligible bins G2 is UNEVALUABLE,
which is not a pass. There is deliberately no practical-difference threshold:
the decision is the statistical test alone.

This replaces the old check_calibration_band(target=0.60) as M7's per-bin
check; that function is kept unchanged for the record.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import asdict, dataclass, field

import numpy as np

from ml.backtest.metrics import expected_calibration_error

N_BINS = 10
MIN_BIN_COUNT = 30  # ml.calibration.calibrator.DEFAULT_MIN_BIN_COUNT
ALPHA = 0.05
ECE_THRESHOLD = 0.05  # D6
MIN_ELIGIBLE_BINS = 2
TIE_TOLERANCE = 1e-7  # relative; R's binom.test convention
SYMMETRY_TOLERANCE = 1e-12

G2_PASS = "pass"
G2_FAIL = "fail"
G2_UNEVALUABLE = "unevaluable"


def bin_index(q: float) -> int:
    """The fixed bin of one prediction -- the same expression as G1's ECE."""
    return min(int(q * N_BINS), N_BINS - 1)


def poisson_binomial_pmf(probabilities: Sequence[float]) -> np.ndarray:
    """Exact distribution of the number of successes of independent Bernoulli(p_i)."""
    p = np.asarray(probabilities, dtype=np.float64)
    pmf = np.zeros(p.size + 1)
    pmf[0] = 1.0
    for i, q in enumerate(p, start=1):
        pmf[1:i + 1] = pmf[1:i + 1] * (1.0 - q) + pmf[0:i] * q
        pmf[0] *= 1.0 - q
    return pmf


def two_sided_p_value(pmf: np.ndarray, observed: int) -> float:
    """Sum of the probabilities of every outcome no more likely than the observed one."""
    threshold = pmf[observed] * (1.0 + TIE_TOLERANCE)
    return float(min(1.0, pmf[pmf <= threshold].sum()))


def central_interval(pmf: np.ndarray) -> tuple[int, int]:
    """Smallest k with CDF >= 0.025, and smallest k with CDF >= 0.975."""
    cdf = np.cumsum(pmf)
    return int(np.searchsorted(cdf, 0.025)), int(np.searchsorted(cdf, 0.975))


def holm(p_values: Sequence[float], alpha: float = ALPHA) -> list[tuple[float, bool]]:
    """Holm-Bonferroni: in ascending order reject p_(j) while p_(j) <= alpha / (m - j + 1),
    stopping at the first non-rejection. Returns (threshold, rejected) in input order;
    ties in p keep input order."""
    m = len(p_values)
    order = sorted(range(m), key=lambda k: (p_values[k], k))
    out: list[tuple[float, bool]] = [(0.0, False)] * m
    still_rejecting = True
    for j, k in enumerate(order, start=1):
        threshold = alpha / (m - j + 1)
        reject = still_rejecting and p_values[k] <= threshold
        still_rejecting = reject
        out[k] = (threshold, reject)
    return out


@dataclass(frozen=True)
class BinTest:
    lower: float
    upper: float
    count: int
    tested: bool
    mean_predicted: float | None = None
    observed_wins: int | None = None
    observed_rate: float | None = None
    expected_wins: float | None = None
    interval_95: tuple[float, float] | None = None
    p_value: float | None = None
    holm_threshold: float | None = None
    rejected: bool | None = None


@dataclass(frozen=True)
class G2Result:
    status: str
    eligible_bins: int
    rejected_bins: int
    bins: list[BinTest] = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)


def g2_bin_consistency(predictions: Sequence[float], labels: Sequence[bool]) -> G2Result:
    if len(predictions) != len(labels):
        raise ValueError(f"predictions ({len(predictions)}) and labels ({len(labels)}) must be the same length")
    members: list[list[int]] = [[] for _ in range(N_BINS)]
    for i, q in enumerate(predictions):
        members[bin_index(q)].append(i)

    raw: list[dict] = []
    for b, idx in enumerate(members):
        entry = {"lower": b / N_BINS, "upper": (b + 1) / N_BINS, "count": len(idx), "tested": len(idx) >= MIN_BIN_COUNT}
        if entry["tested"]:
            q = [predictions[i] for i in idx]
            wins = sum(1 for i in idx if labels[i])
            pmf = poisson_binomial_pmf(q)
            lo, hi = central_interval(pmf)
            entry.update(mean_predicted=float(np.mean(q)), observed_wins=wins, observed_rate=wins / len(idx),
                         expected_wins=float(np.sum(q)), interval_95=(lo / len(idx), hi / len(idx)),
                         p_value=two_sided_p_value(pmf, wins))
        raw.append(entry)

    eligible = [e for e in raw if e["tested"]]
    m = len(eligible)
    if m < MIN_ELIGIBLE_BINS:
        return G2Result(G2_UNEVALUABLE, m, 0, [BinTest(**e) for e in raw])

    decisions = holm([e["p_value"] for e in eligible])
    for e, (threshold, reject) in zip(eligible, decisions):
        e.update(holm_threshold=threshold, rejected=reject)
    rejected = sum(1 for e in raw if e.get("rejected"))
    return G2Result(G2_FAIL if rejected else G2_PASS, m, rejected, [BinTest(**e) for e in raw])


@dataclass(frozen=True)
class CalibrationGateResult:
    ece: float | None
    g1_pass: bool
    g2: G2Result
    g3_max_symmetry_error: float | None
    g3_order_independent: bool | None
    g3_pass: bool
    g4_fit_isolated: bool
    passed: bool

    def to_dict(self) -> dict:
        return {**asdict(self), "g2": self.g2.to_dict()}


def evaluate_calibration_gate(
    predictions: Sequence[float], labels: Sequence[bool], *,
    symmetry_errors: Sequence[float], order_independent: bool, fit_isolated: bool,
) -> CalibrationGateResult:
    """G1-G4 together. passed only if all four pass (G2 unevaluable is not a pass)."""
    ece = expected_calibration_error(predictions, labels)
    g1 = ece is not None and ece < ECE_THRESHOLD
    g2 = g2_bin_consistency(predictions, labels)
    max_symmetry = max(symmetry_errors) if symmetry_errors else None
    g3 = max_symmetry is not None and max_symmetry <= SYMMETRY_TOLERANCE and order_independent
    return CalibrationGateResult(ece, g1, g2, max_symmetry, order_independent, g3, fit_isolated,
                                 g1 and g2.status == G2_PASS and g3 and fit_isolated)
