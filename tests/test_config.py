from __future__ import annotations

import os

import pytest

from data.config import Settings


@pytest.fixture(autouse=True)
def isolated_settings_env(monkeypatch):
    """Clear every Settings-backed environment variable before AND after each test.

    Settings() calls load_dotenv(), which mutates os.environ for the whole
    process and never undoes it. Any earlier Settings() call in the same pytest
    session therefore leaves the project's real .env values behind -- and in a
    full-suite run that happens during *collection*, because several modules
    evaluate `pytest.mark.skipif(not _database_available(), ...)` at import time.

    That leak used to make test_settings_allows_missing_statbotics_api_key fail
    (it cleared only STATBOTICS_API_KEY, so the leaked DATABASE_URL shadowed its
    temp .env, since load_dotenv correctly refuses to override a real env var).
    The other two tests passed only because they happened to clear all four
    variables by hand.

    The post-yield clear uses plain os.environ.pop, deliberately NOT
    monkeypatch.delenv, after a second, sibling leak that survived a first
    attempt at exactly that fix: a test whose temp .env deliberately sets an
    out-of-bounds value (e.g. TBA_TIMEOUT=0, to prove Settings rejects it)
    still runs load_dotenv() before Settings() raises, mutating os.environ
    regardless of whether construction succeeds. Calling
    monkeypatch.delenv(name) in THIS fixture's own teardown does delete it --
    but monkeypatch also records that deletion as undo-able, and monkeypatch's
    own finalizer (which runs after this fixture's teardown completes, since
    this fixture depends on monkeypatch) then "restores" the env var to
    whatever value was present the instant delenv was called here -- which is
    exactly the leaked one, since load_dotenv had already set it earlier in
    the same test. The leak silently came right back after tearing this
    fixture down, confirmed by instrumenting both fixtures directly: this
    fixture's own post-clear snapshot was empty, yet the very next test file's
    fixture saw all four bad values already present in os.environ before it
    ran a single line of its own body. Bypassing monkeypatch for this specific
    cleanup (plain dict mutation, not monkeypatch-tracked) avoids that replay
    entirely. Reproduced by running test_config.py and test_tba_client.py
    together in one pytest invocation.

    Driven by Settings.model_fields rather than a hardcoded list, so a new
    setting cannot silently reintroduce either leak.
    """
    for field_name in Settings.model_fields:
        monkeypatch.delenv(field_name.upper(), raising=False)
    yield
    for field_name in Settings.model_fields:
        os.environ.pop(field_name.upper(), None)


def test_settings_loads_from_environment(tmp_path, monkeypatch):
    env_path = tmp_path / ".env"
    env_path.write_text(
        "DATABASE_URL=postgresql://user:pass@localhost:5432/testdb\n"
        "TBA_API_KEY=test-key\n"
        "STATBOTICS_API_KEY=test-key\n"
        "ENV=development\n"
    )

    monkeypatch.chdir(tmp_path)
    settings = Settings()

    assert str(settings.database_url) == "postgresql://user:pass@localhost:5432/testdb"
    assert settings.tba_api_key == "test-key"
    assert settings.statbotics_api_key == "test-key"
    assert settings.env == "development"


def test_settings_allows_missing_statbotics_api_key(tmp_path, monkeypatch):
    env_path = tmp_path / ".env"
    env_path.write_text(
        "DATABASE_URL=postgresql://user:pass@localhost:5432/testdb\n"
        "TBA_API_KEY=test-key\n"
        "ENV=development\n"
    )

    monkeypatch.chdir(tmp_path)
    settings = Settings()

    assert str(settings.database_url) == "postgresql://user:pass@localhost:5432/testdb"
    assert settings.tba_api_key == "test-key"
    assert settings.statbotics_api_key is None
    assert settings.env == "development"


def test_settings_reject_invalid_env(tmp_path, monkeypatch):
    env_path = tmp_path / ".env"
    env_path.write_text(
        "DATABASE_URL=postgresql://user:pass@localhost:5432/testdb\n"
        "TBA_API_KEY=test-key\n"
        "STATBOTICS_API_KEY=test-key\n"
        "ENV=invalid\n"
    )

    monkeypatch.chdir(tmp_path)
    with pytest.raises(ValueError, match="ENV must be development, staging, or production"):
        Settings()


# ---------------------------------------------------------------------------
# Retry/timeout boundaries (found during a system-wide audit: TBA_MAX_RETRIES=0
# previously reached request_with_retries and silently made zero HTTP
# requests before raising a generic RuntimeError; rejected here instead, at
# the config boundary, with a clear pydantic error).
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("field,value", [
    ("TBA_MAX_RETRIES", "0"), ("STATBOTICS_MAX_RETRIES", "0"),
    ("TBA_MAX_RETRIES", "-1"), ("TBA_TIMEOUT", "0"), ("TBA_TIMEOUT", "-5"),
    ("TBA_BACKOFF_FACTOR", "-0.1"),
])
def test_settings_rejects_a_non_positive_retry_or_timeout_value(tmp_path, monkeypatch, field, value):
    env_path = tmp_path / ".env"
    env_path.write_text(
        "DATABASE_URL=postgresql://user:pass@localhost:5432/testdb\n"
        "TBA_API_KEY=test-key\n"
        f"{field}={value}\n"
    )
    monkeypatch.chdir(tmp_path)
    with pytest.raises(ValueError):
        Settings()


def test_settings_allows_zero_backoff_factor(tmp_path, monkeypatch):
    # 0 is a legitimate choice (retry immediately, no exponential wait) --
    # only a negative backoff is nonsensical.
    env_path = tmp_path / ".env"
    env_path.write_text(
        "DATABASE_URL=postgresql://user:pass@localhost:5432/testdb\n"
        "TBA_API_KEY=test-key\n"
        "TBA_BACKOFF_FACTOR=0\n"
    )
    monkeypatch.chdir(tmp_path)
    assert Settings().tba_backoff_factor == 0
