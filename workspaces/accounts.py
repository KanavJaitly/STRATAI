"""Accounts: team registration, the first administrator, login, passwords and invitation acceptance.

**Registration and ownership.** A team number and name are public, so registering one proves nothing. A new
workspace starts as pending_verification. Its registrant sets a one-time setup password, uses it to create the
first administrator account, and is signed in to a workspace that can configure itself but cannot invite members
or hold scouting until a StratAI operator verifies the team (scripts/workspace_operator.py; the out-of-band check
is docs/team_workspaces.md section 3). Verification is never assumed or simulated. Only one pending or verified
workspace may exist per team number; a rejected registration frees the number for the real team.

**One account per person.** Every member signs in with their own email and password; there is no shared team
login. A person may belong to several teams' workspaces with one account; each sign-in names the team, and the
session is bound to that one membership.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from http import HTTPStatus
from typing import Any

import psycopg

from data.config import Settings
from database.connection import Database
from workspaces import activity, mailer, rate_limit
from workspaces.errors import WorkspaceError, conflict, forbidden, invalid_credentials, invalid_input
from workspaces.passwords import (
    burn_verification_time,
    check_password_policy,
    hash_password,
    needs_rehash,
    verify_password,
)
from workspaces.permissions import ROLE_LABELS, default_role_grants
from workspaces.sessions import SessionContext, create_session, revoke_user_sessions
from workspaces.tokens import new_token, token_hash

ACTIVE_WORKSPACE_STATUSES = ("pending_verification", "verified")


# --- input checks ---------------------------------------------------------------------------------------------


def normalize_email(email: Any) -> str:
    if not isinstance(email, str):
        raise invalid_input("Enter an email address.")
    normalized = email.strip().lower()
    if (len(normalized) > 254 or normalized.count("@") != 1 or normalized.startswith("@")
            or normalized.endswith("@") or any(ch.isspace() for ch in normalized)):
        raise invalid_input("Enter a valid email address.")
    return normalized


def clean_name(value: Any, what: str = "Full name", limit: int = 120) -> str:
    if not isinstance(value, str) or not value.strip():
        raise invalid_input(f"{what} is required.")
    cleaned = " ".join(value.split())
    if len(cleaned) > limit:
        raise invalid_input(f"{what} may have at most {limit} characters.")
    return cleaned


def check_team_number(team_number: Any) -> int:
    if isinstance(team_number, bool) or not isinstance(team_number, int) or not 1 <= team_number <= 99999:
        raise invalid_input("Enter your FRC team number (1 to 99999).")
    return team_number


# --- registration ---------------------------------------------------------------------------------------------


def register_workspace(database: Database, *, team_number: int, team_name: str, setup_password: str,
                       client_ip: str) -> dict[str, Any]:
    """Create a pending workspace for team_number. Refuses a number that already has a pending or verified one."""
    team_number = check_team_number(team_number)
    team_name = clean_name(team_name, "Team name", 100)
    check_password_policy(setup_password)
    rate_limit.check(database, "register_ip", client_ip)
    rate_limit.record(database, "register_ip", client_ip, succeeded=True)
    setup_hash = hash_password(setup_password)
    try:
        with database.cursor() as cursor:
            cursor.execute(
                "INSERT INTO workspaces (team_number, team_name, setup_password_hash) VALUES (%s, %s, %s) "
                "RETURNING id, created_at", (team_number, team_name, setup_hash))
            workspace_id, created_at = cursor.fetchone()
            for role, grants in default_role_grants().items():
                for permission, granted in grants.items():
                    cursor.execute("INSERT INTO workspace_role_permissions (workspace_id, role, permission, granted) "
                                   "VALUES (%s, %s, %s, %s)", (workspace_id, role, permission, granted))
            activity.record(cursor, workspace_id=workspace_id, actor_user_id=None, actor_label="Registrant",
                            action="workspace_registered", details={"team_number": team_number,
                                                                    "team_name": team_name})
            cursor.execute("SELECT name FROM teams WHERE team_number = %s", (team_number,))
            known = cursor.fetchone()
    except psycopg.errors.UniqueViolation:
        raise conflict("team_already_registered",
                       f"Team {team_number} already has a StratAI workspace (verified or awaiting verification). "
                       "If your team did not create it, contact the StratAI operator, who can review and reject it.")
    return {"team_number": team_number, "team_name": team_name, "verification_status": "pending_verification",
            "created_at": created_at, "known_frc_team": known is not None,
            "frc_team_name": known[0] if known else None}


def _locked_active_workspace(cursor: Any, team_number: int) -> tuple | None:
    cursor.execute(
        "SELECT id, team_name, verification_status, setup_password_hash FROM workspaces "
        "WHERE team_number = %s AND verification_status IN ('pending_verification', 'verified') FOR UPDATE",
        (team_number,))
    return cursor.fetchone()


def _find_or_create_user(cursor: Any, *, email: str, full_name: str, password: str) -> tuple[int, bool]:
    """The account for email: an existing one only if password is its password; otherwise a new one.

    Returns (user_id, created). An existing account's password is never replaced here: joining another team with
    the same email means proving you own that account."""
    cursor.execute("SELECT id, password_hash, status FROM users WHERE email = %s FOR UPDATE", (email,))
    row = cursor.fetchone()
    if row is not None:
        user_id, stored, status = row
        if status != "active" or not verify_password(password, stored):
            raise WorkspaceError(HTTPStatus.UNAUTHORIZED, "existing_account_password_mismatch",
                                 "A StratAI account already uses this email. Enter that account's password to "
                                 "join with it, or use a different email.")
        return user_id, False
    check_password_policy(password, email=email)
    cursor.execute("INSERT INTO users (email, full_name, password_hash, password_changed_at) "
                   "VALUES (%s, %s, %s, NOW()) RETURNING id", (email, full_name, hash_password(password)))
    return cursor.fetchone()[0], True


def create_initial_admin(database: Database, settings: Settings, *, team_number: int, setup_password: str,
                         full_name: str, email: str, password: str, client_ip: str) -> str:
    """Create the workspace's first administrator with the setup password, retire that password, and sign them in.

    Returns the new session token."""
    team_number = check_team_number(team_number)
    full_name = clean_name(full_name)
    email = normalize_email(email)
    subject = str(team_number)
    rate_limit.check(database, "setup_team", subject)
    rate_limit.check(database, "login_ip", client_ip)
    try:
        with database.connection() as conn, conn.cursor() as cursor:
            workspace = _locked_active_workspace(cursor, team_number)
            if workspace is None or workspace[3] is None:
                burn_verification_time(setup_password)
                raise WorkspaceError(HTTPStatus.UNAUTHORIZED, "invalid_setup_credentials",
                                     "The team number or setup password is not correct, or this team's first "
                                     "administrator already exists (sign in instead).")
            workspace_id, _, _, setup_hash = workspace
            if not verify_password(setup_password, setup_hash):
                raise WorkspaceError(HTTPStatus.UNAUTHORIZED, "invalid_setup_credentials",
                                     "The team number or setup password is not correct, or this team's first "
                                     "administrator already exists (sign in instead).")
            user_id, created = _find_or_create_user(cursor, email=email, full_name=full_name, password=password)
            cursor.execute("INSERT INTO team_memberships (workspace_id, user_id, role, display_name) "
                           "VALUES (%s, %s, 'admin', %s) RETURNING id", (workspace_id, user_id, full_name))
            membership_id = cursor.fetchone()[0]
            cursor.execute("UPDATE workspaces SET setup_password_hash = NULL, updated_at = NOW() WHERE id = %s",
                           (workspace_id,))
            if created:
                activity.record(cursor, workspace_id=workspace_id, actor_user_id=user_id, actor_label=full_name,
                                action="account_created", target_user_id=user_id, target_label=full_name)
            activity.record(cursor, workspace_id=workspace_id, actor_user_id=user_id, actor_label=full_name,
                            action="initial_admin_created", target_user_id=user_id, target_label=full_name,
                            details={"email": email})
            token = create_session(cursor, membership_id, settings)
    except WorkspaceError as refused:
        if refused.code in ("invalid_setup_credentials", "existing_account_password_mismatch"):
            rate_limit.record(database, "setup_team", subject, succeeded=False)
            rate_limit.record(database, "login_ip", client_ip, succeeded=False)
        raise
    return token


# --- login ----------------------------------------------------------------------------------------------------


def login(database: Database, settings: Settings, *, team_number: int, email: str, password: str,
          client_ip: str) -> str:
    """Check one member's own credentials for one team's workspace and open a session. Returns its token.

    Every failure that does not prove knowledge of the password reads the same (invalid_credentials) and takes the
    same time, so the response never reveals which teams or emails have accounts."""
    if not isinstance(password, str) or not password:
        raise invalid_credentials()
    try:
        team_number = check_team_number(team_number)
        email = normalize_email(email)
    except WorkspaceError:
        raise invalid_credentials() from None
    account = f"{team_number}:{email}"
    rate_limit.check(database, "login_account", account)
    rate_limit.check(database, "login_ip", client_ip)
    with database.connection() as conn, conn.cursor() as cursor:
        cursor.execute(
            "SELECT m.id, m.status, u.id, u.password_hash, u.status FROM workspaces w "
            "JOIN team_memberships m ON m.workspace_id = w.id JOIN users u ON u.id = m.user_id "
            "WHERE w.team_number = %s AND w.verification_status IN ('pending_verification', 'verified') "
            "AND u.email = %s", (team_number, email))
        row = cursor.fetchone()
        if row is None:
            burn_verification_time(password)
            ok = False
        else:
            membership_id, membership_status, user_id, stored, user_status = row
            ok = verify_password(password, stored)
        if not ok:
            conn.rollback()
            rate_limit.record(database, "login_account", account, succeeded=False)
            rate_limit.record(database, "login_ip", client_ip, succeeded=False)
            raise invalid_credentials()
        if membership_status != "active" or user_status != "active":
            raise forbidden("account_inactive",
                            "This account is suspended or no longer a member of this team's workspace. "
                            "Ask one of your team's administrators.")
        if needs_rehash(stored):
            cursor.execute("UPDATE users SET password_hash = %s WHERE id = %s", (hash_password(password), user_id))
        token = create_session(cursor, membership_id, settings)
    rate_limit.clear(database, "login_account", account)
    return token


# --- passwords ------------------------------------------------------------------------------------------------


def change_password(database: Database, context: SessionContext, *, current_password: str,
                    new_password: str) -> None:
    """Change the signed-in person's password. Ends their other sessions, in every team."""
    subject = str(context.user_id)
    rate_limit.check(database, "password_check_user", subject)
    with database.connection() as conn, conn.cursor() as cursor:
        cursor.execute("SELECT password_hash FROM users WHERE id = %s FOR UPDATE", (context.user_id,))
        stored = cursor.fetchone()[0]
        if not verify_password(current_password or "", stored):
            conn.rollback()
            rate_limit.record(database, "password_check_user", subject, succeeded=False)
            raise forbidden("current_password_incorrect", "Your current password is not correct.")
        check_password_policy(new_password, email=context.email)
        if verify_password(new_password, stored):
            raise invalid_input("Choose a new password that differs from your current one.")
        cursor.execute("UPDATE users SET password_hash = %s, password_changed_at = NOW() WHERE id = %s",
                       (hash_password(new_password), context.user_id))
        revoke_user_sessions(cursor, context.user_id, except_session_id=context.session_id)
        activity.record(cursor, workspace_id=context.workspace_id, actor_user_id=context.user_id,
                        actor_label=context.name, action="password_changed", target_user_id=context.user_id,
                        target_label=context.name)


