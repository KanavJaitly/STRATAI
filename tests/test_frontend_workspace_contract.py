"""The web app and the team-workspace API agree on every route.

frontend/src/auth/api.ts lists every (method, path) the web app calls for accounts, Team Management and team
scouting in WORKSPACE_ENDPOINTS. This test checks that list against the API's live OpenAPI schema, both ways:
every route the web app calls exists with that method, and every /auth and /workspace route the API serves is
reachable from the web app. Pure: it builds the app but never opens a database connection.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from api import create_app
from data.config import Settings

CLIENT = Path(__file__).resolve().parents[1] / "frontend" / "src" / "auth" / "api.ts"
ENTRY = re.compile(r"^\s*(\w+): \['(GET|POST)', '(/[^']+)'\],$", re.MULTILINE)


@pytest.fixture(scope="module")
def frontend_routes() -> set[tuple[str, str]]:
    source = CLIENT.read_text(encoding="utf-8")
    block = source[source.index("export const WORKSPACE_ENDPOINTS = {"):source.index("} as const satisfies")]
    routes = {(method, path) for _, method, path in ENTRY.findall(block)}
    assert len(routes) == block.count("['"), "a WORKSPACE_ENDPOINTS entry does not match the expected one-line form"
    return routes


@pytest.fixture(scope="module")
def api_routes() -> set[tuple[str, str]]:
    paths = create_app(Settings()).openapi()["paths"]
    return {(method.upper(), path) for path, methods in paths.items()
            if path.startswith(("/auth", "/workspace")) for method in methods}


def test_every_route_the_web_app_calls_exists(frontend_routes, api_routes):
    assert frontend_routes - api_routes == set()


def test_every_team_workspace_route_is_reachable_from_the_web_app(frontend_routes, api_routes):
    assert api_routes - frontend_routes == set()
