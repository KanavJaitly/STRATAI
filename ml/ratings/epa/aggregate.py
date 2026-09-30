"""Team-event and team-season results (spec §7.2; reference data/epa/agg.py,
data/epa/calc.py:45-48, data/wins.py:28-110).

Built only from the engine's MatchRecords and the prepared stream, after the
season has been processed. Two reference behaviours are reproduced and
flagged because they are not point-in-time:

* A team-event with no counted qualifying match (every qual appearance was
  DQ'd or a surrogate, or the event had none) takes the team's rating at the
  END OF THE SEASON (calc.py:45-48). epa_is_season_end marks it.
* unitless and norm are year-end conversions. norm is also fitted over the
  whole season (see ml.ratings.epa.normalization).

Every result carries ``available_at``: the scheduled time of the last match
its value depends on, so a consumer can require available_at < as_of
(data contract §9). A team-event value depends on the team's last processed
match at the event and on the season statistics, i.e. on every completed
week-1 match; a season-end value, and every norm_epa, on the season's last
completed match.

Team-events are produced for every (team, event) pair that appears in a
retained match. The reference also holds team-events for registered teams
that never played; STRATAI has no source for those (data contract §8.2).
"""

from __future__ import annotations

import statistics
from collections import defaultdict
from collections.abc import Sequence
from dataclasses import dataclass, replace
from typing import Any

import numpy as np

from ml.ratings.epa.constants import (
    CHAMPS_WEEK,
    EPA_FIELD_NAMES,
    NORM_MEAN,
    NORM_SD,
    RP_1,
    RP_2,
    RP_3,
    YEAR_STATS_WEEK,
)
from ml.ratings.epa.engine import MatchRecord, Vector
from ml.ratings.epa.normalization import NormFunction
from ml.ratings.epa.rounding import numpy_round, reference_round
from ml.ratings.epa.validation import PreparedMatch
from ml.ratings.epa.year_stats import YearStats

# max EPA skips a team's first 8 matches (agg.py:21)
MAX_EPA_SKIP_MATCHES = 8


@dataclass(frozen=True)
class Availability:
    """When season-level inputs become known (scheduled times, epoch seconds)."""

    week_one_complete_time: int  # the last completed week-1 match: the statistics' last input
    season_final_time: int  # the last completed match of the season

    def to_dict(self) -> dict[str, int]:
        return {"week_one_complete_time": self.week_one_complete_time, "season_final_time": self.season_final_time}


def season_availability(stream: Sequence[PreparedMatch]) -> Availability:
    completed = [m for m in stream if m.completed]
    week_one = [m.time for m in completed if m.week == YEAR_STATS_WEEK]
    # compute_year_stats already refused a season without week-1 data
    return Availability(week_one_complete_time=max(week_one), season_final_time=max(m.time for m in completed))


def stored_components(vector: Vector, rp_digits: tuple[int, int, int]) -> dict[str, float]:
    """te/ty component fields (main.py:200-226): np.round(., 2); rp via round(np.float64, n)."""
    rounded = np.round(np.array(vector, dtype=np.float64), 2)
    out = {name: float(rounded[i]) for i, name in enumerate(EPA_FIELD_NAMES)}
    for index, digits in zip((RP_1, RP_2, RP_3), rp_digits):
        out[EPA_FIELD_NAMES[index]] = numpy_round(vector[index], digits)
    return out


def unitless_epa(epa: float, stats: YearStats) -> int:
    """unitless.py:11-12 plus agg.py:94-95."""
    mean, sd = stats.score_mean or 0, stats.score_sd or 0
    return int(reference_round(NORM_MEAN + NORM_SD * (epa - mean / 3) / sd))


@dataclass(frozen=True)
class TeamSeasonResult:
    team: int
    start: Vector
    final: Vector
    matches: int
    qual_updates: int
    epa_start: float
    epa: float
    epa_pre_champs: float
    epa_max: float
    components: dict[str, float]
    unitless_epa: int
    available_at: int  # every team-season value is a season-end value
    norm_epa: int | None = None

    def to_dict(self) -> dict[str, Any]:
        return {**self.__dict__, "start": list(self.start), "final": list(self.final)}


@dataclass(frozen=True)
class TeamEventResult:
    team: int
    event_key: str
    matches: int
    qual_count: int
    vector: Vector  # the rating epa and components are read from
    epa: float
    epa_is_season_end: bool  # look-ahead value (calc.py:45-48)
    epa_start: float
    epa_mean: float
    epa_max: float
    epa_pre_elim: float | None
    components: dict[str, float]
    unitless_epa: int
    last_played_time: int | None  # the team's last processed completed match at the event
    available_at: int  # epa, components and unitless: see the module docstring
    norm_available_at: int  # norm is fitted over season-end values
    norm_epa: int | None = None

    def to_dict(self) -> dict[str, Any]:
        return {**self.__dict__, "vector": list(self.vector)}


