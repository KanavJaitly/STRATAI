"""Event-bootstrap confidence intervals (Phase 6: P6-M10, PX-1, PX-4, P6-DM1).

Resamples whole events with replacement, because matches within an event are not independent. In each replicate the
statistic is pooled over every unit of the sampled events, which is the same weighting as the point estimate.
Deterministic given the seed.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence

import numpy as np

DEFAULT_RESAMPLES = 2000


def event_bootstrap_mean_ci(values_by_event: Mapping[str, Sequence[float]], *, seed: int,
                            resamples: int = DEFAULT_RESAMPLES, level: float = 0.95) -> dict[str, float | int]:
    """The pooled mean of `values` over all units, with an event-bootstrap percentile CI."""
    events = sorted(values_by_event)
    if not events:
        raise ValueError("no events")
    sums = np.array([float(np.sum(values_by_event[e])) for e in events])
    counts = np.array([len(values_by_event[e]) for e in events], dtype=np.float64)
    if counts.sum() == 0:
        raise ValueError("no units")
    rng = np.random.default_rng(seed)
    draws = rng.integers(0, len(events), size=(resamples, len(events)))
    means = sums[draws].sum(axis=1) / counts[draws].sum(axis=1)
    alpha = (1.0 - level) / 2.0
    return {"mean": float(sums.sum() / counts.sum()), "ci_low": float(np.quantile(means, alpha)),
            "ci_high": float(np.quantile(means, 1.0 - alpha)), "events": len(events), "units": int(counts.sum()),
            "resamples": resamples, "seed": seed}


def ci_excludes_zero(result: Mapping[str, float | int]) -> bool:
    return result["ci_low"] > 0 or result["ci_high"] < 0
