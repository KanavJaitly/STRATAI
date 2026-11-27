"""Authentication for FRC Team 11's StratAI: sign-up with the team join code, sign-in and sign-out, passwords, and
password reset by emailed code.

Thin HTTP wrappers over workspaces.accounts (docs/team_workspaces.md). Every POST here needs the CSRF header
(api.session). The join code, passwords and reset codes travel only in request bodies, never in a path or query
string, so they never reach the request log.

Error codes: `invalid_input` and `validation_error` (422), `invalid_credentials`, `not_authenticated` (401),
`invalid_join_code`, `signup_closed`, `account_inactive`, `current_password_incorrect`, `csrf_check_failed` (403),
`email_already_registered`, `team_workspace_missing` (409), `reset_code_invalid` (410), `rate_limited` (429).
"""

from __future__ import annotations

from http import HTTPStatus
from typing import Any

from fastapi import APIRouter, BackgroundTasks, Depends, Response
from pydantic import BaseModel, ConfigDict, Field
from starlette.requests import Request

from api.contract import error_responses
from api.dependencies import get_database, get_settings
from api.session import (
    call,
    clear_session_cookie,
    client_ip,
    current_session,
    forwarded_chain,
    require_permission,
    require_csrf,
    require_session,
    set_session_cookie,
)
from data.config import Settings
from database.connection import Database
from workspaces import accounts, mailer
from workspaces.sessions import (
    COOKIE_NAME,
    SessionContext,
    accounts_schema_present,
    resolve_session,
    revoke_token,
)

router = APIRouter(prefix="/auth", tags=["authentication"])

_TEXT = 512  # generous upper bounds on every field; the rules in workspaces/ set the real limits


class _Body(BaseModel):
    model_config = ConfigDict(extra="forbid")


class SignupBody(_Body):
    full_name: str = Field(max_length=_TEXT)
    email: str = Field(max_length=_TEXT)
    password: str = Field(max_length=_TEXT)
    join_code: str = Field(max_length=_TEXT)


class LoginBody(_Body):
    email: str = Field(max_length=_TEXT)
    password: str = Field(max_length=_TEXT)


class ChangePasswordBody(_Body):
    current_password: str = Field(max_length=_TEXT)
    new_password: str = Field(max_length=_TEXT)


class ForgotPasswordBody(_Body):
    email: str = Field(max_length=_TEXT)


class ResetPasswordBody(_Body):
    email: str = Field(max_length=_TEXT)
    code: str = Field(max_length=_TEXT)
    new_password: str = Field(max_length=_TEXT)


def _session_payload(context: SessionContext | None, settings: Settings, *,
                     accounts_available: bool = True) -> dict[str, Any]:
    base = {"access_policy": settings.access_policy,
            "email_delivery_configured": mailer.email_channel(settings) is not None,
            "signup_open": accounts.signup_open(settings),
            "accounts_available": accounts_available}
    if context is None:
        return {"authenticated": False, **base}
    return {**accounts.session_summary(context), **base}


def _signed_in(response: Response, token: str, database: Database, settings: Settings) -> dict[str, Any]:
    set_session_cookie(response, token, settings)
    return _session_payload(resolve_session(database, token, settings), settings)


_CSRF = {403: ["csrf_check_failed"]}


@router.get("/session", summary="Who is signed in (or that nobody is), and how the API is configured",
            responses=error_responses({}, validates_input=False))
def get_session(request: Request, database: Database = Depends(get_database),
                settings: Settings = Depends(get_settings)) -> Any:
    # accounts_available is False when this server's database lacks the account tables: the web app then says so
    # instead of every sign-up or sign-in failing with an unexplained error.
    if not accounts_schema_present(database):
        return _session_payload(None, settings, accounts_available=False)
    return _session_payload(current_session(request), settings)


@router.post("/signup", status_code=HTTPStatus.CREATED, dependencies=[Depends(require_csrf)],
             summary="Create your account with a team join code (member or admin), and sign in",
             responses=error_responses({403: ["invalid_join_code", "signup_closed", "csrf_check_failed"],
                                        409: ["email_already_registered", "team_workspace_missing"],
                                        422: ["invalid_input"], 429: ["rate_limited"]}))
def signup(body: SignupBody, request: Request, response: Response, database: Database = Depends(get_database),
           settings: Settings = Depends(get_settings)) -> Any:
    token = call(accounts.signup, database, settings, full_name=body.full_name, email=body.email,
                 password=body.password, join_code=body.join_code, client_ip=client_ip(request, settings))
    return _signed_in(response, token, database, settings)


