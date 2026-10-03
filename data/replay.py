"""A historical replay source for P5-M6: recorded TBA payloads served as they stood at a replay instant.

History cannot be re-fetched live, so the P5-M6 replay substitutes only the HTTP layer. `ReplayTBAClient`
answers the three calls `data.pipeline.extract_event` makes (`fetch_event`, `fetch_event_matches`,
`fetch_event_teams`, plus `fetch_team_info` for roster backfill). The answers are built from payloads recorded in
a source database's `raw_source_payloads`. Everything after extraction (landing, staging, quality, loading,
lineage, watermarks) is the production `data.orchestrator.sync_event`, unchanged.

**What a replay instant shows:**
- **Completed matches:** their recorded payload, byte for byte.
- **Qualification matches not yet completed:** TBA's own unplayed representation:
  - both alliance scores -1;
  - no `score_breakdown`;
  - no `actual_time` / `post_result_time`;
  - an empty `winning_alliance`.
  The qualification schedule is published before an event starts.
- **Playoff matches:** appear only once played, because their alliances do not exist before selection.

Final rankings and alliances are never served: they are labels, not inputs.
"""

from __future__ import annotations

import copy
from dataclasses import dataclass, field
from types import SimpleNamespace
from typing import Any

RECORDED_SQL = """
SELECT DISTINCT ON (source_object_type, source_object_id) source_object_type, source_object_id, payload_json
FROM raw_source_payloads
WHERE source = 'tba' AND is_current AND (
    (source_object_type = 'event' AND source_object_id = %(event)s)
 OR (source_object_type = 'match' AND payload_json->>'event_key' = %(event)s))
ORDER BY source_object_type, source_object_id, id DESC
"""
TEAM_SQL = """
SELECT DISTINCT ON (source_object_id) source_object_id, payload_json FROM raw_source_payloads
WHERE source = 'tba' AND source_object_type = 'team' AND is_current AND source_object_id = ANY(%(keys)s)
ORDER BY source_object_id, id DESC
"""


def unplayed(payload: dict[str, Any]) -> dict[str, Any]:
    """TBA's representation of a scheduled match that has not been played yet."""
    out = copy.deepcopy(payload)
    for alliance in (out.get("alliances") or {}).values():
        alliance["score"] = -1
    out["score_breakdown"] = None
    out["winning_alliance"] = ""
    out["actual_time"] = None
    out["post_result_time"] = None
    return out


@dataclass
class RecordedEvent:
    event_key: str
    event: dict[str, Any]
    matches: dict[str, dict[str, Any]]  # match_key -> recorded (played) payload
    teams: dict[str, dict[str, Any]]  # team_key -> recorded team payload

    def ordered_matches(self) -> list[tuple[int, str]]:
        return sorted((m.get("time") or 0, key) for key, m in self.matches.items())


def load_recorded_event(database, event_key: str) -> RecordedEvent:
    """The event's current recorded payloads, read from a (read-only) source database."""
    with database.cursor() as cursor:
        cursor.execute(RECORDED_SQL, {"event": event_key})
        rows = cursor.fetchall()
    event = next(payload for kind, _, payload in rows if kind == "event")
    matches = {key: payload for kind, key, payload in rows if kind == "match"}
    team_keys = sorted({k for m in matches.values() for a in (m.get("alliances") or {}).values()
                        for k in (a.get("team_keys") or []) + (a.get("surrogate_team_keys") or [])})
    with database.cursor() as cursor:
        cursor.execute(TEAM_SQL, {"keys": team_keys})
        teams = dict(cursor.fetchall())
    return RecordedEvent(event_key, event, matches, teams)


@dataclass
class ReplayTBAClient:
    """Serves recorded events as they stood at the replay instant (see the module docstring)."""

    events: dict[str, RecordedEvent]
    completed: set[str] = field(default_factory=set)

    def complete(self, match_keys: list[str]) -> None:
        self.completed.update(match_keys)

    def fetch_event(self, event_key: str) -> SimpleNamespace:
        return SimpleNamespace(raw=copy.deepcopy(self.events[event_key].event))

    def fetch_event_matches(self, event_key: str) -> list[SimpleNamespace]:
        out = []
        for key, payload in sorted(self.events[event_key].matches.items()):
            if key in self.completed:
                out.append(SimpleNamespace(raw=copy.deepcopy(payload)))
            elif payload.get("comp_level") == "qm":
                out.append(SimpleNamespace(raw=unplayed(payload)))
        return out

    def fetch_event_teams(self, event_key: str) -> list[SimpleNamespace]:
        return [SimpleNamespace(raw=copy.deepcopy(p)) for _, p in sorted(self.events[event_key].teams.items())]

    def fetch_team_info(self, team_number: int) -> SimpleNamespace:
        for recorded in self.events.values():
            if f"frc{team_number}" in recorded.teams:
                return SimpleNamespace(raw=copy.deepcopy(recorded.teams[f"frc{team_number}"]))
        raise KeyError(f"frc{team_number} is not in the recorded payloads")