def issue_reset_token(cursor: Any, settings: Settings, *, membership_id: int,
                      issued_by_user_id: int | None) -> tuple[str, datetime]:
    """A new single-use reset token for a membership, inside the caller's transaction. Earlier unused tokens for
    the same membership stop working."""
    cursor.execute("UPDATE password_reset_tokens SET used_at = NOW() WHERE membership_id = %s AND used_at IS NULL",
                   (membership_id,))
    token = new_token()
    expires_at = datetime.now(timezone.utc) + timedelta(minutes=settings.password_reset_ttl_minutes)
    cursor.execute("INSERT INTO password_reset_tokens (membership_id, token_hash, expires_at, issued_by_user_id) "
                   "VALUES (%s, %s, %s, %s)", (membership_id, token_hash(token), expires_at, issued_by_user_id))
    return token, expires_at


def reset_link_path(token: str) -> str:
    # In the URL fragment, which browsers never send to a server, so the token stays out of every access log.
    return f"/auth/reset#token={token}"


def request_password_reset(database: Database, settings: Settings, *, team_number: int, email: str,
                           client_ip: str) -> dict[str, Any]:
    """Email a reset link if this is an active member and email is configured. The answer is the same either way,
    so it never reveals whether an account exists."""
    configured = mailer.email_channel(settings) is not None
    answer = {"accepted": True, "email_delivery_configured": configured}
    try:
        team_number = check_team_number(team_number)
        email = normalize_email(email)
    except WorkspaceError:
        return answer
    account = f"{team_number}:{email}"
    rate_limit.check(database, "reset_request_ip", client_ip)
    rate_limit.check(database, "reset_request_account", account)
    rate_limit.record(database, "reset_request_ip", client_ip, succeeded=True)
    rate_limit.record(database, "reset_request_account", account, succeeded=True)
    if not configured:
        return answer
    with database.cursor() as cursor:
        cursor.execute(
            "SELECT m.id, w.team_number, w.team_name FROM workspaces w JOIN team_memberships m "
            "ON m.workspace_id = w.id JOIN users u ON u.id = m.user_id WHERE w.team_number = %s "
            "AND w.verification_status IN ('pending_verification', 'verified') AND u.email = %s "
            "AND m.status = 'active' AND u.status = 'active'", (team_number, email))
        row = cursor.fetchone()
        if row is None:
            return answer
        membership_id, number, name = row
        token, _ = issue_reset_token(cursor, settings, membership_id=membership_id, issued_by_user_id=None)
    link = mailer.absolute_link(settings, reset_link_path(token))
    mailer.send(settings, to=email, subject=f"Reset your StratAI password (team {number})",
                body=f"Someone asked to reset the StratAI password for {email} in team {number} ({name}).\n\n"
                     f"To choose a new password, open this link within {settings.password_reset_ttl_minutes} "
                     f"minutes:\n{link}\n\nIf you did not ask for this, ignore this email; your password is "
                     "unchanged.\n")
    return answer


