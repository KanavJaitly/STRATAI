"""One structured error shape for every non-2xx response the API can produce.

Phase 3 Milestone 12's stated success criterion is that an invalid route and a
forced error both return documented structured responses with no leaked
internals. Two things follow from that, and both are load-bearing here.

**One shape, no mix.** FastAPI's defaults return {"detail": ...}, in a slightly
different form per error class. Leaving any of them in place would mean a
frontend parsing two shapes and discovering the second one in production, so
every error path is routed through error_json_response: unmatched routes (404)
and wrong methods (405) via StarletteHTTPException -- registered on Starlette's
class, not FastAPI's subclass, because the router raises the former on a
no-match -- request validation (422) via RequestValidationError, response
validation and anything uncaught via the generic 500 path.

**Nothing internal crosses the wire.** For any status >= 500 the response body
is assembled from module-level constants and the request id; the exception is
never read into it. That is a structural guarantee rather than a careful habit:
in unhandled_exception_handler there is simply no expression through which the
exception's text could reach the response. The real detail goes to the log via
logger.exception, correlated by request id.

Three supporting rules close the remaining leaks:

  * Starlette's debug mode renders tracebacks into responses, so api.app pins
    debug=False and never wires it to Settings.env -- a staging misconfiguration
    should not be able to turn tracebacks on.
  * HTTPException.detail is surfaced only below 500. A developer-authored 404
    message is useful to a client; a deliberately raised 500's detail is not.
  * 422 details are allow-listed down to (field, message, type). Pydantic's
    raw errors also carry "input" (the caller's own payload) and "ctx", which
    can hold arbitrary objects and exception reprs from custom validators.

**Codes are derived, unless a route needs a finer one.** By default `code` comes
from the HTTP status phrase, so every 404 reads "not_found". Phase 3 Milestone
13 added ApiError for the case where one status covers several genuinely
different situations a client must branch on: its team metrics endpoint returns
404 for four distinct reasons -- unknown team, unknown event, team never at that
event, metrics not computed yet -- of which only the last is worth retrying. A
status cannot express that difference and a stable code can, so a route may
supply one. This is additive: an exception without a `.code` renders exactly as
it did before. The override is also honoured only below 500, mirroring the
detail rule directly above it, which keeps the guarantee that a >= 500 body is
assembled entirely from module constants intact -- the code feature must not
become the one field a route can vary in a 500.
"""

from __future__ import annotations

import logging
import re
from http import HTTPStatus
from typing import Any, Sequence

from fastapi import FastAPI
from fastapi.exceptions import RequestValidationError, ResponseValidationError
from pydantic import BaseModel, Field
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.requests import Request
from starlette.responses import JSONResponse

from api.request_id import get_request_id


logger = logging.getLogger(__name__)


# Client-facing messages. Constants, not f-strings over an exception: see the
# module docstring's second point.
INTERNAL_ERROR_MESSAGE = "An internal error occurred."
VALIDATION_ERROR_MESSAGE = "The request failed validation."
SERVICE_UNAVAILABLE_MESSAGE = "The service is not ready to handle requests."

INTERNAL_ERROR_CODE = "internal_error"
VALIDATION_ERROR_CODE = "validation_error"

# Codes are derived from the HTTP status phrase (404 -> "not_found",
# 503 -> "service_unavailable") so any status gets a stable machine-readable
# code with no lookup table to maintain. These two read better than their
# derived form ("unprocessable_content", "internal_server_error").
_ERROR_CODE_OVERRIDES = {
    HTTPStatus.UNPROCESSABLE_ENTITY: VALIDATION_ERROR_CODE,
    HTTPStatus.INTERNAL_SERVER_ERROR: INTERNAL_ERROR_CODE,
}

# Used when a status carries no developer-authored detail. Starlette raises its
# own 404s and 405s with detail set to the bare status phrase, which is correct
# but terse; these read as sentences.
_DEFAULT_MESSAGES = {
    HTTPStatus.NOT_FOUND: "The requested resource was not found.",
    HTTPStatus.METHOD_NOT_ALLOWED: "That method is not allowed for this resource.",
    HTTPStatus.SERVICE_UNAVAILABLE: SERVICE_UNAVAILABLE_MESSAGE,
}

_FALLBACK_MESSAGE = "The request could not be completed."

_NON_CODE_CHARS = re.compile(r"[^a-z0-9]+")


