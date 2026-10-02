"""FastAPI dependency providers for the collaborators create_app builds.

create_app resolves Settings and constructs one Database, then stores both on
app.state. These read them back so routes declare what they need with
Depends(get_database) instead of reaching into request.app.state ad hoc.

Small on purpose, and written now rather than with the first data route, so the
convention is set before there is a second way to do it. Overriding either one
in a test is then FastAPI's standard dependency_overrides, with no patching of
application internals.

get_ranking_model/get_win_prob_model (Phase 4 Milestone 12) follow the exact
same pattern for the two ML models api.routes.predictions serves: create_app
loads whichever version Settings pins (type, version tag, sha256) exactly
once at startup (api.ml_loading), stores the result (a ServedModel, or None if
nothing is pinned or the pin failed its checks) on app.state, and these two
functions read it back. get_epa_source does the same for the EPA source,
lazily (it needs the database). None is a real, expected, and correctly
representable value here -- see api.ml_loading's own docstring for why "no
model pinned yet" must never be confused with "the process failed to boot".
"""

from __future__ import annotations

from starlette.requests import Request

from api.ml_loading import ServedEpaSource, ServedModel, load_epa_source
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


def get_ranking_model(request: Request) -> ServedModel | None:
    """Return the pinned ranking model (M5 v2) with its identity, or None if nothing
    is pinned/loadable -- routes must handle None as a real, documented
    model_not_loaded response, never treat it as an unreachable branch."""
    return request.app.state.ranking_model


def get_win_prob_model(request: Request) -> ServedModel | None:
    """Return the pinned win-probability model (M6 + its D18-evaluated calibrator), or
    None -- see get_ranking_model's docstring for the identical contract."""
    return request.app.state.win_prob_model


def get_epa_source(request: Request) -> ServedEpaSource | None:
    """The configured EPA source, loaded on first use and then reused; None (served as
    epa_source_not_loaded) if it is unconfigured or fails its integrity checks. A
    failure is not cached, so a later request retries (e.g. once PostgreSQL is up)."""
    state = request.app.state
    if state.epa_source is None:
        with state.epa_source_lock:
            if state.epa_source is None:
                state.epa_source = load_epa_source(state.settings, state.database)
    return state.epa_source
