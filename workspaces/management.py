"""Team Management: members, invitations, roles, account status, role permissions, team settings, the activity
log and team analytics; plus the StratAI operator's verification of a workspace.

Every function here takes the caller's SessionContext and checks the permission itself, so the rule holds however
the function is reached (the API also checks it, before the call). Every row it reads or changes is selected by
the caller's workspace_id as well as its own id: an id from another team's workspace is simply not found.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

import psycopg
from psycopg.types.json import Jsonb

from data.config import Settings
from database.connection import Database
from workspaces import activity, mailer
from workspaces.accounts import (
    clean_name,
    invitation_link_path,
    issue_reset_token,
    normalize_email,
    reset_link_path,
)
from workspaces.errors import WorkspaceError, conflict, forbidden, invalid_input, not_found
from workspaces.permissions import (
    ADMIN,
    ALL_PERMISSIONS,
    ADMIN_ONLY_PERMISSIONS,
    CONFIGURABLE_PERMISSIONS,
    CONFIGURABLE_ROLES,
    DEFAULT_GRANTS,
    ROLE_LABELS,
    ROLES,
)
from workspaces.sessions import SessionContext, revoke_membership_sessions
from workspaces.tokens import new_token, token_hash

LAST_ADMIN_CONSTRAINT = "team_memberships_last_active_admin"


def require(context: SessionContext, permission: str) -> None:
    if not context.can(permission):
        raise forbidden("permission_denied", "Your role does not have permission to do this.")


def require_verified(context: SessionContext, what: str) -> None:
    if not context.verified:
        raise forbidden("workspace_not_verified",
                        f"{what} is available once StratAI has verified that this workspace belongs to team "
                        f"{context.team_number}. Verification is pending.")


def _last_admin_error() -> WorkspaceError:
    return conflict("last_active_admin", "A team must keep at least one active administrator. Make someone else an "
                                         "administrator first.")


# --- overview -------------------------------------------------------------------------------------------------


def workspace_overview(database: Database, context: SessionContext) -> dict[str, Any]:
    """The workspace as any member sees it: team, verification, settings, own role and permissions."""
    with database.cursor() as cursor:
        cursor.execute("SELECT team_number, team_name, verification_status, verified_at, settings, created_at "
                       "FROM workspaces WHERE id = %s", (context.workspace_id,))
        number, name, status, verified_at, settings, created_at = cursor.fetchone()
        cursor.execute("SELECT count(*) FROM team_memberships WHERE workspace_id = %s AND status = 'active'",
                       (context.workspace_id,))
        active_members = cursor.fetchone()[0]
    return {"team_number": number, "team_name": name, "verification_status": status, "verified_at": verified_at,
            "created_at": created_at, "settings": _public_settings(settings), "active_members": active_members,
            "role": context.role, "role_label": ROLE_LABELS[context.role], "permissions": sorted(context.permissions)}


# --- members --------------------------------------------------------------------------------------------------


def list_members(database: Database, context: SessionContext) -> dict[str, Any]:
    """Every member (any status but removed) and every pending invitation of the workspace."""
    require(context, "team_management")
    with database.cursor() as cursor:
        cursor.execute(
            "SELECT m.id, u.id, COALESCE(m.display_name, u.full_name), u.email, m.role, m.status, m.last_login_at, "
            "m.created_at FROM team_memberships m JOIN users u ON u.id = m.user_id "
            "WHERE m.workspace_id = %s AND m.status <> 'removed' ORDER BY m.created_at, m.id",
            (context.workspace_id,))
        members = [{"membership_id": mid, "user_id": uid, "name": name, "email": email, "role": role,
                    "role_label": ROLE_LABELS[role], "status": status, "invitation_status": "accepted",
                    "last_login_at": last_login, "joined_at": joined, "is_self": mid == context.membership_id}
                   for mid, uid, name, email, role, status, last_login, joined in cursor.fetchall()]
        cursor.execute(
            "SELECT i.id, i.email, i.full_name, i.role, i.expires_at, i.created_at, "
            "COALESCE(im.display_name, iu.full_name) FROM invitations i "
            "LEFT JOIN users iu ON iu.id = i.invited_by_user_id "
            "LEFT JOIN team_memberships im ON im.user_id = i.invited_by_user_id AND im.workspace_id = i.workspace_id "
            "WHERE i.workspace_id = %s AND i.status = 'pending' ORDER BY i.created_at",
            (context.workspace_id,))
        now = datetime.now(timezone.utc)
        invitations = [{"invitation_id": iid, "email": email, "name": name, "role": role,
                        "role_label": ROLE_LABELS[role], "expires_at": expires, "invited_at": created,
                        "invited_by": inviter, "invitation_status": "expired" if expires <= now else "pending"}
                       for iid, email, name, role, expires, created, inviter in cursor.fetchall()]
    return {"members": members, "invitations": invitations}


def _check_role(role: Any) -> str:
    if role not in ROLES:
        raise invalid_input(f"Role must be one of {', '.join(ROLES)}.")
    return role


def _deliver_invitation(settings: Settings, context: SessionContext, *, email: str, name: str, role: str,
                        token: str) -> dict[str, Any]:
    link = mailer.absolute_link(settings, invitation_link_path(token))
    channel = mailer.send(
        settings, to=email, subject=f"You are invited to team {context.team_number}'s StratAI",
        body=f"Hello {name},\n\n{context.name} has invited you to join team {context.team_number} "
             f"({context.team_name}) on StratAI as {ROLE_LABELS[role]}.\n\nOpen this link to create your account "
             f"(it works once, for {settings.invitation_ttl_hours} hours):\n{link}\n")
    return {"invitation_link": link, "emailed": channel is not None, "email_channel": channel}


def invite_member(database: Database, settings: Settings, context: SessionContext, *, email: str, full_name: str,
                  role: str) -> dict[str, Any]:
    """Create a single-use, expiring invitation. Returns its link (to deliver by hand when email is not set up)."""
    require(context, "team_management")
    require_verified(context, "Inviting members")
    email, name, role = normalize_email(email), clean_name(full_name), _check_role(role)
    token = new_token()
    expires_at = datetime.now(timezone.utc) + timedelta(hours=settings.invitation_ttl_hours)
    with database.connection() as conn, conn.cursor() as cursor:
        cursor.execute("SELECT m.status FROM team_memberships m JOIN users u ON u.id = m.user_id "
                       "WHERE m.workspace_id = %s AND u.email = %s", (context.workspace_id, email))
        member = cursor.fetchone()
        if member is not None and member[0] != "removed":
            raise conflict("already_member", f"{email} is already a member of this team's workspace.")
        # An expired pending invitation for the same email is superseded rather than left blocking a new one.
        cursor.execute("UPDATE invitations SET status = 'revoked', revoked_at = NOW() WHERE workspace_id = %s "
                       "AND email = %s AND status = 'pending' AND expires_at <= NOW()", (context.workspace_id, email))
        try:
            cursor.execute(
                "INSERT INTO invitations (workspace_id, email, full_name, role, token_hash, expires_at, "
                "invited_by_user_id) VALUES (%s, %s, %s, %s, %s, %s, %s) RETURNING id",
                (context.workspace_id, email, name, role, token_hash(token), expires_at, context.user_id))
        except psycopg.errors.UniqueViolation:
            conn.rollback()
            raise conflict("invitation_pending", f"{email} already has a pending invitation. Resend it instead.")
        invitation_id = cursor.fetchone()[0]
        activity.record(cursor, workspace_id=context.workspace_id, actor_user_id=context.user_id,
                        actor_label=context.name, action="member_invited", target_label=f"{name} <{email}>",
                        details={"role": role, "invitation_id": invitation_id})
    delivery = _deliver_invitation(settings, context, email=email, name=name, role=role, token=token)
    return {"invitation_id": invitation_id, "email": email, "name": name, "role": role, "expires_at": expires_at,
            **delivery}


def _pending_invitation(cursor: Any, context: SessionContext, invitation_id: int) -> tuple:
    cursor.execute("SELECT id, email, full_name, role FROM invitations WHERE id = %s AND workspace_id = %s "
                   "AND status = 'pending' FOR UPDATE", (invitation_id, context.workspace_id))
    row = cursor.fetchone()
    if row is None:
        raise not_found("invitation_not_found", "No pending invitation with that id in this team's workspace.")
    return row


def resend_invitation(database: Database, settings: Settings, context: SessionContext,
                      invitation_id: int) -> dict[str, Any]:
    """Replace the invitation's link with a new one and a new expiry; the old link stops working."""
    require(context, "team_management")
    require_verified(context, "Inviting members")
    token = new_token()
    expires_at = datetime.now(timezone.utc) + timedelta(hours=settings.invitation_ttl_hours)
    with database.cursor() as cursor:
        _, email, name, role = _pending_invitation(cursor, context, invitation_id)
        cursor.execute("UPDATE invitations SET token_hash = %s, expires_at = %s, created_at = NOW() WHERE id = %s",
                       (token_hash(token), expires_at, invitation_id))
        activity.record(cursor, workspace_id=context.workspace_id, actor_user_id=context.user_id,
                        actor_label=context.name, action="invitation_resent", target_label=f"{name} <{email}>",
                        details={"invitation_id": invitation_id})
    delivery = _deliver_invitation(settings, context, email=email, name=name, role=role, token=token)
    return {"invitation_id": invitation_id, "email": email, "name": name, "role": role, "expires_at": expires_at,
            **delivery}


