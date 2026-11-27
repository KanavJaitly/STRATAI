"""Ranking picks for one alliance, with the second pick conditional on the first (audit 2026-11-26, workstream 7).

**First pick.** A candidate is worth what the alliance can expect to complete with it. Between this pick and the
alliance's next, other captains pick, so the best partner may be gone. The caller supplies an `AvailabilityModel`: the
probability each team is still available at the alliance's next pick. For candidate c, partners are sorted by the
value of (captain, c, d), and

    E[c] = sum over k of V(captain, c, d_k) × p_k × product over j < k of (1 − p_j)
           + (product of all (1 − p_j)) × V(captain, c)        (no listed partner left)

assuming teams' availabilities are independent. Two models ship: `EveryoneAvailable` (the optimistic bound: every
partner stays, so E[c] is the best pair) and `GivenProbabilities` (probabilities the caller supplies). Neither is a
model of how other captains pick; that model, and its validation, are open (docs/alliance_optimizer.md).

**Second pick.** With the first pick made, each available candidate is worth V(captain, first, d) exactly.

**Backup pick** (when `roster_size` exceeds `active_robots`): each candidate is worth its backup value
(backup.py), which needs every robot's availability.

Every result carries `status = not_validated` and `stage = foundation_inactive`: this is architecture with synthetic
tests, not an evaluated method, and nothing calls it from the API or the live draft.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Protocol

from ml.alliance.optimizer.backup import backup_value
from ml.alliance.optimizer.config import ConfigError, SeasonScoringConfig
from ml.alliance.optimizer.evaluator import RobotProfile, evaluate_lineup

STATUS = "not_validated"
STAGE = "foundation_inactive"


class AvailabilityModel(Protocol):
    def p_available(self, team: int) -> float:
        """The probability `team` is still unpicked at this alliance's next pick."""


class EveryoneAvailable:
    """Every team stays available: E[c] is the best completed pair (an optimistic bound, not a forecast)."""

    def p_available(self, team: int) -> float:
        return 1.0


@dataclass(frozen=True)
class GivenProbabilities:
    probabilities: Mapping[int, float]

    def p_available(self, team: int) -> float:
        if team not in self.probabilities:
            raise ConfigError(f"no availability probability for team {team}")
        p = float(self.probabilities[team])
        if not 0.0 <= p <= 1.0:
            raise ConfigError(f"team {team}: availability {p} is not a probability")
        return p


@dataclass(frozen=True)
class RankedCandidate:
    team: int
    value: float
    best_partners: tuple[tuple[int, float], ...] = ()  # first pick only: the top completions and their values


@dataclass(frozen=True)
class PickRanking:
    pick: str  # "first", "second", "backup"
    config_season: int
    config_version: str
    config_approval: str
    candidates: tuple[RankedCandidate, ...]
    status: str = STATUS
    stage: str = STAGE
    assumptions: tuple[str, ...] = field(default=())


def _profiles(teams: Sequence[int], profiles: Mapping[int, RobotProfile]) -> list[RobotProfile]:
    missing = [t for t in teams if t not in profiles]
    if missing:
        raise ConfigError(f"no profile for team(s) {missing}")
    return [profiles[t] for t in teams]


def _ranking(pick: str, config: SeasonScoringConfig, ranked: list[RankedCandidate],
             assumptions: tuple[str, ...]) -> PickRanking:
    ranked.sort(key=lambda c: (-c.value, c.team))  # ties: lower team number first, so the order is reproducible
    return PickRanking(pick=pick, config_season=config.season, config_version=config.version,
                       config_approval=config.approval.status, candidates=tuple(ranked), assumptions=assumptions)


def rank_first_picks(captain: int, candidates: Sequence[int], profiles: Mapping[int, RobotProfile],
                     config: SeasonScoringConfig, availability: AvailabilityModel, *, top_partners: int = 3,
                     allow_unapproved: bool = False) -> PickRanking:
    """Each candidate's expected value as a first pick, completing the alliance with the second pick it leads to."""
    config.require_usable(allow_unapproved=allow_unapproved)
    if config.alliance.active_robots != 3:
        raise ConfigError("the first-pick search is written for three active robots")
    pool = [t for t in dict.fromkeys(candidates) if t != captain]
    cap, *_ = _profiles([captain, *pool], profiles)
    ranked = []
    for c in pool:
        first = profiles[c]
        pairs = sorted(((d, evaluate_lineup([cap, first, profiles[d]], config).total) for d in pool if d != c),
                       key=lambda x: (-x[1], x[0]))
        expected, none_left = 0.0, 1.0
        for d, value in pairs:
            p = availability.p_available(d)
            expected += value * p * none_left
            none_left *= 1.0 - p
        expected += none_left * evaluate_lineup([cap, first], config).total
        ranked.append(RankedCandidate(team=c, value=expected, best_partners=tuple(pairs[:top_partners])))
    return _ranking("first", config, ranked, (
        "teams' availabilities at the next pick are independent",
        f"availability model: {type(availability).__name__}",
    ))


def rank_second_picks(captain: int, first: int, candidates: Sequence[int], profiles: Mapping[int, RobotProfile],
                      config: SeasonScoringConfig, *, allow_unapproved: bool = False) -> PickRanking:
    """Each available candidate's value completing the alliance (captain, first)."""
    config.require_usable(allow_unapproved=allow_unapproved)
    pool = [d for d in dict.fromkeys(candidates) if d not in (captain, first)]
    cap, one, *_ = _profiles([captain, first, *pool], profiles)
    ranked = [RankedCandidate(team=d, value=evaluate_lineup([cap, one, profiles[d]], config).total) for d in pool]
    return _ranking("second", config, ranked, ())


def rank_backup_picks(active: Sequence[int], candidates: Sequence[int], profiles: Mapping[int, RobotProfile],
                      config: SeasonScoringConfig, *, allow_unapproved: bool = False) -> PickRanking:
    """Each available candidate's backup value for the alliance's active robots."""
    config.require_usable(allow_unapproved=allow_unapproved)
    if config.alliance.roster_size <= config.alliance.active_robots:
        raise ConfigError("this season's configuration has no backup robot")
    pool = [b for b in dict.fromkeys(candidates) if b not in active]
    active_profiles = _profiles(active, profiles)
    _profiles(pool, profiles)
    ranked = [RankedCandidate(team=b, value=backup_value(active_profiles, profiles[b], config)) for b in pool]
    return _ranking("backup", config, ranked, ("robots' availabilities are independent",))


__all__ = ["AvailabilityModel", "EveryoneAvailable", "GivenProbabilities", "PickRanking", "RankedCandidate", "STAGE",
           "STATUS", "rank_backup_picks", "rank_first_picks", "rank_second_picks"]
