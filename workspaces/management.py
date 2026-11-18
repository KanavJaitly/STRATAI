"""Team Management: members (see them, change a role, suspend, remove), team settings, the activity log and team
analytics; plus set_role_by_email, the command-line role change (scripts/set_role.py).

Every function here takes the caller's SessionContext and checks the permission itself, so the rule holds however
the function is reached (the API also checks it, before the call). Every row it reads or changes is selected by
the caller's workspace_id as well as its own id.
"""

from __future__ import annotations

from datetime import date, datetime, timezone
from typing import Any

import psycopg
from psycopg.types.json import Jsonb

from database.connection import Database
from workspaces import activity
from workspaces.accounts import clean_name, normalize_email, team_workspace_id
from workspaces.errors import WorkspaceError, conflict, forbidden, invalid_input, not_found
from workspaces.permissions import ADMIN, ROLE_LABELS, ROLES
from workspaces.sessions import SessionContext, revoke_membership_sessions

LAST_ADMIN_CONSTRAINT = "team_memberships_last_active_admin"


def require(context: SessionContext, permission: str) -> None:
    if not context.can(permission):
        raise forbidden("permission_denied", "Your role does not have permission to do this.")


def require_verified(context: SessionContext, what: str) -> None:
    """The team's workspace is created verified (migration 0015); this stays as a guard for scouting writes."""
    if not context.verified:
        raise forbidden("workspace_not_verified", f"{what} is not available: the team workspace is not verified.")


def _last_admin_error() -> WorkspaceError:
    return conflict("last_active_admin", "A team must keep at least one active administrator. Make someone else an "
                                         "administrator first.")


# --- overview -------------------------------------------------------------------------------------------------


def workspace_overview(database: Database, context: SessionContext) -> dict[str, Any]:
    """The team overview: team, verification, settings, member count, own role and permissions."""
    require(context, "team_overview")
    with database.cursor() as cursor:
        cursor.execute("SELECT team_number, team_name, verification_status, verified_at, settings, created_at "
                       "FROM workspaces WHERE id = %s", (context.workspace_id,))
        number, name, status, verified_at, settings, created_at = cursor.fetchone()
        cursor.execute("SELECT count(*) FROM team_memberships WHERE workspace_id = %s AND status = 'active'",
                       (context.workspace_id,))
        active_members = cursor.fetchone()[0]
        settings_out = _public_settings(cursor, settings)
    return {"team_number": number, "team_name": name, "verification_status": status, "verified_at": verified_at,
            "created_at": created_at, "settings": settings_out, "active_members": active_members,
            "role": context.role, "role_label": ROLE_LABELS[context.role], "permissions": sorted(context.permissions)}


# --- members --------------------------------------------------------------------------------------------------


def list_members(database: Database, context: SessionContext) -> dict[str, Any]:
    """Every member of the team (any status but removed)."""
    require(context, "team_management")
    with database.cursor() as cursor:
        cursor.execute(
            "SELECT m.id, u.id, COALESCE(m.display_name, u.full_name), u.email, m.role, m.status, m.last_login_at, "
            "m.created_at FROM team_memberships m JOIN users u ON u.id = m.user_id "
            "WHERE m.workspace_id = %s AND m.status <> 'removed' ORDER BY m.created_at, m.id",
            (context.workspace_id,))
        members = [{"membership_id": mid, "user_id": uid, "name": name, "email": email, "role": role,
                    "role_label": ROLE_LABELS[role], "status": status,
                    "last_login_at": last_login, "joined_at": joined, "is_self": mid == context.membership_id}
                   for mid, uid, name, email, role, status, last_login, joined in cursor.fetchall()]
    return {"members": members}