class ApiError(StarletteHTTPException):
    """An HTTPException that carries its own machine-readable error code.

    Raise this instead of HTTPException when a route needs a code more specific
    than the one derived from its status -- see the module docstring's fourth
    rule. Everything else is unchanged: it is an HTTPException, so
    http_exception_handler renders it through the same envelope as any other,
    and `message` becomes the client-visible message via the ordinary
    detail path.

    Subclasses Starlette's HTTPException rather than FastAPI's for the same
    reason register_exception_handlers registers the Starlette class: that is
    the handler both are routed through, so this needs no registration of its
    own.
    """

    def __init__(
        self,
        *,
        status_code: int,
        code: str,
        message: str,
        headers: dict[str, str] | None = None,
    ) -> None:
        super().__init__(status_code=status_code, detail=message, headers=headers)
        self.code = code


class ErrorDetail(BaseModel):
    """One field-level problem, only ever populated for request validation."""

    field: str = Field(description="Dotted path to the offending input, e.g. 'query.team_number'.")
    message: str = Field(description="Human-readable description of the problem.")
    type: str = Field(description="Stable pydantic error type, e.g. 'int_parsing'.")


class ErrorBody(BaseModel):
    """The contents of the single top-level "error" key."""

    code: str = Field(description="Stable machine-readable code, e.g. 'not_found'.")
    message: str = Field(description="Human-readable summary, safe to show a user.")
    status: int = Field(description="HTTP status code, repeated for clients that only read the body.")
    request_id: str = Field(description="Correlates this response with the server-side log line.")
    details: list[ErrorDetail] | None = Field(
        default=None,
        description="Field-level problems. Present on validation failures, omitted otherwise.",
    )


class ErrorResponse(BaseModel):
    """The envelope every non-2xx response uses.

    Nested under one "error" key rather than flattened so a client can tell an
    error from a success by structure alone, without consulting the status code
    or knowing what a successful body for that route looks like.
    """

    error: ErrorBody


def error_code_for_status(status: int) -> str:
    """Return the stable snake_case error code for an HTTP status."""
    try:
        http_status = HTTPStatus(status)
    except ValueError:
        # A non-standard status still gets a well-formed body rather than a crash
        # inside the error handler itself.
        return "error"
    override = _ERROR_CODE_OVERRIDES.get(http_status)
    if override is not None:
        return override
    return _NON_CODE_CHARS.sub("_", http_status.phrase.lower()).strip("_")


def _status_phrase(status: int) -> str:
    try:
        return HTTPStatus(status).phrase
    except ValueError:
        return ""


def _default_message_for(status: int) -> str | None:
    try:
        return _DEFAULT_MESSAGES.get(HTTPStatus(status))
    except ValueError:
        return None


def error_json_response(
    *,
    status: int,
    message: str,
    request_id: str,
    code: str | None = None,
    details: Sequence[ErrorDetail] | None = None,
    headers: dict[str, str] | None = None,
) -> JSONResponse:
    """Build the canonical error response.

    Every error path in the application goes through this function, which is
    what makes "one shape, no mix" checkable rather than aspirational.
    """
    body = ErrorResponse(
        error=ErrorBody(
            code=code or error_code_for_status(status),
            message=message,
            status=status,
            request_id=request_id,
            details=list(details) if details else None,
        )
    )
    # exclude_none drops "details" entirely rather than sending an explicit null.
    return JSONResponse(status_code=status, content=body.model_dump(exclude_none=True), headers=headers)


def _client_safe_message(status: int, detail: Any) -> str:
    """Choose the message a client may see for an HTTPException.

    Developer-authored detail below 500 is intentional and useful, so it passes
    through. At 500 and above it does not: a raised
    HTTPException(500, detail="connection to db-primary:5432 refused") is an
    operator's note, not a client's. Non-string detail is dropped too, so the
    schema's promise that "message" is a string holds unconditionally.
    """
    if status >= 500:
        # The detail is discarded unconditionally -- that is the security rule.
        # A curated message for the status itself is still safe and more useful
        # than a blanket "internal error": a 503 from the readiness check should
        # say the service is not ready, since that is a fact about the service,
        # not about the failure that produced it.
        return _default_message_for(status) or INTERNAL_ERROR_MESSAGE
    if isinstance(detail, str):
        text = detail.strip()
        # Starlette's own 404/405 detail is the bare status phrase; treat that as
        # "no detail was authored" and use the friendlier sentence instead.
        if text and text != _status_phrase(status):
            return text
    return _default_message_for(status) or _status_phrase(status) or _FALLBACK_MESSAGE


def _sanitize_validation_errors(errors: Sequence[Any]) -> list[ErrorDetail]:
    """Reduce pydantic's raw error dicts to the three fields a client may see.

    An allow-list, not a deny-list: only loc, msg and type are read. "input"
    (the caller's raw payload) and "ctx" (which can carry arbitrary objects and
    exception reprs from a custom validator) are never copied out, so a future
    validator cannot widen what this endpoint discloses by accident.
    """
    details: list[ErrorDetail] = []
    for error in errors:
        if not isinstance(error, dict):
            continue
        location = error.get("loc") or ()
        field = ".".join(str(part) for part in location) or "body"
        details.append(
            ErrorDetail(
                field=field,
                message=str(error.get("msg", "")),
                type=str(error.get("type", "")),
            )
        )
    return details


