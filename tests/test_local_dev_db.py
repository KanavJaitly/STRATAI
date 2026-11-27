"""The local development database's safety rules (audit 2026-11-26, workstream 6; scripts/local_dev_db.py).

Pure checks, no database: what the scripts may touch, and that tests can never run against the development copy.
"""

from __future__ import annotations

import pytest

from scripts import local_dev_db, local_test_env
from tests.db_guard import is_allowed_test_database


def test_the_development_copy_is_never_the_serving_database_or_its_source():
    assert local_dev_db.DEV_DATABASE == "stratai_dev_fresh"
    assert local_dev_db.DEV_DATABASE not in local_dev_db.PROTECTED
    assert {"stratai", "stratai_test"} <= local_dev_db.PROTECTED
    assert local_dev_db.SOURCE_DATABASE == "stratai_test"


def test_tests_can_never_run_against_the_development_copy():
    assert not is_allowed_test_database(local_dev_db.DEV_DATABASE)
    assert not is_allowed_test_database("stratai")


def test_the_local_api_serves_the_development_copy_by_default_and_nothing_unlisted():
    assert local_test_env.DEV_DATABASE == local_dev_db.DEV_DATABASE
    assert local_test_env.environment.__defaults__ == (local_dev_db.DEV_DATABASE,)
    for refused in ("stratai", "stratai_dev", "postgres"):
        with pytest.raises(SystemExit):
            local_test_env.environment(refused)


def test_local_sign_up_codes_apply_to_the_development_copy_only_and_yield_to_the_environment(monkeypatch):
    for key in local_test_env.DEV_SIGNUP:
        monkeypatch.delenv(key, raising=False)
    dev = local_test_env.environment(local_dev_db.DEV_DATABASE)
    assert dev["TEAM_JOIN_CODE"] == "local-dev-join" and dev["ACCESS_POLICY"] == "members"
    assert "TEAM_JOIN_CODE" not in local_test_env.environment("stratai_test")
    monkeypatch.setenv("TEAM_JOIN_CODE", "my-own-code")
    assert "TEAM_JOIN_CODE" not in local_test_env.environment(local_dev_db.DEV_DATABASE)  # the set value is kept