def reset_password(database: Database, *, token: str, new_password: str, client_ip: str) -> None:
    """Set a new password with a reset token: single use, unexpired. Ends every session the person holds."""
    rate_limit.check(database, "token_ip", client_ip)
    with database.connection() as conn, conn.cursor() as cursor:
        cursor.execute(
            "SELECT t.id, m.id, m.workspace_id, u.id, u.email, COALESCE(m.display_name, u.full_name) "
            "FROM password_reset_tokens t JOIN team_memberships m ON m.id = t.membership_id "
            "JOIN users u ON u.id = m.user_id WHERE t.token_hash = %s AND t.used_at IS NULL "
            "AND t.expires_at > NOW() FOR UPDATE OF t", (token_hash(token or ""),))
        row = cursor.fetchone()
        if row is None:
            conn.rollback()
            rate_limit.record(database, "token_ip", client_ip, succeeded=False)
            raise WorkspaceError(HTTPStatus.GONE, "reset_link_invalid",
                                 "This password reset link is invalid, expired or already used. Ask for a new one.")
        token_id, membership_id, workspace_id, user_id, email, name = row
        check_password_policy(new_password, email=email)
        cursor.execute("UPDATE password_reset_tokens SET used_at = NOW() WHERE id = %s", (token_id,))
        cursor.execute("UPDATE users SET password_hash = %s, password_changed_at = NOW() WHERE id = %s",
                       (hash_password(new_password), user_id))
        revoke_user_sessions(cursor, user_id)
        activity.record(cursor, workspace_id=workspace_id, actor_user_id=user_id, actor_label=name,
                        action="password_reset_completed", target_user_id=user_id, target_label=name)


