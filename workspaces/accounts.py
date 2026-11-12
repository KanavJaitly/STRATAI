"""Accounts for FRC Team 11 (MORT): sign-up with the team join code, sign-in, passwords and reset codes.

**One team.** StratAI serves one team. Migration 0015 creates its one workspace (team 11), and every account is a
membership in it. Nobody types a team number anywhere.

**Sign-up.** A new member gives their name, email, a password and the team join code (TEAM_JOIN_CODE, an
environment secret, compared in constant time). The code is checked before anything else, so only people who
already have it learn anything (for example that an email is taken). Wrong codes are rate-limited per client
address and across all addresses at once. New accounts are base members, unless their email is in ADMIN_EMAILS,
and are signed in at once.

**Password reset by code.** "Forgot password" emails a 6-digit code. Only a salted hash is stored. A code works
once, for RESET_CODE_TTL, and dies after RESET_CODE_MAX_ATTEMPTS wrong tries; asking for a new code retires the old
one, and at most 3 codes per email are sent per hour, so the attempt limit cannot be reset by asking again. The
answer to "forgot password" never says whether the email has an account, and takes the same time either way: the
account lookup and the email happen in a background task, after the answer is sent.
"""

from __future__ import annotations

import hashlib
import hmac
import logging
import secrets
from datetime import timedelta
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
from workspaces.permissions import ADMIN, BASE, ROLE_LABELS
from workspaces.sessions import SessionContext, create_session, revoke_user_sessions

logger = logging.getLogger(__name__)

TEAM_NUMBER = 11
RESET_CODE_TTL = timedelta(minutes=15)
RESET_CODE_MAX_ATTEMPTS = 5
RESET_CODE_DIGITS = 6


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


def team_workspace_id(cursor: Any) -> int:
    """The id of the team's one workspace (created by migration 0015)."""
    cursor.execute("SELECT id FROM workspaces WHERE team_number = %s", (TEAM_NUMBER,))
    row = cursor.fetchone()
    if row is None:
        raise conflict("team_workspace_missing",
                       "This server's database has no team workspace. Apply the latest migrations "
                       "(database/migrate.py).")
    return row[0]


def role_for_email(settings: Settings, email: str) -> str:
    """admin for an email listed in ADMIN_EMAILS (any case), otherwise base."""
    return ADMIN if email.lower() in settings.admin_emails else BASE


# --- sign-up --------------------------------------------------------------------------------------------------


def join_code_matches(settings: Settings, supplied: Any) -> bool:
    """Whether supplied is the team join code, compared in constant time. False when no code is configured."""
    if settings.team_join_code is None or not isinstance(supplied, str):
        return False
    expected = settings.team_join_code.get_secret_value().strip().encode("utf-8")
    return hmac.compare_digest(supplied.strip().encode("utf-8"), expected)


def signup(database: Database, settings: Settings, *, full_name: str, email: str, password: str, join_code: str,
           client_ip: str) -> str:
    """Create a member account with the team join code and sign it in. Returns the new session token."""
    if settings.team_join_code is None:
        raise forbidden("signup_closed", "Sign-up is not open on this server: no team join code is configured.")
    rate_limit.check(database, "signup_code_global", rate_limit.GLOBAL_SUBJECT)
    rate_limit.check(database, "signup_code_ip", client_ip)
    if not join_code_matches(settings, join_code):
        rate_limit.record(database, "signup_code_ip", client_ip, succeeded=False)
        rate_limit.record(database, "signup_code_global", rate_limit.GLOBAL_SUBJECT, succeeded=False)
        raise forbidden("invalid_join_code",
                        "That team join code is not correct. Ask one of the team's administrators for it.")
    full_name = clean_name(full_name)
    email = normalize_email(email)
    check_password_policy(password)
    role = role_for_email(settings, email)
    password_hash = hash_password(password)
    try:
        with database.connection() as conn, conn.cursor() as cursor:
            workspace_id = team_workspace_id(cursor)
            cursor.execute("INSERT INTO users (email, full_name, password_hash, password_changed_at) "
                           "VALUES (%s, %s, %s, NOW()) RETURNING id", (email, full_name, password_hash))
            user_id = cursor.fetchone()[0]
            cursor.execute("INSERT INTO team_memberships (workspace_id, user_id, role) VALUES (%s, %s, %s) "
                           "RETURNING id", (workspace_id, user_id, role))
            membership_id = cursor.fetchone()[0]
            activity.record(cursor, workspace_id=workspace_id, actor_user_id=user_id, actor_label=full_name,
                            action="account_created", target_user_id=user_id, target_label=full_name,
                            details={"role": role})
            token = create_session(cursor, membership_id, settings)
    except psycopg.errors.UniqueViolation:
        raise conflict("email_already_registered",
                       "An account already uses this email. Sign in instead, or use \"Forgot password\".") from None
    return token


# --- login ----------------------------------------------------------------------------------------------------


