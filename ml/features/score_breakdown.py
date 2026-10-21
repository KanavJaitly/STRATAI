"""Season-aware score_breakdown adapters -- Phase 4 Milestone 11's feature boundary.

TBA's per-match `score_breakdown` changes shape every season. This module is
the one place that knows those shapes. It turns one alliance's raw breakdown
into one canonical logical value, or fails loudly; it never returns a
plausible-but-wrong number.

The logical feature: AUTO POINTS -- the points an alliance scored in the
autonomous period, excluding penalty (foul) points awarded to it and manual
adjustments.

    season  field               why it is that quantity
    2024    autoPoints          = autoLeavePoints + autoTotalNotePoints
    2025    autoPoints          = autoMobilityPoints + autoCoralPoints
    2026    totalAutoPoints     = hubScore.autoPoints + autoTowerPoints

Equivalence was verified on every alliance-row in the database on 2026-09-29,
not assumed from field names (2024: 33,954; 2025: 35,692; 2026: 36,744 rows):
in 100% of rows the field equals the sum of that season's auto-period
components, totalPoints = auto + teleop + foulPoints + adjustPoints, and
totalPoints equals TBA's official alliance score. The name-alike trap is real:
2026's `hubScore.autoPoints` differs from `totalAutoPoints` in 1,764 rows
(it omits tower points).

Each adapter re-checks that season's own decomposition identity, so a changed
schema raises ScoreBreakdownSchemaError instead of drifting silently. A season
with no adapter raises UnsupportedSeasonError. Adapters read the raw body and
never modify it; the untouched payload stays in raw_source_payloads.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

__all__ = [
    "SUPPORTED_SEASONS",
    "ScoreBreakdownSchemaError",
    "UnsupportedSeasonError",
    "auto_points",
]


class UnsupportedSeasonError(ValueError):
    """No adapter exists for this season's score_breakdown schema."""

    def __init__(self, season: int) -> None:
        self.season = season
        super().__init__(
            f"no score_breakdown adapter for season {season} (supported: {sorted(SUPPORTED_SEASONS)}); "
            "add one in ml/features/score_breakdown.py after verifying the new schema"
        )


class ScoreBreakdownSchemaError(ValueError):
    """A breakdown for a supported season does not have the shape its adapter expects."""


@dataclass(frozen=True)
class _SeasonSchema:
    auto: tuple[str, ...]      # path to the auto-period points
    teleop: tuple[str, ...]    # path to the teleop-period points (endgame included)


_SCHEMAS: dict[int, _SeasonSchema] = {
    2024: _SeasonSchema(auto=("autoPoints",), teleop=("teleopPoints",)),
    2025: _SeasonSchema(auto=("autoPoints",), teleop=("teleopPoints",)),
    2026: _SeasonSchema(auto=("totalAutoPoints",), teleop=("totalTeleopPoints",)),
}
SUPPORTED_SEASONS = frozenset(_SCHEMAS)


def _points(breakdown: Mapping[str, Any], path: tuple[str, ...], season: int) -> int:
    value: Any = breakdown
    for key in path:
        if not isinstance(value, Mapping) or key not in value:
            raise ScoreBreakdownSchemaError(f"season {season} breakdown has no {'.'.join(path)}")
        value = value[key]
    # bool is an int subclass; a True here would be a schema change, not 1 point.
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ScoreBreakdownSchemaError(f"season {season} {'.'.join(path)}={value!r} is not a non-negative integer")
    return value


def auto_points(season: int, alliance_breakdown: Mapping[str, Any]) -> int:
    """One alliance's auto-period points under season's schema.

    Raises UnsupportedSeasonError for a season without an adapter, and
    ScoreBreakdownSchemaError if the breakdown is not the shape that season's
    adapter was verified against.
    """
    schema = _SCHEMAS.get(season)
    if schema is None:
        raise UnsupportedSeasonError(season)
    if not isinstance(alliance_breakdown, Mapping):
        raise ScoreBreakdownSchemaError(f"season {season} alliance breakdown is {type(alliance_breakdown).__name__}")

    auto = _points(alliance_breakdown, schema.auto, season)
    teleop = _points(alliance_breakdown, schema.teleop, season)
    fouls = _points(alliance_breakdown, ("foulPoints",), season)
    total = _points(alliance_breakdown, ("totalPoints",), season)
    # adjustPoints may legitimately be negative (a referee deduction).
    adjust = alliance_breakdown.get("adjustPoints", 0)
    if isinstance(adjust, bool) or not isinstance(adjust, int):
        raise ScoreBreakdownSchemaError(f"season {season} adjustPoints={adjust!r} is not an integer")
    if total != auto + teleop + fouls + adjust:
        raise ScoreBreakdownSchemaError(
            f"season {season} breakdown fails its decomposition: totalPoints={total} != "
            f"auto {auto} + teleop {teleop} + fouls {fouls} + adjust {adjust}"
        )
    return auto
