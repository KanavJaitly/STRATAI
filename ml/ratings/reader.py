"""Build the EPA engine's SeasonInput from STRATAI's stored data (data contract §2).

This is the only module in ml.ratings that touches the database, and it only
reads. The canonical tables decide WHICH events and matches exist for a
season; the untouched raw TBA payload (raw_source_payloads, source='tba',
is_current) supplies what the canonical tables do not hold -- event type,
week and district; comp level, DQs, surrogates and score breakdowns -- and is
the contract's source for time, rosters and scores as well.

Canonical and raw values are cross-checked where both exist. A disagreement
is never silently resolved: it becomes a ReaderIssue, either "excluded" (the
record cannot be built, so it does not reach the engine) or "noted" (the
contract's raw value is used and the difference reported).
"""

from __future__ import annotations

import hashlib
from collections import defaultdict
from dataclasses import dataclass
from typing import Any, Literal

from database.connection import Database
from ml.ratings.epa.inputs import AllianceInput, EventInput, MatchInput, SeasonInput

SOURCE_TBA = "tba"
OBJECT_TYPE_EVENT = "event"
OBJECT_TYPE_MATCH = "match"
COMP_LEVELS = ("qm", "ef", "qf", "sf", "f")

# Issue codes. "excluded" issues keep a record away from the engine; "noted" ones do not.
RAW_EVENT_MISSING = "raw_event_payload_missing"
RAW_EVENT_INVALID = "raw_event_payload_invalid"
RAW_MATCH_MISSING = "raw_match_payload_missing"
RAW_MATCH_INVALID = "raw_match_payload_invalid"
RAW_MATCH_EVENT_MISMATCH = "raw_match_event_mismatch"
DUPLICATE_CURRENT_PAYLOAD = "duplicate_current_payload"
UNPARSEABLE_TEAM_KEY = "unparseable_team_key"
PLACEHOLDER_TEAM_KEY = "placeholder_team_key"
CANONICAL_TIME_MISMATCH = "canonical_time_mismatch"
CANONICAL_SCORE_MISMATCH = "canonical_score_mismatch"
CANONICAL_ROSTER_MISMATCH = "canonical_roster_mismatch"

Effect = Literal["excluded", "noted"]


@dataclass(frozen=True)
class ReaderIssue:
    code: str
    effect: Effect
    event_key: str
    match_key: str | None
    detail: str

    def to_dict(self) -> dict[str, Any]:
        return {"code": self.code, "effect": self.effect, "event_key": self.event_key,
                "match_key": self.match_key, "detail": self.detail}


@dataclass(frozen=True)
class ReadResult:
    season_input: SeasonInput
    issues: tuple[ReaderIssue, ...]
    snapshot: dict[str, Any]
    canonical_events: int
    canonical_matches: int


@dataclass(frozen=True)
class CanonicalMatch:
    match_key: str
    event_key: str
    scheduled_time: int | None  # epoch seconds
    score_red: int | None
    score_blue: int | None
    red_roster: tuple[int, ...]  # sorted, from match_teams
    blue_roster: tuple[int, ...]


# --- pure conversions (unit-tested without a database) -----------------------


def event_input_from_payload(event_key: str, payload: dict[str, Any]) -> EventInput | ReaderIssue:
    """A TBA event payload -> EventInput, or why it cannot be one."""
    event_type, week, district = payload.get("event_type"), payload.get("week"), payload.get("district")
    problems = []
    if isinstance(event_type, bool) or not isinstance(event_type, int):
        problems.append(f"event_type={event_type!r}")
    if week is not None and (isinstance(week, bool) or not isinstance(week, int)):
        problems.append(f"week={week!r}")
    if district is not None and not (isinstance(district, dict) and isinstance(district.get("abbreviation"), str)):
        problems.append(f"district={district!r}")
    if problems:
        return ReaderIssue(RAW_EVENT_INVALID, "excluded", event_key, None, ", ".join(problems))
    return EventInput(
        event_key=event_key,
        event_type=event_type,
        week=week,
        district=None if district is None else district["abbreviation"],
    )


def _team_numbers(keys: Any) -> tuple[int, ...] | None:
    if not isinstance(keys, list):
        return None
    out = []
    for key in keys:
        if not (isinstance(key, str) and key.startswith("frc") and key[3:].isdigit()):
            return None
        out.append(int(key[3:]))
    return tuple(out)


def _score(value: Any) -> int | None | str:
    if value is None or (isinstance(value, int) and not isinstance(value, bool)):
        return value
    return "invalid"


