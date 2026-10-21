"""The application factory.

create_app() is the single place the HTTP application is assembled, and it
reuses the pipeline's own configuration: a bare Settings(), exactly as
data/orchestrator.py's CLI entry point constructs it, which inherits that
class's .env discovery unchanged. There is no api-specific config object and no
second env-loading mechanism.
"""

from __future__ import annotations

import logging
import threading

from fastapi import APIRouter, FastAPI
from starlette.middleware.cors import CORSMiddleware

from api.body_limit import UPLOAD_MARGIN_BYTES, BodySizeLimitMiddleware, declare_body_limit
from api.errors import register_exception_handlers
from api.examples import install_examples
from api.middleware import RequestLoggingMiddleware
from api.ml_loading import (
    load_pinned_ranking_model,
    load_pinned_strategy_model,
    load_pinned_win_prob_model,
    load_playoff_models,
)
from api.request_id import REQUEST_ID_HEADER
from api.routes.alliance_selection import router as alliance_selection_router
from api.routes.common import unsupported_season_handler
from api.routes.discovery import router as discovery_router
from api.routes.event_analysis import router as event_analysis_router
from api.routes.explorer import router as explorer_router
from api.routes.health import router as health_router
from api.routes.human_inputs import router as human_inputs_router
from api.routes.manual_manager import router as manual_manager_router
from api.routes.metrics import router as metrics_router
from api.routes.predictions import router as predictions_router
from api.routes.pre_match_report import router as pre_match_report_router
from api.routes.qualification_forecast import router as qualification_forecast_router
from api.routes.strategy import router as strategy_router
from api.routes.strength import router as strength_router
from data.config import Settings
from data.human_inputs import MAX_MANUAL_BYTES
from database.connection import Database, DatabaseConfig
from ml.features.score_breakdown import UnsupportedSeasonError


logger = logging.getLogger(__name__)

API_TITLE = "StratAI API"
API_DESCRIPTION = ("FRC strategy platform API: team metrics, win probability, rankings, event analysis, discovery, match "
                   "strategy and the Phase 5 human-input workflows. Contracts and their locks: docs/phase7.md.")
API_VERSION = "0.1.0"

# No authentication exists yet, so credentialed cross-origin requests are not
# something the API should be inviting. Turning this on later should be a
# deliberate, reviewed change rather than a default that was inherited.
CORS_ALLOW_CREDENTIALS = False
CORS_ALLOW_METHODS = ("GET", "POST", "OPTIONS")
CORS_ALLOW_HEADERS = ("Content-Type", REQUEST_ID_HEADER)


def _briefing_router() -> APIRouter | None:
    """The Phase 9 briefing route, if the briefing layer is installed. It is optional and downstream only (P9-Q1):
    without it every other route is unchanged, which is what "disconnecting the LLM changes nothing" means.

    Only a missing `briefing` package is tolerated, and that is logged. (The SDK itself is imported lazily, only when
    a briefing calls the model.) Any other import error propagates,
    so a real bug in the layer is never hidden."""
    try:
        from api.routes.briefing import router
    except ModuleNotFoundError as exc:
        if exc.name is None or not (exc.name == "briefing" or exc.name.startswith("briefing.")):
            raise
        logger.warning("briefing layer not installed (%s); /matches/{match_key}/briefing is not served", exc.name)
        return None
    return router


