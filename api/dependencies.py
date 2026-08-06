"""FastAPI dependency providers for the collaborators create_app builds.

create_app resolves Settings and constructs one Database, then stores both on
app.state. These read them back so routes declare what they need with
Depends(get_database) instead of reaching into request.app.state ad hoc.

Small on purpose, and written now rather than with the first data route, so the
convention is set before there is a second way to do it. Overriding either one
in a test is then FastAPI's standard dependency_overrides, with no patching of
application internals.
"""

from __future__ import annotations

from starlette.requests import Request

from data.config import Settings
from database.connection import Database


def get_settings(request: Request) -> Settings:
    """Return the Settings instance this application was built with."""
    return request.app.state.settings


def get_database(request: Request) -> Database:
    """Return the shared Database helper.

    Note this is a connection *factory*, not a connection: Database opens and
    closes a psycopg connection per Database.connection() call. Nothing is held
    open between requests.
    """
    return request.app.state.database