def match_input_from_payload(
    canonical: CanonicalMatch, payload: dict[str, Any]
) -> tuple[MatchInput | None, list[ReaderIssue]]:
    """A TBA match payload -> MatchInput, plus every issue found building it."""
    key, event_key = canonical.match_key, canonical.event_key
    issues: list[ReaderIssue] = []

    def excluded(code: str, detail: str) -> tuple[None, list[ReaderIssue]]:
        issues.append(ReaderIssue(code, "excluded", event_key, key, detail))
        return None, issues

    if payload.get("event_key") != event_key:
        return excluded(RAW_MATCH_EVENT_MISMATCH, f"raw event_key {payload.get('event_key')!r}")
    comp_level, time = payload.get("comp_level"), payload.get("time")
    set_number, match_number = payload.get("set_number"), payload.get("match_number")
    if comp_level not in COMP_LEVELS:
        return excluded(RAW_MATCH_INVALID, f"comp_level={comp_level!r}")
    if not all(isinstance(v, int) and not isinstance(v, bool) for v in (set_number, match_number)):
        return excluded(RAW_MATCH_INVALID, f"set_number={set_number!r} match_number={match_number!r}")
    if time is not None and (isinstance(time, bool) or not isinstance(time, int)):
        return excluded(RAW_MATCH_INVALID, f"time={time!r}")
    breakdowns = payload.get("score_breakdown")
    if breakdowns is not None and not isinstance(breakdowns, dict):
        return excluded(RAW_MATCH_INVALID, f"score_breakdown is {type(breakdowns).__name__}")

    alliances: dict[str, AllianceInput] = {}
    for color in ("red", "blue"):
        raw = (payload.get("alliances") or {}).get(color)
        if not isinstance(raw, dict):
            return excluded(RAW_MATCH_INVALID, f"alliances.{color} missing")
        teams = _team_numbers(raw.get("team_keys"))
        dq = _team_numbers(raw.get("dq_team_keys", []))
        surrogates = _team_numbers(raw.get("surrogate_team_keys", []))
        if teams is None or dq is None or surrogates is None:
            return excluded(UNPARSEABLE_TEAM_KEY, f"{color}: team_keys={raw.get('team_keys')!r} "
                            f"dq={raw.get('dq_team_keys')!r} surrogates={raw.get('surrogate_team_keys')!r}")
        if 0 in teams:
            issues.append(ReaderIssue(PLACEHOLDER_TEAM_KEY, "noted", event_key, key,
                                      f"{color} team_keys {raw.get('team_keys')!r}"))
        score = _score(raw.get("score"))
        if score == "invalid":
            return excluded(RAW_MATCH_INVALID, f"{color} score={raw.get('score')!r}")
        breakdown = None if breakdowns is None else breakdowns.get(color)
        if breakdown is not None and not isinstance(breakdown, dict):
            return excluded(RAW_MATCH_INVALID, f"score_breakdown.{color} is {type(breakdown).__name__}")
        alliances[color] = AllianceInput(teams=teams, dq_teams=dq, surrogate_teams=surrogates,
                                         score=score, breakdown=breakdown)  # type: ignore[arg-type]

    _cross_check(canonical, time, alliances, issues)
    match = MatchInput(match_key=key, event_key=event_key, comp_level=comp_level, set_number=set_number,
                       match_number=match_number, time=time, red=alliances["red"], blue=alliances["blue"])
    return match, issues


def _cross_check(canonical: CanonicalMatch, time: int | None, alliances: dict[str, AllianceInput],
                 issues: list[ReaderIssue]) -> None:
    key, event_key = canonical.match_key, canonical.event_key
    if canonical.scheduled_time != time:
        issues.append(ReaderIssue(CANONICAL_TIME_MISMATCH, "noted", event_key, key,
                                  f"canonical {canonical.scheduled_time} raw {time}"))
    for color, stored in (("red", canonical.score_red), ("blue", canonical.score_blue)):
        raw = alliances[color].score
        # TBA reports an unplayed alliance as -1; the canonical table stores NULL
        if stored != raw and not (stored is None and (raw is None or raw < 0)):
            issues.append(ReaderIssue(CANONICAL_SCORE_MISMATCH, "noted", event_key, key,
                                      f"{color}: canonical {stored} raw {raw}"))
    for color, roster in (("red", canonical.red_roster), ("blue", canonical.blue_roster)):
        raw_roster = tuple(sorted(alliances[color].teams))
        if roster != raw_roster:
            issues.append(ReaderIssue(CANONICAL_ROSTER_MISMATCH, "noted", event_key, key,
                                      f"{color}: match_teams {list(roster)} raw {list(raw_roster)}"))


# --- database reads ----------------------------------------------------------------

_EVENTS_SQL = """
    SELECT e.event_key, r.id, r.payload_json
    FROM events e
    LEFT JOIN raw_source_payloads r
      ON r.source = %(source)s AND r.source_object_type = %(event_type)s
     AND r.source_object_id = e.event_key AND r.is_current
    WHERE e.season = %(season)s {event_filter}
    ORDER BY e.event_key, r.id
"""
_MATCHES_SQL = """
    SELECT m.match_key, m.event_key, extract(epoch FROM m.scheduled_time)::bigint,
           m.score_red, m.score_blue, r.id, r.payload_json
    FROM matches m
    LEFT JOIN raw_source_payloads r
      ON r.source = %(source)s AND r.source_object_type = %(match_type)s
     AND r.source_object_id = m.match_key AND r.is_current
    WHERE m.season = %(season)s {match_filter}
    ORDER BY m.match_key, r.id
"""
_ROSTERS_SQL = """
    SELECT mt.match_key, mt.alliance_color, mt.team_number
    FROM match_teams mt JOIN matches m ON m.match_key = mt.match_key
    WHERE m.season = %(season)s {match_filter}
    ORDER BY mt.match_key, mt.alliance_color, mt.team_number
"""


