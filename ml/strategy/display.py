"""The one odds-presentation rule for both strategy paths (P6-A5, P6-Q10).

- Below 0.05 is shown as "<5%"; above 0.95 as ">95%". A low probability is never shown as a higher point value
  (P6-A5).
- Otherwise the Phase 4 rule: 0.05 steps, rounded symmetrically about 0.5, so display(1 - p) is the complement of
  display(p).
- **Comparing two strategies (P6-Q10):** a difference smaller than one display step is "indistinguishable at model
  resolution". A larger difference is reported as a difference under the model, never as one strategy being
  superior.

The AI recommender and the coach-scenario assessment both use exactly these functions. The internal probability is
never clamped; only its presentation is bounded.
"""

from __future__ import annotations

import math

DISPLAY_STEP = 0.05
DISPLAY_LOW, DISPLAY_HIGH = 0.05, 0.95
BELOW_LOW, ABOVE_HIGH = "<5%", ">95%"
INDISTINGUISHABLE = "indistinguishable at model resolution"
DIFFERS = "differs by at least one display step under the model (not a claim that either strategy is better)"


def rounded_probability(p: float) -> float:
    """The Phase 4 display rounding (api.routes.predictions.display_probability without its clip): a 0.05 step,
    symmetric about 0.5."""
    offset = p - 0.5
    steps = math.floor(abs(offset) / DISPLAY_STEP + 0.5)
    return round(0.5 + math.copysign(steps * DISPLAY_STEP, offset), 2)


def display_odds(p: float | None) -> str | None:
    """The odds as shown: '<5%', '>95%', or a 0.05-step percentage. None when there is no probability."""
    if p is None:
        return None
    if not 0.0 <= p <= 1.0:
        raise ValueError(f"{p} is not a probability")
    if p < DISPLAY_LOW:
        return BELOW_LOW
    if p > DISPLAY_HIGH:
        return ABOVE_HIGH
    return f"{round(rounded_probability(p) * 100)}%"


def compare_odds(p_first: float | None, p_second: float | None) -> dict[str, object]:
    """Two strategies' odds under the same model and inputs, with the P6-Q10 resolution label."""
    if p_first is None or p_second is None:
        return {"difference": None, "label": "not comparable: a probability is unavailable"}
    difference = p_first - p_second
    return {"difference": difference,
            "label": INDISTINGUISHABLE if abs(difference) < DISPLAY_STEP else DIFFERS}
