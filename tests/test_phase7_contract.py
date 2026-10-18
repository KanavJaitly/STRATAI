"""Phase 7 contract tests (P7-M1): the frozen specification, the response-shape lock, the declared error contract
and docs/phase7.md agree with the live application.

Pure: these read files, the git index and the app's OpenAPI document, never a database.
"""

from __future__ import annotations

import re
import subprocess
from datetime import date
from http import HTTPStatus
from pathlib import Path

import pytest

from api import create_app
from api.errors import INTERNAL_ERROR_CODE, VALIDATION_ERROR_CODE, error_code_for_status
from data.config import Settings
from scripts.phase7_contract_lock import CODE_PATTERN as _CODE
from scripts.phase7_contract_lock import (
    building_blocks,
    contract_of,
    differences,
    live_contract,
    locked_part,
    operations_of,
    read_lock,
    valid_decision,
)

ROOT = Path(__file__).resolve().parents[1]
FREEZE = ROOT / ".agent" / "phase7" / "P7_M0_FREEZE.md"
DOCS = ROOT / "docs" / "phase7.md"
_SOURCE_DIRS = ("api", "data", "ml")


@pytest.fixture(scope="module")
def openapi() -> dict:
    return create_app(Settings()).openapi()


@pytest.fixture(scope="module")
def lock() -> dict:
    return read_lock()


def _blob(path: str) -> str:
    return subprocess.run(["git", "hash-object", path], capture_output=True, text=True, check=True,
                          cwd=ROOT).stdout.strip()


def test_p7_m0_frozen_files_are_unchanged():
    freeze = FREEZE.read_text(encoding="utf-8")
    for path in ("docs/P7Milestones.md", ".agent/phase7/P7_M0_DECISIONS.md", "docs/ROADMAP.md",
                 "docs/P6Milestones.md", ".agent/phase6/P6_M0_DECISIONS.md"):
        row = next(line for line in freeze.splitlines() if f"`{path}`" in line)
        assert re.search(r"`([0-9a-f]{40})`", row).group(1) == _blob(path), path


# --- the response-shape lock (P7-A4, P7-DM2) --------------------------------------------------------------------


def test_the_live_application_matches_the_contract_lock(lock):
    diff = differences(locked_part(lock), live_contract(list(lock["operations"])))
    assert not diff["changed"] and not diff["added"], diff


def test_every_lock_revision_is_dated_and_reasoned(lock):
    assert lock["revisions"], "the lock has no history"
    for revision in lock["revisions"]:
        assert date.fromisoformat(revision["date"]) <= date.today()
        assert revision["reason"].strip() and revision["command"] in ("lock", "relock", "unlock")
        # A change to (or removal of) an already-locked entry is only ever written with the decision that allowed
        # it, naming an existing decision document and a date.
        if revision["changed"] or revision["operations_removed"]:
            assert valid_decision(revision["decision"]), revision


def test_the_lock_detects_a_planted_shape_change(openapi, lock):
    """Removing a field from the error envelope, or changing a declared error code, must fail the lock."""
    import copy

    planted = copy.deepcopy(openapi)
    del planted["components"]["schemas"]["ErrorBody"]["properties"]["request_id"]
    diff = differences(locked_part(lock), {**contract_of(planted, lock["operations"]),
                                           "building_blocks": building_blocks()})
    assert any("ErrorBody" in leaf and "request_id" in leaf for leaf in diff["changed"]), diff

    planted = copy.deepcopy(openapi)
    planted["paths"]["/ready"]["get"]["responses"]["503"]["description"] = "Service Unavailable. Error codes: `down`."
    diff = differences(locked_part(lock), {**contract_of(planted, lock["operations"]),
                                           "building_blocks": building_blocks()})
    assert any(leaf.startswith("/operations/GET /ready/responses/503/codes") for leaf in diff["changed"]), diff


def test_documentation_changes_are_not_shape_changes(openapi, lock):
    import copy

    edited = copy.deepcopy(openapi)
    edited["paths"]["/health"]["get"]["description"] = "reworded"
    edited["components"]["schemas"]["ErrorBody"]["properties"]["code"]["description"] = "reworded"
    diff = differences(locked_part(lock), {**contract_of(edited, lock["operations"]),
                                           "building_blocks": building_blocks()})
    assert diff == {"changed": [], "added": []}


def test_every_locked_operation_is_documented(lock):
    text = DOCS.read_text(encoding="utf-8")
    for operation in lock["operations"]:
        assert f"`{operation}`" in text, operation


# --- the declared error contract (P7-M1 (f)) ---------------------------------------------------------------------


