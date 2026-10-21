"""P7-M8: the captured examples (P7-Q4) and the capture tooling.

The contract test that every in-scope operation has its required examples is BLOCKED (environment): real examples
need the environment of record (P7-Q5), which is not on this machine. It is a strict xfail, so it fails the moment
the examples exist and the marker has not been removed. Everything else runs: the scope, the validation of any
committed example against its locked contract, the plan template's coverage, and a dry-run capture against the
isolated test database (namespace 9988). The dry-run examples are not evidence about any real event.
"""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path
from typing import Generator

import pytest

from api import create_app
from api.examples import (
    EXAMPLES_DIR,
    LOCK_FILE,
    PROBES,
    REFUSAL_ONLY,
    ApiExample,
    attach_examples,
    examples_scope,
    load_examples,
    missing_examples,
    validate_example,
)
from data.config import Settings
from database.connection import Database, DatabaseConfig
from scripts.phase7_capture_examples import CaptureError, capture, environment_gaps, main, write_examples
from tests.test_live_epa import _isolated_db_name

TEMPLATE = Path(__file__).resolve().parents[1] / "scripts" / "phase7_examples_plan.template.json"
_EVENT = "9988zzzevent"


@pytest.fixture(scope="module")
def app():
    return create_app(Settings())


def _example(**overrides) -> ApiExample:
    values = dict(operation="GET /events/{event_key}/teams", status=404, name="unknown", kind="real",
                  summary="An unknown event", environment={"environment_of_record": True},
                  request={"path_params": {"event_key": "x"}},
                  response={"error": {"code": "event_not_found", "message": "m", "status": 404, "request_id": "r"}})
    values.update(overrides)
    return ApiExample(**values)


# --- scope and completeness -------------------------------------------------------------------------------------------


def test_the_scope_is_every_locked_operation_but_the_probes():
    locked = set(json.loads(LOCK_FILE.read_text(encoding="utf-8"))["operations"])
    # 22 Phase 7 operations, plus the Phase 9 briefing since it was locked (P9-M4, 2026-10-20; P7-Q4 covers every
    # locked operation).
    assert set(examples_scope()) == locked - PROBES and len(examples_scope()) == 23
    assert PROBES <= locked and REFUSAL_ONLY <= set(examples_scope())
    assert not any(op.split(" ", 1)[1].startswith("/human-inputs") for op in examples_scope())


@pytest.mark.xfail(strict=True, reason="BLOCKED (environment, P7-Q5): real examples need the environment of record")
def test_every_operation_in_scope_has_its_required_examples():
    assert missing_examples(load_examples()) == {}


def test_the_plan_template_covers_the_scope_except_the_synthetic_success():
    plan = json.loads(TEMPLATE.read_text(encoding="utf-8"))["examples"]
    planned = [ApiExample(operation=e["operation"], status=e["expect_status"], name=e["name"], kind=e["kind"],
                          summary=e["summary"], environment={}, request={}, response={}) for e in plan]
    assert missing_examples(planned) == {"POST /events/{event_key}/alliance-selection/pick-list": ["synthetic success"]}
    assert {e["operation"] for e in plan} == set(examples_scope())


def test_completeness_rules():
    op = "GET /events/{event_key}/teams"
    ok = _example(status=200, name="ok", response=[])
    assert missing_examples([ok, _example()], scope=[op]) == {}
    assert missing_examples([ok], scope=[op]) == {op: ["real refusal"]}
    assert missing_examples([_example(kind="synthetic", status=200, name="s"), _example()], scope=[op]) == {
        op: ["real success"]}
    pick = "POST /events/{event_key}/alliance-selection/pick-list"
    assert missing_examples([], scope=[pick]) == {pick: ["refusal_only refusal", "synthetic success"]}


# --- validation against the locked contract ---------------------------------------------------------------------------


def test_every_committed_example_validates(app):
    examples = load_examples()
    assert all(not validate_example(app, e) for e in examples), [validate_example(app, e) for e in examples]
    attach_examples(app.openapi(), examples)  # every one documents a declared response


def test_validation_has_teeth(app):
    assert validate_example(app, _example()) == []
    assert validate_example(app, _example(status=409))[0].endswith("not declared")
    assert "not declared for 404" in validate_example(app, _example(response={"error": {
        "code": "team_not_found", "message": "m", "status": 404, "request_id": "r"}}))[0]
    assert "envelope status" in validate_example(app, _example(response={"error": {
        "code": "event_not_found", "message": "m", "status": 400, "request_id": "r"}}))[0]
    assert "does not match" in validate_example(app, _example(status=200, response={"teams": "x"}))[0]
    assert "environment of record" in validate_example(app, _example(environment={}))[0]
    assert validate_example(app, _example(operation="GET /nope"))[0].endswith("no such operation")


# --- the capture tooling (dry run against the isolated test database) ---------------------------------------------------


pytestmark_db = pytest.mark.skipif(_isolated_db_name() is None, reason="needs an isolated stratai_* database copy")


@pytest.fixture
def database() -> Generator[Database, None, None]:
    settings = Settings()
    db = Database(DatabaseConfig(settings.database_url))

    def cleanup():
        with db.cursor() as c:
            c.execute("DELETE FROM events WHERE event_key LIKE '9988zzz%%'")

    cleanup()
    with db.cursor() as c:
        c.execute("INSERT INTO events (event_key, season, name, end_date) VALUES (%s, 9988, 'Example', %s)",
                  (_EVENT, date(2026, 3, 1)))
    try:
        yield db
    finally:
        cleanup()


