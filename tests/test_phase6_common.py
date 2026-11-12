"""The database guards in scripts/phase6_common.py (no database is connected to; refusals happen first, and accepted
targets reach a stub).

- `isolated_database()` (Phase 6): tests/db_guard.py's naming rule, so the bare `stratai_test` and its suffixed
  copies pass, and look-alikes such as `stratai_testing` are refused.
- `strict_isolated_database()` (P11 tools: E5, the Phase 11 replay): database/target_guard.py's rule, so only a local
  `stratai_test_<suffix>` passes, and the server must confirm it.
"""

from __future__ import annotations

import pytest

import scripts.phase6_common as common

URL = "postgresql://postgres@localhost:5432/{name}"


class _Stub:
    """Stands in for ReadOnlySessionDatabase; `server` is what the server reports for current_database()."""

    def __init__(self, server: str) -> None:
        self.server, self.closed = server, False

    def cursor(self):
        stub = self

        class _Cursor:
            def __enter__(self):
                return self

            def __exit__(self, *exc):
                return False

            def execute(self, sql, params=None):
                pass

            def fetchone(self):
                return (stub.server, "127.0.0.1/32", "18.6")

        return _Cursor()

    def close(self) -> None:
        self.closed = True


def _no_connection(*args, **kwargs):
    raise AssertionError("connected before the target check")


@pytest.mark.parametrize("name", ["stratai_test", "stratai_test_p11a", "stratai_test_2023", "stratai_test_p6m12"])
def test_isolated_database_keeps_accepting_the_phase6_copies(monkeypatch, name):
    import database.readonly as readonly

    monkeypatch.setenv("DATABASE_URL", URL.format(name=name))
    monkeypatch.setattr(readonly, "ReadOnlySessionDatabase", lambda config: "session")
    assert common.isolated_database() == "session"


@pytest.mark.parametrize("name", ["stratai", "stratai_testing", "stratai_test2027", "stratai_test_",
                                  "stratai_test-ci", "stratai_p5_replay_debug", "postgres"])
def test_isolated_database_refuses_look_alikes_that_startswith_accepted(monkeypatch, name):
    import database.readonly as readonly

    monkeypatch.setenv("DATABASE_URL", URL.format(name=name))
    monkeypatch.setattr(readonly, "ReadOnlySessionDatabase", _no_connection)
    with pytest.raises(SystemExit, match="refusing database"):
        common.isolated_database()


@pytest.mark.parametrize("name, code", [("stratai_test", "not_a_test_database"), ("stratai", "serving_database"),
                                        ("stratai_testing", "not_a_test_database")])
def test_strict_isolated_database_refuses_the_bare_copy_before_connecting(monkeypatch, name, code):
    monkeypatch.setenv("DATABASE_URL", URL.format(name=name))
    monkeypatch.setattr(common, "isolated_database", _no_connection)
    with pytest.raises(SystemExit, match=code):
        common.strict_isolated_database()


def test_strict_isolated_database_refuses_a_remote_host(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgresql://u@db.example.org:5432/stratai_test_p11a")
    monkeypatch.setattr(common, "isolated_database", _no_connection)
    with pytest.raises(SystemExit, match="remote_host"):
        common.strict_isolated_database()


def test_strict_isolated_database_accepts_a_suffixed_copy_the_server_confirms(monkeypatch):
    stub = _Stub("stratai_test_p11a")
    monkeypatch.setenv("DATABASE_URL", URL.format(name="stratai_test_p11a"))
    monkeypatch.setattr(common, "isolated_database", lambda: stub)
    assert common.strict_isolated_database() is stub and not stub.closed


def test_strict_isolated_database_refuses_and_closes_when_the_server_disagrees(monkeypatch):
    stub = _Stub("stratai_test")  # e.g. a URL alias that lands on the bare copy
    monkeypatch.setenv("DATABASE_URL", URL.format(name="stratai_test_p11a"))
    monkeypatch.setattr(common, "isolated_database", lambda: stub)
    with pytest.raises(SystemExit, match="server_mismatch"):
        common.strict_isolated_database()
    assert stub.closed


def test_the_phase11_replay_refuses_the_bare_stratai_test_before_connecting(monkeypatch):
    from scripts import phase11_replay

    monkeypatch.setenv("DATABASE_URL", URL.format(name="stratai_test"))
    monkeypatch.setattr(common, "isolated_database", _no_connection)
    with pytest.raises(SystemExit, match="not_a_test_database"):
        phase11_replay.main(["--budget-minutes", "1"])