def test_every_operation_declares_500_and_only_envelope_errors(openapi):
    for key, operation in operations_of(openapi).items():
        responses = operation["responses"]
        assert "500" in responses, key
        for status, response in responses.items():
            if status[0] in "45":
                schema = response["content"]["application/json"]["schema"]
                assert schema == {"$ref": "#/components/schemas/ErrorResponse"}, (key, status)
                assert _CODE.findall(response["description"]), (key, status, "declares no error code")


def _can_fail_validation(operation: dict) -> bool:
    """A body, a required query parameter, or a non-string parameter can fail request validation. A path string
    cannot (the router never matches an empty segment), and neither can an optional string query."""
    if operation.get("requestBody"):
        return True
    for parameter in operation.get("parameters", []):
        schema = parameter.get("schema", {})
        types = {schema.get("type")} | {s.get("type") for s in schema.get("anyOf", [])}
        if (parameter["in"] == "query" and parameter.get("required")) or types - {"string", "null", None}:
            return True
    return False


def _declared(operation: dict, status: str) -> list[str]:
    return _CODE.findall(operation["responses"].get(status, {}).get("description", ""))


def test_validation_error_is_declared_exactly_where_it_can_happen(openapi):
    for key, operation in operations_of(openapi).items():
        if _can_fail_validation(operation):
            assert VALIDATION_ERROR_CODE in _declared(operation, "422"), key
        if not operation.get("parameters") and not operation.get("requestBody"):
            assert VALIDATION_ERROR_CODE not in _declared(operation, "422"), key


def _route_scope_source(endpoint) -> str:
    """The source of a route's own module plus every api/data/ml module it imports from: where its codes come
    from (constants in api.routes.common, data.human_inputs' HumanInputError codes, data.metrics.read statuses)."""
    import inspect
    import sys
    import types

    module = sys.modules[endpoint.__module__]
    names = {module.__name__}
    for value in vars(module).values():
        owner = value.__name__ if isinstance(value, types.ModuleType) else getattr(value, "__module__", None)
        if isinstance(owner, str) and owner.split(".")[0] in _SOURCE_DIRS:
            names.add(owner)
    return "\n".join(inspect.getsource(sys.modules[name]) for name in sorted(names))


def test_every_declared_error_code_is_raised_by_the_routes_own_code():
    """A declared code must appear in the route's own module or a module it imports. A code copied onto the
    wrong route, a typo or a stale code fails here. (Behavioural tests in each endpoint family exercise each
    code it can actually return, with tests/phase7_support.assert_declared_error.)

    The route walk is proven complete against the OpenAPI document (api_routes_checked). Until 2026-10-18 this test
    walked `app.routes` for APIRoute, which FastAPI 0.141 wraps, so it checked nothing; see M01_ACCEPTANCE.md.
    """
    app = create_app(Settings())
    problems, checked = _codes_not_raised_by_their_route(app, app.openapi())
    assert not problems, problems
    assert checked > 50, f"only {checked} declared codes were checked; the walk is not reaching the routes"


def _codes_not_raised_by_their_route(app, openapi: dict) -> tuple[list[tuple], int]:
    """(declared codes absent from their route's own code, number of codes checked) for an OpenAPI document."""
    from tests.phase7_support import api_routes_checked

    problems, checked = [], 0
    for path, route in api_routes_checked(app):
        source = _route_scope_source(route.endpoint)
        for method in route.methods:
            operation = openapi["paths"][path][method.lower()]
            for status, response in operation["responses"].items():
                if status[0] not in "45":
                    continue
                derived = {error_code_for_status(int(status)), INTERNAL_ERROR_CODE, VALIDATION_ERROR_CODE}
                for code in _CODE.findall(response["description"]):
                    checked += 1
                    if code not in derived and f'"{code}"' not in source:
                        problems.append((method, path, status, code))
    return problems, checked


def test_the_declared_code_check_catches_a_code_on_the_wrong_route():
    """Not vacuous: the real check, run on a document with `match_not_found` planted on the strength route (whose
    own code never raises it), reports exactly that code."""
    import copy

    app = create_app(Settings())
    planted = copy.deepcopy(app.openapi())
    path = "/teams/{team_number}/events/{event_key}/strength"
    planted["paths"][path]["get"]["responses"]["404"]["description"] += " `match_not_found`."
    problems, _ = _codes_not_raised_by_their_route(app, planted)
    assert problems == [("GET", path, "404", "match_not_found")]


# --- Phase 7's own endpoints -----------------------------------------------------------------------------------

PHASE7_ROUTE_MODULES = {"api.routes.strategy", "api.routes.alliance_selection", "api.routes.pre_match_report",
                        "api.routes.discovery"}


def _documented_phase7_operations() -> set[tuple[str, str]]:
    text = DOCS.read_text(encoding="utf-8")
    section = text.split("## Endpoints owned by Phase 7", 1)[1].split("\n## ", 1)[0]
    return set(re.findall(r"`(GET|POST|PUT|DELETE) (/[^`]+)`", section))


