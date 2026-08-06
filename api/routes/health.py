"""Liveness and readiness endpoints.

Two endpoints, two genuinely different questions:

  GET /health   Is the process up and serving? No I/O at all, always 200.
  GET /ready    Can it serve real traffic? One database round-trip; 503 if not.

They are split because a readiness probe that checks nothing is behaviourally a
liveness probe with a misleading name. Everything this API will serve from
Milestone 13 on is a database-backed read, so "ready" without a reachable
PostgreSQL means nothing.

Both are mounted outside Settings.api_prefix, so probes keep working unchanged
if the API is later re-mounted behind a gateway.

On connection pooling
=====================
The readiness check opens exactly one connection through the existing
Database.connection() context manager, issues SELECT 1, and closes it on block
exit. It does not solve database/connection.py's lack of pooling and does not
try to -- that stays an open backlog item (RUNNING_NOTES.md). Nor can it make
that situation worse: it is the same one-connection-per-call pattern every
existing caller already uses, retains no state between requests, and adds load
only at whatever rate the probe is polled. That cost is exactly why the database
round-trip is on /ready and not on /health -- point aggressive liveness polling
at /health, which does no I/O whatsoever.
"""

from __future__ import annotations

import logging
from http import HTTPStatus

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from starlette.requests import Request

from api.dependencies import get_database, get_settings
from api.errors import ErrorResponse
from api.request_id import get_request_id
from data.config import Settings
from database.connection import Database


logger = logging.getLogger(__name__)

router = APIRouter(tags=["health"])

STATUS_OK = "ok"
STATUS_READY = "ready"


class HealthResponse(BaseModel):
    """Liveness payload."""

    status: str = Field(description="Always 'ok' -- reaching this handler is the check.")
    env: str = Field(description="The configured environment: development, staging, or production.")


class ReadinessResponse(BaseModel):
    """Readiness payload."""

    status: str = Field(description="'ready' when every dependency check passed.")
    checks: dict[str, str] = Field(description="Per-dependency result, keyed by dependency name.")


@router.get(
    "/health",
    response_model=HealthResponse,
    summary="Liveness check",
    description="Returns 200 whenever the process is running. Performs no I/O.",
)
async def health(settings: Settings = Depends(get_settings)) -> HealthResponse:
    """Report that the process is alive.

    async def with no awaits is correct here precisely because there is no I/O:
    the handler runs on the event loop without a threadpool hop.
    """
    return HealthResponse(status=STATUS_OK, env=settings.env)


@router.get(
    "/ready",
    response_model=ReadinessResponse,
    summary="Readiness check",
    description=(
        "Returns 200 when the API can reach every dependency it needs to serve "
        "requests, and 503 otherwise. Verifies database connectivity."
    ),
    responses={HTTPStatus.SERVICE_UNAVAILABLE: {"model": ErrorResponse}},
)
def ready(
    request: Request,
    database: Database = Depends(get_database),
) -> ReadinessResponse:
    """Verify the API's dependencies are reachable.

    Declared with def rather than async def on purpose: psycopg is synchronous,
    so FastAPI runs this in a threadpool and one unreachable database cannot
    block the event loop for every other in-flight request.
    """
    try:
        with database.cursor() as cursor:
            cursor.execute("SELECT 1")
            cursor.fetchone()
    except Exception:
        # The psycopg error text -- which carries host, port, database name and
        # sometimes the connection string -- is logged and never returned. The
        # client gets the generic service_unavailable envelope.
        logger.exception("Readiness check failed: database unreachable request_id=%s", get_request_id(request))
        raise HTTPException(status_code=HTTPStatus.SERVICE_UNAVAILABLE) from None

    return ReadinessResponse(status=STATUS_READY, checks={"database": STATUS_OK})
