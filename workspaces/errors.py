"""The one exception the workspace rules raise. The API turns it into its error envelope (api.routes.auth)."""

from __future__ import annotations

from http import HTTPStatus


class WorkspaceError(Exception):
    """A refused request: a stable machine-readable code, an HTTP status and a message safe to show the caller."""

    def __init__(self, status: HTTPStatus, code: str, message: str) -> None:
        super().__init__(message)
        self.status = status
        self.code = code
        self.message = message


def invalid_input(message: str) -> WorkspaceError:
    return WorkspaceError(HTTPStatus.UNPROCESSABLE_ENTITY, "invalid_input", message)


def not_found(code: str, message: str) -> WorkspaceError:
    return WorkspaceError(HTTPStatus.NOT_FOUND, code, message)


def conflict(code: str, message: str) -> WorkspaceError:
    return WorkspaceError(HTTPStatus.CONFLICT, code, message)


def forbidden(code: str, message: str) -> WorkspaceError:
    return WorkspaceError(HTTPStatus.FORBIDDEN, code, message)


# Login failures all read the same, whatever was wrong, so the response never says which team numbers or emails
# have accounts.
INVALID_CREDENTIALS = "invalid_credentials"
INVALID_CREDENTIALS_MESSAGE = "The team number, email or password is not correct."


def invalid_credentials() -> WorkspaceError:
    return WorkspaceError(HTTPStatus.UNAUTHORIZED, INVALID_CREDENTIALS, INVALID_CREDENTIALS_MESSAGE)