# --- invitations ----------------------------------------------------------------------------------------------


def invitation_link_path(token: str) -> str:
    return f"/auth/invite#token={token}"


_INVITATION_SQL = """
SELECT i.id, i.workspace_id, i.email, i.full_name, i.role, i.status, i.expires_at, w.team_number, w.team_name,
       w.verification_status
FROM invitations i JOIN workspaces w ON w.id = i.workspace_id
WHERE i.token_hash = %s
"""


def _usable_invitation(row: tuple | None) -> tuple:
    if row is None or row[5] != "pending" or row[9] != "verified":
        raise WorkspaceError(HTTPStatus.GONE, "invitation_invalid",
                             "This invitation link is not valid: it was already used, revoked or replaced by a "
                             "newer one. Ask your team's administrator for a new invitation.")
    if row[6] <= datetime.now(timezone.utc):
        raise WorkspaceError(HTTPStatus.GONE, "invitation_expired",
                             "This invitation has expired. Ask your team's administrator to resend it.")
    return row


def preview_invitation(database: Database, *, token: str, client_ip: str) -> dict[str, Any]:
    """What an invitation offers, for the acceptance page."""
    rate_limit.check(database, "token_ip", client_ip)
    with database.cursor() as cursor:
        cursor.execute(_INVITATION_SQL, (token_hash(token or ""),))
        row = cursor.fetchone()
        try:
            _usable_invitation(row)
        except WorkspaceError:
            rate_limit.record(database, "token_ip", client_ip, succeeded=False)
            raise
        cursor.execute("SELECT 1 FROM users WHERE email = %s", (row[2],))
        existing = cursor.fetchone() is not None
    return {"team_number": row[7], "team_name": row[8], "email": row[2], "full_name": row[3], "role": row[4],
            "role_label": ROLE_LABELS[row[4]], "expires_at": row[6], "existing_account": existing}


