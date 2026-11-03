"""Team Management and the Admin Dashboard: members, invitations, roles, account status, role permissions, team
settings, the activity log and team analytics.

Thin HTTP wrappers over workspaces.management. Every route needs a signed-in member; every administrative route
needs the administrative permission it names, checked here and again inside workspaces.management. The workspace
is always the caller's own (from the session): no path or body names a workspace, so no route can reach another
team's. Every POST needs the CSRF header (api.session).

Error codes: `not_authenticated` (401), `permission_denied`, `workspace_not_verified`, `cannot_target_self`,
`permission_not_grantable`, `csrf_check_failed` (403), `member_not_found`, `invitation_not_found` (404),
`already_member`, `invitation_pending`, `last_active_admin`, `member_not_active` (409), `invalid_input` and
`validation_error` (422).
"""

from __future__ import annotations

from http import HTTPStatus
from typing import Any, Literal

from fastapi import APIRouter, Depends, Path, Query
from pydantic import BaseModel, ConfigDict, Field

from api.contract import error_responses
from api.dependencies import get_database, get_settings
from api.session import call, require_csrf, require_permission, require_session
from data.config import Settings
from database.connection import Database
from workspaces import management
from workspaces.sessions import SessionContext

router = APIRouter(prefix="/workspace", tags=["team workspace"])

_AUTH = {401: ["not_authenticated"]}
_ADMIN = {401: ["not_authenticated"], 403: ["permission_denied"]}
_ADMIN_WRITE = {401: ["not_authenticated"], 403: ["permission_denied", "csrf_check_failed"]}


class _Body(BaseModel):
    model_config = ConfigDict(extra="forbid")


class InviteBody(_Body):
    email: str = Field(max_length=512)
    full_name: str = Field(max_length=512)
    role: Literal["admin", "strategy", "scouter"]


class RoleBody(_Body):
    role: Literal["admin", "strategy", "scouter"]


class StatusBody(_Body):
    status: Literal["active", "suspended"]


class MemberProfileBody(_Body):
    name: str = Field(max_length=512)


class PermissionsBody(_Body):
    role: Literal["strategy", "scouter"]
    grants: dict[str, bool]


class SettingsBody(_Body):
    team_name: str | None = Field(default=None, max_length=512)
    default_event_key: str | None = Field(default=None, max_length=64)
    scouting_instructions: str | None = Field(default=None, max_length=4000)


_member_id = Path(ge=1, description="A membership id from GET /workspace/members")
_invitation_id = Path(ge=1, description="An invitation id from GET /workspace/members")


@router.get("", summary="Your team's workspace: team, verification status, settings, your role and permissions",
            responses=error_responses(_AUTH, validates_input=False))
def get_workspace(database: Database = Depends(get_database),
                  context: SessionContext = Depends(require_session)) -> Any:
    return call(management.workspace_overview, database, context)


@router.get("/members", summary="Every member and pending invitation (Team Management)",
            responses=error_responses(_ADMIN, validates_input=False))
def get_members(database: Database = Depends(get_database),
                context: SessionContext = Depends(require_permission("team_management"))) -> Any:
    return call(management.list_members, database, context)


@router.post("/invitations", status_code=HTTPStatus.CREATED, dependencies=[Depends(require_csrf)],
             summary="Invite a member: a single-use, expiring link (emailed when email is configured)",
             responses=error_responses({401: ["not_authenticated"],
                                        403: ["permission_denied", "workspace_not_verified", "csrf_check_failed"],
                                        409: ["already_member", "invitation_pending"], 422: ["invalid_input"]}))
def post_invitation(body: InviteBody, database: Database = Depends(get_database),
                    settings: Settings = Depends(get_settings),
                    context: SessionContext = Depends(require_permission("team_management"))) -> Any:
    return call(management.invite_member, database, settings, context, email=body.email, full_name=body.full_name,
                role=body.role)


@router.post("/invitations/{invitation_id}/resend", dependencies=[Depends(require_csrf)],
             summary="Replace an invitation's link and expiry (the old link stops working)",
             responses=error_responses({401: ["not_authenticated"],
                                        403: ["permission_denied", "workspace_not_verified", "csrf_check_failed"],
                                        404: ["invitation_not_found"]}))
def resend_invitation(invitation_id: int = _invitation_id, database: Database = Depends(get_database),
                      settings: Settings = Depends(get_settings),
                      context: SessionContext = Depends(require_permission("team_management"))) -> Any:
    return call(management.resend_invitation, database, settings, context, invitation_id)


@router.post("/invitations/{invitation_id}/revoke", dependencies=[Depends(require_csrf)],
             summary="Revoke a pending invitation",
             responses=error_responses({**_ADMIN_WRITE, 404: ["invitation_not_found"]}))
def revoke_invitation(invitation_id: int = _invitation_id, database: Database = Depends(get_database),
                      context: SessionContext = Depends(require_permission("team_management"))) -> Any:
    call(management.revoke_invitation, database, context, invitation_id)
    return {"invitation_id": invitation_id, "status": "revoked"}


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
             summary="Remove a member from the team (their account remains; they can be invited back)",
             responses=error_responses({401: ["not_authenticated"],
                                        403: ["permission_denied", "cannot_target_self", "csrf_check_failed"],
                                        404: ["member_not_found"], 409: ["last_active_admin"]}))
def post_remove(membership_id: int = _member_id, database: Database = Depends(get_database),
                context: SessionContext = Depends(require_permission("team_management"))) -> Any:
    call(management.remove_member, database, context, membership_id)
    return {"membership_id": membership_id, "status": "removed"}


@router.post("/members/{membership_id}/password-reset", dependencies=[Depends(require_csrf)],
             summary="Issue a single-use password reset link for a member (recorded in the activity log)",
             responses=error_responses({**_ADMIN_WRITE, 404: ["member_not_found"], 409: ["member_not_active"]}))
def post_password_reset(membership_id: int = _member_id, database: Database = Depends(get_database),
                        settings: Settings = Depends(get_settings),
                        context: SessionContext = Depends(require_permission("team_management"))) -> Any:
    return call(management.issue_member_password_reset, database, settings, context, membership_id)


@router.get("/permissions", summary="The role/permission matrix",
            responses=error_responses(_ADMIN, validates_input=False))
def get_permissions(database: Database = Depends(get_database),
                    context: SessionContext = Depends(require_permission("manage_permissions"))) -> Any:
    return call(management.get_permissions, database, context)


@router.post("/permissions", dependencies=[Depends(require_csrf)],
             summary="Change what the strategy or scouter role may do (administrative permissions are never "
                     "grantable)",
             responses=error_responses({401: ["not_authenticated"],
                                        403: ["permission_denied", "permission_not_grantable", "csrf_check_failed"],
                                        422: ["invalid_input"]}))
def post_permissions(body: PermissionsBody, database: Database = Depends(get_database),
                     context: SessionContext = Depends(require_permission("manage_permissions"))) -> Any:
    return call(management.set_role_permissions, database, context, role=body.role, grants=body.grants)


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


@router.get("/analytics", summary="Workspace usage: membership, sign-ins, invitations, scouting activity",
            responses=error_responses(_ADMIN, validates_input=False))
def get_analytics(database: Database = Depends(get_database),
                  context: SessionContext = Depends(require_permission("team_management"))) -> Any:
    return call(management.team_analytics, database, context)