def create_app(settings: Settings | None = None) -> FastAPI:
    """Build and return the StratAI FastAPI application.

    Args:
        settings: Configuration to build against. Defaults to a fresh
            Settings(), which resolves the environment and .env file the same
            way every other entry point in the project does. The parameter
            exists so a test can supply a stub without touching os.environ.

    Returns:
        A configured FastAPI application: CORS and request logging installed,
        this project's structured error shape registered on every error path,
        and the health router mounted.

    Constructing the Database here does not open a connection -- psycopg
    connects per Database.connection() call -- so create_app() succeeds with
    PostgreSQL down. That is what lets /health stay meaningful when the database
    is unreachable, instead of the process failing to boot at all.
    """
    settings = settings or Settings()

    app = FastAPI(
        title=API_TITLE,
        description=API_DESCRIPTION,
        version=API_VERSION,
        # Hardcoded, never wired to settings.env. Starlette's debug mode renders
        # tracebacks into HTTP responses; making that environment-driven is how a
        # staging misconfiguration turns into a production traceback.
        debug=False,
    )

    app.state.settings = settings
    app.state.database = Database(DatabaseConfig(
        settings.database_url, connect_timeout=settings.db_connect_timeout_seconds,
        statement_timeout_ms=settings.api_db_statement_timeout_ms or None))  # P10-M1 (Phase 7 R7)

    # ML models (Phase 4 Milestone 12; aligned with D18 on 2026-10-02): loaded once here
    # from the registry pins in Settings (type, version tag, sha256) -- small local
    # files, no external service. Each resolves to None if nothing is pinned or the pin
    # fails its checks, which must not fail startup (see api.ml_loading).
    app.state.ranking_model = load_pinned_ranking_model(settings)
    app.state.win_prob_model = load_pinned_win_prob_model(settings)
    app.state.strategy_model = load_pinned_strategy_model(settings)  # P7-M5: the P6-M10 model, or None
    app.state.playoff_models = load_playoff_models(settings)  # P7-M6: PX-1 + PX-2, or None
    # The EPA source reads the database (and, for D18, verifies its snapshot), so it is
    # loaded lazily on first use by api.dependencies.get_epa_source, never at startup:
    # the API still boots with PostgreSQL down.
    app.state.epa_source = None
    app.state.epa_source_lock = threading.Lock()
    app.state.epa_source_failed_at = None  # P10-M1 (Phase 7 R7): the monotonic time of the last failed load
    app.state.epa_source_reload_failed_at = None  # likewise for a failed reload after a live refresh

    # add_middleware inserts at the front of the stack, so the last one added is
    # the outermost. CORS must be outermost: RequestLoggingMiddleware catches
    # unhandled exceptions and returns the 500 itself, and that response has to
    # pass back out through CORS to pick up its headers.
    # P10-M1 (Phase 7 R6): innermost of the three, so a 413 is logged and carries the request id and CORS headers.
    app.add_middleware(BodySizeLimitMiddleware, default_limit=settings.max_request_body_bytes,
                       upload_limit=MAX_MANUAL_BYTES + UPLOAD_MARGIN_BYTES)
    app.add_middleware(RequestLoggingMiddleware)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=list(settings.cors_origins),
        allow_credentials=CORS_ALLOW_CREDENTIALS,
        allow_methods=list(CORS_ALLOW_METHODS),
        allow_headers=list(CORS_ALLOW_HEADERS),
        expose_headers=[REQUEST_ID_HEADER],
    )

    register_exception_handlers(app)
    app.add_exception_handler(UnsupportedSeasonError, unsupported_season_handler)

    # Health and readiness are mounted at the application root, deliberately
    # outside api_prefix, so probes do not move when the API is re-mounted.
    app.include_router(health_router)

    # Data routes, unlike the probes, DO sit under api_prefix -- which is what
    # that setting exists for. It defaults to "", so the team metrics endpoint
    # is served at the path the milestone documents it at.
    app.include_router(metrics_router, prefix=settings.api_prefix)
    app.include_router(predictions_router, prefix=settings.api_prefix)
    app.include_router(strength_router, prefix=settings.api_prefix)
    app.include_router(event_analysis_router, prefix=settings.api_prefix)
    app.include_router(qualification_forecast_router, prefix=settings.api_prefix)
    app.include_router(human_inputs_router, prefix=settings.api_prefix)
    app.include_router(discovery_router, prefix=settings.api_prefix)  # Phase 7 (P7-M4, P7-Q8)
    app.include_router(strategy_router, prefix=settings.api_prefix)  # Phase 7 (P7-M5)
    app.include_router(alliance_selection_router, prefix=settings.api_prefix)  # Phase 7 (P7-M6)
    app.include_router(pre_match_report_router, prefix=settings.api_prefix)  # Phase 7 (P7-M7)
    app.include_router(manual_manager_router, prefix=settings.api_prefix)  # game manuals, rulesets, readiness
    app.include_router(explorer_router, prefix=settings.api_prefix)  # historical season explorer (read-only)
    briefing_router = _briefing_router()
    if briefing_router is not None:  # Phase 9 (P9-M4): optional and downstream only (P9-Q1)
        app.include_router(briefing_router, prefix=settings.api_prefix)

    # Captured request/response examples (docs/api_examples/, P7-Q4) appear in the OpenAPI document. They are
    # documentation only: the locked response shapes ignore them. Installed after every router is included.
    declare_body_limit(app)  # P10-Q9: the 413 the body-limit middleware serves, declared where a body is sent
    install_examples(app, prefix=settings.api_prefix)

    logger.info(
        "Application created: env=%s prefix=%r cors_origins=%s",
        settings.env, settings.api_prefix, settings.cors_origins,
    )
    return app