def _check_role(role: Any) -> str:
    if role not in ROLES:
        raise invalid_input(f"Role must be one of {', '.join(ROLES)}.")
    return role


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

    The account itself remains, so the email stays taken: `python -m scripts.set_role <email> <role>` restores
    the member."""
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


# --- settings -------------------------------------------------------------------------------------------------

SETTINGS_KEYS = ("default_event_key", "scouting_instructions")
MAX_TEAM_EVENTS = 20

# The team's events live in workspaces.settings (JSONB, so no migration): "team_event_keys", the events the team is
# going to, and "default_event_key", which since 2026-11-17 is the optional *pin*. The current event the dashboards
# open on is computed: the pin when set, else the team event happening today, else the next one, else the most recent.


def _today() -> date:
    return datetime.now(timezone.utc).date()


def _event_rows(cursor: Any, keys: list[str]) -> list[dict[str, Any]]:
    if not keys:
        return []
    cursor.execute("SELECT event_key, name, start_date, end_date FROM events WHERE event_key = ANY(%s)", (keys,))
    rows = {key: (name, start, end) for key, name, start, end in cursor.fetchall()}
    today = _today()
    out = []
    for key in keys:
        if key not in rows:
            continue
        name, start, end = rows[key]
        status = None if start is None else ("upcoming" if start > today
                                             else "past" if (end or start) < today else "happening")
        out.append({"event_key": key, "name": name, "start_date": start, "end_date": end, "status": status})
    # by date, undated last
    return sorted(out, key=lambda e: (e["start_date"] is None, e["start_date"] or date.max, e["event_key"]))


def current_team_event(events: list[dict[str, Any]], pinned: str | None) -> tuple[str | None, str | None]:
    """(event_key, reason): the pin; else the team event happening today; else the next; else the most recent."""
    if pinned:
        return pinned, "pinned"
    for status, pick in (("happening", min), ("upcoming", min)):
        found = [e for e in events if e["status"] == status]
        if found:
            return pick(found, key=lambda e: e["start_date"])["event_key"], "happening" if status == "happening" else "next"
    past = [e for e in events if e["status"] == "past"]
    if past:
        return max(past, key=lambda e: e["end_date"] or e["start_date"])["event_key"], "most_recent"
    return None, None


def _team_event_state(cursor: Any, stored: dict[str, Any] | None) -> dict[str, Any]:
    stored = stored or {}
    pinned = stored.get("default_event_key")
    keys = list(dict.fromkeys([*(stored.get("team_event_keys") or []), *([pinned] if pinned else [])]))
    events = _event_rows(cursor, keys)
    current, reason = current_team_event(events, pinned)
    return {"team_events": events, "pinned_event_key": pinned, "current_event_key": current, "current_reason": reason}


def _public_settings(cursor: Any, stored: dict[str, Any] | None) -> dict[str, Any]:
    state = _team_event_state(cursor, stored)
    return {
        # the event dashboards open on: the computed current event (the pin when one is set)
        "default_event_key": state["current_event_key"],
        "scouting_instructions": (stored or {}).get("scouting_instructions"),
        "team_event_keys": [e["event_key"] for e in state["team_events"]],
        **state,
    }


def get_team_settings(database: Database, context: SessionContext) -> dict[str, Any]:
    require(context, "team_settings")
    with database.cursor() as cursor:
        cursor.execute("SELECT team_number, team_name, settings FROM workspaces WHERE id = %s", (context.workspace_id,))
        number, name, settings = cursor.fetchone()
        return {"team_number": number, "team_name": name, **_public_settings(cursor, settings)}


def team_events(database: Database, context: SessionContext) -> dict[str, Any]:
    """What every member reads from the team's settings: its events, its current event, and the instructions shown
    to scouters (the events page and the dashboards; scouts are not administrators)."""
    require(context, "team_info")
    with database.cursor() as cursor:
        cursor.execute("SELECT settings FROM workspaces WHERE id = %s", (context.workspace_id,))
        stored = cursor.fetchone()[0]
        return {**_team_event_state(cursor, stored), "scouting_instructions": (stored or {}).get("scouting_instructions")}


def _known_event(cursor: Any, event_key: Any) -> str:
    if not isinstance(event_key, str) or not event_key.strip():
        raise invalid_input("An event key must be text.")
    cursor.execute("SELECT 1 FROM events WHERE event_key = %s", (event_key,))
    if cursor.fetchone() is None:
        raise invalid_input(f"Event '{event_key}' is not known to StratAI.")
    return event_key


def update_team_settings(database: Database, context: SessionContext, changes: dict[str, Any]) -> dict[str, Any]:
    """Change the team name, the team's events and pinned current event, or the instructions scouters see. The team
    number never changes. `default_event_key` is still accepted, as the pin."""
    require(context, "team_settings")
    if "default_event_key" in changes and "pinned_event_key" not in changes:
        changes = {**changes, "pinned_event_key": changes["default_event_key"]}
    changes = {k: v for k, v in changes.items() if k != "default_event_key"}
    unknown = set(changes) - {"team_name", "scouting_instructions", "team_event_keys", "pinned_event_key"}
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
        if "team_event_keys" in changes:
            keys = changes["team_event_keys"] or []
            if not isinstance(keys, list):
                raise invalid_input("team_event_keys must be a list of event keys.")
            keys = list(dict.fromkeys(_known_event(cursor, k) for k in keys))
            if len(keys) > MAX_TEAM_EVENTS:
                raise invalid_input(f"A team can list at most {MAX_TEAM_EVENTS} events.")
            if (stored.get("team_event_keys") or []) != keys:
                diff["team_event_keys"] = {"from": stored.get("team_event_keys") or [], "to": keys}
            stored["team_event_keys"] = keys
        if "pinned_event_key" in changes:
            pinned = changes["pinned_event_key"] or None
            if pinned is not None:
                _known_event(cursor, pinned)
                if pinned not in (stored.get("team_event_keys") or []):  # a pinned event is one of the team's events
                    stored["team_event_keys"] = [*(stored.get("team_event_keys") or []), pinned]
            if stored.get("default_event_key") != pinned:
                diff["pinned_event_key"] = {"from": stored.get("default_event_key"), "to": pinned}
            stored["default_event_key"] = pinned
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
        return {"team_number": context.team_number, "team_name": updated_name, **_public_settings(cursor, stored)}


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
    """Workspace usage for the Admin Dashboard: membership, sign-ins and scouting activity."""
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
            "scouting": {"reports": reports, "reports_last_7_days": reports_7d, "events": events,
                         "open_assignments": open_assignments, "completed_assignments": done_assignments,
                         "top_scouts": top_scouts}}


# --- the command line -----------------------------------------------------------------------------------------


def set_role_by_email(database: Database, email: str, role: str) -> dict[str, Any]:
    """Give the member with email the role, reactivating them if they were suspended or removed (scripts/set_role.py).

    For whoever runs the server, outside any session: it is recorded in the activity log as done from the command
    line. Demoting the last active administrator is refused, as in the web app."""
    email = normalize_email(email)
    role = _check_role(role)
    try:
        with database.cursor() as cursor:
            workspace_id = team_workspace_id(cursor)
            cursor.execute("SELECT 1 FROM workspaces WHERE id = %s FOR UPDATE", (workspace_id,))
            cursor.execute(
                "SELECT m.id, u.id, m.role, m.status, COALESCE(m.display_name, u.full_name) FROM team_memberships m "
                "JOIN users u ON u.id = m.user_id WHERE m.workspace_id = %s AND u.email = %s FOR UPDATE OF m",
                (workspace_id, email))
            row = cursor.fetchone()
            if row is None:
                raise not_found("member_not_found", f"No account uses {email}. They must sign up first.")
            membership_id, user_id, old_role, old_status, name = row
            cursor.execute("UPDATE team_memberships SET role = %s, status = 'active', updated_at = NOW() "
                           "WHERE id = %s", (role, membership_id))
            if old_role != role:
                activity.record(cursor, workspace_id=workspace_id, actor_user_id=None, actor_label="Command line",
                                action="role_changed", target_user_id=user_id, target_label=name,
                                details={"from": old_role, "to": role})
            if old_status != "active":
                activity.record(cursor, workspace_id=workspace_id, actor_user_id=None, actor_label="Command line",
                                action="member_reactivated", target_user_id=user_id, target_label=name)
    except psycopg.errors.CheckViolation as exc:
        if exc.diag.constraint_name == LAST_ADMIN_CONSTRAINT:
            raise _last_admin_error() from None
        raise
    return {"email": email, "name": name, "role": role, "previous_role": old_role, "previous_status": old_status}