def login(database: Database, settings: Settings, *, email: str, password: str, client_ip: str) -> str:
    """Check a member's email and password and open a session. Returns its token.

    Every failure that does not prove knowledge of the password reads the same (invalid_credentials) and takes the
    same time, so the response never reveals which emails have accounts."""
    if not isinstance(password, str) or not password:
        raise invalid_credentials()
    try:
        email = normalize_email(email)
    except WorkspaceError:
        raise invalid_credentials() from None
    rate_limit.check(database, "login_account", email)
    rate_limit.check(database, "login_ip", client_ip)
    with database.connection() as conn, conn.cursor() as cursor:
        cursor.execute(
            "SELECT m.id, m.status, u.id, u.password_hash, u.status FROM workspaces w "
            "JOIN team_memberships m ON m.workspace_id = w.id JOIN users u ON u.id = m.user_id "
            "WHERE w.team_number = %s AND u.email = %s", (TEAM_NUMBER, email))
        row = cursor.fetchone()
        if row is None:
            burn_verification_time(password)
            ok = False
        else:
            membership_id, membership_status, user_id, stored, user_status = row
            ok = verify_password(password, stored)
        if not ok:
            conn.rollback()
            rate_limit.record(database, "login_account", email, succeeded=False)
            rate_limit.record(database, "login_ip", client_ip, succeeded=False)
            raise invalid_credentials()
        if membership_status != "active" or user_status != "active":
            raise forbidden("account_inactive",
                            "This account is suspended or was removed from the team. Ask one of the team's "
                            "administrators.")
        if needs_rehash(stored):
            cursor.execute("UPDATE users SET password_hash = %s WHERE id = %s", (hash_password(password), user_id))
        token = create_session(cursor, membership_id, settings)
    rate_limit.clear(database, "login_account", email)
    return token


# --- passwords ------------------------------------------------------------------------------------------------


def change_password(database: Database, context: SessionContext, *, current_password: str,
                    new_password: str) -> None:
    """Change the signed-in person's password. Ends their other sessions."""
    subject = str(context.user_id)
    rate_limit.check(database, "password_check_user", subject)
    with database.connection() as conn, conn.cursor() as cursor:
        cursor.execute("SELECT password_hash FROM users WHERE id = %s FOR UPDATE", (context.user_id,))
        stored = cursor.fetchone()[0]
        if not verify_password(current_password or "", stored):
            conn.rollback()
            rate_limit.record(database, "password_check_user", subject, succeeded=False)
            raise forbidden("current_password_incorrect", "Your current password is not correct.")
        check_password_policy(new_password)
        if verify_password(new_password, stored):
            raise invalid_input("Choose a new password that differs from your current one.")
        cursor.execute("UPDATE users SET password_hash = %s, password_changed_at = NOW() WHERE id = %s",
                       (hash_password(new_password), context.user_id))
        revoke_user_sessions(cursor, context.user_id, except_session_id=context.session_id)
        activity.record(cursor, workspace_id=context.workspace_id, actor_user_id=context.user_id,
                        actor_label=context.name, action="password_changed", target_user_id=context.user_id,
                        target_label=context.name)


def new_reset_code() -> str:
    """A uniformly random 6-digit code (leading zeros kept)."""
    return f"{secrets.randbelow(10 ** RESET_CODE_DIGITS):0{RESET_CODE_DIGITS}d}"


def reset_code_hash(salt: str, code: str) -> str:
    """The stored form of a reset code: SHA-256 over the row's random salt and the code."""
    return hashlib.sha256(f"{salt}:{code}".encode("utf-8")).hexdigest()


def request_password_reset(database: Database, settings: Settings, *, email: str,
                           client_ip: str) -> tuple[dict[str, Any], str | None]:
    """The answer to "forgot password", and the email to send a code to afterwards (or None).

    Only the email's format and the rate limits are checked here: whether the account exists is looked up by
    send_reset_code, which the API runs as a background task after answering. So the answer, and the time it takes,
    are the same whether or not the account exists."""
    configured = mailer.email_channel(settings) is not None
    answer = {"accepted": True, "email_delivery_configured": configured}
    try:
        email = normalize_email(email)
    except WorkspaceError:
        return answer, None
    rate_limit.check(database, "reset_request_ip", client_ip)
    rate_limit.check(database, "reset_request_account", email)
    rate_limit.record(database, "reset_request_ip", client_ip, succeeded=True)
    rate_limit.record(database, "reset_request_account", email, succeeded=True)
    return answer, (email if configured else None)


