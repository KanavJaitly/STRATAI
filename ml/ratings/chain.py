"""The bounded prior-season chain: 2024 -> 2025 -> 2026 (spec §4.5).

STRATAI holds 2024-2026 only, so the reference's initialization chain (which
runs back to 2002) is cut at 2024 and the prior for each later season is
built from STRATAI's own earlier results:

* 2024 has no earlier STRATAI season: every team starts as the reference
  starts a team with no prior TeamYear (1450, z = -0.2). The run is labelled
  "initialized without prior-season history".
* 2025 receives each team's STRATAI 2024 norm_epa as its most recent prior
  TeamYear. No second prior season exists, so the reference's formula uses
  1450 in its place (the same value the reference uses when a team has only
  one earlier TeamYear).
* 2026 receives each team's STRATAI 2025 and 2024 norm_epa (the two most
  recent, as the reference takes them).
* A team with no STRATAI result in an earlier season (a rookie, or a team
  that did not play that season) gets 1450 for that slot, exactly the
  reference's rule for a missing TeamYear. The reference would look further
  back (to Y-4) for a team that skipped a season; STRATAI cannot.

norm_epa is a season-end value, fitted over the whole earlier season. It is
used only to start a strictly later season, so no information from the season
being rated reaches its own starting ratings. prior_from_results refuses any
result that is not from an earlier season.

The 2026 isr rule (no mean reversion for teams in the Israel district) needs
each team's district. STRATAI does not sync TBA's district team lists, so the
district is derived from the district events a team actually played in that
season (team_districts_from_events); a team whose district events disagree is
left without a district and counted.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Sequence

from ml.ratings.epa.constants import (
    EVENT_TYPE_OVERRIDES,
    TBA_DISTRICT,
    TBA_DISTRICT_CMP,
    TBA_DISTRICT_CMP_DIVISION,
)
from ml.ratings.epa.inputs import PriorSeasonInput, PriorTeamYear, SeasonInput
from ml.ratings.epa.season import SeasonResult

CHAIN_SEASONS: tuple[int, ...] = (2024, 2025, 2026)
CHAIN_SOURCE_PREFIX = "stratai-epa-chain"
DISTRICT_EVENT_TYPES = frozenset({TBA_DISTRICT, TBA_DISTRICT_CMP, TBA_DISTRICT_CMP_DIVISION})


def prior_from_results(season: int, previous: Sequence[SeasonResult]) -> PriorSeasonInput | None:
    """Explicit prior history for ``season`` from STRATAI's own earlier results.

    None when there is no earlier result (the 2024 case).
    """
    if any(r.season >= season for r in previous):
        raise ValueError(f"prior for {season} may only use earlier seasons, got {[r.season for r in previous]}")
    if len({r.season for r in previous}) != len(previous):
        raise ValueError("each earlier season may appear once")
    if not previous:
        return None
    missing_norm = [r.season for r in previous if not r.norm_computed]
    if missing_norm:
        raise ValueError(f"seasons {missing_norm} have no norm_epa; the chain needs it")

    team_years: dict[int, list[PriorTeamYear]] = defaultdict(list)
    for result in sorted(previous, key=lambda r: -r.season):
        for team_season in result.team_seasons:
            team_years[team_season.team].append(PriorTeamYear(season=result.season, norm_epa=team_season.norm_epa))
    source = CHAIN_SOURCE_PREFIX + ":" + ",".join(
        f"{r.season}={r.results_fingerprint()}" for r in sorted(previous, key=lambda r: r.season)
    )
    return PriorSeasonInput(source=source, team_years={t: tuple(ys) for t, ys in sorted(team_years.items())})


def team_districts_from_events(season_input: SeasonInput) -> tuple[dict[int, str], tuple[int, ...]]:
    """Each team's district, from the district-type events it played this season.

    Returns (team -> district abbreviation, teams whose district events disagree).
    Teams that played no district event are absent from the mapping.
    """
    districts: dict[str, str] = {}
    for event in season_input.events:
        event_type = EVENT_TYPE_OVERRIDES.get(event.event_key, event.event_type)
        if event_type in DISTRICT_EVENT_TYPES and event.district is not None:
            districts[event.event_key] = event.district
    seen: dict[int, set[str]] = defaultdict(set)
    for match in season_input.matches:
        district = districts.get(match.event_key)
        if district is None:
            continue
        for team in (*match.red.teams, *match.blue.teams):
            seen[team].add(district)
    mapping = {team: next(iter(ds)) for team, ds in sorted(seen.items()) if len(ds) == 1}
    conflicts = tuple(sorted(team for team, ds in seen.items() if len(ds) > 1))
    return mapping, conflicts


def prior_coverage(season_input: SeasonInput, teams: Sequence[int]) -> dict[str, int]:
    """How many rated teams start from 2, 1 or 0 earlier STRATAI seasons."""
    prior = season_input.prior
    window = range(season_input.season - 4, season_input.season)
    counts = {"two_prior_seasons": 0, "one_prior_season": 0, "no_prior_season": 0}
    for team in teams:
        found = 0 if prior is None else sum(1 for y in prior.team_years.get(team, ()) if y.season in window)
        counts[("no_prior_season", "one_prior_season", "two_prior_seasons")[min(found, 2)]] += 1
    return counts
