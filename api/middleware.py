"""Request logging, correlation ids, and the application's primary catch-all.

Logging style follows the rest of the codebase rather than introducing a second
convention: a module-level logging.getLogger(__name__) and %-style lazy
formatting, exactly as data/pipeline.py and data/orchestrator.py do. No handler
is configured anywhere in the api package except api/__main__.py, mirroring the
rule that only an entry point calls logging.basicConfig.

Why the catch-all lives here rather than only in an exception handler
============================================================================
Starlette's ServerErrorMiddleware calls a registered Exception handler and then
re-raises the original exception (starlette/middleware/errors.py). Relying on
that handler alone has two consequences that matter:

  * the 500 it produces is generated outside CORSMiddleware, so it carries no
    CORS headers -- a browser frontend would see an opaque network failure
    instead of the structured error body, precisely when something is broken;
  * the re-raise means behaviour under TestClient differs from behaviour under
    uvicorn unless the test opts out with raise_server_exceptions=False.

Catching here instead -- inside CORSMiddleware, outside the router -- gives one
consistent 500: same envelope, CORS headers applied on the way out, no re-raise,
and identical behaviour in tests and in production. The handler in api.errors
stays registered as a backstop for anything that fails outside this middleware.

The trade-off, accepted deliberately: swallowing the exception means uvicorn
never prints its own traceback. What replaces it is strictly more useful -- the
same traceback through this project's logger, correlated by request id and
tagged with the method and path.
"""

from __future__ import annotations

import logging
import time
from http import HTTPStatus

from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import Response

from api.errors import INTERNAL_ERROR_CODE, INTERNAL_ERROR_MESSAGE, error_json_response
from api.request_id import REQUEST_ID_HEADER, ensure_request_id


logger = logging.getLogger(__name__)


class RequestLoggingMiddleware(BaseHTTPMiddleware):
    """Log one line per completed request and guarantee a structured 500.

    What is logged: method, path, status, duration, request id.

    What is deliberately not logged: request bodies, headers, and query strings.
    Not boilerplate caution -- Milestone 7's scouting submission path is gated by
    a per-event access code, and the routes that will carry it (Milestone 13
    onward) would write that credential to disk on every request if bodies or
    headers were logged. The path is logged, the query string is not; if a
    future route ever accepts a secret as a query parameter, this decision needs
    revisiting rather than quietly relying on it.
    """

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        request_id = ensure_request_id(request)
        started = time.perf_counter()

        try:
            response = await call_next(request)
        except Exception:
            duration_ms = (time.perf_counter() - started) * 1000
            # logger.exception attaches the live traceback. This is the only
            # place the exception is recorded; the response below is built from
            # constants.
            logger.exception(
                "Unhandled exception request_id=%s %s %s",
                request_id, request.method, request.url.path,
            )
            response = error_json_response(
                status=HTTPStatus.INTERNAL_SERVER_ERROR,
                message=INTERNAL_ERROR_MESSAGE,
                code=INTERNAL_ERROR_CODE,
                request_id=request_id,
            )
        else:
            duration_ms = (time.perf_counter() - started) * 1000

        response.headers[REQUEST_ID_HEADER] = request_id
        logger.info(
            "%s %s -> %d (%.1fms) request_id=%s",
            request.method, request.url.path, response.status_code, duration_ms, request_id,
        )
        return response