def _client_safe_code(status: int, exc: StarletteHTTPException) -> str | None:
    """Return a route-supplied error code, or None to derive one from the status.

    Reads the attribute rather than isinstance-checking ApiError so any
    exception carrying a `.code` works, and so an exception without one is
    completely unaffected -- None makes error_json_response fall back to
    error_code_for_status, which is exactly what happened before ApiError
    existed. Ignored at 500 and above: see the module docstring.
    """
    if status >= 500:
        return None
    code = getattr(exc, "code", None)
    return code if isinstance(code, str) and code else None


async def http_exception_handler(request: Request, exc: StarletteHTTPException) -> JSONResponse:
    """Render any HTTPException -- including the router's own 404 and 405."""
    request_id = get_request_id(request)
    if exc.status_code >= 500:
        # The detail is dropped from the response, so this is the only place it
        # is recorded at all.
        logger.error(
            "HTTPException %d on %s %s request_id=%s: %s",
            exc.status_code, request.method, request.url.path, request_id, exc.detail,
        )
    return error_json_response(
        status=exc.status_code,
        message=_client_safe_message(exc.status_code, exc.detail),
        request_id=request_id,
        code=_client_safe_code(exc.status_code, exc),
        # Preserves headers the protocol requires, notably Allow on a 405 and
        # WWW-Authenticate on a 401.
        headers=getattr(exc, "headers", None),
    )


async def request_validation_exception_handler(
    request: Request, exc: RequestValidationError
) -> JSONResponse:
    """Render a request-validation failure as a 422 with sanitized details."""
    request_id = get_request_id(request)
    details = _sanitize_validation_errors(exc.errors())
    logger.info(
        "Request validation failed on %s %s request_id=%s: %d problem(s)",
        request.method, request.url.path, request_id, len(details),
    )
    return error_json_response(
        status=HTTPStatus.UNPROCESSABLE_ENTITY,
        message=VALIDATION_ERROR_MESSAGE,
        code=VALIDATION_ERROR_CODE,
        request_id=request_id,
        details=details,
    )


async def response_validation_exception_handler(
    request: Request, exc: ResponseValidationError
) -> JSONResponse:
    """Render a response-model validation failure as a generic 500.

    This is the server's bug, not the caller's, and the errors describe the
    shape of data StratAI failed to serialize -- so the client is told nothing
    beyond "internal error" and the detail goes to the log. Matters from
    Milestone 13 on, when routes start returning TeamMetrics.
    """
    request_id = get_request_id(request)
    logger.exception(
        "Response validation failed on %s %s request_id=%s",
        request.method, request.url.path, request_id,
    )
    return error_json_response(
        status=HTTPStatus.INTERNAL_SERVER_ERROR,
        message=INTERNAL_ERROR_MESSAGE,
        code=INTERNAL_ERROR_CODE,
        request_id=request_id,
    )


async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    """Render any uncaught exception as a generic 500.

    Registered as a backstop. The primary catch-all is in
    api.middleware.RequestLoggingMiddleware, which sits inside CORSMiddleware so
    that a 500 still carries CORS headers; Starlette's ServerErrorMiddleware,
    which is what invokes this handler, re-raises after calling it. See that
    middleware's docstring for the full reasoning.

    Note what this function does *not* do: it never reads `exc` into the
    response. Below the logging call the exception is not referenced again, so
    there is no path by which a traceback, a psycopg error string, or a
    filesystem path reaches the client.
    """
    request_id = get_request_id(request)
    logger.exception(
        "Unhandled exception request_id=%s %s %s",
        request_id, request.method, request.url.path,
    )
    return error_json_response(
        status=HTTPStatus.INTERNAL_SERVER_ERROR,
        message=INTERNAL_ERROR_MESSAGE,
        code=INTERNAL_ERROR_CODE,
        request_id=request_id,
    )


def register_exception_handlers(app: FastAPI) -> None:
    """Replace FastAPI's default error rendering with this module's shape.

    StarletteHTTPException rather than fastapi.HTTPException is deliberate: the
    router raises Starlette's class for an unmatched route, and FastAPI's
    subclasses it, so registering the base covers both.
    """
    app.add_exception_handler(StarletteHTTPException, http_exception_handler)
    app.add_exception_handler(RequestValidationError, request_validation_exception_handler)
    app.add_exception_handler(ResponseValidationError, response_validation_exception_handler)
    app.add_exception_handler(Exception, unhandled_exception_handler)