def revoke_invitation(database: Database, context: SessionContext, invitation_id: int) -> None:
    require(context, "team_management")
    with database.cursor() as cursor:
        _, email, name, _ = _pending_invitation(cursor, context, invitation_id)
        cursor.execute("UPDATE invitations SET status = 'revoked', revoked_at = NOW() WHERE id = %s",
                       (invitation_id,))
        activity.record(cursor, workspace_id=context.workspace_id, actor_user_id=context.user_id,
                        actor_label=context.name, action="invitation_revoked", target_label=f"{name} <{email}>",
                        details={"invitation_id": invitation_id})


def _locked_member(cursor: Any, context: SessionContext, membership_id: int) -> tuple:
    """Lock the workspace, then the member: the same order everywhere, so concurrent changes serialise."""
    cursor.execute("SELECT 1 FROM workspaces WHERE id = %s FOR UPDATE", (context.workspace_id,))
    cursor.execute(
        "SELECT m.id, m.user_id, m.role, m.status, COALESCE(m.display_name, u.full_name) FROM team_memberships m "
        "JOIN users u ON u.id = m.user_id WHERE m.id = %s AND m.workspace_id = %s AND m.status <> 'removed' "
        "FOR UPDATE OF m", (membership_id, context.workspace_id))
    row = cursor.fetchone()
    if row is None:
        raise not_found("member_not_found", "No member with that id in this team's workspace.")
    return row


