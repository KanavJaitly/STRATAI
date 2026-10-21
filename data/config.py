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
    # Set API_PREFIX only to mount behind a gateway path. Phase 7 keeps paths unversioned (P7-Q6): the contract
    # lock (docs/api_contract_lock.json), not a version prefix, is the stability guarantee.
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
    # P7-M5: the P6-M10 strategy-conditional outcome model the strategy endpoints serve. Same pin pattern (type,
    # version tag, artifact sha256); unpinned means model_not_loaded. It is always loaded through
    # ml.strategy.outcome.load_registered_strategy_model, so its baseline status is the recorded p6_m10_gate_failed.
    ml_strategy_model_type: Literal["strategy_outcome_component"] = "strategy_outcome_component"
    ml_strategy_model_version_tag: str | None = None
    ml_strategy_model_sha256: str | None = None
    # P7-M6: the playoff models the alliance-selection pick list needs once its PX gates have passed (P6-M2 PX-1,
    # P6-M3 PX-2): the PX-1 model in the registry (playoff_px1/<tag>/model.json) and the PX-2 calibrator file, each
    # pinned with its sha256. Unpinned (the state while PX-1/PX-2 have not run) means model_not_loaded; the pick
    # list refuses earlier anyway until the gates pass.
    ml_px1_version_tag: str | None = None
    ml_px1_sha256: str | None = None
    ml_px2_calibrator_path: str | None = None
    ml_px2_calibrator_sha256: str | None = None
    # EPA source for Phase 4 features (ml.ratings.provider). The default is the evaluated
    # production configuration, D18: Statbotics primary from a verified snapshot
    # (STATBOTICS_SNAPSHOT_DIR), STRATAI fallback for 2026iscmp only (STRATAI_EPA_CHAIN).
    # Unconfigured, it fails loudly rather than silently using another source.
    # "stratai" (D15, historical) and "statbotics" (plain D13 over team_event_stats, no
    # availability rule or fallback) remain selectable as non-evaluated references.
    #
    # "p5_live_statbotics" is the P5-M2 live-refreshed provider (ml.ratings.live_epa). It is
    # not the evaluated configuration: adoption is a recorded human decision (P5-D3), and it
    # loads only with LIVE_EPA_LOG_DIR (a snapshot log rooted at STATBOTICS_SNAPSHOT_DIR) and an
    # explicit LIVE_EPA_A1A2_POLICY (open decision Q1, .agent/phase5/M02_DECISION_REQUIRED.md).
    epa_source: Literal["d18_statbotics_primary", "stratai", "statbotics", "p5_live_statbotics"] = (
        "d18_statbotics_primary")
    stratai_epa_chain: str | None = None
    statbotics_snapshot_dir: str | None = None
    live_epa_log_dir: str | None = None
    live_epa_a1a2_policy: Literal["d18_skip", "literal_state"] | None = None
    live_epa_concluded_seasons: list[int] = []
    # Phase 5 human-input workflows (data/human_inputs.py, api/routes/human_inputs.py).
    # - human_inputs_write_token: the shared secret every write request must present in the
    #   X-StratAI-Write-Token header. Unset means every write is refused (fail closed); reads stay open, as
    #   for every other endpoint.
    # - artifact_store_dir: where uploaded game-manual PDFs are kept write-once, named by sha256.
    human_inputs_write_token: str | None = None
    artifact_store_dir: str = str(PROJECT_ROOT.parent / "StratAI-artifacts" / "uploads")
    # Phase 9 briefing layer (briefing/, api/routes/briefing.py). Fail closed: the LLM formatter runs only when it is
    # enabled AND the data egress to the LLM provider is approved (P9-Q3, a human decision) AND a credential resolves;
    # otherwise the deterministic briefing is served. The credential is never a setting: the Anthropic SDK reads it
    # from its own chain (ANTHROPIC_API_KEY, ...), so it can never appear in a Settings dump (P9-Q11).
    briefing_llm_enabled: bool = False
    briefing_data_egress_approved: bool = False
    briefing_model: str = "claude-opus-5-5"
    briefing_max_tokens: int = Field(default=16000, gt=0)
    briefing_timeout_seconds: float = Field(default=30.0, gt=0)

    # P10-M1 (Phase 7 R6, R7): platform hardening. All have safe defaults.
    # The largest request body any route but the manual upload accepts (the upload has its own cap).
    max_request_body_bytes: int = Field(default=1024 * 1024, gt=0)
    # Every database connection gives up after this many seconds instead of hanging.
    db_connect_timeout_seconds: int = Field(default=10, gt=0)
    # The API's statements are cancelled after this many milliseconds (0 = no limit). Long batch jobs build their own
    # Database without it.
    api_db_statement_timeout_ms: int = Field(default=60000, ge=0)
    # After a failed EPA-source load, the API waits this long before trying again, instead of retrying (under a lock)
    # on every request.
    epa_source_retry_seconds: float = Field(default=30.0, ge=0)

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