PLAN = {"examples": [
    {"operation": "GET /events", "name": "season", "kind": "real", "summary": "One season", "expect_status": 200,
     "request": {"query": {"season": "<<SEASON>>"}}},
    {"operation": "GET /events/{event_key}/teams", "name": "unknown_event", "kind": "real", "summary": "Unknown",
     "expect_status": 404, "request": {"path_params": {"event_key": "9988zzznosuch"},
                                        "headers": {"X-StratAI-Write-Token": "secret-token-value"}}},
]}
AS_OF = "2026-03-08T18:00:00+00:00"


@pytestmark_db
def test_a_dry_run_capture_writes_validated_fingerprinted_examples(database, tmp_path, app):
    examples = capture(PLAN, environment_name="local-dry-run", as_of=AS_OF, allow_incomplete=True,
                       values={"SEASON": "9988"})
    paths = write_examples(examples, tmp_path)
    loaded = load_examples(tmp_path)
    assert [e.name for e in loaded] == ["season", "unknown_event"] and len(paths) == 2
    season = next(e for e in loaded if e.name == "season")
    assert [event["event_key"] for event in season.response["events"]] == [_EVENT]
    assert season.request == {"query": {"season": 9988}}
    env = season.environment
    assert env["environment_name"] == "local-dry-run" and env["as_of"] == AS_OF
    assert env["environment_of_record"] is False and env["environment_gaps"]
    assert {"models", "epa", "database", "git", "captured_at"} <= set(env)
    assert env["database"]["name"] and env["database"]["latest_migration"]
    assert "secret-token-value" not in "".join(p.read_text() for p in paths)  # headers are sent, never recorded
    attach_examples(app.openapi(), loaded)
    # A dry run's "real" examples can never satisfy the contract test: they are not from the environment of record.
    assert all(any("environment of record" in p for p in validate_example(app, e)) for e in loaded)


@pytestmark_db
def test_outside_the_environment_of_record_capture_refuses(database):
    with pytest.raises(CaptureError, match="not the environment of record"):
        capture(PLAN, environment_name="local", as_of=AS_OF, allow_incomplete=False, values={"SEASON": "9988"})


@pytestmark_db
def test_an_unexpected_status_writes_nothing(database):
    plan = {"examples": [{**PLAN["examples"][0], "expect_status": 404}]}
    with pytest.raises(CaptureError, match="status 200, planned 404"):
        capture(plan, environment_name="local", as_of=AS_OF, allow_incomplete=True, values={"SEASON": "9988"})


@pytestmark_db
def test_an_unfilled_placeholder_is_refused(database):
    with pytest.raises(CaptureError, match="unfilled placeholder"):
        capture(PLAN, environment_name="local", as_of=AS_OF, allow_incomplete=True, values={})


def test_a_dry_run_can_never_write_into_docs_api_examples(tmp_path):
    plan = tmp_path / "plan.json"
    plan.write_text(json.dumps(PLAN), encoding="utf-8")
    with pytest.raises(SystemExit) as raised:
        main(["--plan", str(plan), "--environment-name", "x", "--as-of", AS_OF, "--out", str(EXAMPLES_DIR),
              "--allow-incomplete-environment"])
    assert raised.value.code == 2  # argparse error


def test_environment_gaps_name_what_is_missing():
    complete = {"models": {"ranking": {}, "win_probability": {}, "strategy": {}}, "epa": {},
                "database": {"latest_migration": "0011_rulesets.sql"}}
    assert environment_gaps(complete) == []
    gaps = environment_gaps({"models": {"ranking": None, "win_probability": {}, "strategy": None}, "epa": None,
                             "database": {"latest_migration": "0009_x.sql"}})
    assert gaps == ["model ranking not loaded", "model strategy not loaded", "EPA source not loaded",
                    "migrations only through 0009_x.sql (needs 0011)"]


def test_the_synthetic_pick_list_success_is_written_by_its_test(tmp_path, monkeypatch):
    """P7-Q1: the refusal-only pick list's synthetic success comes from its own test, labelled synthetic."""
    import subprocess
    import sys

    if _isolated_db_name() is None:
        pytest.skip("needs an isolated stratai_* database copy")
    env = {**__import__("os").environ, "STRATAI_SYNTHETIC_EXAMPLES_DIR": str(tmp_path)}
    result = subprocess.run([sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider",
                             "tests/test_phase7_alliance_selection_api.py::"
                             "test_the_synthetic_success_path_serves_the_full_shape_without_raw_precision"],
                            cwd=Path(__file__).resolve().parents[1], env=env, capture_output=True, text=True,
                            timeout=600)
    assert result.returncode == 0, result.stdout[-2000:]
    (example,) = load_examples(tmp_path)
    assert example.kind == "synthetic" and example.status == 200 and example.summary.startswith("SYNTHETIC")
    assert validate_example(create_app(Settings()), example) == []


@pytestmark_db
def test_capture_and_validation_work_under_an_api_prefix(database, monkeypatch):
    """Mid-Phase Audit #1 / P7-D6: a deployment's API_PREFIX mounts the data routes; examples keep their unmounted
    paths, and capture and validation resolve them."""
    monkeypatch.setenv("API_PREFIX", "/api")
    settings = Settings()
    assert settings.api_prefix == "/api"
    examples = capture(PLAN, environment_name="prefixed-dry-run", as_of=AS_OF, allow_incomplete=True,
                       values={"SEASON": "9988"}, settings=settings)
    prefixed = create_app(settings)
    assert [e.operation for e in examples] == ["GET /events", "GET /events/{event_key}/teams"]
    assert all(all("environment of record" in p for p in validate_example(prefixed, e)) for e in examples)
    attach_examples(prefixed.openapi(), examples, "/api")
