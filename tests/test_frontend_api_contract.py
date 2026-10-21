"""The web app (frontend/) and the human-input API agree on every route.

frontend/src/api/client.ts lists every (method, path) the web app calls in ENDPOINTS. This test reads that list
and checks it against the API's live OpenAPI schema, in both directions:
- every route the web app calls exists, with that method;
- every human-input route the API serves is reachable from the web app.

Pure: it builds the app but never opens a database connection.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from api import create_app
from data.config import Settings

CLIENT = Path(__file__).resolve().parents[1] / "frontend" / "src" / "api" / "client.ts"
ENTRY = re.compile(r"^\s*(\w+): \['(GET|POST|PUT)', '(/[^']+)'\],$", re.MULTILINE)


@pytest.fixture(scope="module")
def frontend_routes() -> set[tuple[str, str]]:
    source = CLIENT.read_text(encoding="utf-8")
    block = source[source.index("export const ENDPOINTS = {"):source.index("} as const satisfies")]
    routes = {(method, path) for _, method, path in ENTRY.findall(block)}
    assert len(routes) == block.count("['"), "an ENDPOINTS entry does not match the expected one-line form"
    return routes


@pytest.fixture(scope="module")
def api_routes() -> set[tuple[str, str]]:
    paths = create_app(Settings()).openapi()["paths"]
    return {(method.upper(), path) for path, methods in paths.items() if path.startswith("/human-inputs")
            for method in methods}


def test_every_route_the_web_app_calls_exists(frontend_routes, api_routes):
    assert frontend_routes - api_routes == set()


def test_every_human_input_route_is_reachable_from_the_web_app(frontend_routes, api_routes):
    assert api_routes - frontend_routes == set()


def test_the_human_input_list_calls_only_human_input_routes(frontend_routes):
    """The human-input list (ENDPOINTS) only enters and reviews human inputs; it calls no prediction or analysis
    endpoint. The historical explorer's reads are listed separately (EXPLORER_ENDPOINTS, below)."""
    assert all(path.startswith("/human-inputs/") for _, path in frontend_routes)


# The historical explorer (Kanav, 2026-10-11): the web app may read season data and the existing analysis endpoints,
# but only through EXPLORER_ENDPOINTS, which is read-only, never a human-input route, never a Phase 6 route (P6-A1).
EXPLORER_ENTRY = re.compile(r"^\s*(\w+): \['(GET)', '(/[^']+)'\],$", re.MULTILINE)


@pytest.fixture(scope="module")
def explorer_routes() -> set[tuple[str, str]]:
    source = CLIENT.read_text(encoding="utf-8")
    start = source.index("export const EXPLORER_ENDPOINTS = {")
    block = source[start:source.index("} as const satisfies", start)]
    routes = {(method, path) for _, method, path in EXPLORER_ENTRY.findall(block)}
    assert len(routes) == block.count("['"), "an EXPLORER_ENDPOINTS entry is not a one-line GET"
    return routes


def test_the_explorer_only_reads_existing_routes(explorer_routes):
    all_routes = {(method.upper(), path) for path, methods in create_app(Settings()).openapi()["paths"].items()
                  for method in methods}
    assert explorer_routes and explorer_routes <= all_routes
    assert all(method == "GET" for method, _ in explorer_routes)
    assert not [p for _, p in explorer_routes if p.startswith("/human-inputs")]
    assert not [p for _, p in explorer_routes if re.search(r"strategy|alliance-selection|pick-list|playoff", p)]
