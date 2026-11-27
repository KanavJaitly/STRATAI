"""What a roster is worth when robots can be unavailable, and so what a backup robot adds (workstream 7).

A roster holds `roster_size` robots, of which `active_robots` play. Each robot is available for a match with its
profile's `availability` probability, independently (an assumption that needs approval; docs/alliance_optimizer.md).
For every pattern of availability:
- with `lineup_choice`, the alliance plays the best `active_robots` of those available;
- without it, the starters are the first `active_robots` of the roster, and a backup steps in, in roster order, for a
  starter who is unavailable;
- with fewer available robots than `active_robots`, `short_handed` decides: `plays_with_available` evaluates the
  smaller lineup, `forfeits` scores 0.

The roster's value is the probability-weighted value over all patterns (2^roster_size of them: 16 for four robots).
A backup's value is the roster's value with it minus the value without it. A missing availability is refused, never
assumed.
"""

from __future__ import annotations

import itertools
from collections.abc import Sequence

from ml.alliance.optimizer.config import ConfigError, SeasonScoringConfig
from ml.alliance.optimizer.evaluator import RobotProfile, evaluate_lineup


def _lineup_value(available: Sequence[RobotProfile], roster: Sequence[RobotProfile],
                  config: SeasonScoringConfig) -> float:
    shape = config.alliance
    if not available:
        return 0.0
    if len(available) < shape.active_robots:
        return evaluate_lineup(available, config).total if shape.short_handed == "plays_with_available" else 0.0
    if shape.lineup_choice:
        return max(evaluate_lineup(combo, config).total
                   for combo in itertools.combinations(available, shape.active_robots))
    playing = [r for r in roster if r in available][: shape.active_robots]  # starters first, then backups in order
    return evaluate_lineup(playing, config).total


def roster_value(roster: Sequence[RobotProfile], config: SeasonScoringConfig) -> float:
    """The expected value of a roster over every pattern of which of its robots can play."""
    if len(roster) > config.alliance.roster_size:
        raise ConfigError(f"{len(roster)} robots exceed the roster size {config.alliance.roster_size}")
    missing = [r.team for r in roster if r.availability is None]
    if missing:
        raise ConfigError(f"no availability estimate for team(s) {missing}; a backup value needs one for every robot")
    expected = 0.0
    for pattern in itertools.product((True, False), repeat=len(roster)):
        probability = 1.0
        for robot, up in zip(roster, pattern):
            probability *= robot.availability if up else 1.0 - robot.availability  # type: ignore[operator]
        if probability:
            available = [robot for robot, up in zip(roster, pattern) if up]
            expected += probability * _lineup_value(available, roster, config)
    return expected


def backup_value(active: Sequence[RobotProfile], backup: RobotProfile, config: SeasonScoringConfig) -> float:
    """What adding `backup` to the roster `active` is worth (never negative when lineups are chosen)."""
    return roster_value([*active, backup], config) - roster_value(active, config)


__all__ = ["backup_value", "roster_value"]