def read_season_input(database: Database, season: int, *, event_keys: list[str] | None = None) -> ReadResult:
    """Read one season (optionally only some events) into a SeasonInput. Read-only."""
    params: dict[str, Any] = {"source": SOURCE_TBA, "event_type": OBJECT_TYPE_EVENT,
                              "match_type": OBJECT_TYPE_MATCH, "season": season, "event_keys": event_keys}
    event_filter = "AND e.event_key = ANY(%(event_keys)s)" if event_keys is not None else ""
    match_filter = "AND m.event_key = ANY(%(event_keys)s)" if event_keys is not None else ""
    with database.connection() as conn, conn.cursor() as cur:
        cur.execute(_EVENTS_SQL.format(event_filter=event_filter), params)
        event_rows = cur.fetchall()
        cur.execute(_MATCHES_SQL.format(match_filter=match_filter), params)
        match_rows = cur.fetchall()
        cur.execute(_ROSTERS_SQL.format(match_filter=match_filter), params)
        roster_rows = cur.fetchall()
        conn.rollback()  # nothing was written; end the read transaction explicitly
    return assemble_season_input(season, event_rows, match_rows, roster_rows)


def assemble_season_input(season: int, event_rows: list[tuple], match_rows: list[tuple],
                          roster_rows: list[tuple]) -> ReadResult:
    """Pure: the three query results -> ReadResult."""
    issues: list[ReaderIssue] = []
    payload_ids: list[int] = []

    by_event: dict[str, list[tuple[int, dict]]] = defaultdict(list)
    for event_key, raw_id, payload in event_rows:
        by_event.setdefault(event_key, [])
        if raw_id is not None:
            by_event[event_key].append((raw_id, payload))
    events: list[EventInput] = []
    excluded_events: set[str] = set()
    for event_key in sorted(by_event):
        found = by_event[event_key]
        if len(found) != 1:
            code = RAW_EVENT_MISSING if not found else DUPLICATE_CURRENT_PAYLOAD
            issues.append(ReaderIssue(code, "excluded", event_key, None, f"{len(found)} current raw event payloads"))
            excluded_events.add(event_key)
            continue
        payload_ids.append(found[0][0])
        converted = event_input_from_payload(event_key, found[0][1])
        if isinstance(converted, ReaderIssue):
            issues.append(converted)
            excluded_events.add(event_key)
        else:
            events.append(converted)

    rosters: dict[str, dict[str, list[int]]] = defaultdict(lambda: {"red": [], "blue": []})
    for match_key, color, team in roster_rows:
        rosters[match_key].setdefault(color, []).append(team)

    by_match: dict[str, list[tuple]] = defaultdict(list)
    for row in match_rows:
        by_match[row[0]].append(row)
    matches: list[MatchInput] = []
    for match_key in sorted(by_match):
        rows = by_match[match_key]
        _, event_key, scheduled, score_red, score_blue, _, _ = rows[0]
        if event_key in excluded_events:
            issues.append(ReaderIssue(RAW_EVENT_MISSING if not by_event[event_key] else RAW_EVENT_INVALID,
                                      "excluded", event_key, match_key, "its event could not be read"))
            continue
        found = [(raw_id, payload) for *_, raw_id, payload in rows if raw_id is not None]
        if len(found) != 1:
            code = RAW_MATCH_MISSING if not found else DUPLICATE_CURRENT_PAYLOAD
            issues.append(ReaderIssue(code, "excluded", event_key, match_key, f"{len(found)} current raw match payloads"))
            continue
        payload_ids.append(found[0][0])
        roster = rosters.get(match_key, {"red": [], "blue": []})
        canonical = CanonicalMatch(match_key, event_key, None if scheduled is None else int(scheduled),
                                   score_red, score_blue, tuple(sorted(roster.get("red", []))),
                                   tuple(sorted(roster.get("blue", []))))
        match, match_issues = match_input_from_payload(canonical, found[0][1])
        issues.extend(match_issues)
        if match is not None:
            matches.append(match)

    snapshot = {
        "raw_payloads_read": len(payload_ids),
        "max_raw_payload_id": max(payload_ids, default=None),
        "raw_payload_ids_sha256": hashlib.sha256(",".join(map(str, sorted(payload_ids))).encode()).hexdigest(),
        "canonical_rows": {"events": len(by_event), "matches": len(by_match), "match_teams": len(roster_rows)},
    }
    issues.sort(key=lambda i: (i.code, i.event_key, i.match_key or "", i.detail))
    return ReadResult(
        season_input=SeasonInput(season=season, events=tuple(events), matches=tuple(matches)),
        issues=tuple(issues),
        snapshot=snapshot,
        canonical_events=len(by_event),
        canonical_matches=len(by_match),
    )
