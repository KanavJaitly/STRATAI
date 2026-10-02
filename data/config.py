from __future__ import annotations

from pathlib import Path
from typing import Annotated, Literal, Any

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

    # --- ML layer (Phase 4 Milestone 12) --------------------------------------
    # Same rationale as the API fields above: one Settings object, one place to
    # look. version_tag fields default to None -- "nothing pinned" -- which is
    # this project's actual current state (M4-M7's real, dated backtest numbers
    # are blocked on a Statbotics outage; no model has been accepted for
    # production serving yet). An operator sets these once a real model is
    # registered and accepted, at which point api.app.create_app loads it once
    # at startup; until then, every prediction endpoint correctly reports
    # model_not_loaded rather than serving from an unaccepted model by default.
    ml_registry_dir: str = str(PROJECT_ROOT / "ml_registry")
    # Which model types may be served (2026-10-02). Each is a single-value Literal: the
    # evaluated D18 model of record. M5 v1 ("ranking_xgb", FAILED) and raw M6 without
    # its evaluated calibrator ("win_prob_xgb") are not servable, so the API can never
    # fall back to them; serving a different model requires changing this code-level
    # allow-list and the pins below, i.e. an explicit configuration change.
    ml_ranking_model_type: Literal["ranking_xgb_v2"] = "ranking_xgb_v2"
    ml_ranking_model_version_tag: str | None = None
    ml_ranking_model_sha256: str | None = None
    ml_win_prob_model_type: Literal["win_prob_xgb_calibrated"] = "win_prob_xgb_calibrated"
    ml_win_prob_model_version_tag: str | None = None
    ml_win_prob_model_sha256: str | None = None
    # EPA source for Phase 4 features (ml.ratings.provider). The default is the evaluated
    # production configuration, D18: Statbotics primary from a verified snapshot
    # (STATBOTICS_SNAPSHOT_DIR), STRATAI fallback for 2026iscmp only (STRATAI_EPA_CHAIN).
    # Unconfigured, it fails loudly rather than silently using another source.
    # "stratai" (D15, historical) and "statbotics" (plain D13 over team_event_stats, no
    # availability rule or fallback) remain selectable as non-evaluated references.
    epa_source: Literal["d18_statbotics_primary", "stratai", "statbotics"] = "d18_statbotics_primary"
    stratai_epa_chain: str | None = None
    statbotics_snapshot_dir: str | None = None

    model_config = ConfigDict(
        case_sensitive=False,
    )

    def __init__(self, **values: Any) -> None:
        _ensure_env_loaded()
        super().__init__(**values)

    @model_validator(mode="after")
    def require_artifact_hash_with_a_pinned_model(self) -> "Settings":
        """A pinned model version must also pin its artifact's sha256, so the served
        artifact is exactly the configured one (ml.registry.model_file_sha256)."""
        for kind in ("ranking", "win_prob"):
            if getattr(self, f"ml_{kind}_model_version_tag") and not getattr(self, f"ml_{kind}_model_sha256"):
                raise ValueError(f"ML_{kind.upper()}_MODEL_VERSION_TAG is set but ML_{kind.upper()}_MODEL_SHA256 "
                                 "is not: pin the registered artifact's sha256 too")
        return self

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
