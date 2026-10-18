"""P7-M4: discovery reads (P7-Q8) -- how a client finds an event, a team or a match.

    GET /events?season=<year>
    GET /events/{event_key}/teams
    GET /events/{event_key}/matches[?as_of=<ISO-8601 with offset>]

Read-only views of the canonical tables (ml.views.discovery). An event's matches show the qualification schedule
always, a playoff match only once scheduled before as_of, and a result only for a match scheduled before as_of
(default now); a withheld result is null with its reason (ml.views.discovery documents the rules and their limits).
Every response carries a `validation` block: these are canonical records, `descriptive`.

Codes: event_not_found (404), invalid_as_of (422), validation_error (422, the season), internal_error (500).
"""

from __future__ import annotations

from datetime import date, datetime
from http import HTTPStatus

from fastapi import APIRouter, Depends, Path, Query
from pydantic import BaseModel, Field

from api.contract import Validation, error_responses
from api.dependencies import get_database
from api.routes.common import AS_OF_DESCRIPTION, CODE_EVENT_NOT_FOUND, CODE_INVALID_AS_OF, event_not_found_error, parse_as_of
from database.connection import Database
from ml.features.roster import event_exists
from ml.views.discovery import event_matches, event_roster, season_events
from ml.views.strength import DESCRIPTIVE

router = APIRouter(tags=["discovery"])

CANONICAL_RECORD = "canonical_tba_record"
_VALIDATION = Validation(status=DESCRIPTIVE, reasons=[CANONICAL_RECORD])


class EventOut(BaseModel):
    event_key: str
    season: int
    name: str | None
    start_date: date | None
    end_date: date | None
    city: str | None
    state_province: str | None
    country: str | None


class SeasonEventsResponse(BaseModel):
    season: int
    validation: Validation
    events: list[EventOut] = Field(description="By start date, then event key; empty when the season has none.")


class RosterTeamOut(BaseModel):
    team_number: int
    name: str | None
    city: str | None
    state_province: str | None
    country: str | None
    rookie_year: int | None


class EventTeamsResponse(BaseModel):
    event_key: str
    validation: Validation
    teams: list[RosterTeamOut] = Field(description="Every team rostered into at least one match, ascending.")


class MatchResultOut(BaseModel):
    score_red: int
    score_blue: int
    winning_alliance: str | None = Field(description="red, blue or tie; null only when the record has no winner.")


class ScheduledMatchOut(BaseModel):
    match_key: str
    competition_level: str | None
    set_number: int | None
    match_number: int | None
    scheduled_time: datetime | None
    red_team_numbers: list[int]
    blue_team_numbers: list[int]
    result: MatchResultOut | None = Field(description="Null unless the match was scheduled before as_of and played.")
    result_withheld_reason: str | None = Field(
        description="not_scheduled_before_as_of, no_scheduled_time or not_played; null when a result is shown.")


class EventMatchesResponse(BaseModel):
    event_key: str
    as_of: datetime
    validation: Validation
    matches: list[ScheduledMatchOut] = Field(description="Schedule order; matches without a time last.")


@router.get(
    "/events",
    response_model=SeasonEventsResponse,
    summary="The events of a season",
    description="Every event of one season from the canonical events table, by start date then key.",
    responses=error_responses({}),
)
def list_season_events(
    season: int = Query(ge=1992, description="FRC season, e.g. 2026."),
    database: Database = Depends(get_database),
) -> SeasonEventsResponse:
    events = [EventOut(**vars(event)) for event in season_events(database, season)]
    return SeasonEventsResponse(season=season, validation=_VALIDATION, events=events)


@router.get(
    "/events/{event_key}/teams",
    response_model=EventTeamsResponse,
    summary="An event's teams",
    description="Every team rostered into at least one match at the event (the roster every analysis uses).",
    # validation_error is declared because FastAPI documents its own 422 for any path parameter otherwise.
    responses=error_responses({HTTPStatus.NOT_FOUND: [CODE_EVENT_NOT_FOUND]}),
)
def list_event_teams(
    event_key: str = Path(min_length=1),
    database: Database = Depends(get_database),
) -> EventTeamsResponse:
    if not event_exists(database, event_key):
        raise event_not_found_error(event_key)
    teams = [RosterTeamOut(**vars(team)) for team in event_roster(database, event_key)]
    return EventTeamsResponse(event_key=event_key, validation=_VALIDATION, teams=teams)


@router.get(
    "/events/{event_key}/matches",
    response_model=EventMatchesResponse,
    summary="An event's matches available at as_of",
    description="The qualification schedule (alliances and times) is always listed. A playoff match is listed only "
                "once it was scheduled before as_of (default now): its alliances are the selection outcome. A result "
                "is shown only for a match scheduled before as_of; otherwise it is null with result_withheld_reason. "
                "Limits: scheduled_time is the planned time (a late match's result can show early), and a result is "
                "the score as stored now.",
    responses=error_responses({HTTPStatus.NOT_FOUND: [CODE_EVENT_NOT_FOUND],
                               HTTPStatus.UNPROCESSABLE_ENTITY: [CODE_INVALID_AS_OF]}, validates_input=False),
)
def list_event_matches(
    event_key: str = Path(min_length=1),
    as_of: str | None = Query(default=None, description=AS_OF_DESCRIPTION),
    database: Database = Depends(get_database),
) -> EventMatchesResponse:
    when = parse_as_of(as_of)
    if not event_exists(database, event_key):
        raise event_not_found_error(event_key)
    matches = [ScheduledMatchOut(**{**vars(m), "result": None if m.result is None else MatchResultOut(**vars(m.result))})
               for m in event_matches(database, event_key, when)]
    return EventMatchesResponse(event_key=event_key, as_of=when, validation=_VALIDATION, matches=matches)


__all__ = ["router"]
