"""Discovery reads (P7-M4, P7-Q8): the events of a season, an event's teams, and an event's matches.

Read-only views of the canonical tables (events, teams, matches, match_teams), so a client can find an event, a team
or a match before asking for an analysis.

**Point in time.**
- **Qualification schedule.** Always visible: it is published before the event.
- **Playoff matches.** A playoff match is listed only once it was scheduled before `as_of`. Its alliances are the
  alliance-selection outcome, and which alliances fill a later bracket match reveals earlier results (data/replay.py:
  playoff matches "appear only once played"). A playoff match with no scheduled time is never listed.
- **Results.** A result is visible only for a match scheduled before `as_of`, the same availability rule the feature
  assembler uses (ml.features.assembler: `scheduled_time < as_of`). A match with no scheduled time cannot be placed
  in time, so its result is withheld too. A withheld result is null with its reason, never a 0.

**Honest limits** (shared with the feature assembler):
- `scheduled_time` is TBA's planned time, not when the match was played or posted. At an event running late, a
  result can become visible between its scheduled time and its real time.
- A visible result is the score as stored now, which may include later corrections, not the score as first posted.
- The canonical tables hold no actual or post-result time, so no tighter rule is available without a decision.

The roster is ml.features.roster.list_teams_at_event, the roster every other view uses.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime

from database.connection import Database
from ml.features.roster import list_teams_at_event

QUALIFICATION = "qualification"
RESULT_NOT_BEFORE_AS_OF = "not_scheduled_before_as_of"
RESULT_NO_SCHEDULED_TIME = "no_scheduled_time"
RESULT_NOT_PLAYED = "not_played"


@dataclass(frozen=True)
class EventSummary:
    event_key: str
    season: int
    name: str | None
    start_date: date | None
    end_date: date | None
    city: str | None
    state_province: str | None  # events.state_prov, named as on teams (P7-D4)
    country: str | None


@dataclass(frozen=True)
class RosterTeam:
    team_number: int
    name: str | None
    city: str | None
    state_province: str | None
    country: str | None
    rookie_year: int | None


@dataclass(frozen=True)
class MatchResult:
    score_red: int
    score_blue: int
    winning_alliance: str | None  # "red", "blue" or "tie" (data/staging/normalizer.py); null only if none recorded


@dataclass(frozen=True)
class ScheduledMatch:
    match_key: str
    competition_level: str | None
    set_number: int | None
    match_number: int | None
    scheduled_time: datetime | None
    red_team_numbers: list[int]
    blue_team_numbers: list[int]
    result: MatchResult | None
    result_withheld_reason: str | None


def season_events(database: Database, season: int) -> list[EventSummary]:
    """Every event of a season, by start date then key (events without a start date last)."""
    with database.cursor() as cursor:
        cursor.execute(
            "SELECT event_key, season, name, start_date, end_date, city, state_prov, country "
            "FROM events WHERE season = %s ORDER BY start_date NULLS LAST, event_key", (season,))
        return [EventSummary(*row) for row in cursor.fetchall()]


def event_roster(database: Database, event_key: str) -> list[RosterTeam]:
    """The event's roster (list_teams_at_event), with each team's details; a team missing from `teams` keeps its
    number with null details."""
    numbers = list_teams_at_event(database, event_key)
    if not numbers:
        return []
    with database.cursor() as cursor:
        cursor.execute("SELECT team_number, name, city, state_province, country, rookie_year FROM teams "
                       "WHERE team_number = ANY(%s)", (numbers,))
        details = {row[0]: row for row in cursor.fetchall()}
    return [RosterTeam(*details[n]) if n in details else RosterTeam(n, None, None, None, None, None)
            for n in numbers]


def event_matches(database: Database, event_key: str, as_of: datetime) -> list[ScheduledMatch]:
    """The event's matches available at `as_of` (the module's point-in-time rules), in schedule order: scheduled
    time, then qualification before playoffs, set and match number; untimed qualification matches last."""
    with database.cursor() as cursor:
        cursor.execute(
            "SELECT m.match_key, m.competition_level, m.set_number, m.match_number, m.scheduled_time, "
            "m.score_red, m.score_blue, m.winning_alliance FROM matches m WHERE m.event_key = %s "
            "ORDER BY m.scheduled_time NULLS LAST, (m.competition_level = %s) DESC, m.set_number NULLS FIRST, "
            "m.match_number NULLS LAST, m.match_key", (event_key, QUALIFICATION))
        rows = [row for row in cursor.fetchall()
                if row[1] == QUALIFICATION or (row[4] is not None and row[4] < as_of)]
        cursor.execute(
            "SELECT mt.match_key, mt.alliance_color, mt.team_number FROM match_teams mt "
            "JOIN matches m ON m.match_key = mt.match_key WHERE m.event_key = %s "
            "ORDER BY mt.match_key, mt.station_position NULLS LAST, mt.team_number", (event_key,))
        alliances: dict[tuple[str, str], list[int]] = {}
        for match_key, color, team in cursor.fetchall():
            alliances.setdefault((match_key, color), []).append(team)
    out = []
    for key, level, set_number, number, scheduled, red, blue, winner in rows:
        if scheduled is None:
            result, reason = None, RESULT_NO_SCHEDULED_TIME
        elif not scheduled < as_of:
            result, reason = None, RESULT_NOT_BEFORE_AS_OF
        elif red is None or blue is None:
            result, reason = None, RESULT_NOT_PLAYED
        else:
            result, reason = MatchResult(red, blue, winner), None
        out.append(ScheduledMatch(key, level, set_number, number, scheduled, alliances.get((key, "red"), []),
                                  alliances.get((key, "blue"), []), result, reason))
    return out


__all__ = [
    "EventSummary", "MatchResult", "RESULT_NOT_BEFORE_AS_OF", "RESULT_NOT_PLAYED", "RESULT_NO_SCHEDULED_TIME",
    "RosterTeam", "ScheduledMatch", "event_matches", "event_roster", "season_events",
]
