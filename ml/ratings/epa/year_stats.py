"""Season statistics from week-1 matches (spec §3; reference data/avg.py:9-75).

These fix the scale of the whole season: starting ratings, the win-probability
spread, and the foul rate. They are computed from every completed match of
the first competition week (adjusted week 1), so a week-1 match's own result
contributes to the statistics used to predict it and every other week-1
match. That is the reference's methodology, reproduced as specified, and the
one place a rating before a match can depend on that match's result
(tests/test_ratings_epa_leakage.py pins it so it stays visible).
"""

from __future__ import annotations

import statistics
from collections.abc import Callable, Sequence
from dataclasses import asdict, dataclass

import numpy as np

from ml.ratings.epa.adapters import CleanedAlliance
from ml.ratings.epa.constants import COMP_0, COMPONENT_COUNT, PROCESSOR_ALGAE_REVALUE, YEAR_STATS_WEEK
from ml.ratings.epa.exclusions import NO_WEEK_ONE_DATA, RunRejected
from ml.ratings.epa.rounding import reference_round
from ml.ratings.epa.validation import PreparedMatch

r = reference_round


@dataclass(frozen=True)
class YearStats:
    season: int
    week_one_matches: int
    score_mean: float
    score_sd: float
    no_foul_mean: float
    foul_mean: float
    auto_mean: float
    teleop_mean: float
    endgame_mean: float
    rp_1_mean: float
    rp_2_mean: float
    rp_3_mean: float
    tiebreaker_mean: float
    comp_means: tuple[float, ...]

    def mean_components(self) -> np.ndarray:
        """db/models/year.py:179-203, in rating-vector order."""
        return np.array(
            [
                self.no_foul_mean, self.auto_mean, self.teleop_mean, self.endgame_mean,
                self.rp_1_mean, self.rp_2_mean, self.rp_3_mean, self.tiebreaker_mean,
                *self.comp_means,
            ],
            dtype=np.float64,
        )

    def foul_rate(self) -> float:
        """db/models/year.py:176-177."""
        return (self.foul_mean or 0) / (self.no_foul_mean or 1)

    def to_dict(self) -> dict:
        data = asdict(self)
        data["comp_means"] = list(self.comp_means)
        return data

    @classmethod
    def from_dict(cls, data: dict) -> YearStats:
        return cls(**{**data, "comp_means": tuple(data["comp_means"])})


Accessor = Callable[[CleanedAlliance], object]


def compute_year_stats(season: int, stream: Sequence[PreparedMatch]) -> YearStats:
    """Week-1 means and score spread, red and blue pooled. Raises RunRejected."""
    week_one = [m for m in stream if m.week == YEAR_STATS_WEEK and m.completed]
    alliances: list[CleanedAlliance] = [m.red for m in week_one] + [m.blue for m in week_one]  # type: ignore[misc]

    def values(accessor: Accessor) -> list:
        return [v for v in (accessor(a) for a in alliances) if v is not None]

    def get_mean(accessor: Accessor) -> float:
        clean = values(accessor)
        if len(clean) < 1:
            return 0
        return r(statistics.mean(clean), 2)

    def get_mean_sd(accessor: Accessor) -> tuple[float, float]:
        clean = values(accessor)
        if len(clean) < 2:
            return 0, 0
        return r(statistics.mean(clean), 2), r(statistics.stdev(clean), 2)

    score_mean, score_sd = get_mean_sd(lambda a: a.score)
    no_foul_mean, _ = get_mean_sd(lambda a: a.values[0])
    means = [get_mean(lambda a, i=i: a.values[i]) for i in range(1, COMP_0)]
    comp_means = [get_mean(lambda a, i=i: a.values[COMP_0 + i]) for i in range(COMPONENT_COUNT)]
    foul_mean = get_mean(lambda a: a.foul)
    auto_mean, teleop_mean, endgame_mean, rp_1_mean, rp_2_mean, rp_3_mean, tiebreaker_mean = means

    if season == 2025:
        # data/avg.py:66-73: processor algae counted at 3 points, not 6
        update = PROCESSOR_ALGAE_REVALUE * comp_means[6]
        no_foul_mean -= update
        teleop_mean -= update
        comp_means[7] -= update

    if not score_sd:
        raise RunRejected(
            NO_WEEK_ONE_DATA,
            f"{len(week_one)} completed week-1 matches give score_sd={score_sd}; the season has no scale",
        )
    return YearStats(
        season=season,
        week_one_matches=len(week_one),
        score_mean=score_mean,
        score_sd=score_sd,
        no_foul_mean=no_foul_mean,
        foul_mean=foul_mean,
        auto_mean=auto_mean,
        teleop_mean=teleop_mean,
        endgame_mean=endgame_mean,
        rp_1_mean=rp_1_mean,
        rp_2_mean=rp_2_mean,
        rp_3_mean=rp_3_mean,
        tiebreaker_mean=tiebreaker_mean,
        comp_means=tuple(comp_means),
    )
