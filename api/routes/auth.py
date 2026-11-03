"""Authentication: team registration, the first administrator, sign-in and sign-out, passwords, invitations.

Thin HTTP wrappers over workspaces.accounts (docs/team_workspaces.md). Every POST here needs the CSRF header
(api.session). Secret tokens (invitation, reset) travel only in request bodies, never in a path or query string,
so they never reach the request log.

Error codes: `invalid_input` and `validation_error` (422), `invalid_credentials`, `invalid_setup_credentials`,
`existing_account_password_mismatch`, `not_authenticated` (401), `account_inactive`, `current_password_incorrect`,
`csrf_check_failed` (403), `team_already_registered`, `already_member` (409), `invitation_invalid`,
`invitation_expired`, `reset_link_invalid` (410), `rate_limited` (429).
"""

from __future__ import annotations

from http import HTTPStatus
from typing import Any

from fastapi import APIRouter, Depends, Response
from pydantic import BaseModel, ConfigDict, Field
from starlette.requests import Request

from api.contract import error_responses
from api.dependencies import get_database, get_settings
from api.session import (
    call,
    clear_session_cookie,
    client_ip,
    current_session,
    require_csrf,
    require_session,
    set_session_cookie,
)
from data.config import Settings
from database.connection import Database
from workspaces import accounts, mailer
from workspaces.sessions import COOKIE_NAME, SessionContext, resolve_session, revoke_token

router = APIRouter(prefix="/auth", tags=["authentication"])

_TEXT = 512  # generous upper bounds on every field; the rules in workspaces/ set the real limits


class _Body(BaseModel):
    model_config = ConfigDict(extra="forbid")


class RegisterTeamBody(_Body):
    team_number: int
    team_name: str = Field(max_length=_TEXT)
    setup_password: str = Field(max_length=_TEXT)


class InitialAdminBody(_Body):
    team_number: int
    setup_password: str = Field(max_length=_TEXT)
    full_name: str = Field(max_length=_TEXT)
    email: str = Field(max_length=_TEXT)
    password: str = Field(max_length=_TEXT)


class LoginBody(_Body):
    team_number: int
    email: str = Field(max_length=_TEXT)
    password: str = Field(max_length=_TEXT)


class ChangePasswordBody(_Body):
    current_password: str = Field(max_length=_TEXT)
    new_password: str = Field(max_length=_TEXT)


class ForgotPasswordBody(_Body):
    team_number: int
    email: str = Field(max_length=_TEXT)


class ResetPasswordBody(_Body):
    token: str = Field(max_length=_TEXT)
    new_password: str = Field(max_length=_TEXT)


class InvitationTokenBody(_Body):
    token: str = Field(max_length=_TEXT)


class AcceptInvitationBody(_Body):
    token: str = Field(max_length=_TEXT)
    full_name: str | None = Field(default=None, max_length=_TEXT)
    password: str = Field(max_length=_TEXT)


def _session_payload(context: SessionContext | None, settings: Settings) -> dict[str, Any]:
    base = {"access_policy": settings.access_policy,
            "email_delivery_configured": mailer.email_channel(settings) is not None}
    if context is None:
        return {"authenticated": False, **base}
    return {**accounts.session_summary(context), **base}


def _signed_in(response: Response, token: str, database: Database, settings: Settings) -> dict[str, Any]:
    set_session_cookie(response, token, settings)
    return _session_payload(resolve_session(database, token, settings), settings)


_CSRF = {403: ["csrf_check_failed"]}


@router.get("/session", summary="Who is signed in (or that nobody is), and how the API is configured",
            responses=error_responses({}, validates_input=False))
def get_session(request: Request, settings: Settings = Depends(get_settings)) -> Any:
    return _session_payload(current_session(request), settings)


@router.post("/teams/register", status_code=HTTPStatus.CREATED, dependencies=[Depends(require_csrf)],
             summary="Register a new team workspace (it starts pending verification)",
             responses=error_responses({**_CSRF, 409: ["team_already_registered"], 422: ["invalid_input"],
                                        429: ["rate_limited"]}))
