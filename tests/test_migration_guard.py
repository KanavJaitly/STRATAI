"""The migration runner's and the P11A preflight's target guard (database/target_guard.py, database/migrate.py).

No database is used: every refusal must happen before any connection (psycopg.connect is replaced by a failure),
and the server-identity check and the history planner are exercised with fakes and the real migration files.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from database import migrate
from database.target_guard import Target, TargetRefused, check_target, verify_server

LOCAL = "postgresql://tester@localhost:5432/stratai_test_p11a_20261107"
FILES = sorted((Path(migrate.__file__).parent / "migrations").glob("*.sql"))
NAMES = [f.name for f in FILES]


@pytest.fixture
def no_connection(monkeypatch):
    import psycopg

    def refuse(*args, **kwargs):
        raise AssertionError("a connection was attempted")

    monkeypatch.setattr(psycopg, "connect", refuse)


@pytest.mark.parametrize("url,code", [
    ("postgresql://u:p@dpg-abc123-a.oregon-postgres.render.com:5432/stratai_test_x", "remote_host"),
    ("postgresql://u@dpg-abc123-a.oregon-postgres.render.com/stratai", "remote_host"),
    ("postgresql://u@db.example.org:5432/stratai_test_x", "remote_host"),
    ("postgresql://u@192.168.1.20:5432/stratai_test_x", "remote_host"),
    ("postgresql://u@localhost,db.example.org/stratai_test_x", "remote_host"),
    ("host=localhost hostaddr=10.0.0.5 dbname=stratai_test_x", "remote_host"),
    ("postgresql://u@localhost:5432/stratai", "serving_database"),
    ("postgresql://u@localhost:5432/stratai_test", "not_a_test_database"),
    ("postgresql://u@localhost:5432/stratai_dev", "not_a_test_database"),
    ("postgresql://u@localhost:5432/postgres", "not_a_test_database"),
    ("postgresql://u@localhost:5432/Stratai_Test_X", "not_a_test_database"),
    ("postgresql://u@localhost:5432/", "database_not_named"),
    ("service=stratai", "service_file"),
])
def test_refused_targets_are_refused_before_any_connection(url, code, no_connection):
    with pytest.raises(TargetRefused) as refused:
        check_target(url, environ={})
    assert refused.value.code == code
    assert "p@" not in refused.value.message  # never echoes credentials


@pytest.mark.parametrize("url", [
    LOCAL,
    "postgresql://tester@127.0.0.1:5432/stratai_test_p11a",
    "postgresql://tester@[::1]:5432/stratai_test_p11a",
    "host=/tmp dbname=stratai_test_p11a_20261107 user=tester",
    "dbname=stratai_test_a_b user=tester",
])
def test_local_test_databases_are_accepted(url, no_connection):
    target = check_target(url, environ={})
    assert target.dbname.startswith("stratai_test_")
    assert "password" not in json.dumps(target.describe())


def test_environment_defaults_libpq_would_use_are_checked_too(no_connection):
    url = "postgresql:///stratai_test_p11a"  # no host: libpq would take PGHOST
    with pytest.raises(TargetRefused):
        check_target(url, environ={"PGHOST": "dpg-x.oregon-postgres.render.com"})
    with pytest.raises(TargetRefused):
        check_target(url, environ={"PGHOSTADDR": "10.1.2.3"})
    with pytest.raises(TargetRefused):
        check_target(url, environ={"PGSERVICE": "prod"})
    assert check_target(url, environ={"PGHOST": "/tmp"}).dbname == "stratai_test_p11a"


class FakeCursor:
    def __init__(self, row):
        self.row = row

    def execute(self, sql, params=()):
        pass

    def fetchone(self):
        return self.row


def test_the_server_must_confirm_the_database_and_a_local_address():
    target = check_target(LOCAL, environ={})
    assert verify_server(FakeCursor(("stratai_test_p11a_20261107", None, "18.6")), target)["server_address"] == \
        "unix socket"
    assert verify_server(FakeCursor(("stratai_test_p11a_20261107", "127.0.0.1/32", "18.6")), target)
    assert verify_server(FakeCursor(("stratai_test_p11a_20261107", "::1/128", "18.6")), target)
    with pytest.raises(TargetRefused) as refused:
        verify_server(FakeCursor(("stratai", None, "18.6")), target)
    assert refused.value.code == "server_mismatch"
    with pytest.raises(TargetRefused) as refused:  # e.g. a tunnel to a remote server
        verify_server(FakeCursor(("stratai_test_p11a_20261107", "35.80.1.2/32", "17.2")), target)
    assert refused.value.code == "remote_host"


# --- the history planner (the real migration files) -----------------------------------------------------------------


def test_a_fresh_empty_database_gets_every_migration():
    assert migrate.plan_pending(FILES, None, 0) == tuple(NAMES)


def test_a_restored_copy_through_0012_has_only_0013_pending():
    assert migrate.plan_pending(FILES, NAMES[:12], 40) == (NAMES[12],)
    assert migrate.plan_pending(FILES, NAMES, 40) == ()


def test_missing_history_on_a_populated_database_is_refused():
    with pytest.raises(migrate.MigrationRefused) as refused:
        migrate.plan_pending(FILES, None, 25)
    assert refused.value.code == "missing_history"


def test_an_incomplete_or_foreign_history_is_refused():
    gap = NAMES[:4] + NAMES[5:12]  # 0005 missing
    with pytest.raises(migrate.MigrationRefused) as refused:
        migrate.plan_pending(FILES, gap, 25)
    assert refused.value.code == "incomplete_history" and NAMES[4] in refused.value.message
    with pytest.raises(migrate.MigrationRefused) as refused:
        migrate.plan_pending(FILES, NAMES[:12] + ["9999_from_another_branch.sql"], 25)
    assert refused.value.code == "unknown_history"


def test_a_destructive_pending_migration_on_a_populated_database_is_refused():
    assert migrate.destructive(FILES[4].read_text())  # 0005 drops teams, match_teams, team_event_stats
    assert not migrate.destructive(FILES[12].read_text())  # 0013 drops only a trigger and a constraint
    assert not migrate.destructive("-- DELETE FROM x in a comment\nCREATE TABLE t (id int);")
    with pytest.raises(migrate.MigrationRefused) as refused:
        migrate.plan_pending(FILES, NAMES[:4], 10)
    assert refused.value.code == "destructive_pending"


# --- the command line and run_migrations -------------------------------------------------------------------------------


def _env(monkeypatch, url):
    monkeypatch.setenv("DATABASE_URL", url)
    monkeypatch.setenv("TBA_API_KEY", "unused")


@pytest.mark.parametrize("url", ["postgresql://u@dpg-x.oregon-postgres.render.com/stratai",
                                 "postgresql://u@localhost/stratai", "postgresql://u@localhost/stratai_test"])
def test_the_cli_and_run_migrations_refuse_before_connecting(url, monkeypatch, no_connection, capsys):
    from data.config import Settings

    _env(monkeypatch, url)
    for argv in ([], ["--apply", "--confirm-database", "stratai"]):
        assert migrate.main(argv) == 2
        assert json.loads(capsys.readouterr().out)["status"] == "refused"
    with pytest.raises(TargetRefused):
        migrate.run_migrations(Settings())


def test_apply_needs_the_exact_database_name(monkeypatch, no_connection, capsys):
    _env(monkeypatch, LOCAL)
    for argv in (["--apply"], ["--apply", "--confirm-database", "stratai_test_other"]):
        assert migrate.main(argv) == 2
        out = json.loads(capsys.readouterr().out)
        assert out["code"] == "not_confirmed"


def test_init_db_is_the_same_guarded_command_line():
    source = (Path(migrate.__file__).parent / "init_db.py").read_text()
    assert "sys.exit(main())" in source


# --- the P11A preflight ------------------------------------------------------------------------------------------------


@pytest.mark.parametrize("url", ["postgresql://u@localhost/stratai", "postgresql://u@localhost/stratai_test",
                                 "postgresql://u@dpg-x.oregon-postgres.render.com/stratai_test_x",
                                 "postgresql://u@localhost/stratai_dev"])
def test_the_preflight_refuses_with_the_same_guard(url, no_connection, capsys):
    from scripts.p11a_db_preflight import refuse_unless_isolated

    with pytest.raises(SystemExit) as refused:
        refuse_unless_isolated(url)
    assert refused.value.code == 2 and json.loads(capsys.readouterr().out)["status"] == "refused"


def test_the_preflight_flags_missing_history_and_pending_migrations():
    from scripts.p11a_db_preflight import problems_of

    base = {"transaction_read_only": "on", "migration_problem": None, "migrations_pending": [], "data_tables_missing": [],
            "seasons": {2024: {"played_with_breakdown": 5}, 2025: {"played_with_breakdown": 0},
                        2026: {"played_with_breakdown": 0}, 2027: {}}, "live_draft_tables": 2}
    assert problems_of(base) == []
    assert any("missing_history" in p for p in problems_of({**base, "migration_problem": "missing_history: x"}))
    assert any("pending" in p for p in problems_of({**base, "migrations_pending": [NAMES[12]]}))
    assert problems_of({**base, "seasons": {**base["seasons"], 2027: {"events": 1}}})
    assert isinstance(Target(("",), "5432", "stratai_test_x", None).describe(), dict)
