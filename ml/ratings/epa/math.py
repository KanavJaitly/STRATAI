"""Per-match EPA arithmetic (spec §5; reference models/epa/main.py, breakdown.py, math.py).

Each function is the reference's, operation for operation and in numpy, so
that floating-point results can match rather than merely agree to a
tolerance. Arrays passed in are never mutated unless the docstring says so.
"""

from __future__ import annotations

import numpy as np

from ml.ratings.epa.constants import (
    NET_ALGAE_POINTS_2025,
    NO_FOUL,
    NUM_TEAMS,
    PERCENT_FACTOR,
    PERCENT_MAX,
    PERCENT_MIN,
    PERCENT_PIVOT,
    PERCENT_SLOPE,
    PROCESSOR_ALGAE_2025,
    PROCESSOR_ALGAE_POINTS_2025,
    PROCESSOR_ALGAE_REVALUE,
    RP_1,
    RP_2,
    RP_3,
    TELEOP,
    WIN_PROB_K,
)

def unit_sigmoid(x: float) -> float:
    """math.py:37-38."""
    return 1 / (1 + np.exp(-4 * (x - 0.5)))


def inv_unit_sigmoid(x: float) -> float:
    """math.py:41-42."""
    return 0.5 + np.log(x / (1 - x)) / 4


def percent(qual_matches_played: int) -> float:
    """main.py:35-40 for seasons >= 2016: the EWMA step size."""
    prev = min(PERCENT_MAX, max(PERCENT_MIN, PERCENT_MAX - PERCENT_SLOPE * (qual_matches_played - PERCENT_PIVOT)))
    return PERCENT_FACTOR * prev


def alliance_sum(ratings: list[np.ndarray]) -> np.ndarray:
    """main.py:97: the alliance's summed rating vector (a new array)."""
    return np.array(ratings).sum(axis=0)


def post_process_breakdown(season: int, breakdown: np.ndarray, opp_breakdown: np.ndarray) -> np.ndarray:
    """breakdown.py:8-91 for 2024-2026. Mutates and returns ``breakdown``."""
    total_change = 0
    breakdown[RP_1] = unit_sigmoid(breakdown[RP_1])
    breakdown[RP_2] = unit_sigmoid(breakdown[RP_2])
    if season >= 2025:
        breakdown[RP_3] = unit_sigmoid(breakdown[RP_3])
    if season == 2025:
        # processor algae is internally 3 points; add 3 per algae scored by either alliance
        my_processor_algae = breakdown[PROCESSOR_ALGAE_2025]
        opp_processor_algae = opp_breakdown[PROCESSOR_ALGAE_2025]
        processor_algae = my_processor_algae + opp_processor_algae
        breakdown[PROCESSOR_ALGAE_POINTS_2025] += PROCESSOR_ALGAE_REVALUE * my_processor_algae
        breakdown[NET_ALGAE_POINTS_2025] += PROCESSOR_ALGAE_REVALUE * opp_processor_algae
        breakdown[TELEOP] += PROCESSOR_ALGAE_REVALUE * processor_algae
        total_change += PROCESSOR_ALGAE_REVALUE * processor_algae
    breakdown[NO_FOUL] += total_change
    return breakdown


def predicted_rps(season: int, breakdown: np.ndarray) -> tuple[float, float, float]:
    """main.py:104-109."""
    rp_3 = breakdown[RP_3] if season >= 2025 else 0
    return breakdown[RP_1], breakdown[RP_2], rp_3


def win_probability(red_score: float, blue_score: float, score_sd: float) -> float:
    """main.py:125-126."""
    norm_diff = (red_score - blue_score) / score_sd
    return 1 / (1 + 10 ** (WIN_PROB_K * norm_diff))


def post_process_attrib(season: int, epa: np.ndarray, err: np.ndarray, elim: bool) -> np.ndarray:
    """breakdown.py:155-202 for 2024-2026. ``err`` is the per-team error; it is mutated."""
    attrib = epa + err
    if season == 2025:
        update = PROCESSOR_ALGAE_REVALUE * err[PROCESSOR_ALGAE_2025]
        err[PROCESSOR_ALGAE_POINTS_2025] -= update
        err[TELEOP] -= update
        err[NO_FOUL] -= update
        attrib = epa + err
    if elim:
        # ranking points are not updated from playoff matches
        attrib[RP_1] = epa[RP_1]
        attrib[RP_2] = epa[RP_2]
        if season >= 2025:
            attrib[RP_3] = epa[RP_3]
    return attrib


def attribution(
    season: int, epa: np.ndarray, my_err: np.ndarray, opp_err: np.ndarray, elim: bool
) -> np.ndarray:
    """main.py:157-163. margin_func is 0 for every season after 2003."""
    margin = 0
    err = (my_err - margin * opp_err) / (1 + margin)
    return post_process_attrib(season, epa, err / NUM_TEAMS, elim)


def add_observation(mean: np.ndarray, x: np.ndarray, step: float, weight: float) -> np.ndarray:
    """math.py:17-24 (EPARating.add_obs); returns the new mean."""
    new_mean = (1 - step) * mean + step * x
    return weight * new_mean + (1 - weight) * mean
