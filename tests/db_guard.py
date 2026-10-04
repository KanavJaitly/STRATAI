"""The test-database safety guard: database-backed tests run only against an isolated test copy.

**Why.** On 2026-10-04 a contract-test run resolved `DATABASE_URL` from `.env` to the serving database `stratai`, and
a fixture's `run_migrations` applied migration 0010 there (.agent/phase5/INCIDENT_2026-10-04_0010_on_serving.md).
Kanav approved this guard as a permanent engineering invariant.

**The rule.** A test session may use only `stratai_test` or an isolated `stratai_test_<suffix>` copy (made by
`python -m scripts.phase5_isolated_db --name ...`). Every other database is refused, the serving `stratai` above all.

**Two layers, both installed by tests/conftest.py before collection** (so before any test module connects, migrates
or writes):
1. **Session check** (`check_session_database`): the URL every test resolves, i.e. `DATABASE_URL` from the
   environment, else `.env`, exactly as `data.config.Settings` loads it. A non-isolated database stops the session
   with a usage error. No database configured at all is allowed: the database-backed tests then skip.
2. **Connection guard** (`install_connection_guard`): `psycopg.connect` refuses a non-isolated database before
   opening a socket, whatever URL a test builds later. Many tests probe availability inside `except Exception`, so a
   refusal is also recorded. tests/conftest.py fails the session if any was recorded, so a refusal can never turn
   into a silent skip.

There is deliberately no environment-variable or flag bypass.
"""

from __future__ import annotations

import os
import re
from collections.abc import Callable
from typing import Any

ALLOWED_TEST_DATABASE = re.compile(r"^stratai_test(?:_[a-z0-9]+(?:_[a-z0-9]+)*)?$")
SERVING_DATABASE = "stratai"
HELP = ("Tests must target an isolated stratai_* test database (stratai_test or stratai_test_<suffix>), never the "
        "serving database. Export it first, e.g.\n"
        "  export DATABASE_URL=$(python -m scripts.phase5_isolated_db --name stratai_test --print-url-env)")


class TestDatabaseRefused(RuntimeError):
    """A test tried to use a database that is not an isolated test copy."""

    __test__ = False  # not a pytest test class


def database_name(conninfo: str) -> str | None:
    """The database a URL or key=value conninfo names (None when it names none)."""
    from psycopg.conninfo import conninfo_to_dict

    try:
        params = conninfo_to_dict(conninfo)
    except Exception:
        return None
    name = params.get("dbname")
    return None if name is None else str(name)


def is_allowed_test_database(name: str | None) -> bool:
    return name is not None and bool(ALLOWED_TEST_DATABASE.fullmatch(name))


def refusal_message(name: str | None, where: str) -> str:
    what = "the SERVING database" if name == SERVING_DATABASE else f"database {name!r}"
    return f"STRATAI test-database guard ({where}): refusing {what}. {HELP}"


def check_database(conninfo: str, where: str) -> None:
    name = database_name(conninfo)
    if not is_allowed_test_database(name):
        raise TestDatabaseRefused(refusal_message(name, where))


def resolved_test_database_url() -> str | None:
    """The URL a test's Settings() resolves: the environment wins, else the project's .env."""
    from data.config import _ensure_env_loaded

    _ensure_env_loaded()
    return os.environ.get("DATABASE_URL") or None


session_database_url: str | None = None  # the isolated URL the session check accepted


def check_session_database() -> None:
    global session_database_url
    url = resolved_test_database_url()
    if url is not None:
        check_database(url, "session start")
    session_database_url = url


refusals: list[str] = []


def install_connection_guard() -> Callable[[], None]:
    """Wrap psycopg's connect so a non-isolated database is refused before any socket opens. Returns an undo."""
    import psycopg

    original_function, original_method = psycopg.connect, psycopg.Connection.connect.__func__

    def _check(conninfo: str, kwargs: dict[str, Any]) -> None:
        target = kwargs.get("dbname")
        name = str(target) if target is not None else database_name(str(conninfo))
        if not is_allowed_test_database(name):
            message = refusal_message(name, "connection")
            refusals.append(message)
            raise TestDatabaseRefused(message)

    def guarded_connect(conninfo: str = "", *args: Any, **kwargs: Any):
        _check(conninfo, kwargs)
        return original_function(conninfo, *args, **kwargs)

    def guarded_method(cls, conninfo: str = "", *args: Any, **kwargs: Any):
        _check(conninfo, kwargs)
        return original_method(cls, conninfo, *args, **kwargs)

    psycopg.connect = guarded_connect
    psycopg.Connection.connect = classmethod(guarded_method)

    def undo() -> None:
        psycopg.connect = original_function
        psycopg.Connection.connect = classmethod(original_method)

    return undo
