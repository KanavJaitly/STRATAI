"""Historical season explorer (2026-10-11): read-only browsing of the canonical season data the web app needs.

Seasons, events, an event's teams and matches, and a team's season. Every value is read from the canonical tables
exactly as synced (TBA matches and teams; Statbotics EPA in `team_event_stats`). Nothing is computed, imputed or
filled in: absent data is returned as absent, with counts, so the web app can say so.

No model is called here. The analysis endpoints (metrics, strength, event analysis, qualification forecast,
predictions) are unchanged and keep their own validation statuses.

The routes live under /explorer (2026-10-21, integration with Phase 7): P7-M4's discovery reads own
/events/{event_key}/teams and /events/{event_key}/matches with their own locked shapes, so the explorer never
shadows them.
"""

from __future__ import annotations

import re
from http import HTTPStatus
from typing import Any

from fastapi import APIRouter, Depends, Path, Query

from api.contract import error_responses
from api.dependencies import get_database
from api.errors import ApiError
from data.readiness import SUPPORTED_SEASONS, data_coverage
from database.connection import Database

router = APIRouter(prefix="/explorer", tags=["historical season explorer (read-only)"])
# Declared error responses (the P7-M1 (f) contract every route keeps), with the codes each route raises.
_EVENT_ERRORS = error_responses({HTTPStatus.NOT_FOUND: ["event_not_found"],
                                 HTTPStatus.UNPROCESSABLE_ENTITY: ["invalid_input"]})
_TEAM_ERRORS = error_responses({HTTPStatus.NOT_FOUND: ["team_not_found"]})
EVENT_KEY = re.compile(r"^(\d{4})[a-z0-9]+$")


def _rows(cursor) -> list[dict[str, Any]]:
    columns = [d[0] for d in cursor.description]
    return [dict(zip(columns, row)) for row in cursor.fetchall()]


def _event(database: Database, event_key: str) -> dict[str, Any]:
    if not EVENT_KEY.fullmatch(event_key):
        raise ApiError(status_code=HTTPStatus.UNPROCESSABLE_ENTITY, code="invalid_input",
                       message="an event key is a 4-digit season followed by lowercase letters and digits")
    with database.cursor() as c:
        c.execute("SELECT * FROM events WHERE event_key = %s", (event_key,))
        rows = _rows(c)
    if not rows:
        raise ApiError(status_code=HTTPStatus.NOT_FOUND, code="event_not_found", message=f"no event {event_key}")
    return rows[0]


@router.get("/seasons", responses=error_responses({}, validates_input=False), summary="The supported seasons and the real data each has")
def get_seasons(database: Database = Depends(get_database)) -> Any:
    return [{"season": s, "coverage": data_coverage(database, s)} for s in SUPPORTED_SEASONS]


@router.get("/seasons/{season}/events", responses=error_responses({}), summary="A season's events, with team and match counts")
def get_season_events(season: int = Path(ge=1992, le=2100), database: Database = Depends(get_database)) -> Any:
    with database.cursor() as c:
        c.execute(
            "SELECT e.event_key, e.name, e.event_code, e.event_type, e.start_date, e.end_date, e.city, e.state_prov, "
            "e.country, count(DISTINCT m.match_key) AS matches, "
            "count(DISTINCT m.match_key) FILTER (WHERE m.score_red IS NOT NULL) AS matches_played, "
            "count(DISTINCT mt.team_number) AS teams "
            "FROM events e LEFT JOIN matches m USING (event_key) LEFT JOIN match_teams mt USING (match_key) "
            "WHERE e.season = %s GROUP BY e.event_key ORDER BY e.start_date NULLS LAST, e.event_key", (season,))
        return _rows(c)


@router.get("/events/{event_key}/teams", responses=_EVENT_ERRORS,
            summary="An event's teams with their synced EPA and record (absent values stay null)")
def get_event_teams(event_key: str = Path(min_length=5, max_length=32), database: Database = Depends(get_database)
                    ) -> Any:
    event = _event(database, event_key)
    with database.cursor() as c:
        c.execute(
            "SELECT t.team_number, t.name, t.city, t.state_province, t.country, s.epa_total, s.epa_auto, "
            "s.epa_teleop, s.epa_endgame, s.wins, s.losses, s.ties, s.matches_played, "
            "(tm.team_number IS NOT NULL) AS metrics_computed "
            "FROM (SELECT DISTINCT mt.team_number FROM match_teams mt JOIN matches m USING (match_key) "
            "      WHERE m.event_key = %s) roster "
            "JOIN teams t USING (team_number) "
            "LEFT JOIN team_event_stats s ON s.team_number = t.team_number AND s.event_key = %s "
            "LEFT JOIN team_metrics tm ON tm.team_number = t.team_number AND tm.event_key = %s "
            "ORDER BY s.epa_total DESC NULLS LAST, t.team_number", (event_key, event_key, event_key))
        teams = _rows(c)
    return {"event": event, "teams": teams,
            "epa_source": "Statbotics team_event_stats as synced (end-of-event values, not point-in-time)"}


@router.get("/events/{event_key}/matches", responses=_EVENT_ERRORS, summary="An event's matches, alliances and scores")
def get_event_matches(event_key: str = Path(min_length=5, max_length=32), database: Database = Depends(get_database)
                      ) -> Any:
    event = _event(database, event_key)
    with database.cursor() as c:
        c.execute(
            "SELECT m.match_key, m.competition_level, m.set_number, m.match_number, m.scheduled_time, m.score_red, "
            "m.score_blue, m.winning_alliance, "
            "array_agg(mt.team_number ORDER BY mt.station_position) FILTER (WHERE mt.alliance_color = 'red') AS red, "
            "array_agg(mt.team_number ORDER BY mt.station_position) FILTER (WHERE mt.alliance_color = 'blue') AS blue "
            "FROM matches m LEFT JOIN match_teams mt USING (match_key) WHERE m.event_key = %s "
            "GROUP BY m.match_key ORDER BY m.scheduled_time NULLS LAST, m.match_key", (event_key,))
        return {"event": event, "matches": _rows(c)}


@router.get("/teams/{team_number}/seasons/{season}", responses=_TEAM_ERRORS,
            summary="A team's events in a season, with synced EPA and record")
def get_team_season(team_number: int = Path(ge=1), season: int = Path(ge=1992, le=2100),
                    database: Database = Depends(get_database)) -> Any:
    with database.cursor() as c:
        c.execute("SELECT * FROM teams WHERE team_number = %s", (team_number,))
        team = _rows(c)
        if not team:
            raise ApiError(status_code=HTTPStatus.NOT_FOUND, code="team_not_found", message=f"no team {team_number}")
        c.execute(
            "SELECT e.event_key, e.name, e.start_date, s.epa_total, s.epa_auto, s.epa_teleop, s.epa_endgame, s.wins, "
            "s.losses, s.ties, s.matches_played, (tm.team_number IS NOT NULL) AS metrics_computed "
            "FROM events e JOIN (SELECT DISTINCT m.event_key FROM matches m JOIN match_teams mt USING (match_key) "
            "                    WHERE mt.team_number = %s AND m.season = %s) played USING (event_key) "
            "LEFT JOIN team_event_stats s ON s.event_key = e.event_key AND s.team_number = %s "
            "LEFT JOIN team_metrics tm ON tm.event_key = e.event_key AND tm.team_number = %s "
            "ORDER BY e.start_date NULLS LAST, e.event_key", (team_number, season, team_number, team_number))
        return {"team": team[0], "season": season, "events": _rows(c)}
