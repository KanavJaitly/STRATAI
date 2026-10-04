"""Session-wide test setup: the test-database safety guard (tests/db_guard.py).

pytest_configure runs before collection, so the guard is in place before any test module connects at import time,
applies migrations, or writes.
"""

from __future__ import annotations

import pytest

from tests import db_guard


def pytest_configure(config: pytest.Config) -> None:
    try:
        db_guard.check_session_database()
    except db_guard.TestDatabaseRefused as refused:
        raise pytest.UsageError(str(refused)) from None
    config._stratai_undo_db_guard = db_guard.install_connection_guard()  # type: ignore[attr-defined]


def pytest_sessionfinish(session: pytest.Session, exitstatus: int) -> None:
    if db_guard.refusals:  # a refused connection must never pass as a skip
        reporter = session.config.pluginmanager.get_plugin("terminalreporter")
        if reporter is not None:
            reporter.write_line("")
            for message in sorted(set(db_guard.refusals)):
                reporter.write_line(message, red=True)
        session.exitstatus = pytest.ExitCode.TESTS_FAILED


def pytest_unconfigure(config: pytest.Config) -> None:
    undo = getattr(config, "_stratai_undo_db_guard", None)
    if undo is not None:
        undo()
