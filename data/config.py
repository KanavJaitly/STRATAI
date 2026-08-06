from __future__ import annotations

from pathlib import Path
from typing import Annotated, Any

from dotenv import load_dotenv
from pydantic import ConfigDict, Field, PostgresDsn, field_validator, model_validator
from pydantic_settings import BaseSettings, NoDecode


PROJECT_ROOT = Path(__file__).resolve().parents[1]
ENV_FILE_CANDIDATES = (
    Path(".env"),
    PROJECT_ROOT / ".env",
)

# Dev-server origins the future React frontend is most likely to run on (Vite and
# Create React App / Next defaults). A guess, deliberately: no frontend exists yet
# (Phase 3 Milestone 12 is the API foundation, the frontend is a later phase). It is
# a guess in the safe direction -- two explicit localhost origins rather than "*" --
# and any real deployment overrides it via the CORS_ORIGINS environment variable.
DEFAULT_CORS_ORIGINS = ("http://localhost:5173", "http://localhost:3000")

CORS_WILDCARD_ORIGIN = "*"


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

    # --- API layer (Phase 3 Milestone 12) -------------------------------------
    # These live on the same Settings object the pipeline already uses rather
    # than in a parallel api/config.py: one env/.env resolution mechanism, one
    # place to look, and api.app.create_app() constructs Settings() exactly the
    # way data/orchestrator.py's CLI entry point does.
    #
    # 127.0.0.1, not 0.0.0.0: a local `python -m api` should not silently expose
    # the API to every host on the network. Deployments set API_HOST explicitly.
    api_host: str = "127.0.0.1"
    api_port: int = Field(default=8000, ge=1, le=65535)
    # Empty by default so routes are mounted at exactly the paths the milestone
    # docs write them at (Milestone 13's is /teams/{team_number}/events/{event_key}/metrics).
    # Set API_PREFIX when mounting behind a gateway that expects, say, /api/v1.
    api_prefix: str = ""
    # NoDecode is required, not decorative: pydantic-settings treats a list[str]
    # field as complex and JSON-decodes the environment value *before* any
    # validator runs, so a plain comma-separated CORS_ORIGINS raises a
    # SettingsError that parse_cors_origins below would never get to see.
    # NoDecode hands the raw string to the validator instead.
    cors_origins: Annotated[list[str], NoDecode] = Field(
        default_factory=lambda: list(DEFAULT_CORS_ORIGINS)
    )

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

    @field_validator("api_prefix")
    def validate_api_prefix(cls, value: str) -> str:
        """Normalize the prefix to either "" or a leading-slash, no-trailing-slash path."""
        normalized = value.strip().rstrip("/")
        if not normalized:
            return ""
        if not normalized.startswith("/"):
            normalized = f"/{normalized}"
        return normalized

    @field_validator("cors_origins", mode="before")
    def parse_cors_origins(cls, value: Any) -> Any:
        """Accept a comma-separated string so CORS_ORIGINS reads naturally in a .env file.

        pydantic-settings parses a bare list[str] field from the environment as
        JSON, which would force CORS_ORIGINS='["http://localhost:5173"]'. Splitting
        a plain comma-separated string here keeps the env format ordinary while the
        parsed value stays a real list.
        """
        if isinstance(value, str):
            return [origin.strip() for origin in value.split(",") if origin.strip()]
        return value

    @model_validator(mode="after")
    def reject_wildcard_cors_in_production(self) -> "Settings":
        """Refuse an allow-all CORS policy when ENV=production.

        Structural, not conventional: "never ship allow-all origins" is the kind of
        rule that survives exactly as long as everyone remembers it, so it is
        enforced at the config boundary instead -- the same reasoning that put
        Field(ge=1) on the retry counts. A wildcard remains available in
        development and staging, where it is a convenience rather than a hole.
        """
        if self.env == "production" and CORS_WILDCARD_ORIGIN in self.cors_origins:
            raise ValueError(
                "CORS_ORIGINS must not contain '*' when ENV=production; "
                "list the frontend's real origins explicitly"
            )
        return self
