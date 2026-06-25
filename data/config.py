from __future__ import annotations

from typing import Any

from pydantic import ConfigDict, Field, PostgresDsn, field_validator
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """Application settings for the StratAI data pipeline."""

    database_url: PostgresDsn = Field(...)
    tba_api_key: str = Field(...)
    statbotics_api_key: str = Field(...)
    env: str = Field("development")

    model_config = ConfigDict(
        case_sensitive=False,
        env_file=".env",
        env_file_encoding="utf-8",
    )

    @field_validator("env")
    def validate_env(cls, value: str) -> str:
        normalized = value.strip().lower()
        if normalized not in {"development", "staging", "production"}:
            raise ValueError("ENV must be development, staging, or production")
        return normalized

    def dict(self, *args: Any, **kwargs: Any) -> dict[str, Any]:
        return super().dict(*args, **kwargs)
