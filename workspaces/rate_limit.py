"""Rate limiting for every credential check and every email-sending request.

Attempts are recorded in auth_attempts on their own connection and committed at once, never inside the caller's
transaction: a refused login raises, which rolls the caller's transaction back, and the failure must survive that
or the limit would never trip. Subjects (an IP address; a team number and email) are stored only as hashes.

Two subjects per credential check: the account (the real protection against guessing one person's password) and
the client address (against spraying many accounts). Behind the Vercel and Render proxies every request can come
from the same proxy address unless AUTH_TRUSTED_PROXY_HOPS is set, so the address limits are deliberately loose.
"""

from __future__ import annotations

import random
from dataclasses import dataclass
from datetime import timedelta
from http import HTTPStatus

from database.connection import Database
from workspaces.errors import WorkspaceError
from workspaces.tokens import subject_hash


@dataclass(frozen=True)
class Limit:
    attempts: int
    window: timedelta
    # True: every attempt counts (requests that send email). False: only failures count (credential checks).
    count_all: bool = False


LIMITS: dict[str, Limit] = {
    "login_account": Limit(5, timedelta(minutes=15)),
    "login_ip": Limit(100, timedelta(minutes=15)),
    "setup_team": Limit(5, timedelta(minutes=15)),
    "register_ip": Limit(10, timedelta(hours=1), count_all=True),
    "reset_request_account": Limit(3, timedelta(hours=1), count_all=True),
    "reset_request_ip": Limit(30, timedelta(hours=1), count_all=True),
    "token_ip": Limit(30, timedelta(minutes=15)),
    "password_check_user": Limit(5, timedelta(minutes=15)),
}
RETENTION = timedelta(days=2)
PRUNE_PROBABILITY = 0.02


def _limit(scope: str) -> Limit:
    if scope not in LIMITS:
        raise KeyError(f"unknown rate-limit scope {scope!r}")
    return LIMITS[scope]


def check(database: Database, scope: str, subject: str) -> None:
    """Raise rate_limited (429) if subject has used up scope's allowance in its window."""
    limit = _limit(scope)
    with database.cursor() as cursor:
        cursor.execute(
            "SELECT count(*) FROM auth_attempts WHERE scope = %s AND subject_hash = %s AND attempted_at > NOW() - %s"
            + ("" if limit.count_all else " AND NOT succeeded"),
            (scope, subject_hash(scope, subject), limit.window))
        used = cursor.fetchone()[0]
    if used >= limit.attempts:
        minutes = int(limit.window.total_seconds() // 60)
        raise WorkspaceError(HTTPStatus.TOO_MANY_REQUESTS, "rate_limited",
                             f"Too many attempts. Wait up to {minutes} minutes and try again.")


def record(database: Database, scope: str, subject: str, *, succeeded: bool) -> None:
    """Record one attempt, committed immediately and independently of the caller's transaction."""
    _limit(scope)
    with database.cursor() as cursor:
        cursor.execute("INSERT INTO auth_attempts (scope, subject_hash, succeeded) VALUES (%s, %s, %s)",
                       (scope, subject_hash(scope, subject), succeeded))
        if random.random() < PRUNE_PROBABILITY:
            cursor.execute("DELETE FROM auth_attempts WHERE attempted_at < NOW() - %s", (RETENTION,))


def clear(database: Database, scope: str, subject: str) -> None:
    """Forget subject's failures in scope (after a successful login, so earlier typos do not linger)."""
    with database.cursor() as cursor:
        cursor.execute("DELETE FROM auth_attempts WHERE scope = %s AND subject_hash = %s AND NOT succeeded",
                       (scope, subject_hash(scope, subject)))
