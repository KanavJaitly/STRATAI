"""The M6/M7 win-probability display rule (Phase 4 M12; moved here from api.routes.predictions by P7-M3).

A served M6/M7 probability is rounded to PROBABILITY_DISPLAY_STEP, symmetrically about 0.5, and clipped to
[PROBABILITY_DISPLAY_MIN, PROBABILITY_DISPLAY_MAX]: never a precise decimal, never 0% or 100%, and the swapped
matchup always shows the complement. Behaviour is unchanged by the move; api.routes.predictions re-exports it.

This is the M6/M7 rule only. P6 strategy odds use their own rule (ml.strategy.display, P6-A5).
"""

from __future__ import annotations

import math

PROBABILITY_DISPLAY_STEP = 0.05
PROBABILITY_DISPLAY_MIN = 0.05
PROBABILITY_DISPLAY_MAX = 0.95


def display_probability(probability: float) -> float:
    """Round to PROBABILITY_DISPLAY_STEP, symmetrically about 0.5, and clip to
    [PROBABILITY_DISPLAY_MIN, PROBABILITY_DISPLAY_MAX]: display(1 - p) = 1 - display(p),
    so the swapped matchup always shows the complement, and nothing reads as certain."""
    offset = probability - 0.5
    steps = math.floor(abs(offset) / PROBABILITY_DISPLAY_STEP + 0.5)
    shown = 0.5 + math.copysign(steps * PROBABILITY_DISPLAY_STEP, offset)
    return round(min(max(shown, PROBABILITY_DISPLAY_MIN), PROBABILITY_DISPLAY_MAX), 2)


__all__ = ["PROBABILITY_DISPLAY_MAX", "PROBABILITY_DISPLAY_MIN", "PROBABILITY_DISPLAY_STEP", "display_probability"]
