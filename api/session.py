"""The API side of team workspaces: the session cookie, CSRF check, client address, permission gates, and turning a
workspaces.errors.WorkspaceError into the error envelope.

**The session cookie** (`stratai_session`) is HttpOnly, SameSite=Lax, Path=/, and Secure outside development. The
web app reaches the API on its own origin (the Vite proxy locally, the Vercel rewrite when hosted), so the cookie
is first-party and the API's CORS policy stays closed to credentialed cross-origin requests.

**CSRF.** Every state-changing /auth and /workspace request must carry `X-StratAI-CSRF: 1`. A page on another site
cannot add a custom header to a request without a CORS preflight, which this API does not grant; together with
SameSite=Lax this keeps another site from acting with a member's cookie.

**Gates on the existing routes.** create_app attaches permission_gate(permission) to each existing router, so no
existing handler changes. Under ACCESS_POLICY=open (the default) the gates admit everyone, exactly as before; under
ACCESS_POLICY=members they require a signed-in member holding the router's permission (401 not_authenticated,
403 permission_denied). The gate reads the cookie from the request instead of declaring a Cookie parameter, so it
adds nothing to any locked operation's OpenAPI contract.
"""

from __future__ import annotations

import hmac
from http import HTTPStatus
from typing import Any, Callable

from fastapi import Response
from starlette.requests import Request

from api.errors import ApiError
from data.config import Settings
from database.connection import Database
from workspaces.errors import WorkspaceError
from workspaces.sessions import COOKIE_NAME, SessionContext, cookie_secure, resolve_session

CSRF_HEADER = "X-StratAI-CSRF"
CODE_NOT_AUTHENTICATED = "not_authenticated"
CODE_PERMISSION_DENIED = "permission_denied"
CODE_CSRF = "csrf_check_failed"
_CACHE_ATTR = "stratai_session"


def api_error(exc: WorkspaceError) -> ApiError:
    return ApiError(status_code=exc.status, code=exc.code, message=exc.message)


def call(function: Callable[..., Any], *args: Any, **kwargs: Any) -> Any:
    """Run a workspaces function, turning its refusals into the API's error envelope."""
    try:
        return function(*args, **kwargs)
    except WorkspaceError as exc:
        raise api_error(exc) from None


def client_ip(request: Request, settings: Settings) -> str:
    """The caller's address for rate limiting: X-Forwarded-For counted back AUTH_TRUSTED_PROXY_HOPS entries when
    proxies are configured, else the connecting peer (forwarded headers are spoofable, so trusted only by setting)."""
    hops = settings.auth_trusted_proxy_hops
    if hops:
        forwarded = [part.strip() for part in request.headers.get("x-forwarded-for", "").split(",") if part.strip()]
        if len(forwarded) >= hops:
            return forwarded[-hops]
    return request.client.host if request.client else "unknown"


def current_session(request: Request) -> SessionContext | None:
    """The live session behind the request's cookie, resolved once per request."""
    if not hasattr(request.state, _CACHE_ATTR):
        settings: Settings = request.app.state.settings
        database: Database = request.app.state.database
        setattr(request.state, _CACHE_ATTR,
                resolve_session(database, request.cookies.get(COOKIE_NAME), settings))
    return getattr(request.state, _CACHE_ATTR)


def require_session(request: Request) -> SessionContext:
    context = current_session(request)
    if context is None:
        raise ApiError(status_code=HTTPStatus.UNAUTHORIZED, code=CODE_NOT_AUTHENTICATED,
                       message="Sign in to your team's StratAI to continue.")
    return context


def require_csrf(request: Request) -> None:
    if request.method not in ("GET", "HEAD", "OPTIONS") and request.headers.get(CSRF_HEADER) != "1":
        raise ApiError(status_code=HTTPStatus.FORBIDDEN, code=CODE_CSRF,
                       message=f"This request must carry the {CSRF_HEADER} header.")


def require_permission(permission: str) -> Callable[[Request], SessionContext]:
    """A dependency: a signed-in member whose role holds permission."""

    def dependency(request: Request) -> SessionContext:
        context = require_session(request)
        if not context.can(permission):
            raise ApiError(status_code=HTTPStatus.FORBIDDEN, code=CODE_PERMISSION_DENIED,
                           message="Your role does not have permission to do this.")
        return context

    return dependency


def permission_gate(permission: str) -> Callable[[Request], None]:
    """The gate create_app attaches to an existing router (see the module docstring)."""

    def gate(request: Request) -> None:
        if request.app.state.settings.access_policy == "members":
            require_permission(permission)(request)

    gate.__name__ = f"permission_gate_{permission}"
    return gate


def platform_gate(request: Request) -> None:
    """The gate for the platform-wide human-input routes (game manuals, rulesets, capability profiles). Their writes
    keep the platform write token (they change data every team shares, so no team role may change them); under
    ACCESS_POLICY=members their reads, and token-holding tools, need a signed-in member or that token."""
    settings: Settings = request.app.state.settings
    if settings.access_policy != "members":
        return
    from api.routes.common import WRITE_TOKEN_HEADER

    supplied = request.headers.get(WRITE_TOKEN_HEADER, "")
    expected = settings.human_inputs_write_token
    if supplied and expected and hmac.compare_digest(supplied.encode("utf-8"), expected.encode("utf-8")):
        return
    require_session(request)


def set_session_cookie(response: Response, token: str, settings: Settings) -> None:
    response.set_cookie(COOKIE_NAME, token, max_age=settings.session_ttl_hours * 3600, httponly=True,
                        secure=cookie_secure(settings), samesite="lax", path="/")


def clear_session_cookie(response: Response, settings: Settings) -> None:
    response.delete_cookie(COOKIE_NAME, httponly=True, secure=cookie_secure(settings), samesite="lax", path="/")