def accept_invitation(database: Database, settings: Settings, *, token: str, full_name: str, password: str,
                      client_ip: str) -> str:
    """Accept an invitation: create the account (or join with an existing one by its password), make the
    membership, spend the invitation, and sign in. Returns the session token."""
    rate_limit.check(database, "token_ip", client_ip)
    try:
        with database.connection() as conn, conn.cursor() as cursor:
            cursor.execute(_INVITATION_SQL + " FOR UPDATE OF i", (token_hash(token or ""),))
            row = _usable_invitation(cursor.fetchone())
            invitation_id, workspace_id, email, invited_name, role = row[:5]
            name = clean_name(full_name or invited_name)
            user_id, created = _find_or_create_user(cursor, email=email, full_name=name, password=password)
            cursor.execute("SELECT id, status FROM team_memberships WHERE workspace_id = %s AND user_id = %s "
                           "FOR UPDATE", (workspace_id, user_id))
            existing = cursor.fetchone()
            if existing is not None and existing[1] != "removed":
                raise conflict("already_member", "This account is already a member of this team's workspace.")
            if existing is None:
                cursor.execute("INSERT INTO team_memberships (workspace_id, user_id, role, display_name) "
                               "VALUES (%s, %s, %s, %s) RETURNING id", (workspace_id, user_id, role, name))
                membership_id = cursor.fetchone()[0]
            else:
                membership_id = existing[0]
                cursor.execute("UPDATE team_memberships SET status = 'active', role = %s, display_name = %s, "
                               "updated_at = NOW() WHERE id = %s", (role, name, membership_id))
            cursor.execute("UPDATE invitations SET status = 'accepted', accepted_at = NOW(), accepted_user_id = %s "
                           "WHERE id = %s", (user_id, invitation_id))
            if created:
                activity.record(cursor, workspace_id=workspace_id, actor_user_id=user_id, actor_label=name,
                                action="account_created", target_user_id=user_id, target_label=name)
            activity.record(cursor, workspace_id=workspace_id, actor_user_id=user_id, actor_label=name,
                            action="invitation_accepted", target_user_id=user_id, target_label=name,
                            details={"role": role, "email": email})
            token_out = create_session(cursor, membership_id, settings)
    except WorkspaceError as refused:
        if refused.code in ("invitation_invalid", "invitation_expired", "existing_account_password_mismatch"):
            rate_limit.record(database, "token_ip", client_ip, succeeded=False)
        raise
    return token_out


def session_summary(context: SessionContext) -> dict[str, Any]:
    """What the web app needs to know about the signed-in member."""
    return {"authenticated": True, "user": {"id": context.user_id, "name": context.name, "email": context.email},
            "workspace": {"team_number": context.team_number, "team_name": context.team_name,
                          "verification_status": context.verification_status},
            "role": context.role, "role_label": ROLE_LABELS[context.role],
            "permissions": sorted(context.permissions)}


def seed_missing_permissions(cursor: Any, workspace_id: int) -> None:
    """Add a stored row for any configurable permission a workspace has none for (a permission added later)."""
    for role, grants in default_role_grants().items():
        for permission, granted in grants.items():
            cursor.execute("INSERT INTO workspace_role_permissions (workspace_id, role, permission, granted) "
                           "VALUES (%s, %s, %s, %s) ON CONFLICT DO NOTHING", (workspace_id, role, permission, granted))
