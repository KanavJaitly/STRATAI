"""P10-M1 (Phase 7 R6): a request-body size limit for every route.

Without it, any route that reads its body (every JSON POST, and the manual upload's `await request.body()`) would
read an unbounded body into memory before anything could refuse it. This ASGI middleware refuses:
- a declared `Content-Length` over the limit, before the body is read;
- a streamed body that grows past it, as soon as it does.

Either way the answer is 413 in the standard error envelope (`payload_too_large`).

The limit depends on the path:
- the game-manual upload may carry a manual up to `data.human_inputs.MAX_MANUAL_BYTES` (its own validated cap), plus
  a margin;
- every other route takes `Settings.max_request_body_bytes` (default 1 MiB, far above any legitimate JSON body).

It is pure ASGI rather than BaseHTTPMiddleware, so it can stop a streamed body without buffering it. On overflow the
app is told the client disconnected, anything it answers is discarded, and the 413 is sent instead.
"""

from __future__ import annotations

from http import HTTPStatus
from typing import Any, Awaitable, Callable

from starlette.requests import Request

from api.errors import PAYLOAD_TOO_LARGE_CODE, ErrorResponse, error_json_response
from api.request_id import get_request_id

CODE_PAYLOAD_TOO_LARGE = PAYLOAD_TOO_LARGE_CODE
UPLOAD_PATH_SUFFIX = "/human-inputs/game-manuals"
# Fixed wording (the phrase of 413 differs between Python versions); only the code is part of the contract.
DECLARED_413 = {"model": ErrorResponse,
                "description": f"Content Too Large: the request body is over this endpoint's limit. "
                               f"Error codes: `{PAYLOAD_TOO_LARGE_CODE}`."}
UPLOAD_MARGIN_BYTES = 64 * 1024  # slack above the manual cap, so the route's own validation (a clear 400) decides

Scope = dict[str, Any]
Receive = Callable[[], Awaitable[dict[str, Any]]]
Send = Callable[[dict[str, Any]], Awaitable[None]]


class BodySizeLimitMiddleware:
    def __init__(self, app: Callable[..., Awaitable[None]], *, default_limit: int, upload_limit: int,
                 upload_path_suffix: str = UPLOAD_PATH_SUFFIX) -> None:
        self.app = app
        self.default_limit = default_limit
        self.upload_limit = upload_limit
        self.upload_path_suffix = upload_path_suffix

    def limit_for(self, method: str, path: str) -> int:
        if method == "POST" and path.rstrip("/").endswith(self.upload_path_suffix):
            return self.upload_limit
        return self.default_limit

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        limit = self.limit_for(scope.get("method", "GET"), scope.get("path", ""))
        declared = dict(scope.get("headers") or []).get(b"content-length")
        if declared is not None and declared.isdigit() and int(declared) > limit:
            await self._refuse(scope, receive, send, limit)
            return
        received = 0
        too_large = False

        async def limited_receive() -> dict[str, Any]:
            nonlocal received, too_large
            if too_large:
                return {"type": "http.disconnect"}
            message = await receive()
            if message["type"] == "http.request":
                received += len(message.get("body", b""))
                if received > limit:
                    # Stop reading: the app sees the client go away, whatever it answers is discarded, and the
                    # 413 below is sent instead.
                    too_large = True
                    return {"type": "http.disconnect"}
            return message

        started = False

        async def guarded_send(message: dict[str, Any]) -> None:
            nonlocal started
            if not too_large or started:  # a response already under way is finished as it is
                started = started or message["type"] == "http.response.start"
                await send(message)

        try:
            await self.app(scope, limited_receive, guarded_send)
        except Exception:
            # A route that reads its own body (the manual upload's `await request.body()`) sees the simulated
            # disconnect as ClientDisconnect and raises. When that is our overflow, it is a 413, not a 500 (review
            # P10-R1).
            if not (too_large and not started):
                raise
        if too_large and not started:
            await self._refuse(scope, receive, send, limit)

    async def _refuse(self, scope: Scope, receive: Receive, send: Send, limit: int) -> None:
        request = Request(scope, receive)
        response = error_json_response(
            status=HTTPStatus.REQUEST_ENTITY_TOO_LARGE, code=CODE_PAYLOAD_TOO_LARGE,
            message=f"The request body is larger than this endpoint accepts ({limit} bytes).",
            request_id=get_request_id(request), headers={"Connection": "close"})
        await response(scope, receive, send)


def declare_body_limit(app) -> list[str]:
    """P10-Q9 (approved by Sven Morais, 2026-10-21): declare the 413 in OpenAPI on every operation that takes a
    request body: every route with a body parameter, plus the raw-body manual upload. Those are the operations a
    legitimate client sends a body to, so they are the ones whose 413 a client must handle.

    A body sent to a GET route is refused the same way, but no client of the API sends one; that case is documented
    in docs/phase10.md rather than declared on every GET. Returns the operations declared (for the tests)."""
    from api.examples import iter_api_routes

    declared = []
    for path, route in iter_api_routes(app):
        takes_body = route.body_field is not None or (
            "POST" in route.methods and path.rstrip("/").endswith(UPLOAD_PATH_SUFFIX))
        if takes_body:
            route.responses[413] = DECLARED_413
            declared += [f"{method} {path}" for method in sorted(route.methods)]
    return sorted(declared)