@router.post("/login", dependencies=[Depends(require_csrf)],
             summary="Sign in with your email and password",
             responses=error_responses({401: ["invalid_credentials"], 403: ["account_inactive", "csrf_check_failed"],
                                        429: ["rate_limited"]}))
def login(body: LoginBody, request: Request, response: Response, database: Database = Depends(get_database),
          settings: Settings = Depends(get_settings)) -> Any:
    token = call(accounts.login, database, settings, email=body.email, password=body.password,
                 client_ip=client_ip(request, settings))
    return _signed_in(response, token, database, settings)


@router.post("/logout", dependencies=[Depends(require_csrf)], summary="Sign out: this session ends at once",
             responses=error_responses(_CSRF, validates_input=False))
def logout(request: Request, response: Response, database: Database = Depends(get_database),
           settings: Settings = Depends(get_settings)) -> Any:
    revoke_token(database, request.cookies.get(COOKIE_NAME))
    clear_session_cookie(response, settings)
    return {"authenticated": False}


@router.post("/password/change", dependencies=[Depends(require_csrf)],
             summary="Change your password (ends your other sessions)",
             responses=error_responses({401: ["not_authenticated"],
                                        403: ["current_password_incorrect", "csrf_check_failed"],
                                        422: ["invalid_input"], 429: ["rate_limited"]}))
def change_password(body: ChangePasswordBody, database: Database = Depends(get_database),
                    context: SessionContext = Depends(require_session)) -> Any:
    call(accounts.change_password, database, context, current_password=body.current_password,
         new_password=body.new_password)
    return {"changed": True}


@router.post("/password/forgot", status_code=HTTPStatus.ACCEPTED, dependencies=[Depends(require_csrf)],
             summary="Email a 6-digit password reset code (the answer never says whether the account exists)",
             responses=error_responses({**_CSRF, 429: ["rate_limited"]}))
def forgot_password(body: ForgotPasswordBody, request: Request, background: BackgroundTasks,
                    database: Database = Depends(get_database), settings: Settings = Depends(get_settings)) -> Any:
    answer, send_to = call(accounts.request_password_reset, database, settings, email=body.email,
                           client_ip=client_ip(request, settings))
    if send_to is not None:
        # After the response: the account lookup and the email never affect the answer or its timing.
        background.add_task(accounts.send_reset_code, database, settings, send_to)
    return answer


@router.post("/password/reset", dependencies=[Depends(require_csrf)],
             summary="Set a new password with the emailed code (ends every session), and sign in",
             responses=error_responses({**_CSRF, 410: ["reset_code_invalid"], 422: ["invalid_input"],
                                        429: ["rate_limited"]}))
def reset_password(body: ResetPasswordBody, request: Request, response: Response,
                   database: Database = Depends(get_database), settings: Settings = Depends(get_settings)) -> Any:
    token = call(accounts.reset_password, database, settings, email=body.email, code=body.code,
                 new_password=body.new_password, client_ip=client_ip(request, settings))
    return _signed_in(response, token, database, settings)


@router.get("/network-check", summary="How the server sees this request's address (administrators; to verify proxies)",
            description="For verifying AUTH_TRUSTED_PROXY_HOPS after a deployment (docs/DEPLOYMENT.md): the number "
                        "of X-Forwarded-For entries this request arrived with, the setting, and the address the rate "
                        "limits use for this caller. Open it from two different networks: each should show that "
                        "network's own public address, and forwarded_entries should equal trusted_proxy_hops. Shows "
                        "only the caller's own request; no other header is returned.",
            dependencies=[Depends(require_permission("team_management"))],
            responses=error_responses({401: ["not_authenticated"], 403: ["permission_denied"]},
                                      validates_input=False))
def get_network_check(request: Request, settings: Settings = Depends(get_settings)) -> Any:
    chain = forwarded_chain(request)
    hops = settings.auth_trusted_proxy_hops
    used = client_ip(request, settings)
    return {"trusted_proxy_hops": hops, "forwarded_entries": len(chain),
            "rate_limit_address": used,
            "address_source": "x_forwarded_for" if hops and len(chain) >= hops and used == chain[-hops]
            else "connecting_peer",
            "consistent": hops == 0 or len(chain) == hops,
            "note": "forwarded_entries > trusted_proxy_hops: another proxy appends an entry, or the client sent its "
                    "own header (only the right-most hops entries are trusted). forwarded_entries < "
                    "trusted_proxy_hops: fewer proxies than configured; the connecting peer is used."}

