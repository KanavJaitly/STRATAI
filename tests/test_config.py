from __future__ import annotations

import pytest

from data.config import Settings


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
