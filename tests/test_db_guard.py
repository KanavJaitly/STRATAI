"""Regression tests for the test-database safety guard (tests/db_guard.py).

None of these connects anywhere: refused connections are refused before a socket opens. The subprocess runs point
DATABASE_URL at an unroutable host (127.0.0.1, port 1), so even a broken guard could not reach a real database.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import psycopg
import pytest

from tests import db_guard

ROOT = Path(__file__).resolve().parents[1]
UNREACHABLE = "postgresql://guard:guard@127.0.0.1:1/{name}"


@pytest.mark.parametrize("name", ["stratai_test", "stratai_test_ci", "stratai_test_p5_frontend"])
def test_isolated_test_copies_are_allowed(name):
    assert db_guard.is_allowed_test_database(name)
    db_guard.check_database(UNREACHABLE.format(name=name), "test")


@pytest.mark.parametrize("name", [
    "stratai",  # the serving database
    "postgres", "template1", "testdb", "",
    "stratai_testing", "stratai_test_", "stratai_test-ci", "STRATAI_TEST", "stratai_p5_m6_verification",
    "stratai_p5_replay_debug", "xstratai_test", "stratai_test;drop",
])
def test_everything_else_is_refused(name):
    assert not db_guard.is_allowed_test_database(name)
    with pytest.raises(db_guard.TestDatabaseRefused, match="isolated stratai_"):
        db_guard.check_database(UNREACHABLE.format(name=name), "test")


def test_the_serving_database_is_named_in_the_refusal():
    for conninfo in (UNREACHABLE.format(name="stratai"), "host=127.0.0.1 port=1 dbname=stratai user=guard",
                     "postgresql://guard@127.0.0.1:1/stratai?sslmode=disable&connect_timeout=1"):
        with pytest.raises(db_guard.TestDatabaseRefused, match="the SERVING database"):
            db_guard.check_database(conninfo, "test")


def test_a_url_naming_no_database_is_refused():
    assert not db_guard.is_allowed_test_database(db_guard.database_name("postgresql://guard@127.0.0.1:1"))


def test_the_connection_guard_is_active_and_refuses_before_any_socket(monkeypatch):
    """Installed for the whole session by tests/conftest.py: both connect entry points refuse the serving database."""
    monkeypatch.setattr(db_guard, "refusals", [])  # these deliberate refusals must not fail the session
    for connect in (psycopg.connect, psycopg.Connection.connect):
        with pytest.raises(db_guard.TestDatabaseRefused, match="the SERVING database"):
            connect(UNREACHABLE.format(name="stratai"), connect_timeout=1)
    with pytest.raises(db_guard.TestDatabaseRefused):
        psycopg.connect("host=127.0.0.1 port=1 user=guard", dbname="stratai")
    assert len(db_guard.refusals) == 3


def test_the_connection_guard_lets_an_isolated_copy_through(monkeypatch):
    monkeypatch.setattr(db_guard, "refusals", [])
    with pytest.raises(psycopg.OperationalError):  # reached the (unroutable) server: not refused by the guard
        psycopg.connect(UNREACHABLE.format(name="stratai_test"), connect_timeout=1)
    assert db_guard.refusals == []


def _pytest_in_subprocess(database_url: str, *targets: str) -> subprocess.CompletedProcess:
    env = {**os.environ, "DATABASE_URL": database_url, "PYTHONDONTWRITEBYTECODE": "1"}
    return subprocess.run([sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", *targets],
                          cwd=ROOT, env=env, capture_output=True, text=True, timeout=120)


def test_a_session_pointed_at_the_serving_database_stops_before_any_test_runs():
    """The guard runs before collection: no module is imported for testing, no fixture migrates, nothing runs."""
    run = _pytest_in_subprocess(UNREACHABLE.format(name="stratai"), "tests/test_db_guard.py::test_canary")
    output = run.stdout + run.stderr
    assert run.returncode == pytest.ExitCode.USAGE_ERROR, output
    assert "refusing the SERVING database" in output and "isolated stratai_*" in output
    assert "passed" not in output


def test_a_session_pointed_at_an_isolated_copy_runs():
    run = _pytest_in_subprocess(UNREACHABLE.format(name="stratai_test"), "tests/test_db_guard.py::test_canary")
    assert run.returncode == 0, run.stdout + run.stderr


def test_canary():
    """Collected only to show a session got past the guard."""
