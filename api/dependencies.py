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
loads whichever version is pinned by Settings.ml_*_model_version_tag exactly
once at startup (api.ml_loading), stores the result (a model, or None if
nothing is pinned or the pinned version failed to load) on app.state, and
these two functions read it back. None is a real, expected, and correctly
representable value here -- see api.ml_loading's own docstring for why "no
model pinned yet" must never be confused with "the process failed to boot".
"""

from __future__ import annotations

from starlette.requests import Request

from data.config import Settings
from database.connection import Database
from ml.models.ranking_xgb import RankingXGBModel
from ml.models.win_prob import WinProbXGBModel
from ml.registry import ModelManifest


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


def get_ranking_model(request: Request) -> RankingXGBModel | None:
    """Return the pinned ranking model, or None if nothing is currently
    pinned/loadable -- routes must handle None as a real, documented
    model_not_loaded response, never treat it as an unreachable branch."""
    return request.app.state.ranking_model


def get_win_prob_model(request: Request) -> WinProbXGBModel | None:
    """Return the pinned win-probability model, or None -- see
    get_ranking_model's docstring for the identical contract."""
    return request.app.state.win_prob_model


def get_ranking_model_manifest(request: Request) -> ModelManifest | None:
    """The pinned ranking model's own registry manifest -- version, training
    dataset hash, feature list, seed, metrics -- so a response can echo
    exactly what produced it. None whenever get_ranking_model is None."""
    return request.app.state.ranking_model_manifest


def get_win_prob_model_manifest(request: Request) -> ModelManifest | None:
    """See get_ranking_model_manifest's docstring for the identical
    contract, for the win-probability model."""
    return request.app.state.win_prob_model_manifest