def register_team(body: RegisterTeamBody, request: Request, database: Database = Depends(get_database),
                  settings: Settings = Depends(get_settings)) -> Any:
    return call(accounts.register_workspace, database, team_number=body.team_number, team_name=body.team_name,
                setup_password=body.setup_password, client_ip=client_ip(request, settings))


@router.post("/teams/initial-admin", status_code=HTTPStatus.CREATED, dependencies=[Depends(require_csrf)],
             summary="Create the team's first administrator with the setup password, and sign in",
             responses=error_responses({401: ["invalid_setup_credentials", "existing_account_password_mismatch"],
                                        **_CSRF, 422: ["invalid_input"], 429: ["rate_limited"]}))
def create_initial_admin(body: InitialAdminBody, request: Request, response: Response,
                         database: Database = Depends(get_database), settings: Settings = Depends(get_settings)) -> Any:
    token = call(accounts.create_initial_admin, database, settings, team_number=body.team_number,
                 setup_password=body.setup_password, full_name=body.full_name, email=body.email,
                 password=body.password, client_ip=client_ip(request, settings))
    return _signed_in(response, token, database, settings)


@router.post("/login", dependencies=[Depends(require_csrf)],
             summary="Sign in with your team number, email and your own password",
             responses=error_responses({401: ["invalid_credentials"], 403: ["account_inactive", "csrf_check_failed"],
                                        429: ["rate_limited"]}))
def login(body: LoginBody, request: Request, response: Response, database: Database = Depends(get_database),
          settings: Settings = Depends(get_settings)) -> Any:
    token = call(accounts.login, database, settings, team_number=body.team_number, email=body.email,
                 password=body.password, client_ip=client_ip(request, settings))
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
             summary="Email a password reset link (the answer never says whether the account exists)",
             responses=error_responses({**_CSRF, 429: ["rate_limited"]}))
def forgot_password(body: ForgotPasswordBody, request: Request, database: Database = Depends(get_database),
                    settings: Settings = Depends(get_settings)) -> Any:
    return call(accounts.request_password_reset, database, settings, team_number=body.team_number, email=body.email,
                client_ip=client_ip(request, settings))


@router.post("/password/reset", dependencies=[Depends(require_csrf)],
             summary="Set a new password with a reset link's token (ends every session)",
             responses=error_responses({**_CSRF, 410: ["reset_link_invalid"], 422: ["invalid_input"],
                                        429: ["rate_limited"]}))
def reset_password(body: ResetPasswordBody, request: Request, database: Database = Depends(get_database),
                   settings: Settings = Depends(get_settings)) -> Any:
    call(accounts.reset_password, database, token=body.token, new_password=body.new_password,
         client_ip=client_ip(request, settings))
    return {"reset": True}


@router.post("/invitations/preview", dependencies=[Depends(require_csrf)],
             summary="What an invitation offers (team, role, email), for the acceptance page",
             responses=error_responses({**_CSRF, 410: ["invitation_invalid", "invitation_expired"],
                                        429: ["rate_limited"]}))
def preview_invitation(body: InvitationTokenBody, request: Request, database: Database = Depends(get_database),
                       settings: Settings = Depends(get_settings)) -> Any:
    return call(accounts.preview_invitation, database, token=body.token, client_ip=client_ip(request, settings))


@router.post("/invitations/accept", status_code=HTTPStatus.CREATED, dependencies=[Depends(require_csrf)],
             summary="Accept an invitation: create your account (or join with an existing one) and sign in",
             responses=error_responses({401: ["existing_account_password_mismatch"], **_CSRF,
                                        409: ["already_member"], 410: ["invitation_invalid", "invitation_expired"],
                                        422: ["invalid_input"], 429: ["rate_limited"]}))
def accept_invitation(body: AcceptInvitationBody, request: Request, response: Response,
                      database: Database = Depends(get_database), settings: Settings = Depends(get_settings)) -> Any:
    token = call(accounts.accept_invitation, database, settings, token=body.token, full_name=body.full_name,
                 password=body.password, client_ip=client_ip(request, settings))
    return _signed_in(response, token, database, settings)
