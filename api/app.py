"""The application factory.

create_app() is the single place the HTTP application is assembled, and it
reuses the pipeline's own configuration: a bare Settings(), exactly as
data/orchestrator.py's CLI entry point constructs it, which inherits that
class's .env discovery unchanged. There is no api-specific config object and no
second env-loading mechanism.
"""

from __future__ import annotations

import logging

from fastapi import FastAPI
from starlette.middleware.cors import CORSMiddleware

from api.errors import register_exception_handlers
from api.middleware import RequestLoggingMiddleware
from api.request_id import REQUEST_ID_HEADER
from api.routes.health import router as health_router
from data.config import Settings
from database.connection import Database, DatabaseConfig


logger = logging.getLogger(__name__)

API_TITLE = "StratAI API"
API_DESCRIPTION = "FRC strategy platform API. Phase 3 Milestone 12: foundation only."
API_VERSION = "0.1.0"

# No authentication exists yet, so credentialed cross-origin requests are not
# something the API should be inviting. Turning this on later should be a
# deliberate, reviewed change rather than a default that was inherited.
CORS_ALLOW_CREDENTIALS = False
CORS_ALLOW_METHODS = ("GET", "POST", "OPTIONS")
CORS_ALLOW_HEADERS = ("Content-Type", REQUEST_ID_HEADER)


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
    app.state.database = Database(DatabaseConfig(settings.database_url))

    # add_middleware inserts at the front of the stack, so the last one added is
    # the outermost. CORS must be outermost: RequestLoggingMiddleware catches
    # unhandled exceptions and returns the 500 itself, and that response has to
    # pass back out through CORS to pick up its headers.
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

    # Health and readiness are mounted at the application root, deliberately
    # outside api_prefix, so probes do not move when the API is re-mounted.
    app.include_router(health_router)

    logger.info(
        "Application created: env=%s prefix=%r cors_origins=%s",
        settings.env, settings.api_prefix, settings.cors_origins,
    )
    return app
