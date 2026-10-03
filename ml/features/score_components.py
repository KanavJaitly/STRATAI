"""P5-M7 per-season score component adapters: auto, teleop, endgame, fouls, adjustments.

These extend Phase 4's auto-points adapter (ml.features.score_breakdown, frozen and unmodified; `auto` comes from
its `auto_points`, which also re-checks the season's decomposition) to every scoring component. Each component is
an alliance's points in that period as TBA labels it:

| Season | teleop + endgame (TBA field) | endgame |
|---|---|---|
| 2024 | `teleopPoints` = teleopTotalNotePoints + endGameTotalStagePoints | `endGameTotalStagePoints` |
| 2025 | `teleopPoints` = teleopCoralPoints + algaePoints + endGameBargePoints | `endGameBargePoints` |
| 2026 | `totalTeleopPoints` = hubScore.teleopPoints + endGameTowerPoints | `hubScore.endgamePoints` + `endGameTowerPoints` |

`teleop` is that teleop total minus the endgame. `fouls` is `foulPoints` (points awarded for the opponent's
fouls). `adjust` is `adjustPoints` (possibly negative).

**Parity:** auto + teleop + endgame + fouls + adjust = totalPoints = the official score. Checked on every
2024–2026 alliance row on 2026-10-03 (33,954 / 35,692 / 36,744 rows, 100%), and re-checked by every call; a
violation raises.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from ml.features.score_breakdown import ScoreBreakdownSchemaError, UnsupportedSeasonError, auto_points

COMPONENTS = ("auto", "teleop", "endgame", "fouls")


@dataclass(frozen=True)
class ScoreComponents:
    auto: int
    teleop: int  # teleop excluding the endgame
    endgame: int
    fouls: int
    adjust: int
    total: int

    def share(self, component: str) -> float | None:
        """The component's share of the alliance's official score; None when the score is 0."""
        return None if self.total == 0 else getattr(self, component) / self.total


def _int(breakdown: Mapping[str, Any], *path: str, allow_negative: bool = False) -> int:
    value: Any = breakdown
    for key in path:
        if not isinstance(value, Mapping) or key not in value:
            raise ScoreBreakdownSchemaError(f"breakdown has no {'.'.join(path)}")
        value = value[key]
    if isinstance(value, bool) or not isinstance(value, int) or (value < 0 and not allow_negative):
        raise ScoreBreakdownSchemaError(f"{'.'.join(path)}={value!r} is not a valid integer")
    return value


def _teleop_and_endgame(season: int, b: Mapping[str, Any]) -> tuple[int, int]:
    if season == 2024:
        return _int(b, "teleopPoints"), _int(b, "endGameTotalStagePoints")
    if season == 2025:
        return _int(b, "teleopPoints"), _int(b, "endGameBargePoints")
    if season == 2026:
        return _int(b, "totalTeleopPoints"), _int(b, "hubScore", "endgamePoints") + _int(b, "endGameTowerPoints")
    raise UnsupportedSeasonError(season)


def score_components(season: int, alliance_breakdown: Mapping[str, Any]) -> ScoreComponents:
    """One alliance's components, or ScoreBreakdownSchemaError / UnsupportedSeasonError (never a guessed 0)."""
    auto = auto_points(season, alliance_breakdown)  # frozen Phase 4 adapter; checks the season decomposition
    teleop_total, endgame = _teleop_and_endgame(season, alliance_breakdown)
    if endgame > teleop_total:
        raise ScoreBreakdownSchemaError(f"season {season}: endgame {endgame} exceeds teleop total {teleop_total}")
    fouls = _int(alliance_breakdown, "foulPoints")
    adjust = alliance_breakdown.get("adjustPoints", 0)
    if isinstance(adjust, bool) or not isinstance(adjust, int):
        raise ScoreBreakdownSchemaError(f"adjustPoints={adjust!r} is not an integer")
    total = _int(alliance_breakdown, "totalPoints")
    parts = ScoreComponents(auto, teleop_total - endgame, endgame, fouls, adjust, total)
    if parts.auto + parts.teleop + parts.endgame + parts.fouls + parts.adjust != total:
        raise ScoreBreakdownSchemaError(f"season {season}: components do not sum to totalPoints {total}")
    return parts