def _other_active_admins(cursor: Any, context: SessionContext, membership_id: int) -> int:
    cursor.execute("SELECT count(*) FROM team_memberships WHERE workspace_id = %s AND role = 'admin' "
                   "AND status = 'active' AND id <> %s", (context.workspace_id, membership_id))
    return cursor.fetchone()[0]


def _apply_member_change(database: Database, context: SessionContext, membership_id: int, change) -> Any:
    """Run change(cursor, member_row) in a transaction, turning the database's last-administrator guard into the
    same error the application check raises."""
    try:
        with database.cursor() as cursor:
            return change(cursor, _locked_member(cursor, context, membership_id))
    except psycopg.errors.CheckViolation as exc:
        if exc.diag.constraint_name == LAST_ADMIN_CONSTRAINT:
            raise _last_admin_error() from None
        raise


def change_role(database: Database, context: SessionContext, membership_id: int, role: str) -> dict[str, Any]:
    require(context, "team_management")
    role = _check_role(role)

    def change(cursor: Any, member: tuple) -> dict[str, Any]:
        _, user_id, old_role, status, name = member
        if old_role == role:
            return {"membership_id": membership_id, "role": role}
        if old_role == ADMIN and status == "active" and _other_active_admins(cursor, context, membership_id) == 0:
            raise _last_admin_error()
        cursor.execute("UPDATE team_memberships SET role = %s, updated_at = NOW() WHERE id = %s",
                       (role, membership_id))
        activity.record(cursor, workspace_id=context.workspace_id, actor_user_id=context.user_id,
                        actor_label=context.name, action="role_changed", target_user_id=user_id, target_label=name,
                        details={"from": old_role, "to": role})
        return {"membership_id": membership_id, "role": role}

    return _apply_member_change(database, context, membership_id, change)


