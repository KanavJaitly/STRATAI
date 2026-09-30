"""The EPA source boundary (data contract §7). Interface plus the STRATAI side.

Future consumers ask one question -- a team's EPA at an event -- and name the
source. Nothing is switched here: Phase 4's assembler still reads Statbotics'
team_event_stats directly and is untouched. A "statbotics" provider over that
table, and any consumer switch, are later, separate decisions.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, Protocol

from ml.ratings.epa.season import SeasonResult

EpaSource = Literal["statbotics", "stratai"]

UNAVAILABLE_NOT_RUN = "season_not_run"
UNAVAILABLE_NO_TEAM_EVENT = "team_did_not_play_event"


@dataclass(frozen=True)
class TeamEventEpa:
    """End-of-event EPA, the snapshot semantics Phase 4 reads from team_event_stats."""

    team: int
    event_key: str
    total: float
    auto: float
    teleop: float
    endgame: float
    source: EpaSource
    lookahead: bool  # True when the value is the team's season-end rating (aggregate.py)
    provenance: dict


@dataclass(frozen=True)
class Unavailable:
    reason: str
    detail: str


class EpaProvider(Protocol):
    source: EpaSource

    def team_event_epa(self, team: int, event_key: str) -> TeamEventEpa | Unavailable: ...


class StrataiEpaProvider:
    """Serves team-event EPA from in-memory SeasonResults of the STRATAI engine."""

    source: EpaSource = "stratai"

    def __init__(self, results: list[SeasonResult]) -> None:
        self._results = {r.season: r for r in results}
        self._fingerprints = {r.season: r.results_fingerprint() for r in results}

    def team_event_epa(self, team: int, event_key: str) -> TeamEventEpa | Unavailable:
        season = int(event_key[:4]) if event_key[:4].isdigit() else None
        result = self._results.get(season) if season is not None else None
        if result is None:
            return Unavailable(UNAVAILABLE_NOT_RUN, f"no STRATAI EPA run for season of {event_key}")
        team_event = result.team_event(team, event_key)
        if team_event is None:
            return Unavailable(UNAVAILABLE_NO_TEAM_EVENT, f"team {team} has no retained match at {event_key}")
        components = team_event.components
        return TeamEventEpa(
            team=team,
            event_key=event_key,
            total=team_event.epa,
            auto=components["auto_epa"],
            teleop=components["teleop_epa"],
            endgame=components["endgame_epa"],
            source=self.source,
            lookahead=team_event.epa_is_season_end,
            provenance={
                "engine_version": result.manifest["engine_version"],
                "input_fingerprint": result.manifest["input_fingerprint"],
                "results_fingerprint": self._fingerprints[result.season],
                "initialization": result.initialization,
            },
        )
