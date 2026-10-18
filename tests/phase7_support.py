"""Shared assertions for Phase 7 API tests.

tests/test_phase7_contract.py checks statically that every *declared* error code exists in the route's own code.
The other direction -- every code a route actually *returns* is declared -- can only be checked by driving each
error path, so each endpoint family's behavioural tests call assert_declared_error on every error response.
"""

from __future__ import annotations

from typing import Any

from api.errors import INTERNAL_ERROR_CODE, VALIDATION_ERROR_CODE, error_code_for_status
from scripts.phase7_contract_lock import CODE_PATTERN


def api_routes(app: Any) -> list[tuple[str, Any]]:
    """Every APIRoute the application serves, with its full path: (full path, route).

    FastAPI 0.141 keeps an included router as one `_IncludedRouter` entry in `app.routes`, so walking `app.routes`
    for APIRoute finds nothing; a test that walked it that way passed vacuously. The walk is api.examples'
    iter_api_routes (a mounted sub-application is refused). Callers should use api_routes_checked, which proves the
    walk complete against the OpenAPI document.
    """
    from api.examples import iter_api_routes

    try:
        return iter_api_routes(app)
    except ValueError as exc:
        raise AssertionError(str(exc)) from exc


def api_routes_checked(app: Any) -> list[tuple[str, Any]]:
    """api_routes, asserted to cover exactly the operations in the OpenAPI document -- so a route walk can never
    silently find nothing again."""
    routes = api_routes(app)
    walked = {(method, path) for path, route in routes if route.include_in_schema for method in route.methods}
    documented = {(method.upper(), path) for path, item in app.openapi()["paths"].items() for method in item}
    assert walked == documented, f"route walk incomplete: {sorted(walked ^ documented)[:10]}"
    return routes


def stub_served_model(*, predict_win_prob: Any = None, predict_rating: Any = None, sha256: str = "stub",
                      model_type: str = "stub") -> Any:
    """A stand-in for api.ml_loading.ServedModel in route tests: the model's prediction methods plus the served
    identity (sha256 and identity()), the same interface the routes read."""
    from types import SimpleNamespace

    model = SimpleNamespace(predict_win_prob=predict_win_prob or (lambda row: 0.5),
                            predict_rating=predict_rating or (lambda features: 0.0))
    identity = {"model_type": model_type, "model_version": "stub", "model_version_tag": "stub", "model_sha256": sha256,
                "training_dataset_hash": "stub", "provenance": {}}
    return SimpleNamespace(model=model, sha256=sha256, identity=lambda: dict(identity))


def declared_codes(openapi: dict[str, Any], method: str, path: str, status: int) -> set[str]:
    """The error codes an operation declares for one status (empty when the status is not declared)."""
    response = openapi["paths"][path][method.lower()]["responses"].get(str(status))
    if response is None:
        return set()
    return set(CODE_PATTERN.findall(response.get("description", "")))


def assert_declared_error(openapi: dict[str, Any], response: Any, method: str, path: str,
                          code: str | None = None) -> dict[str, Any]:
    """Assert `response` is an error envelope whose status and code the operation declares (and, when given,
    that the code is `code`). Returns the envelope's `error` object for further checks."""
    body = response.json()
    error = body["error"]
    assert error["status"] == response.status_code
    declared = declared_codes(openapi, method, path, response.status_code)
    assert declared, f"{method} {path} does not declare status {response.status_code}"
    allowed = declared | ({error_code_for_status(response.status_code)} if response.status_code >= 500 else set())
    assert error["code"] in allowed or error["code"] in {VALIDATION_ERROR_CODE, INTERNAL_ERROR_CODE} & declared, (
        f"{method} {path} returned undeclared code {error['code']!r} at {response.status_code}; declared {declared}")
    if code is not None:
        assert error["code"] == code, error
    return error


__all__ = ["api_routes", "api_routes_checked", "assert_declared_error", "declared_codes", "stub_served_model"]