def set_member_status(database: Database, context: SessionContext, membership_id: int,
                      status: str) -> dict[str, Any]:
    """Suspend (status "suspended": sessions end, sign-in refused) or reactivate (status "active") a member."""
    require(context, "team_management")
    if status not in ("active", "suspended"):
        raise invalid_input("Status must be active or suspended.")
    if membership_id == context.membership_id:
        raise forbidden("cannot_target_self", "You cannot suspend or reactivate your own account.")

    def change(cursor: Any, member: tuple) -> dict[str, Any]:
        _, user_id, role, old_status, name = member
        if old_status == status:
            return {"membership_id": membership_id, "status": status}
        if role == ADMIN and old_status == "active" and _other_active_admins(cursor, context, membership_id) == 0:
            raise _last_admin_error()
        cursor.execute("UPDATE team_memberships SET status = %s, updated_at = NOW() WHERE id = %s",
                       (status, membership_id))
        if status == "suspended":
            revoke_membership_sessions(cursor, membership_id)
        activity.record(cursor, workspace_id=context.workspace_id, actor_user_id=context.user_id,
                        actor_label=context.name,
                        action="member_suspended" if status == "suspended" else "member_reactivated",
                        target_user_id=user_id, target_label=name)
        return {"membership_id": membership_id, "status": status}

    return _apply_member_change(database, context, membership_id, change)


def update_member(database: Database, context: SessionContext, membership_id: int, *,
                  display_name: str) -> dict[str, Any]:
    """Edit the name this team shows for a member."""
    require(context, "team_management")
    new_name = clean_name(display_name, "Name")

    def change(cursor: Any, member: tuple) -> dict[str, Any]:
        _, user_id, _, _, old_name = member
        cursor.execute("UPDATE team_memberships SET display_name = %s, updated_at = NOW() WHERE id = %s",
                       (new_name, membership_id))
        activity.record(cursor, workspace_id=context.workspace_id, actor_user_id=context.user_id,
                        actor_label=context.name, action="member_updated", target_user_id=user_id,
                        target_label=new_name, details={"name": {"from": old_name, "to": new_name}})
        return {"membership_id": membership_id, "name": new_name}

    return _apply_member_change(database, context, membership_id, change)


def remove_member(database: Database, context: SessionContext, membership_id: int) -> None:
    """Remove a member from the workspace: sessions end, sign-in refused, their past scouting stays attributed.

    The person's account itself remains (it may belong to other teams); they can be invited back."""
    require(context, "team_management")
    if membership_id == context.membership_id:
        raise forbidden("cannot_target_self", "You cannot remove yourself. Ask another administrator.")

    def change(cursor: Any, member: tuple) -> None:
        _, user_id, role, status, name = member
        if role == ADMIN and status == "active" and _other_active_admins(cursor, context, membership_id) == 0:
            raise _last_admin_error()
        cursor.execute("UPDATE team_memberships SET status = 'removed', updated_at = NOW() WHERE id = %s",
                       (membership_id,))
        cursor.execute("UPDATE scouting_assignments SET status = 'cancelled' WHERE workspace_id = %s "
                       "AND assigned_user_id = %s AND status = 'assigned'", (context.workspace_id, user_id))
        revoke_membership_sessions(cursor, membership_id)
        activity.record(cursor, workspace_id=context.workspace_id, actor_user_id=context.user_id,
                        actor_label=context.name, action="member_removed", target_user_id=user_id,
                        target_label=name, details={"role": role})

    _apply_member_change(database, context, membership_id, change)


