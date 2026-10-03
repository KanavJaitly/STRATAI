"""Data-quality checks for landed playoff alliances (Phase 5 P5-M1 acceptance).

Pure functions over data.alliances.Alliance lists and plain mappings, so each
criterion is unit-testable without a database. scripts/phase5_m1_alliance_acceptance.py
applies them to the canonical database once and records the result write-once.

The criteria are P5-M1's frozen acceptance criteria (docs/P5Milestones.md):

(b) every team that appears in an event's playoff matches is in that event's alliance
    picks. TBA's backup field is null for every 2024-2026 alliance, so a backup robot
    that played is an *exception to list*, never silently accepted or rejected.
(c) seed-rank consistency, seeded events only: alliance k's captain is the
    best-ranked team not already on alliances 1..k-1. A team that declined an
    invitation stays eligible to captain (FRC rules), and a pick may be better-ranked
    than a later captain; both are consistent with the rule as stated. Any other
    disagreement is a violation to list.

A failing criterion is a data finding to report, never a pass.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass

from data.alliances import Alliance

__all__ = [
    "MembershipException",
    "SeedRankViolation",
    "is_seeded_event",
    "playoff_membership_exceptions",
    "seed_rank_violations",
]


@dataclass(frozen=True)
class MembershipException:
    team: int
    reason: str  # "not_on_any_alliance"


@dataclass(frozen=True)
class SeedRankViolation:
    seed: int
    captain: int | None
    expected_captain: int | None
    reason: str  # "captain_not_best_ranked_available" | "captain_unranked" | "no_ranked_candidate"


def is_seeded_event(alliances: list[Alliance]) -> bool:
    """True when every alliance carries a seed (an "Alliance N" event)."""
    return bool(alliances) and all(a.seed is not None for a in alliances)


def playoff_membership_exceptions(alliances: list[Alliance], playoff_teams: Iterable[int]) -> list[MembershipException]:
    """Criterion (b): playoff participants that are on no alliance's picks."""
    members = {team for a in alliances for team in a.picks}
    members |= {a.backup for a in alliances if a.backup is not None}
    return [MembershipException(team, "not_on_any_alliance") for team in sorted(set(playoff_teams) - members)]


def seed_rank_violations(alliances: list[Alliance], final_ranks: Mapping[int, int]) -> list[SeedRankViolation]:
    """Criterion (c), for a seeded event: compare each captain with the best-ranked
    team not on alliances 1..k-1. Raises ValueError for an unseeded event."""
    if not is_seeded_event(alliances):
        raise ValueError("seed_rank_violations applies to seeded events only")
    taken: set[int] = set()
    violations: list[SeedRankViolation] = []
    for alliance in sorted(alliances, key=lambda a: a.seed):  # type: ignore[arg-type, return-value]
        available = sorted((rank, team) for team, rank in final_ranks.items() if team not in taken)
        expected = available[0][1] if available else None
        if alliance.captain is None or expected is None:
            violations.append(SeedRankViolation(alliance.seed, alliance.captain, expected, "no_ranked_candidate"))  # type: ignore[arg-type]
        elif alliance.captain not in final_ranks:
            violations.append(SeedRankViolation(alliance.seed, alliance.captain, expected, "captain_unranked"))  # type: ignore[arg-type]
        elif alliance.captain != expected:
            violations.append(SeedRankViolation(alliance.seed, alliance.captain, expected,  # type: ignore[arg-type]
                                                "captain_not_best_ranked_available"))
        taken |= set(alliance.picks)
    return violations
