"""Decision D18's EPA source: Statbotics primary, STRATAI fallback for one event only.

Specification: .agent/phase4/D18_SOURCE_SPEC.md (frozen at commit ec1b0af).
This module implements its sections 1-3 and nothing else:

* Selection is D13 (ml.ratings.provider's ordering over canonical facts):
  the team's other events whose end instant and whose latest completed match
  for the team are both strictly before as_of, ordered by end date desc, then
  latest completed match desc, then event_key asc.
* Each candidate must have a valid Statbotics team-event row (epa_total not
  null, matches_played > 0). A missing or invalid row is a hard error
  (SilentFallbackError), never a silent step to an older event.
* Availability: a value is servable only when available_at < as_of, else the
  candidate is skipped (counted) and the next D13 candidate is considered.
    A1  record.qual.count == 0 (or absent): Statbotics' season-end value;
        available_at = T_end(Y), the season's last completed match.
    A2  otherwise: available_at = max(the team's last completed match at the
        source event, T_w1(Y)), T_w1(Y) the last completed match at events
        Statbotics lists as status "Completed", week 1.
* Fallback: an appearance whose target event is FALLBACK_EVENT is answered by
  the STRATAI provider, unchanged, and labelled "stratai_fallback". No other
  appearance ever reaches it.

The class takes plain data and reads nothing, so it is testable without a
database; scripts/run_phase4_d18.py loads and verifies that data from the
cached snapshot (scripts/sync_statbotics_snapshot.py) and the canonical tables.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field, replace
from datetime import datetime
from typing import Any

from ml.ratings.provider import (
    EPA_WITHHELD_NO_PRIOR_EVENT,
    PointInTimeEpaProvider,
    TeamEventEpa,
    TeamEventFacts,
    Unavailable,
    _d13_order,
)

D18_SPEC = ".agent/phase4/D18_SOURCE_SPEC.md"
D18_FREEZE_COMMIT = "ec1b0af"
FALLBACK_EVENT = "2026iscmp"
VALUE_SOURCE_STATBOTICS = "statbotics"
VALUE_SOURCE_FALLBACK = "stratai_fallback"
RULE_A1_SEASON_END = "A1_season_end"
RULE_A2_WEEK_ONE = "A2_week_one"
HARD_ERROR_MISSING_ROW = "missing_statbotics_row"
HARD_ERROR_INVALID_ROW = "invalid_statbotics_row"


@dataclass(frozen=True)
class StatboticsTeamEvent:
    """One team_event_stats row joined to its raw snapshot record's metadata."""

    season: int
    total: float | None
    auto: float | None
    teleop: float | None
    endgame: float | None
    matches_played: int | None
    qual_count: int | None  # raw record.qual.count

    @property
    def valid(self) -> bool:  # D8's validity rule
        return self.total is not None and self.matches_played is not None and self.matches_played > 0

    @property
    def rule(self) -> str:
        return RULE_A2_WEEK_ONE if self.qual_count else RULE_A1_SEASON_END


class SilentFallbackError(RuntimeError):
    """A D13 candidate outside the fallback scope has no valid Statbotics row (D18 §2)."""

    def __init__(self, team: int, target_event_key: str, as_of: datetime, candidate: str, reason: str) -> None:
        super().__init__(f"team {team} at {target_event_key} ({as_of.isoformat()}): D13 candidate {candidate} "
                         f"is a {reason}; D18 forbids falling back to an older event")
        self.record = {"team": team, "target_event_key": target_event_key, "as_of": as_of.isoformat(),
                       "candidate": candidate, "reason": reason}