def test_phase7_owned_endpoints_are_live_new_and_served_by_phase7_modules():
    """docs/phase7.md's "Endpoints owned by Phase 7" list excludes paths from the Phase 3 documentation checks
    (tests/test_metrics_docs_contract.py), so it must not be able to claim an earlier phase's route: every entry
    is live, is served by a Phase 7 route module, and is not one of the routes that existed before Phase 7."""
    from tests.phase7_support import api_routes_checked
    from tests.test_api_foundation import PRE_PHASE7_PATHS

    served = {(method, path): route.endpoint.__module__ for path, route in api_routes_checked(create_app(Settings()))
              for method in route.methods}
    for method, path in _documented_phase7_operations():
        assert (method, path) in served, (method, path, "is not live")
        assert served[(method, path)] in PHASE7_ROUTE_MODULES, (method, path, served[(method, path)])
        assert path not in PRE_PHASE7_PATHS, (method, path, "existed before Phase 7")
    phase7_live = {key for key, module in served.items() if module in PHASE7_ROUTE_MODULES}
    assert phase7_live == _documented_phase7_operations(), phase7_live ^ _documented_phase7_operations()


# --- cross-cutting rules ---------------------------------------------------------------------------------------


def _reaches(schema: dict, components: dict, field: str, seen: set[str]) -> bool:
    if isinstance(schema, dict):
        if field in schema.get("properties", {}):
            return True
        ref = schema.get("$ref", "")
        if ref.startswith("#/components/schemas/"):
            name = ref.rsplit("/", 1)[1]
            if name in seen:
                return False
            seen.add(name)
            return _reaches(components[name], components, field, seen)
        return any(_reaches(value, components, field, seen) for value in schema.values())
    if isinstance(schema, list):
        return any(_reaches(item, components, field, seen) for item in schema)
    return False


def test_every_route_serving_reliability_score_carries_the_interim_caveat(openapi):
    """P7 standing rule: the Phase 3 INTERIM caveat travels with reliability_score on every route that serves it."""
    components = openapi["components"]["schemas"]
    serving = []
    for key, operation in operations_of(openapi).items():
        ok = operation["responses"].get(str(int(HTTPStatus.OK)), {})
        schema = ok.get("content", {}).get("application/json", {}).get("schema", {})
        if _reaches(schema, components, "reliability_score", set()):
            serving.append(key)
            assert "INTERIM" in operation.get("description", ""), key
    assert serving, "no route serves reliability_score; the check would be vacuous"


def test_paths_are_unversioned_and_the_docs_are_served():
    """P7-Q6: no version prefix; /docs and /openapi.json stay on."""
    from data.config import Settings as SettingsClass

    app = create_app(Settings(api_prefix=""))
    assert SettingsClass.model_fields["api_prefix"].default == ""  # the declared default, not this machine's .env
    assert app.docs_url == "/docs" and app.openapi_url == "/openapi.json"
    assert not [path for path in app.openapi()["paths"] if re.match(r"^/(api/)?v\d+/", path)]


def test_docs_cover_every_milestone_and_decision():
    text = DOCS.read_text(encoding="utf-8")
    for milestone in [f"P7-M{i}" for i in range(10)]:
        assert milestone in text, milestone
    assert "P7_M0_DECISIONS.md" in text and "P7_M0_FREEZE.md" in text
    assert "## Endpoints owned by Phase 7" in text and "## Contract-test changes" in text


def test_the_lock_and_examples_hold_under_a_deployment_api_prefix(monkeypatch, tmp_path):
    """A gateway mount (API_PREFIX) moves the data routes, not their shapes: the lock check still matches, and a
    captured example still attaches to its (now prefixed) operation."""
    import json

    from api.examples import install_examples

    monkeypatch.setenv("API_PREFIX", "/api")
    lock = read_lock()
    diff = differences(locked_part(lock), live_contract(list(lock["operations"])))
    assert diff == {"changed": [], "added": []}, diff
    app = create_app(Settings())
    assert "/api/events" in app.openapi()["paths"]
    examples = tmp_path / "ex"
    examples.mkdir()
    (examples / "e.json").write_text(json.dumps({
        "operation": "GET /events", "status": 200, "name": "one", "kind": "synthetic", "summary": "s",
        "environment": {}, "request": {"query": {"season": 2026}}, "response": {"season": 2026}}), encoding="utf-8")
    app = create_app(Settings())
    app.openapi_schema = None
    install_examples(app, examples, prefix="/api")
    shown = app.openapi()["paths"]["/api/events"]["get"]["responses"]["200"]["content"]["application/json"]
    assert shown["examples"]["one"]["value"] == {"season": 2026}
