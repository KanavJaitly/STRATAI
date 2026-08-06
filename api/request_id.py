"""Per-request correlation identifiers.

Small enough to inline somewhere, but it lives in its own module deliberately:
both api.errors (which quotes the id in every error body) and api.middleware
(which generates it and echoes it in a response header) need these helpers, and
having either import the other would be circular.

The request id is the mechanism that makes the API's no-leakage rule usable
rather than merely strict. A client that hits a 500 gets an opaque id and
nothing else -- no traceback, no exception text -- while the server log line for
that same request carries the id alongside the full traceback. Support asks for
the id, an engineer greps for it, and no internal detail ever crossed the wire.
"""

from __future__ import annotations

import re
from uuid import uuid4

from starlette.requests import Request


REQUEST_ID_HEADER = "X-Request-ID"

# Used when an error response is built for a request that never passed through
# RequestLoggingMiddleware -- practically only if something fails in the
# middleware stack outside it. Never raises; an error response missing its
# correlation id is still worth returning.
UNKNOWN_REQUEST_ID = "unknown"

# An inbound X-Request-ID is client-controlled and we both echo it into a
# response header and log it, so it is constrained rather than trusted: a
# newline would let a caller forge log lines or inject a header, and an
# unbounded string would let them bloat every log record they touch.
_SAFE_REQUEST_ID = re.compile(r"^[A-Za-z0-9._-]{1,128}$")


def new_request_id() -> str:
    """Return a fresh opaque request identifier."""
    return uuid4().hex


def ensure_request_id(request: Request) -> str:
    """Resolve this request's id, store it on request.state, and return it.

    Reuses a well-formed inbound X-Request-ID header so a trace started by a
    gateway or frontend survives into StratAI's own logs; generates a new id
    when the header is absent or fails the safe-charset check.
    """
    incoming = request.headers.get(REQUEST_ID_HEADER)
    request_id = incoming if incoming and _SAFE_REQUEST_ID.match(incoming) else new_request_id()
    request.state.request_id = request_id
    return request_id


def get_request_id(request: Request) -> str:
    """Return the id set by ensure_request_id, or UNKNOWN_REQUEST_ID if unset."""
    return getattr(request.state, "request_id", UNKNOWN_REQUEST_ID)