def issue_member_password_reset(database: Database, settings: Settings, context: SessionContext,
                                membership_id: int) -> dict[str, Any]:
    """An administrator-issued, single-use reset link for a member (for teams without email delivery). It is
    recorded in the activity log, so issuing one is never invisible to the team."""
    require(context, "team_management")

    def change(cursor: Any, member: tuple) -> tuple[str, datetime, str, int, str]:
        _, user_id, _, status, name = member
        if status != "active":
            raise conflict("member_not_active", "Reactivate this member before issuing a password reset.")
        token, expires_at = issue_reset_token(cursor, settings, membership_id=membership_id,
                                              issued_by_user_id=context.user_id)
        cursor.execute("SELECT email FROM users WHERE id = %s", (user_id,))
        email = cursor.fetchone()[0]
        activity.record(cursor, workspace_id=context.workspace_id, actor_user_id=context.user_id,
                        actor_label=context.name, action="password_reset_issued", target_user_id=user_id,
                        target_label=name)
        return token, expires_at, email, user_id, name

    token, expires_at, email, _, name = _apply_member_change(database, context, membership_id, change)
    link = mailer.absolute_link(settings, reset_link_path(token))
    channel = mailer.send(settings, to=email, subject=f"Reset your StratAI password (team {context.team_number})",
                          body=f"Hello {name},\n\nAn administrator of team {context.team_number} issued you a "
                               f"password reset link. It works once, for {settings.password_reset_ttl_minutes} "
                               f"minutes:\n{link}\n")
    return {"membership_id": membership_id, "reset_link": link, "expires_at": expires_at,
            "emailed": channel is not None, "email_channel": channel}


# --- permissions ----------------------------------------------------------------------------------------------


def get_permissions(database: Database, context: SessionContext) -> dict[str, Any]:
    """The role/permission matrix: administrators fixed, the two other roles as configured."""
    require(context, "manage_permissions")
    with database.cursor() as cursor:
        cursor.execute("SELECT role, permission, granted FROM workspace_role_permissions WHERE workspace_id = %s",
                       (context.workspace_id,))
        stored = {(role, permission): granted for role, permission, granted in cursor.fetchall()}
    rows = []
    for permission, description in ALL_PERMISSIONS.items():
        configurable = permission in CONFIGURABLE_PERMISSIONS
        roles = {ADMIN: {"granted": True, "editable": False}}
        for role in CONFIGURABLE_ROLES:
            granted = stored.get((role, permission), permission in DEFAULT_GRANTS[role]) if configurable else False
            roles[role] = {"granted": granted, "editable": configurable,
                           "default": configurable and permission in DEFAULT_GRANTS[role]}
        rows.append({"permission": permission, "description": description, "admin_only": not configurable,
                     "roles": roles})
    return {"roles": [{"role": role, "label": ROLE_LABELS[role]} for role in ROLES], "permissions": rows}


