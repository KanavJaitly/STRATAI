"""Readiness of STRATAI EPA for Phase 4 (the STRATAI counterpart of decision D8).

automation/data_readiness.py checks the Statbotics source: for every team
appearance, the event D13 selects from canonical data must have a valid
team_event_stats row, because a missing row would silently fall back to an
older event's EPA. This module asks the same question of the STRATAI source,
read-only, for every (team, match) appearance in the given seasons:

* expected source -- the event D13 selects from canonical facts alone
  (end_date and the team's latest completed match both before as_of);
* served -- what StrataiPointInTimeEpa actually returns.

Outcomes, all counted, none dropped:

* served_expected -- the expected source's STRATAI value was served;
* withheld_no_prior_event -- no expected source exists (legitimate absence);
* availability_fallback / availability_withheld -- the expected source's
  value was not yet knowable at as_of (a season-end value, or week-1
  statistics still incomplete), so an older event was served or nothing was;
* missing_stratai_value -- the expected source has no STRATAI value at all.
  This is the silent-fallback defect D8 exists to catch; readiness requires 0.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from database.connection import Database
from ml.ratings.provider import StrataiPointInTimeEpa, TeamEventEpa

APPEARANCES_SQL = """
SELECT mt.team_number, m.event_key, m.scheduled_time, m.match_key
FROM matches m JOIN match_teams mt ON mt.match_key = m.match_key
WHERE m.season = ANY(%(seasons)s) AND m.scheduled_time IS NOT NULL
ORDER BY m.scheduled_time, m.match_key, mt.team_number
"""


@dataclass
class StrataiReadiness:
    seasons: list[int]
    counts: Counter = field(default_factory=Counter)
    missing_examples: list[dict[str, Any]] = field(default_factory=list)

    @property
    def ready(self) -> bool:
        return self.counts["missing_stratai_value"] == 0 and self.counts["appearances"] > 0

    def to_dict(self) -> dict[str, Any]:
        return {"seasons": self.seasons, "ready": self.ready, "counts": dict(sorted(self.counts.items())),
                "missing_examples": self.missing_examples}


def expected_source(provider: StrataiPointInTimeEpa, team: int, target: str, as_of: datetime) -> str | None:
    """D13 over canonical facts only, ignoring whether a STRATAI value exists."""
    for facts in provider._ordered.get(team, ()):  # noqa: SLF001 - the same ordering the provider serves from
        if facts.event_key != target and facts.end_instant < as_of and facts.last_completed_match < as_of:  # type: ignore[operator]
            return facts.event_key
    return None


def assess_stratai_readiness(database: Database, provider: StrataiPointInTimeEpa,
                             seasons: Sequence[int]) -> StrataiReadiness:
    report = StrataiReadiness(seasons=sorted(seasons))
    with database.cursor() as cursor:
        cursor.execute(APPEARANCES_SQL, {"seasons": list(seasons)})
        appearances = cursor.fetchall()
    for team, target, as_of, match_key in appearances:
        report.counts["appearances"] += 1
        expected = expected_source(provider, team, target, as_of)
        served = provider.point_in_time_epa(team, target, as_of)
        served_key = served.event_key if isinstance(served, TeamEventEpa) else None
        if expected is None:
            report.counts["withheld_no_prior_event" if served_key is None else "served_without_expected_source"] += 1
        elif (team, expected) not in provider.values:
            report.counts["missing_stratai_value"] += 1
            if len(report.missing_examples) < 20:
                report.missing_examples.append({"team": team, "match_key": match_key, "expected_source": expected})
        elif served_key == expected:
            report.counts["served_expected"] += 1
        else:
            report.counts["availability_fallback" if served_key is not None else "availability_withheld"] += 1
    return report