def send_reset_code(database: Database, settings: Settings, email: str) -> None:
    """Create a reset code for email and send it, if email belongs to an active member; otherwise do nothing.

    Runs after the response has been sent (api/routes/auth.py), so nothing here can change what the caller sees or
    how long it waits. A failure is logged without the address and never raised."""
    try:
        code = new_reset_code()
        salt = secrets.token_hex(16)
        with database.cursor() as cursor:
            cursor.execute(
                "SELECT u.id FROM users u JOIN team_memberships m ON m.user_id = u.id JOIN workspaces w "
                "ON w.id = m.workspace_id WHERE w.team_number = %s AND u.email = %s AND u.status = 'active' "
                "AND m.status = 'active'", (TEAM_NUMBER, email))
            row = cursor.fetchone()
            if row is None:
                return
            user_id = row[0]
            cursor.execute("UPDATE password_reset_codes SET used_at = NOW() WHERE user_id = %s AND used_at IS NULL",
                           (user_id,))
            cursor.execute("INSERT INTO password_reset_codes (user_id, code_salt, code_hash, expires_at) "
                           "VALUES (%s, %s, %s, NOW() + %s)",
                           (user_id, salt, reset_code_hash(salt, code), RESET_CODE_TTL))
        minutes = int(RESET_CODE_TTL.total_seconds() // 60)
        where = f" at {settings.public_app_url.rstrip('/')}/auth/reset" if settings.public_app_url else ""
        mailer.send(settings, to=email, subject="Your StratAI password reset code",
                    body=f"Someone asked to reset the StratAI password for {email}.\n\n"
                         f"Your code is: {code}\n\nEnter it{where} within {minutes} minutes. It works once.\n\n"
                         "If you did not ask for this, ignore this email; your password is unchanged.\n")
    except Exception as exc:  # a background task: nobody is waiting for the error
        logger.warning("password reset code not sent: %s", type(exc).__name__)


def _invalid_reset_code() -> WorkspaceError:
    return WorkspaceError(HTTPStatus.GONE, "reset_code_invalid",
                          "That code is not correct, has expired or was already used. Ask for a new code.")


def reset_password(database: Database, settings: Settings, *, email: str, code: str, new_password: str,
                   client_ip: str) -> str:
    """Set a new password with an emailed reset code, end every session the person holds, and sign them in.
    Returns the new session token."""
    rate_limit.check(database, "reset_code_ip", client_ip)
    check_password_policy(new_password)
    try:
        email = normalize_email(email)
    except WorkspaceError:
        raise _invalid_reset_code() from None
    supplied = code.strip() if isinstance(code, str) else ""
    with database.connection() as conn, conn.cursor() as cursor:
        cursor.execute(
            "SELECT c.id, c.code_salt, c.code_hash, u.id, m.id, m.workspace_id, "
            "COALESCE(m.display_name, u.full_name) FROM password_reset_codes c JOIN users u ON u.id = c.user_id "
            "JOIN team_memberships m ON m.user_id = u.id JOIN workspaces w ON w.id = m.workspace_id "
            "WHERE w.team_number = %s AND u.email = %s AND u.status = 'active' AND m.status = 'active' "
            "AND c.used_at IS NULL AND c.expires_at > NOW() AND c.failed_attempts < %s "
            "ORDER BY c.created_at DESC LIMIT 1 FOR UPDATE OF c",
            (TEAM_NUMBER, email, RESET_CODE_MAX_ATTEMPTS))
        row = cursor.fetchone()
        if row is None:
            conn.rollback()
            rate_limit.record(database, "reset_code_ip", client_ip, succeeded=False)
            raise _invalid_reset_code()
        code_id, salt, stored_hash, user_id, membership_id, workspace_id, name = row
        if not hmac.compare_digest(reset_code_hash(salt, supplied), stored_hash):
            # Kept even though the request fails: the attempt count is what stops a code being guessed.
            cursor.execute("UPDATE password_reset_codes SET failed_attempts = failed_attempts + 1 WHERE id = %s",
                           (code_id,))
            conn.commit()
            rate_limit.record(database, "reset_code_ip", client_ip, succeeded=False)
            raise _invalid_reset_code()
        cursor.execute("UPDATE password_reset_codes SET used_at = NOW() WHERE id = %s", (code_id,))
        cursor.execute("UPDATE users SET password_hash = %s, password_changed_at = NOW() WHERE id = %s",
                       (hash_password(new_password), user_id))
        revoke_user_sessions(cursor, user_id)
        activity.record(cursor, workspace_id=workspace_id, actor_user_id=user_id, actor_label=name,
                        action="password_reset_completed", target_user_id=user_id, target_label=name)
        token = create_session(cursor, membership_id, settings)
    rate_limit.clear(database, "login_account", email)
    return token


def session_summary(context: SessionContext) -> dict[str, Any]:
    """What the web app needs to know about the signed-in member."""
    return {"authenticated": True, "user": {"id": context.user_id, "name": context.name, "email": context.email},
            "workspace": {"team_number": context.team_number, "team_name": context.team_name,
                          "verification_status": context.verification_status},
            "role": context.role, "role_label": ROLE_LABELS.get(context.role, context.role),
            "permissions": sorted(context.permissions)}