def set_role_permissions(database: Database, context: SessionContext, *, role: str,
                         grants: dict[str, bool]) -> dict[str, Any]:
    """Change what one non-administrator role may do. Administrative permissions can never be granted."""
    require(context, "manage_permissions")
    if role not in CONFIGURABLE_ROLES:
        raise invalid_input("Only the strategy and scouter roles are configurable; administrators hold every "
                            "permission.")
    if not isinstance(grants, dict) or not grants:
        raise invalid_input("Name at least one permission to change.")
    for permission, granted in grants.items():
        if permission in ADMIN_ONLY_PERMISSIONS:
            raise forbidden("permission_not_grantable",
                            f"'{permission}' is reserved for administrators and cannot be granted to another role.")
        if permission not in CONFIGURABLE_PERMISSIONS:
            raise invalid_input(f"Unknown permission '{permission}'.")
        if not isinstance(granted, bool):
            raise invalid_input(f"'{permission}' must be true or false.")
    with database.cursor() as cursor:
        cursor.execute("SELECT permission, granted FROM workspace_role_permissions WHERE workspace_id = %s "
                       "AND role = %s FOR UPDATE", (context.workspace_id, role))
        before = dict(cursor.fetchall())
        changed = {}
        for permission, granted in grants.items():
            previous = before.get(permission, permission in DEFAULT_GRANTS[role])
            try:
                cursor.execute(
                    "INSERT INTO workspace_role_permissions (workspace_id, role, permission, granted, "
                    "updated_by_user_id) VALUES (%s, %s, %s, %s, %s) ON CONFLICT (workspace_id, role, permission) "
                    "DO UPDATE SET granted = EXCLUDED.granted, updated_at = NOW(), "
                    "updated_by_user_id = EXCLUDED.updated_by_user_id",
                    (context.workspace_id, role, permission, granted, context.user_id))
            except psycopg.errors.CheckViolation:
                # A permission added by a later migration (e.g. alliance_selection_record, 0013) on a database that
                # has not applied it: say so instead of failing with a 500. The whole change is rolled back.
                raise conflict("permission_needs_migration",
                               f"'{permission}' needs a newer database migration on this server before it can be "
                               "changed. Ask whoever runs StratAI to apply the latest migrations.") from None
            if previous != granted:
                changed[permission] = {"from": previous, "to": granted}
        if changed:
            activity.record(cursor, workspace_id=context.workspace_id, actor_user_id=context.user_id,
                            actor_label=context.name, action="permissions_changed",
                            target_label=ROLE_LABELS[role], details={"role": role, "changes": changed})
    return {"role": role, "changed": changed}


# --- settings -------------------------------------------------------------------------------------------------

SETTINGS_KEYS = ("default_event_key", "scouting_instructions")


def _public_settings(stored: dict[str, Any] | None) -> dict[str, Any]:
    stored = stored or {}
    return {key: stored.get(key) for key in SETTINGS_KEYS}


def get_team_settings(database: Database, context: SessionContext) -> dict[str, Any]:
    require(context, "team_settings")
    with database.cursor() as cursor:
        cursor.execute("SELECT team_number, team_name, settings FROM workspaces WHERE id = %s", (context.workspace_id,))
        number, name, settings = cursor.fetchone()
    return {"team_number": number, "team_name": name, **_public_settings(settings)}


def update_team_settings(database: Database, context: SessionContext, changes: dict[str, Any]) -> dict[str, Any]:
    """Change the team name, the default event, or the instructions scouters see. The team number never changes."""
    require(context, "team_settings")
    unknown = set(changes) - {"team_name", *SETTINGS_KEYS}
    if unknown:
        raise invalid_input(f"Unknown settings: {', '.join(sorted(unknown))}.")
    with database.cursor() as cursor:
        cursor.execute("SELECT team_name, settings FROM workspaces WHERE id = %s FOR UPDATE", (context.workspace_id,))
        team_name, stored = cursor.fetchone()
        stored = dict(stored or {})
        updated_name, diff = team_name, {}
        if "team_name" in changes:
            updated_name = clean_name(changes["team_name"], "Team name", 100)
            if updated_name != team_name:
                diff["team_name"] = {"from": team_name, "to": updated_name}
        if "default_event_key" in changes:
            event_key = changes["default_event_key"] or None
            if event_key is not None:
                cursor.execute("SELECT 1 FROM events WHERE event_key = %s", (event_key,))
                if cursor.fetchone() is None:
                    raise invalid_input(f"Event '{event_key}' is not known to StratAI.")
            if stored.get("default_event_key") != event_key:
                diff["default_event_key"] = {"from": stored.get("default_event_key"), "to": event_key}
            stored["default_event_key"] = event_key
        if "scouting_instructions" in changes:
            text = changes["scouting_instructions"]
            if text is not None and (not isinstance(text, str) or len(text) > 2000):
                raise invalid_input("Scouting instructions must be text of at most 2000 characters.")
            text = text.strip() if text else None
            if stored.get("scouting_instructions") != text:
                diff["scouting_instructions"] = {"changed": True}
            stored["scouting_instructions"] = text
        cursor.execute("UPDATE workspaces SET team_name = %s, settings = %s, updated_at = NOW() WHERE id = %s",
                       (updated_name, Jsonb(stored), context.workspace_id))
        if diff:
            activity.record(cursor, workspace_id=context.workspace_id, actor_user_id=context.user_id,
                            actor_label=context.name, action="settings_changed", details=diff)
    return {"team_number": context.team_number, "team_name": updated_name, **_public_settings(stored)}