def _counted_qual(match: PreparedMatch, team: int) -> bool:
    # wins.py:67-81: completed quals, excluding the team's DQ and surrogate appearances
    if match.elim or not match.completed:
        return False
    dq, surrogates = (
        (match.red_dq, match.red_surrogates) if team in match.red_teams else (match.blue_dq, match.blue_surrogates)
    )
    return team not in dq and team not in surrogates


def aggregate(
    stats: YearStats,
    stream: Sequence[PreparedMatch],
    records: Sequence[MatchRecord],
    start: dict[int, Vector],
    final: dict[int, Vector],
    final_qual_counts: dict[int, int],
    availability: Availability,
) -> tuple[list[TeamSeasonResult], list[TeamEventResult]]:
    """Team-season and team-event results, without norm (see with_norm)."""
    team_matches: dict[int, list[tuple[PreparedMatch, MatchRecord]]] = defaultdict(list)
    for match, record in zip(stream, records, strict=True):
        for team in match.teams:
            team_matches[team].append((match, record))

    seasons: list[TeamSeasonResult] = []
    events: list[TeamEventResult] = []
    for team in sorted(start):
        pairs = team_matches[team]
        epa_start = reference_round(start[team][0], 2)
        post_epas = [numpy_round(r.post[team][0], 2) if r.post is not None else None for _, r in pairs]
        played = [x for x in post_epas if x is not None]
        pre_champs = [x for x, (m, _) in zip(post_epas, pairs) if x is not None and m.week < CHAMPS_WEEK]
        end = played[-1] if played else epa_start
        seasons.append(
            TeamSeasonResult(
                team=team,
                start=start[team],
                final=final[team],
                matches=len(pairs),
                qual_updates=final_qual_counts[team],
                epa_start=epa_start,
                epa=end,
                epa_pre_champs=pre_champs[-1] if pre_champs else epa_start,
                epa_max=max(played[MAX_EPA_SKIP_MATCHES:]) if len(played) > MAX_EPA_SKIP_MATCHES else end,
                components=stored_components(final[team], (4, 4, 5)),
                unitless_epa=unitless_epa(end, stats),
                available_at=availability.season_final_time,
            )
        )
        events.extend(_team_events(team, pairs, final[team], stats, availability))
    return seasons, events


def _team_events(
    team: int, pairs: list[tuple[PreparedMatch, MatchRecord]], season_final: Vector, stats: YearStats,
    availability: Availability,
) -> list[TeamEventResult]:
    by_event: dict[str, list[tuple[PreparedMatch, MatchRecord]]] = defaultdict(list)
    for match, record in pairs:
        by_event[match.event_key].append((match, record))
    out: list[TeamEventResult] = []
    for event_key in sorted(by_event):
        event_pairs = by_event[event_key]
        qual_count = sum(1 for m, _ in event_pairs if _counted_qual(m, team))
        played = [r.post[team] for _, r in event_pairs if r.post is not None]
        played_times = [m.time for m, r in event_pairs if r.post is not None]
        season_end = qual_count == 0 or not played
        vector = season_final if season_end else played[-1]
        pre_epas = [numpy_round(r.pre[team][0], 2) for _, r in event_pairs]
        quals = [r for m, r in event_pairs if not m.elim]
        epa = numpy_round(vector[0], 2)
        out.append(
            TeamEventResult(
                team=team,
                event_key=event_key,
                matches=len(event_pairs),
                qual_count=qual_count,
                vector=vector,
                epa=epa,
                epa_is_season_end=season_end,
                epa_start=reference_round(pre_epas[0], 2),
                epa_mean=reference_round(statistics.mean(pre_epas), 2),
                epa_max=reference_round(max(pre_epas), 2),
                epa_pre_elim=reference_round(numpy_round(quals[-1].pre[team][0], 2), 2) if quals else None,
                components=stored_components(vector, (4, 4, 4)),
                unitless_epa=unitless_epa(epa, stats),
                last_played_time=played_times[-1] if played_times else None,
                available_at=availability.season_final_time if season_end
                else max(played_times[-1], availability.week_one_complete_time),
                norm_available_at=availability.season_final_time,
            )
        )
    return out


def with_norm(
    seasons: list[TeamSeasonResult], events: list[TeamEventResult], norm: NormFunction | None
) -> tuple[list[TeamSeasonResult], list[TeamEventResult]]:
    """Attach norm_epa = r(norm(epa)) (agg.py:97-98, 161-162)."""
    if norm is None:
        return seasons, events
    return (
        [replace(s, norm_epa=int(reference_round(norm(s.epa)))) for s in seasons],
        [replace(e, norm_epa=int(reference_round(norm(e.epa)))) for e in events],
    )
