"""Starting ratings (spec §4; reference models/epa/init.py:15-59, main.py:55-79).

A team's start depends on its year-normalized EPA from its two most recent
earlier seasons (searching Y-1 .. Y-4). Those values are an explicit input
(PriorSeasonInput); with none supplied, every team starts exactly as the
reference starts a team with no earlier TeamYear. Building the historical
chain that would supply them is a separate, later milestone (spec §4.5).
"""

from __future__ import annotations

import numpy as np

from ml.ratings.epa.constants import (
    EPS,
    INIT_PENALTY,
    ISR_DISTRICT,
    ISR_SEASON,
    MEAN_REVERSION,
    NORM_MEAN,
    NORM_SD,
    NUM_TEAMS,
    PRIOR_LOOKBACK_SEASONS,
    RP_INDICES,
    YEAR_ONE_WEIGHT,
)
from ml.ratings.epa.inputs import PriorSeasonInput, PriorTeamYear
from ml.ratings.epa.math import inv_unit_sigmoid
from ml.ratings.epa.year_stats import YearStats

INIT_EPA = NORM_MEAN - INIT_PENALTY * NORM_SD  # 1450


def initial_rating(
    stats: YearStats,
    team_year_1: PriorTeamYear | None,
    team_year_2: PriorTeamYear | None,
    mean_reversion: float,
) -> np.ndarray:
    """get_init_epa, operation for operation."""
    year_mean = stats.no_foul_mean or stats.score_mean or 0
    year_sd = stats.score_sd or 0

    norm_epa_1 = norm_epa_2 = INIT_EPA
    if team_year_1 is not None and team_year_1.norm_epa is not None:
        norm_epa_1 = team_year_1.norm_epa
    if team_year_2 is not None and team_year_2.norm_epa is not None:
        norm_epa_2 = team_year_2.norm_epa

    prev_norm_epa = YEAR_ONE_WEIGHT * norm_epa_1 + (1 - YEAR_ONE_WEIGHT) * norm_epa_2
    curr_norm_epa = (1 - mean_reversion) * prev_norm_epa + mean_reversion * INIT_EPA
    curr_epa_z_score = (curr_norm_epa - NORM_MEAN) / NORM_SD
    # enforces a starting total EPA >= 0
    curr_epa_z_score = max(-year_mean / NUM_TEAMS / year_sd, curr_epa_z_score)

    mean = stats.mean_components()
    sd_frac = (year_sd or 0) / (year_mean or 1)
    sd = mean * sd_frac  # before the rp transform below, as in the reference
    for i in RP_INDICES:
        # the prediction applies a sigmoid to rp, so start from its inverse
        mean[i] = max(-1, inv_unit_sigmoid(max(EPS, min(1 - EPS, mean[i]))))
    return mean / NUM_TEAMS + sd * curr_epa_z_score


def prior_team_years(
    prior: PriorSeasonInput | None, team: int, season: int
) -> tuple[PriorTeamYear | None, PriorTeamYear | None]:
    """The two most recent PriorTeamYears within Y-1 .. Y-4 (main.py:58-65)."""
    if prior is None:
        return None, None
    window = range(season - PRIOR_LOOKBACK_SEASONS, season)
    found = sorted((y for y in prior.team_years.get(team, ()) if y.season in window), key=lambda y: -y.season)
    return (found[0] if found else None), (found[1] if len(found) > 1 else None)


def mean_reversion_for(season: int, team: int, team_districts: dict[int, str] | None) -> float:
    """main.py:68-70: 2026 isr teams did not compete before championship."""
    if season == ISR_SEASON and team_districts is not None and team_districts.get(team) == ISR_DISTRICT:
        return 0
    return MEAN_REVERSION


def initial_ratings(
    stats: YearStats,
    teams: tuple[int, ...],
    prior: PriorSeasonInput | None,
    team_districts: dict[int, str] | None,
) -> dict[int, np.ndarray]:
    """One independent starting vector per team (never a shared default object)."""
    out: dict[int, np.ndarray] = {}
    for team in teams:
        year_1, year_2 = prior_team_years(prior, team, stats.season)
        out[team] = initial_rating(stats, year_1, year_2, mean_reversion_for(stats.season, team, team_districts))
    return out