# --- activity log and analytics -------------------------------------------------------------------------------

MAX_ACTIVITY_PAGE = 200


def list_activity(database: Database, context: SessionContext, *, limit: int = 50, offset: int = 0,
                  action: str | None = None) -> dict[str, Any]:
    require(context, "activity_log")
    if action is not None and action not in activity.ACTIONS:
        raise invalid_input(f"Unknown action '{action}'.")
    limit = max(1, min(limit, MAX_ACTIVITY_PAGE))
    with database.cursor() as cursor:
        cursor.execute(
            "SELECT id, actor_label, action, target_label, details, created_at FROM activity_logs "
            "WHERE workspace_id = %s AND (%s::text IS NULL OR action = %s) ORDER BY created_at DESC, id DESC "
            "LIMIT %s OFFSET %s", (context.workspace_id, action, action, limit + 1, max(0, offset)))
        rows = cursor.fetchall()
    entries = [{"id": row_id, "actor": actor, "action": act, "action_label": activity.ACTIONS[act],
                "target": target, "details": details, "at": at}
               for row_id, actor, act, target, details, at in rows[:limit]]
    return {"entries": entries, "has_more": len(rows) > limit,
            "actions": [{"action": key, "label": label} for key, label in activity.ACTIONS.items()]}


def team_analytics(database: Database, context: SessionContext) -> dict[str, Any]:
    """Workspace usage for the Admin Dashboard: membership, sign-ins, invitations and scouting activity."""
    require(context, "team_management")
    workspace_id = context.workspace_id
    with database.cursor() as cursor:
        cursor.execute("SELECT role, status, count(*) FROM team_memberships WHERE workspace_id = %s "
                       "GROUP BY role, status", (workspace_id,))
        by_role: dict[str, dict[str, int]] = {role: {"active": 0, "suspended": 0} for role in ROLES}
        for role, status, count in cursor.fetchall():
            if status != "removed":
                by_role[role][status] = count
        cursor.execute("SELECT count(*) FILTER (WHERE last_login_at > NOW() - interval '7 days'), "
                       "count(*) FILTER (WHERE last_login_at IS NULL) FROM team_memberships "
                       "WHERE workspace_id = %s AND status = 'active'", (workspace_id,))
        active_7d, never = cursor.fetchone()
        cursor.execute("SELECT count(*) FILTER (WHERE expires_at > NOW()), count(*) FILTER (WHERE expires_at <= NOW()) "
                       "FROM invitations WHERE workspace_id = %s AND status = 'pending'", (workspace_id,))
        pending, expired = cursor.fetchone()
        cursor.execute("SELECT count(*), count(*) FILTER (WHERE submitted_at > NOW() - interval '7 days'), "
                       "count(DISTINCT event_key) FROM workspace_scouting_reports WHERE workspace_id = %s",
                       (workspace_id,))
        reports, reports_7d, events = cursor.fetchone()
        cursor.execute("SELECT count(*) FILTER (WHERE status = 'assigned'), count(*) FILTER (WHERE status = 'completed') "
                       "FROM scouting_assignments WHERE workspace_id = %s", (workspace_id,))
        open_assignments, done_assignments = cursor.fetchone()
        cursor.execute(
            "SELECT COALESCE(m.display_name, u.full_name), count(*) FROM workspace_scouting_reports r "
            "JOIN team_memberships m ON m.workspace_id = r.workspace_id AND m.user_id = r.user_id "
            "JOIN users u ON u.id = r.user_id WHERE r.workspace_id = %s GROUP BY 1 ORDER BY 2 DESC, 1 LIMIT 10",
            (workspace_id,))
        top_scouts = [{"name": name, "reports": count} for name, count in cursor.fetchall()]
    return {"members_by_role": by_role, "active_last_7_days": active_7d, "never_signed_in": never,
            "pending_invitations": pending, "expired_invitations": expired,
            "scouting": {"reports": reports, "reports_last_7_days": reports_7d, "events": events,
                         "open_assignments": open_assignments, "completed_assignments": done_assignments,
                         "top_scouts": top_scouts}}