@dataclass
class StatboticsPrimaryEpa:
    """D18's point-in-time EPA provider (see the module docstring)."""

    statbotics: dict[tuple[int, str], StatboticsTeamEvent]
    facts: dict[int, list[TeamEventFacts]]
    season_end: dict[int, datetime]  # T_end(Y)
    week_one_complete: dict[int, datetime]  # T_w1(Y)
    fallback: PointInTimeEpaProvider
    provenance_info: dict[str, Any] = field(default_factory=dict)
    strict: bool = True  # False only for verification, which counts hard errors instead of stopping
    diagnostics: Counter = field(default_factory=Counter)
    hard_errors: list[dict[str, Any]] = field(default_factory=list)
    source: str = "d18_statbotics_primary"

    def __post_init__(self) -> None:
        self._ordered = {
            team: sorted((f for f in items if f.end_instant is not None and f.last_completed_match is not None),
                         key=_d13_order)
            for team, items in self.facts.items()
        }

    def available_at(self, value: StatboticsTeamEvent, facts: TeamEventFacts) -> datetime:
        if value.rule == RULE_A1_SEASON_END:
            return self.season_end[value.season]
        return max(facts.last_completed_match, self.week_one_complete[value.season])  # type: ignore[type-var]

    def point_in_time_epa(self, team: int, target_event_key: str, as_of: datetime) -> TeamEventEpa | Unavailable:
        if target_event_key == FALLBACK_EVENT:
            return self._fallback(team, target_event_key, as_of)
        skipped: list[str] = []
        for facts in self._ordered.get(team, ()):
            if facts.event_key == target_event_key:
                continue
            if not (facts.end_instant < as_of and facts.last_completed_match < as_of):  # type: ignore[operator]
                continue
            value = self.statbotics.get((team, facts.event_key))
            if value is None or not value.valid:
                reason = HARD_ERROR_MISSING_ROW if value is None else HARD_ERROR_INVALID_ROW
                error = SilentFallbackError(team, target_event_key, as_of, facts.event_key, reason)
                if self.strict:
                    raise error
                self.diagnostics[f"hard_error:{reason}"] += 1
                self.hard_errors.append(error.record)
                return Unavailable("d18_hard_error", str(error))
            available_at = self.available_at(value, facts)
            if not available_at < as_of:
                self.diagnostics[f"skipped:{value.rule}"] += 1
                skipped.append(facts.event_key)
                continue
            self.diagnostics[f"served:{VALUE_SOURCE_STATBOTICS}:{value.rule}"] += 1
            return TeamEventEpa(team, facts.event_key, value.total, value.auto, value.teleop, value.endgame,  # type: ignore[arg-type]
                                VALUE_SOURCE_STATBOTICS, False,  # type: ignore[arg-type]
                                {"rule": value.rule, "available_at": available_at.isoformat(), "skipped": skipped})
        # every candidate unavailable (§3) vs no candidate at all (legitimate, as under D13)
        self.diagnostics["withheld:availability" if skipped else "withheld:no_prior_event"] += 1
        return Unavailable(EPA_WITHHELD_NO_PRIOR_EVENT, "no qualifying prior event with an available Statbotics EPA")

    def _fallback(self, team: int, target_event_key: str, as_of: datetime) -> TeamEventEpa | Unavailable:
        found = self.fallback.point_in_time_epa(team, target_event_key, as_of)
        if not isinstance(found, TeamEventEpa):
            self.diagnostics["withheld:fallback_scope"] += 1
            return found
        self.diagnostics[f"served:{VALUE_SOURCE_FALLBACK}"] += 1
        return replace(found, source=VALUE_SOURCE_FALLBACK,  # type: ignore[arg-type]
                       provenance={**found.provenance, "fallback_provider": self.fallback.source})

    def provenance(self) -> dict[str, Any]:
        return {"source": self.source, "spec": D18_SPEC, "freeze_commit": D18_FREEZE_COMMIT,
                "fallback_event": FALLBACK_EVENT, "fallback": self.fallback.provenance(),
                "season_end": {str(k): v.isoformat() for k, v in sorted(self.season_end.items())},
                "week_one_complete": {str(k): v.isoformat() for k, v in sorted(self.week_one_complete.items())},
                "lookup_diagnostics": dict(sorted(self.diagnostics.items())),
                **self.provenance_info}
