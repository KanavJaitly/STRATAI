"""Captured request/response examples, attached to the OpenAPI document (Phase 7, P7-M1 (b); P7-Q4).

Examples live as JSON files under docs/api_examples/ (one file per example), written by the P7-M8 capture script
from real calls in a named environment. Each file is::

    {"operation": "GET /events/{event_key}/analysis",   # METHOD and the OpenAPI path template
     "status": 200,
     "name": "2026casj_mid_event",                       # unique within its operation and status
     "kind": "real" | "refusal_only" | "synthetic",      # P7-Q1 / P7-M8: refusal-only and synthetic are labelled
     "summary": "One line saying what the example shows",
     "environment": {...},                               # where it was captured (models, EPA source, database)
     "request": {"path_params": {...}, "query": {...}, "body": ...},
     "response": {...}}

The OpenAPI document shows each example under its operation's response (and the request body, when the
operation takes one). Examples never affect the locked shapes: the contract lock ignores `examples` keys.
"""

from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any, Callable, Literal, get_args

from fastapi import FastAPI
from pydantic import BaseModel, Field

EXAMPLES_DIR = Path(__file__).resolve().parents[1] / "docs" / "api_examples"
ExampleKind = Literal["real", "refusal_only", "synthetic"]
EXAMPLE_KINDS: tuple[str, ...] = get_args(ExampleKind)


class ApiExample(BaseModel):
    """One captured example file."""

    operation: str = Field(pattern=r"^(GET|POST|PUT|DELETE|PATCH) /\S*$")
    status: int = Field(ge=100, le=599)
    name: str = Field(min_length=1, pattern=r"^[A-Za-z0-9_.-]+$")
    kind: ExampleKind
    summary: str = Field(min_length=1)
    environment: dict[str, Any]
    request: dict[str, Any]
    response: Any

    @property
    def method(self) -> str:
        return self.operation.split(" ", 1)[0].lower()

    @property
    def path(self) -> str:
        return self.operation.split(" ", 1)[1]

    def label(self) -> str:
        """The summary shown in the docs, carrying the kind so a refusal-only or synthetic example is never
        mistaken for a real success."""
        return f"[{self.kind}] {self.summary}"


def load_examples(directory: Path = EXAMPLES_DIR) -> list[ApiExample]:
    """Every example file in `directory` (sorted by file name), validated. A missing directory has none."""
    if not directory.is_dir():
        return []
    examples = [ApiExample.model_validate_json(path.read_text(encoding="utf-8"))
                for path in sorted(directory.glob("*.json"))]
    seen: set[tuple[str, int, str]] = set()
    for example in examples:
        key = (example.operation, example.status, example.name)
        if key in seen:
            raise ValueError(f"duplicate example {key}")
        seen.add(key)
    return examples


def attach_examples(schema: dict[str, Any], examples: list[ApiExample], prefix: str = "") -> dict[str, Any]:
    """Add each example to its operation's response (and request body) in an OpenAPI document, in place.

    An example for an operation or status the document does not declare is an error: it would document a
    response the API does not say it returns.
    """
    for example in examples:
        # Examples are recorded at their unmounted paths; a deployment's API_PREFIX mounts the data routes (not the
        # probes) under a prefix, so the prefixed path is tried first.
        paths = schema.get("paths", {})
        item = paths.get(prefix + example.path) if prefix and prefix + example.path in paths else paths.get(example.path)
        operation = (item or {}).get(example.method)
        if operation is None:
            raise ValueError(f"example {example.name!r} names an unknown operation {example.operation!r}")
        response = operation.get("responses", {}).get(str(example.status))
        if response is None:
            raise ValueError(f"example {example.name!r}: {example.operation} declares no {example.status} response")
        content = response.setdefault("content", {}).setdefault("application/json", {})
        content.setdefault("examples", {})[example.name] = {"summary": example.label(), "value": example.response}
        body = example.request.get("body")
        request_body = operation.get("requestBody")
        if body is not None and request_body is not None:
            target = request_body.setdefault("content", {}).setdefault("application/json", {})
            target.setdefault("examples", {})[example.name] = {"summary": example.label(), "value": body}
    return schema


def install_examples(app: FastAPI, directory: Path = EXAMPLES_DIR, prefix: str = "") -> None:
    """Make app.openapi() include the captured examples.

    The example files are parsed and checked here, when the application is built, so a malformed file stops the
    application from starting. Attaching them needs the finished document, so it happens on first generation;
    if that fails (an example names an undeclared response), nothing is cached and every later call fails the
    same way -- the document is never served without its examples.
    """
    examples = load_examples(directory)
    generate: Callable[[], dict[str, Any]] = app.openapi

    def openapi() -> dict[str, Any]:
        if app.openapi_schema is None:
            try:
                schema = attach_examples(copy.deepcopy(generate()), examples, prefix)
            finally:
                app.openapi_schema = None  # FastAPI's generator caches its own, example-free document
            app.openapi_schema = schema
        return app.openapi_schema

    app.openapi = openapi  # type: ignore[method-assign]


# --- scope, validation and completeness (P7-M8; P7-Q4) ------------------------------------------------------------

