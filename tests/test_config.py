from __future__ import annotations

import pytest

from data.config import Settings


@pytest.fixture(autouse=True)
def isolated_settings_env(monkeypatch):
    """Clear every Settings-backed environment variable before each test.

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

    Driven by Settings.model_fields rather than a hardcoded list, so a new
    setting cannot silently reintroduce the same leak.
    """
    for field_name in Settings.model_fields:
        monkeypatch.delenv(field_name.upper(), raising=False)


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
