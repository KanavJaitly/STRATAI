"""What one lineup of robots is worth under a season's scoring configuration (audit 2026-11-26, workstream 7).

The value of an alliance is not the sum of its robots' values. The configuration's rules decide how contributions
combine (config.py):
- a `capped` component saturates, so two robots that score the same shared resource add less than their sum;
- a `best_k` component counts only the k best robots, so a third robot good only at it adds nothing;
- a bonus is reached by the alliance total, so a robot can be worth more to an alliance near a threshold;
- a role (for example defense) replaces a robot's normal contributions with its role-mode ones, and the evaluator
  assigns roles to maximise the alliance's value, within each role's limit.

With per-robot variances, a capped component's expectation is computed exactly under a normal model
(E[min(S, cap)]), and a bonus's expectation is value × P(S ≥ threshold). `best_k` orders robots by their expected
contribution (an approximation; stated in docs/alliance_optimizer.md). Without variances everything is evaluated at
the expected values.

Profiles are inputs. This module estimates nothing: where the numbers come from (for example the P11A A3 per-robot
component estimates, or measured defense from scouting) is the caller's, and the values a season needs are listed
for approval in docs/alliance_optimizer.md. Nothing here is validated; nothing here is served.
"""

from __future__ import annotations

import itertools
import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field

from ml.alliance.optimizer.config import ComponentRule, ConfigError, SeasonScoringConfig


@dataclass(frozen=True)
class RobotProfile:
    """One robot's inputs. `contributions` and `variances` are per component, when it plays normally. A role it can
    play has `role_contributions[role]` (its scoring while in that role, missing components count as 0) and may have a
    `role_values[role]` (value credited for the role itself, such as measured points denied). `availability` is the
    probability it can play a given match (needed only for backup values)."""

    team: int
    contributions: Mapping[str, float]
    variances: Mapping[str, float] | None = None
    role_contributions: Mapping[str, Mapping[str, float]] = field(default_factory=dict)
    role_values: Mapping[str, float] = field(default_factory=dict)
    availability: float | None = None

    def __post_init__(self) -> None:
        if self.availability is not None and not 0.0 <= self.availability <= 1.0:
            raise ValueError(f"team {self.team}: availability must be a probability")
        for name, variance in (self.variances or {}).items():
            if variance < 0:
                raise ValueError(f"team {self.team}: negative variance for {name!r}")


@dataclass(frozen=True)
class LineupValue:
    teams: tuple[int, ...]
    total: float
    components: Mapping[str, float]
    bonuses: Mapping[str, float]
    roles: Mapping[int, str]  # team -> role, for robots not scoring normally
    role_value: float


def _phi(z: float) -> float:
    return math.exp(-0.5 * z * z) / math.sqrt(2 * math.pi)


def _cdf(z: float) -> float:
    return 0.5 * (1.0 + math.erf(z / math.sqrt(2.0)))


def _expected_capped(mean: float, variance: float, cap: float) -> float:
    """E[min(S, cap)] for S ~ N(mean, variance)."""
    if variance <= 0:
        return min(mean, cap)
    sd = math.sqrt(variance)
    z = (cap - mean) / sd
    return mean - (sd * _phi(z) + (mean - cap) * (1.0 - _cdf(z)))


def _p_at_least(mean: float, variance: float, threshold: float) -> float:
    if variance <= 0:
        return 1.0 if mean >= threshold else 0.0
    return 1.0 - _cdf((threshold - mean) / math.sqrt(variance))


def _component(rule: ComponentRule, parts: Sequence[tuple[float, float]]) -> tuple[float, float, float]:
    """(expected value, mean of the counted sum, its variance) for one component from (mean, variance) per robot."""
    if rule.kind == "best_k":
        parts = sorted(parts, key=lambda p: p[0], reverse=True)[: rule.k]
    mean = sum(p[0] for p in parts)
    variance = sum(p[1] for p in parts)
    if rule.kind == "capped":
        assert rule.cap is not None
        return _expected_capped(mean, variance, rule.cap), mean, variance
    return mean, mean, variance


def _assignments(robots: Sequence[RobotProfile], config: SeasonScoringConfig):
    """Every way to put robots in roles they can play, within each role's limit (None = scoring normally)."""
    options = [[None, *[r.name for r in config.roles if r.name in robot.role_contributions]] for robot in robots]
    limits = {r.name: r.max_per_alliance for r in config.roles}
    for combo in itertools.product(*options):
        used = [role for role in combo if role is not None]
        if all(used.count(role) <= limits[role] for role in set(used)):
            yield combo


def evaluate_lineup(robots: Sequence[RobotProfile], config: SeasonScoringConfig) -> LineupValue:
    """The best value of these robots playing together, over every allowed role assignment."""
    if not robots:
        raise ConfigError("a lineup needs at least one robot")
    if len(robots) > config.alliance.active_robots:
        raise ConfigError(f"{len(robots)} robots exceed the {config.alliance.active_robots} active robots")
    if len({r.team for r in robots}) != len(robots):
        raise ConfigError("a robot cannot appear twice in one lineup")
    best: LineupValue | None = None
    for combo in _assignments(robots, config):
        components: dict[str, float] = {}
        sums: dict[str, tuple[float, float]] = {}
        for rule in config.components:
            parts = []
            for robot, role in zip(robots, combo):
                source = robot.contributions if role is None else robot.role_contributions[role]
                variance = (robot.variances or {}).get(rule.name, 0.0) if role is None else 0.0
                parts.append((float(source.get(rule.name, 0.0)), float(variance)))
            components[rule.name], mean, variance = _component(rule, parts)
            sums[rule.name] = (mean, variance)
        bonuses = {}
        for bonus in config.bonuses:
            mean, variance = sums[bonus.component]
            rule = next(c for c in config.components if c.name == bonus.component)
            reachable = rule.kind != "capped" or bonus.threshold <= (rule.cap or 0)
            bonuses[bonus.name] = bonus.value * _p_at_least(mean, variance, bonus.threshold) if reachable else 0.0
        role_value = sum(float(robot.role_values.get(role, 0.0)) for robot, role in zip(robots, combo) if role)
        total = sum(components.values()) + sum(bonuses.values()) + role_value
        candidate = LineupValue(teams=tuple(r.team for r in robots), total=total, components=components,
                                bonuses=bonuses, roles={r.team: role for r, role in zip(robots, combo) if role},
                                role_value=role_value)
        # Strictly better only: among equal totals the first (fewest roles, in enumeration order) is kept.
        if best is None or candidate.total > best.total + 1e-12:
            best = candidate
    assert best is not None
    return best


__all__ = ["LineupValue", "RobotProfile", "evaluate_lineup"]