LOCK_FILE = Path(__file__).resolve().parents[1] / "docs" / "api_contract_lock.json"
# Locked, but documented without captured examples (P7-Q4): the liveness and readiness probes.
PROBES = frozenset({"GET /health", "GET /ready"})
# Operations that can only refuse today (P7-Q1): a real refusal labelled refusal_only, plus the synthetic success
# from their tests, labelled synthetic, stand in for the real success until P6-DM1's inputs exist.
REFUSAL_ONLY = frozenset({"POST /events/{event_key}/alliance-selection/pick-list"})


def examples_scope(lock_file: Path = LOCK_FILE) -> list[str]:
    """Every operation that needs examples: each locked operation except the probes (P7-Q4: core features and
    discovery reads; the human-input operations are not locked and have none)."""
    operations = json.loads(lock_file.read_text(encoding="utf-8"))["operations"]
    return sorted(op for op in operations if op not in PROBES)


def iter_api_routes(app: FastAPI) -> list[tuple[str, Any]]:
    """Every APIRoute the application serves, with its full path. FastAPI 0.141 keeps an included router as one
    `_IncludedRouter` entry whose `original_router` holds the routes, so the wrappers are walked at any depth."""
    from fastapi.routing import APIRoute
    from starlette.routing import Mount

    found: list[tuple[str, Any]] = []

    def walk(routes: Any, prefix: str) -> None:
        for route in routes:
            if isinstance(route, APIRoute):
                found.append((prefix + route.path, route))
            elif isinstance(route, Mount):
                raise ValueError(f"a mounted sub-application at {prefix + route.path} is not walked")
            elif hasattr(route, "original_router"):
                walk(route.original_router.routes, prefix + (route.include_context.prefix or ""))

    walk(app.routes, "")
    return found


def served_path(app: FastAPI, path: str) -> str:
    """Where `path` (an example's unmounted path) is served: under the deployment's API_PREFIX for the data routes,
    unprefixed for the probes, exactly as attach_examples resolves it."""
    settings = getattr(app.state, "settings", None)
    prefix = getattr(settings, "api_prefix", "") or ""
    return prefix + path if prefix and prefix + path in app.openapi().get("paths", {}) else path


def validate_example(app: FastAPI, example: ApiExample) -> list[str]:
    """Why `example` does not match its operation's locked contract (empty when it does).

    The status must be declared by the operation. A 2xx response must validate against the route's response model
    (the same schema the contract lock pins); any other must be the error envelope with its own status and a code
    the operation declares for that status."""
    from api.contract import DECLARED_CODE_PATTERN
    from api.errors import ErrorResponse

    problems: list[str] = []
    routes = {(method, path): route for path, route in iter_api_routes(app) for method in route.methods}
    path = served_path(app, example.path)
    route = routes.get((example.method.upper(), path))
    if route is None:
        return [f"{example.operation}: no such operation"]
    declared = app.openapi()["paths"][path][example.method]["responses"].get(str(example.status))
    if declared is None:
        return [f"{example.operation}: status {example.status} is not declared"]
    try:
        if 200 <= example.status < 300:
            if route.response_model is not None:
                route.response_model.model_validate(example.response)
        else:
            envelope = ErrorResponse.model_validate(example.response)
            codes = set(DECLARED_CODE_PATTERN.findall(declared.get("description", "")))
            if envelope.error.status != example.status:
                problems.append(f"{example.name}: envelope status {envelope.error.status} != {example.status}")
            if envelope.error.code not in codes:
                problems.append(f"{example.name}: code {envelope.error.code!r} not declared for {example.status}")
    except ValueError as exc:  # pydantic's ValidationError is a ValueError
        problems.append(f"{example.name}: response does not match the contract: {exc}")
    if example.kind == "real" and not example.environment.get("environment_of_record"):
        problems.append(f"{example.name}: a real example must come from the environment of record (P7-Q5)")
    return problems


def missing_examples(examples: list[ApiExample], scope: list[str] | None = None) -> dict[str, list[str]]:
    """What each in-scope operation still lacks (P7-M8): a real 2xx and a real refusal, or for a refusal-only
    operation a refusal_only refusal and a synthetic 2xx. Empty when complete."""
    missing: dict[str, list[str]] = {}
    for operation in scope if scope is not None else examples_scope():
        mine = [e for e in examples if e.operation == operation]
        ok = [e for e in mine if 200 <= e.status < 300]
        refused = [e for e in mine if e.status >= 400]
        if operation in REFUSAL_ONLY:
            needs = {"refusal_only refusal": any(e.kind == "refusal_only" for e in refused),
                     "synthetic success": any(e.kind == "synthetic" for e in ok)}
        else:
            needs = {"real success": any(e.kind == "real" for e in ok),
                     "real refusal": any(e.kind == "real" for e in refused)}
        lacking = [need for need, met in needs.items() if not met]
        if lacking:
            missing[operation] = lacking
    return missing


__all__ = ["ApiExample", "EXAMPLES_DIR", "EXAMPLE_KINDS", "LOCK_FILE", "PROBES", "REFUSAL_ONLY", "attach_examples",
           "examples_scope", "install_examples", "iter_api_routes", "load_examples", "missing_examples",
           "served_path", "validate_example"]
