"""A team's private scouting: match assignments, scouting reports and the team's own scouting summary.

Thin HTTP wrappers over workspaces.scouting. Everything is private to the caller's workspace; nothing here reads
or writes the shared scouting_observations table or the public team_metrics (see workspaces.scouting).

Error codes: `not_authenticated` (401), `permission_denied`, `workspace_not_verified`, `not_your_assignment`,
`csrf_check_failed` (403), `match_not_found`, `member_not_found`, `assignment_not_found`, `event_not_found` (404),
`assignment_exists`, `assignment_cancelled` (409), `invalid_input` and `validation_error` (422).
"""

from __future__ import annotations

from http import HTTPStatus
from typing import Any

from fastapi import APIRouter, Depends, Path, Query
from pydantic import BaseModel, ConfigDict, Field

from api.contract import error_responses
from api.dependencies import get_database
from api.session import call, require_csrf, require_session
from database.connection import Database
from workspaces import scouting
from workspaces.sessions import SessionContext

router = APIRouter(prefix="/workspace/scouting", tags=["team scouting"])

_READ = {401: ["not_authenticated"], 403: ["permission_denied"]}


class _Body(BaseModel):
    model_config = ConfigDict(extra="forbid")


class AssignmentBody(_Body):
    match_key: str = Field(max_length=64)
    team_number: int
    membership_id: int = Field(ge=1)


class ReportBody(_Body):
    match_key: str = Field(max_length=64)
    team_number: int
    defense_rating: int | None = None
    feeding_rating: int | None = None
    notes: str | None = Field(default=None, max_length=4000)
    assignment_id: int | None = Field(default=None, ge=1)


@router.get("/scouts", summary="The active members an assignment can name (names and roles only)",
            responses=error_responses(_READ, validates_input=False))
def get_scouts(database: Database = Depends(get_database),
               context: SessionContext = Depends(require_session)) -> Any:
    return call(scouting.list_scouts, database, context)


@router.get("/assignments", summary="Scouting assignments: your own (mine=true) or the whole team's",
            responses=error_responses(_READ))
def get_assignments(mine: bool = Query(default=True), event_key: str | None = Query(default=None, max_length=64),
                    include_closed: bool = Query(default=False), database: Database = Depends(get_database),
                    context: SessionContext = Depends(require_session)) -> Any:
    return call(scouting.list_assignments, database, context, mine=mine, event_key=event_key,
                include_closed=include_closed)


@router.post("/assignments", status_code=HTTPStatus.CREATED, dependencies=[Depends(require_csrf)],
             summary="Assign a member to scout one team in one match",
             responses=error_responses({401: ["not_authenticated"],
                                        403: ["permission_denied", "workspace_not_verified", "csrf_check_failed"],
                                        404: ["match_not_found", "member_not_found"], 409: ["assignment_exists"],
                                        422: ["invalid_input"]}))
def post_assignment(body: AssignmentBody, database: Database = Depends(get_database),
                    context: SessionContext = Depends(require_session)) -> Any:
    return call(scouting.create_assignment, database, context, match_key=body.match_key,
                team_number=body.team_number, membership_id=body.membership_id)


@router.post("/assignments/{assignment_id}/cancel", dependencies=[Depends(require_csrf)],
             summary="Cancel an open assignment",
             responses=error_responses({401: ["not_authenticated"], 403: ["permission_denied", "csrf_check_failed"],
                                        404: ["assignment_not_found"]}))
def cancel_assignment(assignment_id: int = Path(ge=1), database: Database = Depends(get_database),
                      context: SessionContext = Depends(require_session)) -> Any:
    call(scouting.cancel_assignment, database, context, assignment_id)
    return {"assignment_id": assignment_id, "status": "cancelled"}


@router.get("/reports", summary="Scouting reports: your own (mine=true) or the whole team's",
            responses=error_responses(_READ))
def get_reports(mine: bool = Query(default=True), event_key: str | None = Query(default=None, max_length=64),
                team_number: int | None = Query(default=None), limit: int = Query(default=200, ge=1, le=1000),
                database: Database = Depends(get_database),
                context: SessionContext = Depends(require_session)) -> Any:
    return call(scouting.list_reports, database, context, mine=mine, event_key=event_key, team_number=team_number,
                limit=limit)


@router.post("/reports", status_code=HTTPStatus.CREATED, dependencies=[Depends(require_csrf)],
             summary="Submit a scouting report (private to your team)",
             responses=error_responses({401: ["not_authenticated"],
                                        403: ["permission_denied", "workspace_not_verified", "not_your_assignment",
                                              "csrf_check_failed"],
                                        404: ["match_not_found", "assignment_not_found"],
                                        409: ["assignment_cancelled"], 422: ["invalid_input"]}))
def post_report(body: ReportBody, database: Database = Depends(get_database),
                context: SessionContext = Depends(require_session)) -> Any:
    return call(scouting.submit_report, database, context, match_key=body.match_key, team_number=body.team_number,
                defense_rating=body.defense_rating, feeding_rating=body.feeding_rating, notes=body.notes,
                assignment_id=body.assignment_id)


@router.get("/summary", summary="Your team's own defense/feeding profile of each team it scouted at an event",
            responses=error_responses({**_READ, 404: ["event_not_found"]}))
def get_summary(event_key: str = Query(max_length=64), database: Database = Depends(get_database),
                context: SessionContext = Depends(require_session)) -> Any:
    return call(scouting.scouting_summary, database, context, event_key=event_key)
