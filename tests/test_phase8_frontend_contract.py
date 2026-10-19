"""P8-M1: the dashboard and the Phase 7 API agree, and the dashboard's types are the locked contract's.

- frontend/src/api/dashboard.ts lists every (method, path) the dashboard calls in DASHBOARD_ENDPOINTS. Each must
  exist in the API's OpenAPI document. Every operation in the Phase 7 contract lock must be either called by the
  dashboard or listed in NOT_CALLED with a reason, so a locked operation is never silently ignored.
- frontend/src/api/generated.ts must equal what scripts/phase8_generate_api_types.py renders from the live OpenAPI
  document (P8-Q2), so the dashboard's types cannot drift from the shapes the lock pins.

Pure: it builds the app but never opens a database connection.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from api import create_app
from data.config import Settings
from scripts.phase8_generate_api_types import OUTPUT, openapi_document, render

ROOT = Path(__file__).resolve().parents[1]
DASHBOARD = ROOT / "frontend" / "src" / "api" / "dashboard.ts"
LOCK = ROOT / "docs" / "api_contract_lock.json"
ENTRY = re.compile(r"^\s*(\w+): \['(GET|POST|PUT)', '(/[^']+)'\],$", re.MULTILINE)
NOT_CALLED_ENTRY = re.compile(r"^\s*'((?:GET|POST|PUT) /[^']+)': '([^']+)',$", re.MULTILINE)


@pytest.fixture(scope="module")
def dashboard_source() -> str:
    return DASHBOARD.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def dashboard_routes(dashboard_source) -> set[tuple[str, str]]:
    block = dashboard_source[dashboard_source.index("export const DASHBOARD_ENDPOINTS = {"):
                             dashboard_source.index("} as const satisfies")]
    routes = {(method, path) for _, method, path in ENTRY.findall(block)}
    assert len(routes) == block.count("['"), "a DASHBOARD_ENDPOINTS entry does not match the expected one-line form"
    return routes


@pytest.fixture(scope="module")
def not_called(dashboard_source) -> dict[str, str]:
    block = dashboard_source[dashboard_source.index("export const NOT_CALLED = {"):]
    block = block[:block.index("} as const")]
    return dict(NOT_CALLED_ENTRY.findall(block))


@pytest.fixture(scope="module")
def api_routes() -> set[tuple[str, str]]:
    paths = create_app(Settings(api_prefix="")).openapi()["paths"]
    return {(method.upper(), path) for path, methods in paths.items() for method in methods}


@pytest.fixture(scope="module")
def locked_operations() -> set[str]:
    return set(json.loads(LOCK.read_text(encoding="utf-8"))["operations"])


def test_every_route_the_dashboard_calls_exists(dashboard_routes, api_routes):
    assert dashboard_routes, "no dashboard routes parsed"
    assert dashboard_routes - api_routes == set()


def test_every_locked_operation_is_called_or_explicitly_not_called(dashboard_routes, not_called, locked_operations):
    called = {f"{method} {path}" for method, path in dashboard_routes}
    assert locked_operations - called - set(not_called) == set()
    assert set(not_called) <= locked_operations, "NOT_CALLED names an operation that is not locked"
    assert not set(not_called) & called, "an operation is both called and listed as not called"
    assert all(reason.strip() for reason in not_called.values())


def test_the_dashboard_calls_only_locked_operations(dashboard_routes, locked_operations):
    """The dashboard is built on the Phase 7 locked contract only (no human-input or unlocked route)."""
    assert {f"{method} {path}" for method, path in dashboard_routes} <= locked_operations


def test_the_generated_types_are_current():
    """Regenerate with `python -m scripts.phase8_generate_api_types` after any API change."""
    assert OUTPUT.read_text(encoding="utf-8") == render(openapi_document())


def test_the_generated_types_carry_the_locked_validation_literals():
    text = OUTPUT.read_text(encoding="utf-8")
    assert 'probability_status: "validated_playoff_success"' in text  # P7-D7, as locked
    assert "export interface CalibratedWinProbability {" in text
    assert "export interface StrategyOdds {" in text


def test_every_query_parameter_the_dashboard_sends_is_declared(dashboard_source, dashboard_routes):
    """FastAPI ignores an unknown query parameter, so a renamed `as_of` would silently show "now" while the page
    claims a moment. DASHBOARD_QUERY_PARAMS (enforced at runtime by call()) must match OpenAPI exactly."""
    block = dashboard_source[dashboard_source.index("export const DASHBOARD_QUERY_PARAMS"):]
    block = block[block.index("{") + 1:block.index("\n}\n")]
    declared_by_dashboard = {name: {p.strip().strip("'") for p in params.split(",") if p.strip()}
                             for name, params in re.findall(r"(\w+): \[([^\]]*)\]", block)}
    source = dashboard_source[dashboard_source.index("export const DASHBOARD_ENDPOINTS = {"):
                              dashboard_source.index("} as const satisfies")]
    endpoints = {name: (method, path) for name, method, path in ENTRY.findall(source)}
    assert set(declared_by_dashboard) == set(endpoints), "every endpoint needs a query-parameter list"
    paths = create_app(Settings(api_prefix="")).openapi()["paths"]
    for name, (method, path) in endpoints.items():
        operation = paths[path][method.lower()]
        openapi_query = {p["name"] for p in operation.get("parameters", []) if p["in"] == "query"}
        assert declared_by_dashboard[name] <= openapi_query, (name, declared_by_dashboard[name] - openapi_query)
        assert openapi_query <= declared_by_dashboard[name], (name, "the dashboard never sends", openapi_query - declared_by_dashboard[name])

