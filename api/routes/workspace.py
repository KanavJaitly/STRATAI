"""Team Management and the Admin Dashboard: members (list, change a role, suspend, remove), team settings, the
activity log and team analytics.

Thin HTTP wrappers over workspaces.management. Every route needs a signed-in member; every administrative route
needs the administrative permission it names, checked here and again inside workspaces.management. The workspace
is always the caller's own (from the session); there is only one, team 11's. Every POST needs the CSRF header (api.session).

Error codes: `not_authenticated` (401), `permission_denied`, `cannot_target_self`, `csrf_check_failed` (403),
`member_not_found` (404), `last_active_admin` (409), `invalid_input` and `validation_error` (422).
"""

from __future__ import annotations

from typing import Any, Literal

from fastapi import APIRouter, Depends, Path, Query
from pydantic import BaseModel, ConfigDict, Field

from api.contract import error_responses
from api.dependencies import get_database
from api.session import call, require_csrf, require_permission
from database.connection import Database
from workspaces import management
from workspaces.sessions import SessionContext

router = APIRouter(prefix="/workspace", tags=["team workspace"])

_ADMIN = {401: ["not_authenticated"], 403: ["permission_denied"]}
_ADMIN_WRITE = {401: ["not_authenticated"], 403: ["permission_denied", "csrf_check_failed"]}


class _Body(BaseModel):
    model_config = ConfigDict(extra="forbid")


class RoleBody(_Body):
    role: Literal["admin", "base"]


class StatusBody(_Body):
    status: Literal["active", "suspended"]


class MemberProfileBody(_Body):
    name: str = Field(max_length=512)


class SettingsBody(_Body):
    team_name: str | None = Field(default=None, max_length=512)
    default_event_key: str | None = Field(default=None, max_length=64)
    scouting_instructions: str | None = Field(default=None, max_length=4000)


_member_id = Path(ge=1, description="A membership id from GET /workspace/members")


@router.get("", summary="Your team's workspace: team, verification status, settings, your role and permissions",
            responses=error_responses(_ADMIN, validates_input=False))
def get_workspace(database: Database = Depends(get_database),
                  context: SessionContext = Depends(require_permission("team_overview"))) -> Any:
    return call(management.workspace_overview, database, context)


@router.get("/members", summary="Every member of the team (Team Management)",
            responses=error_responses(_ADMIN, validates_input=False))
def get_members(database: Database = Depends(get_database),
                context: SessionContext = Depends(require_permission("team_management"))) -> Any:
    return call(management.list_members, database, context)


@router.post("/members/{membership_id}/role", dependencies=[Depends(require_csrf)], summary="Change a member's role",
             responses=error_responses({**_ADMIN_WRITE, 404: ["member_not_found"], 409: ["last_active_admin"]}))
def post_role(body: RoleBody, membership_id: int = _member_id, database: Database = Depends(get_database),
              context: SessionContext = Depends(require_permission("team_management"))) -> Any:
    return call(management.change_role, database, context, membership_id, body.role)


@router.post("/members/{membership_id}/status", dependencies=[Depends(require_csrf)],
             summary="Suspend or reactivate a member (suspension ends their sessions)",
             responses=error_responses({401: ["not_authenticated"],
                                        403: ["permission_denied", "cannot_target_self", "csrf_check_failed"],
                                        404: ["member_not_found"], 409: ["last_active_admin"]}))
def post_status(body: StatusBody, membership_id: int = _member_id, database: Database = Depends(get_database),
                context: SessionContext = Depends(require_permission("team_management"))) -> Any:
    return call(management.set_member_status, database, context, membership_id, body.status)


@router.post("/members/{membership_id}/profile", dependencies=[Depends(require_csrf)],
             summary="Edit the name your team shows for a member",
             responses=error_responses({**_ADMIN_WRITE, 404: ["member_not_found"], 422: ["invalid_input"]}))
def post_profile(body: MemberProfileBody, membership_id: int = _member_id, database: Database = Depends(get_database),
                 context: SessionContext = Depends(require_permission("team_management"))) -> Any:
    return call(management.update_member, database, context, membership_id, display_name=body.name)


@router.post("/members/{membership_id}/remove", dependencies=[Depends(require_csrf)],
             summary="Remove a member from the team (sessions end; `python -m scripts.set_role` restores them)",
             responses=error_responses({401: ["not_authenticated"],
                                        403: ["permission_denied", "cannot_target_self", "csrf_check_failed"],
                                        404: ["member_not_found"], 409: ["last_active_admin"]}))
def post_remove(membership_id: int = _member_id, database: Database = Depends(get_database),
                context: SessionContext = Depends(require_permission("team_management"))) -> Any:
    call(management.remove_member, database, context, membership_id)
    return {"membership_id": membership_id, "status": "removed"}


@router.get("/settings", summary="Team settings", responses=error_responses(_ADMIN, validates_input=False))
def get_team_settings(database: Database = Depends(get_database),
                      context: SessionContext = Depends(require_permission("team_settings"))) -> Any:
    return call(management.get_team_settings, database, context)


@router.post("/settings", dependencies=[Depends(require_csrf)], summary="Change team settings",
             responses=error_responses({**_ADMIN_WRITE, 422: ["invalid_input"]}))
def post_team_settings(body: SettingsBody, database: Database = Depends(get_database),
                       context: SessionContext = Depends(require_permission("team_settings"))) -> Any:
    return call(management.update_team_settings, database, context, body.model_dump(exclude_unset=True))


@router.get("/activity", summary="The team's activity log, newest first",
            responses=error_responses({**_ADMIN, 422: ["invalid_input"]}))
def get_activity(limit: int = Query(default=50, ge=1, le=management.MAX_ACTIVITY_PAGE),
                 offset: int = Query(default=0, ge=0), action: str | None = Query(default=None, max_length=64),
                 database: Database = Depends(get_database),
                 context: SessionContext = Depends(require_permission("activity_log"))) -> Any:
    return call(management.list_activity, database, context, limit=limit, offset=offset, action=action)


@router.get("/analytics", summary="Workspace usage: membership, sign-ins, scouting activity",
            responses=error_responses(_ADMIN, validates_input=False))
def get_analytics(database: Database = Depends(get_database),
                  context: SessionContext = Depends(require_permission("team_management"))) -> Any:
    return call(management.team_analytics, database, context)
