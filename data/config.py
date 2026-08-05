from __future__ import annotations

from pathlib import Path
from typing import Any

from dotenv import load_dotenv
from pydantic import ConfigDict, Field, PostgresDsn, field_validator
from pydantic_settings import BaseSettings


PROJECT_ROOT = Path(__file__).resolve().parents[1]
ENV_FILE_CANDIDATES = (
    Path(".env"),
    PROJECT_ROOT / ".env",
)


def _ensure_env_loaded() -> None:
    for env_file in ENV_FILE_CANDIDATES:
        if env_file.exists():
            load_dotenv(env_file)
            break


class Settings(BaseSettings):
    """Application settings for the StratAI data pipeline."""

    database_url: PostgresDsn
    tba_api_key: str
    statbotics_api_key: str | None = None
    tba_timeout: float = Field(default=10.0, gt=0)
    # ge=1, not ge=0: request_with_retries treats this as a total attempt
    # count (range(1, max_retries + 1)), so 0 would make zero HTTP requests
    # and fall straight through to a generic RuntimeError -- found during a
    # system-wide audit. Caught here, at the config boundary, with a clear
    # pydantic error instead of a confusing one deep in a retry loop.
    tba_max_retries: int = Field(default=3, ge=1)
    tba_backoff_factor: float = Field(default=0.5, ge=0)
    statbotics_timeout: float = Field(default=10.0, gt=0)
    statbotics_max_retries: int = Field(default=3, ge=1)
    statbotics_backoff_factor: float = Field(default=0.5, ge=0)
    env: str = "development"

    model_config = ConfigDict(
        case_sensitive=False,
    )

    def __init__(self, **values: Any) -> None:
        _ensure_env_loaded()
        super().__init__(**values)

    @field_validator("env")
    def validate_env(cls, value: str) -> str:
        normalized = value.strip().lower()
        if normalized not in {"development", "staging", "production"}:
            raise ValueError("ENV must be development, staging, or production")
        return normalized
