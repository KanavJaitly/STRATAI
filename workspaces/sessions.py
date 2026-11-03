"""Server-side sessions.

A session is bound to one membership (one person in one team's workspace). The browser holds only the random token,
in an HttpOnly cookie; the database holds only its hash. Every request re-resolves the session against current
state, so suspending or removing a member, rejecting a workspace, disabling a user, changing a role or changing a
role's permissions takes effect on that member's very next request, not at the session's expiry.

A session ends at the first of: logout, revocation (suspension, removal, password change or reset, workspace
rejection), its absolute lifetime (SESSION_TTL_HOURS), or SESSION_IDLE_HOURS without a request.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

from data.config import Settings
from database.connection import Database
from workspaces.permissions import ADMIN, effective_permissions
from workspaces.tokens import new_token, token_hash

COOKIE_NAME = "stratai_session"
# last_seen_at is written at most this often per session, so an active page does not write on every request.
TOUCH_INTERVAL = timedelta(minutes=5)


@dataclass(frozen=True)
class SessionContext:
    """Who is calling: one active member of one workspace, with the permissions their role holds right now."""

    session_id: int
    membership_id: int
    user_id: int
    workspace_id: int
    team_number: int
    team_name: str
    verification_status: str
    role: str
    email: str
    name: str
    permissions: frozenset[str]

    @property
    def is_admin(self) -> bool:
        return self.role == ADMIN

    @property
    def verified(self) -> bool:
        return self.verification_status == "verified"

    def can(self, permission: str) -> bool:
        return permission in self.permissions


def cookie_secure(settings: Settings) -> bool:
    return settings.session_cookie_secure if settings.session_cookie_secure is not None else settings.env != "development"


def create_session(cursor: Any, membership_id: int, settings: Settings) -> str:
    """A new session for membership_id, inside the caller's transaction. Returns the token for the cookie."""
    token = new_token()
    cursor.execute(
        "INSERT INTO auth_sessions (token_hash, membership_id, expires_at) "
        "VALUES (%s, %s, NOW() + %s)",
        (token_hash(token), membership_id, timedelta(hours=settings.session_ttl_hours)))
    cursor.execute("UPDATE team_memberships SET last_login_at = NOW() WHERE id = %s", (membership_id,))
    return token


def role_grants(cursor: Any, workspace_id: int, role: str) -> dict[str, bool]:
    cursor.execute("SELECT permission, granted FROM workspace_role_permissions WHERE workspace_id = %s AND role = %s",
                   (workspace_id, role))
    return {permission: granted for permission, granted in cursor.fetchall()}


_RESOLVE_SQL = """
SELECT s.id, s.last_seen_at, m.id, m.role, u.id, u.email, COALESCE(m.display_name, u.full_name),
       w.id, w.team_number, w.team_name, w.verification_status
FROM auth_sessions s
JOIN team_memberships m ON m.id = s.membership_id
JOIN users u ON u.id = m.user_id
JOIN workspaces w ON w.id = m.workspace_id
WHERE s.token_hash = %s
  AND s.revoked_at IS NULL
  AND s.expires_at > NOW()
  AND s.last_seen_at > NOW() - %s
  AND m.status = 'active'
  AND u.status = 'active'
  AND w.verification_status IN ('pending_verification', 'verified')
"""


def resolve_session(database: Database, token: str | None, settings: Settings) -> SessionContext | None:
    """The live session behind token, or None if there is none (absent, unknown, expired, idle, revoked, or its
    member, user or workspace is no longer active)."""
    if not token or len(token) > 200:
        return None
    with database.cursor() as cursor:
        cursor.execute(_RESOLVE_SQL, (token_hash(token), timedelta(hours=settings.session_idle_hours)))
        row = cursor.fetchone()
        if row is None:
            return None
        (session_id, last_seen, membership_id, role, user_id, email, name,
         workspace_id, team_number, team_name, status) = row
        if datetime.now(timezone.utc) - last_seen > TOUCH_INTERVAL:
            cursor.execute("UPDATE auth_sessions SET last_seen_at = NOW() WHERE id = %s", (session_id,))
        grants = role_grants(cursor, workspace_id, role) if role != ADMIN else {}
    return SessionContext(session_id=session_id, membership_id=membership_id, user_id=user_id,
                          workspace_id=workspace_id, team_number=team_number, team_name=team_name,
                          verification_status=status, role=role, email=email, name=name,
                          permissions=effective_permissions(role, grants))


def revoke_token(database: Database, token: str | None) -> None:
    """End the session behind token (logout). Unknown tokens are ignored."""
    if not token or len(token) > 200:
        return
    with database.cursor() as cursor:
        cursor.execute("UPDATE auth_sessions SET revoked_at = NOW() WHERE token_hash = %s AND revoked_at IS NULL",
                       (token_hash(token),))


def revoke_membership_sessions(cursor: Any, membership_id: int) -> None:
    cursor.execute("UPDATE auth_sessions SET revoked_at = NOW() WHERE membership_id = %s AND revoked_at IS NULL",
                   (membership_id,))


def revoke_user_sessions(cursor: Any, user_id: int, *, except_session_id: int | None = None) -> None:
    """End every session the person holds, in every team, except optionally the one making the request."""
    cursor.execute(
        "UPDATE auth_sessions SET revoked_at = NOW() WHERE revoked_at IS NULL AND id <> %s "
        "AND membership_id IN (SELECT id FROM team_memberships WHERE user_id = %s)",
        (except_session_id or 0, user_id))