# --- the StratAI operator -------------------------------------------------------------------------------------


def list_workspaces(database: Database, status: str | None = None) -> list[dict[str, Any]]:
    with database.cursor() as cursor:
        cursor.execute(
            "SELECT w.id, w.team_number, w.team_name, w.verification_status, w.created_at, w.verified_at, "
            "w.verified_by, (SELECT count(*) FROM team_memberships m WHERE m.workspace_id = w.id "
            "AND m.status = 'active'), t.name FROM workspaces w LEFT JOIN teams t ON t.team_number = w.team_number "
            "WHERE (%s::text IS NULL OR w.verification_status = %s) ORDER BY w.created_at", (status, status))
        return [{"id": wid, "team_number": number, "team_name": name, "verification_status": vstatus,
                 "created_at": created, "verified_at": verified_at, "verified_by": verified_by,
                 "active_members": members, "frc_team_name": frc_name}
                for wid, number, name, vstatus, created, verified_at, verified_by, members, frc_name
                in cursor.fetchall()]


def operator_decide(database: Database, *, team_number: int, decision: str, operator: str, note: str) -> dict:
    """Record the StratAI operator's verdict on a pending workspace: "verified" or "rejected".

    Rejecting ends every session in the workspace and frees the team number for the real team."""
    if decision not in ("verified", "rejected"):
        raise invalid_input("decision must be verified or rejected")
    operator, note = clean_name(operator, "Operator name"), (note or "").strip()
    if not note:
        raise invalid_input("Record how ownership was checked (or why it was rejected) in the note.")
    with database.cursor() as cursor:
        cursor.execute("SELECT id, verification_status FROM workspaces WHERE team_number = %s "
                       "AND verification_status IN ('pending_verification', 'verified') FOR UPDATE", (team_number,))
        row = cursor.fetchone()
        if row is None:
            raise not_found("workspace_not_found", f"Team {team_number} has no pending or verified workspace.")
        workspace_id, status = row
        if decision == "verified" and status == "verified":
            raise conflict("already_verified", f"Team {team_number}'s workspace is already verified.")
        cursor.execute(
            "UPDATE workspaces SET verification_status = %s, verification_note = %s, verified_by = %s, "
            "verified_at = CASE WHEN %s = 'verified' THEN NOW() ELSE verified_at END, "
            # Verifying keeps the setup password: the registrant may not have created the first administrator yet.
            "setup_password_hash = CASE WHEN %s = 'rejected' THEN NULL ELSE setup_password_hash END, "
            "updated_at = NOW() WHERE id = %s", (decision, note, operator, decision, decision, workspace_id))
        if decision == "rejected":
            cursor.execute("UPDATE auth_sessions SET revoked_at = NOW() WHERE revoked_at IS NULL AND membership_id IN "
                           "(SELECT id FROM team_memberships WHERE workspace_id = %s)", (workspace_id,))
            cursor.execute("UPDATE invitations SET status = 'revoked', revoked_at = NOW() WHERE workspace_id = %s "
                           "AND status = 'pending'", (workspace_id,))
        activity.record(cursor, workspace_id=workspace_id, actor_user_id=None, actor_label=f"StratAI operator {operator}",
                        action="workspace_verified" if decision == "verified" else "workspace_rejected",
                        details={"note": note})
    return {"team_number": team_number, "verification_status": decision}
