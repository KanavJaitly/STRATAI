"""Unit tests for the Phase 7 contract building blocks (api.contract), the examples mechanism (api.examples) and the
contract lock's normalization and diff (scripts.phase7_contract_lock). Pure: no database."""

from __future__ import annotations

import json
from http import HTTPStatus

import pytest
from fastapi import FastAPI
from pydantic import BaseModel, ValidationError

from api.contract import CalibratedWinProbability, ServedModelInfo, StrategyOdds, Validation, error_responses
from api.examples import EXAMPLES_DIR, ApiExample, attach_examples, install_examples, load_examples
from ml.strategy.display import display_odds
from scripts.phase7_contract_lock import contract_of, differences, normalize_operation, normalize_schema

MODEL = ServedModelInfo(model_type="win_prob_xgb_calibrated", model_version="1", model_version_tag="d18",
                        model_sha256="0" * 64, training_dataset_hash="ab", provenance={})


# --- CalibratedWinProbability: the M12 split -------------------------------------------------------------------


def _probability(**overrides):
    fields = dict(validated_value=0.65, unvalidated_value=None, unvalidated_reason=None, rounding=0.05,
                  calibration_status="m7_gate_failed",
                  validation=Validation(status="approximately_calibrated_qualification"), model=MODEL)
    fields.update(overrides)
    return CalibratedWinProbability(**fields)


def test_a_validated_probability_has_only_the_validated_value():
    probability = _probability()
    assert probability.validated_value == 0.65 and probability.unvalidated_value is None


def test_an_unvalidated_probability_has_only_the_unvalidated_value_and_its_reason():
    probability = _probability(validated_value=None, unvalidated_value=0.7, unvalidated_reason="playoff_scope",
                               validation=Validation(status="not_validated", reasons=["playoff_scope"]))
    assert probability.validated_value is None and probability.unvalidated_reason == "playoff_scope"


def test_every_output_of_the_m6m7_display_rule_is_accepted_and_nothing_more_precise():
    from api.routes.predictions import display_probability

    for p in [i / 1000 for i in range(0, 1001)]:
        shown = display_probability(p)
        _probability(validated_value=shown)
        _probability(validated_value=None, unvalidated_value=shown, unvalidated_reason="epa_incomplete",
                     validation=Validation(status="not_validated"))
    for raw in (0.0, 1.0, 0.1234, 0.97, 0.03, 0.651):
        with pytest.raises(ValidationError):
            _probability(validated_value=raw)


@pytest.mark.parametrize("overrides", [
    {"unvalidated_reason": "made_up", "validated_value": None, "unvalidated_value": 0.6,
     "validation": Validation(status="not_validated")},          # not a documented reason
    {"rounding": 0.01},                                          # not the M6/M7 step
    {"calibration_status": "passed"},                            # M7 did not pass
    {"unvalidated_value": 0.6},                                  # both values set
    {"validated_value": None},                                   # neither value set
    {"unvalidated_reason": "playoff_scope"},                     # a reason on a validated value
    {"validation": Validation(status="not_validated")},          # status disagrees with the value's key
    {"validated_value": None, "unvalidated_value": 0.6,          # unvalidated without a reason
     "validation": Validation(status="not_validated")},
    {"validated_value": None, "unvalidated_value": 0.6, "unvalidated_reason": "epa_incomplete",
     "validation": Validation(status="approximately_calibrated_qualification")},  # unvalidated labelled validated
    {"validated_value": 1.2},                                    # not a probability
])
def test_the_split_cannot_be_violated(overrides):
    with pytest.raises(ValidationError):
        _probability(**overrides)


# --- StrategyOdds: display strings only ------------------------------------------------------------------------


@pytest.mark.parametrize("p", [i / 1000 for i in range(0, 1001, 7)] + [0.0, 0.05, 0.95, 1.0, 0.049, 0.951])
def test_every_output_of_the_p6_a5_display_rule_is_accepted(p):
    StrategyOdds(display=display_odds(p), validation=Validation(status="not_validated", reasons=["x"]))


@pytest.mark.parametrize("display", ["0.55", "55.0%", "57%", "6%", "100%", "0%", "<10%", "55", ""])
def test_anything_else_is_refused(display):
    with pytest.raises(ValidationError):
        StrategyOdds(display=display, validation=Validation(status="not_validated", reasons=["x"]))


def test_a_missing_probability_must_carry_the_engines_reason():
    StrategyOdds(display=None, validation=Validation(status="not_validated", reasons=["playoff_model_unavailable"]))
    with pytest.raises(ValidationError):
        StrategyOdds(display=None, validation=Validation(status="not_validated"))


def test_strategy_odds_have_no_field_for_a_raw_probability():
    assert set(StrategyOdds.model_fields) == {"display", "validation"}


def test_validation_status_is_required():
    with pytest.raises(ValidationError):
        Validation(status="")


# --- error_responses ---------------------------------------------------------------------------------------------


def test_error_responses_always_declare_500_and_the_validation_error():
    declared = error_responses({HTTPStatus.NOT_FOUND: ["event_not_found"]})
    assert set(declared) == {404, 422, 500}
    assert "`event_not_found`" in declared[404]["description"]
    assert "`validation_error`" in declared[422]["description"]
    assert "`internal_error`" in declared[500]["description"]


def test_error_responses_refuse_a_route_code_at_500_or_above():
    error_responses({HTTPStatus.SERVICE_UNAVAILABLE: ["service_unavailable"]}, validates_input=False)
    with pytest.raises(ValueError):
        error_responses({HTTPStatus.SERVICE_UNAVAILABLE: ["db_down"]})


def test_assert_declared_error_accepts_declared_codes_and_rejects_others():
    from fastapi.testclient import TestClient

    from api.errors import ApiError, register_exception_handlers
    from tests.phase7_support import assert_declared_error

    app = FastAPI()
    register_exception_handlers(app)

    @app.get("/x/{key}", responses=error_responses({HTTPStatus.NOT_FOUND: ["gone"]}, validates_input=False))
    def x(key: str):
        raise ApiError(status_code=HTTPStatus.NOT_FOUND, code="gone" if key == "a" else "other", message="m")

    client = TestClient(app)
    assert_declared_error(app.openapi(), client.get("/x/a"), "GET", "/x/{key}", code="gone")
    with pytest.raises(AssertionError, match="undeclared code"):
        assert_declared_error(app.openapi(), client.get("/x/b"), "GET", "/x/{key}")


def test_error_responses_without_input_omit_422_and_keep_route_codes():
    assert set(error_responses({}, validates_input=False)) == {500}
    declared = error_responses({HTTPStatus.UNPROCESSABLE_ENTITY: ["invalid_as_of"]})
    assert "`invalid_as_of`" in declared[422]["description"] and "`validation_error`" in declared[422]["description"]


# --- examples ------------------------------------------------------------------------------------------------------


class _Out(BaseModel):
    value: int


def _app() -> FastAPI:
    app = FastAPI()

    @app.get("/things/{key}", response_model=_Out, responses=error_responses({HTTPStatus.NOT_FOUND: ["gone"]}))
    def thing(key: str) -> _Out:
        return _Out(value=1)

    @app.post("/things", response_model=_Out)
    def make(body: _Out) -> _Out:
        return body

    return app


def _example(**overrides) -> dict:
    example = {"operation": "GET /things/{key}", "status": 200, "name": "one", "kind": "real",
               "summary": "A thing", "environment": {"database": "test"},
               "request": {"path_params": {"key": "a"}}, "response": {"value": 1}}
    example.update(overrides)
    return example


def _write(directory, *examples) -> None:
    directory.mkdir(exist_ok=True)
    for index, example in enumerate(examples):
        (directory / f"{index:02d}.json").write_text(json.dumps(example), encoding="utf-8")


def test_examples_appear_under_their_operation_labelled_with_their_kind(tmp_path):
    _write(tmp_path / "ex", _example(), _example(status=404, name="missing", kind="refusal_only",
                                                 response={"error": {"code": "gone"}}),
           _example(operation="POST /things", name="made", kind="synthetic", request={"body": {"value": 2}},
                    response={"value": 2}))
    app = _app()
    install_examples(app, tmp_path / "ex")
    paths = app.openapi()["paths"]
    shown = paths["/things/{key}"]["get"]["responses"]["200"]["content"]["application/json"]["examples"]["one"]
    assert shown == {"summary": "[real] A thing", "value": {"value": 1}}
    refusal = paths["/things/{key}"]["get"]["responses"]["404"]["content"]["application/json"]["examples"]
    assert refusal["missing"]["summary"].startswith("[refusal_only]")
    body = paths["/things"]["post"]["requestBody"]["content"]["application/json"]["examples"]["made"]
    assert body == {"summary": "[synthetic] A thing", "value": {"value": 2}}


@pytest.mark.parametrize("bad", [
    {"operation": "GET /nowhere"},          # an operation the API does not have
    {"status": 418},                         # a status the operation does not declare
])
def test_an_example_for_an_undeclared_response_is_refused(tmp_path, bad):
    _write(tmp_path / "ex", _example(**bad))
    with pytest.raises(ValueError):
        attach_examples(_app().openapi(), load_examples(tmp_path / "ex"))


@pytest.mark.parametrize("bad", [{"kind": "made_up"}, {"name": "has space"}, {"operation": "/things"},
                                 {"summary": ""}])
def test_a_malformed_example_file_fails_loudly(tmp_path, bad):
    _write(tmp_path / "ex", _example(**bad))
    with pytest.raises(ValidationError):
        load_examples(tmp_path / "ex")


def test_duplicate_examples_are_refused(tmp_path):
    _write(tmp_path / "ex", _example(), _example())
    with pytest.raises(ValueError, match="duplicate"):
        load_examples(tmp_path / "ex")


def test_a_missing_examples_directory_has_none(tmp_path):
    assert load_examples(tmp_path / "absent") == []


def test_every_committed_example_attaches_to_the_real_application():
    from api import create_app
    from data.config import Settings

    create_app(Settings()).openapi()  # raises if any committed example is malformed or names an undeclared response
    for example in load_examples(EXAMPLES_DIR):
        assert isinstance(example, ApiExample)


# --- the lock's normalization and diff ---------------------------------------------------------------------------


def test_normalization_drops_documentation_only():
    schema = {"title": "T", "description": "d", "type": "object", "examples": [1],
              "properties": {"a": {"type": "integer", "minimum": 0, "description": "x", "default": 3}}}
    assert normalize_schema(schema) == {"type": "object",
                                        "properties": {"a": {"type": "integer", "minimum": 0, "default": 3}}}


def test_an_operations_declared_error_codes_are_part_of_its_contract():
    operation = {"responses": {"404": {"description": "Not Found. Error codes: `b`, `a`.",
                                       "content": {"application/json": {"schema": {"$ref": "#/x"}}}}}}
    assert normalize_operation(operation)["responses"]["404"]["codes"] == ["a", "b"]


def test_a_new_optional_field_is_an_addition_and_a_removed_field_is_a_change():
    app = _app()
    before = contract_of(app.openapi(), ["GET /things/{key}"])

    class _Wider(BaseModel):
        value: int
        extra: str | None = None

    wider = FastAPI()
    wider.get("/things/{key}", response_model=_Wider, responses=error_responses({HTTPStatus.NOT_FOUND: ["gone"]}))(
        lambda key: _Wider(value=1))
    after = contract_of(wider.openapi(), ["GET /things/{key}"])
    # The component is renamed with the model, so compare the shape of the response schema itself.
    before_schema = before["schemas"]["_Out"]
    after_schema = after["schemas"]["_Wider"]
    diff = differences(before_schema, after_schema)
    assert diff["changed"] == [] and diff["added"] and all(leaf.startswith("/properties/extra/")
                                                           for leaf in diff["added"])
    assert differences(after_schema, before_schema)["changed"]  # removing it is a change


def test_a_property_named_like_a_documentation_keyword_is_still_locked():
    """`summary`, `description` and `title` are plausible field names in Phase 7 shapes; only schema keywords of
    those names are documentation."""
    schema = {"type": "object", "title": "T", "required": ["summary"],
              "properties": {"summary": {"type": "string", "title": "Summary"}, "title": {"type": "integer"}}}
    assert normalize_schema(schema) == {"type": "object", "required": ["summary"],
                                        "properties": {"summary": {"type": "string"}, "title": {"type": "integer"}}}


def test_reordering_is_not_a_change():
    a = {"required": ["b", "a"], "anyOf": [{"type": "integer"}, {"type": "null"}]}
    b = {"required": ["a", "b"], "anyOf": [{"type": "null"}, {"type": "integer"}]}
    assert normalize_schema(a) == normalize_schema(b)


def test_an_empty_response_body_is_visible_to_the_lock():
    """A status whose content normalizes to nothing (an `Any` body) must still be a locked entry: moving it from
    200 to 201, or dropping it, is a change."""
    before = {"operations": {"GET /x": {"responses": {"200": {"content": {"application/json": {}}}}}}}
    moved = {"operations": {"GET /x": {"responses": {"201": {"content": {"application/json": {}}}}}}}
    assert differences(before, moved)["changed"] == ["/operations/GET /x/responses/200/content/application/json"]
    filled = {"operations": {"GET /x": {"responses": {"200": {"content": {"application/json": {"type": "object"}}}}}}}
    assert differences(before, filled) == {"changed": [],
                                           "added": ["/operations/GET /x/responses/200/content/application/json/type"]}


def test_a_failed_example_attachment_is_never_cached(tmp_path):
    """If attaching fails, every later call fails too: the document is never served without its examples."""
    _write(tmp_path / "ex", _example(status=418))
    app = _app()
    install_examples(app, tmp_path / "ex")
    for _ in range(2):
        with pytest.raises(ValueError):
            app.openapi()


def test_a_malformed_example_file_stops_the_application_from_being_built(tmp_path):
    _write(tmp_path / "ex", _example(kind="made_up"))
    with pytest.raises(ValidationError):
        install_examples(_app(), tmp_path / "ex")


def test_the_lock_cli_refuses_unrecorded_changes(tmp_path, monkeypatch):
    """lock adds only; relock needs a decision for a changed entry; unlock always needs one."""
    from scripts import phase7_contract_lock as cli

    contracts = {"v1": {"operations": {"GET /a": {"deprecated": False}}, "schemas": {}, "building_blocks": {}},
                 "v2": {"operations": {"GET /a": {"deprecated": True}}, "schemas": {}, "building_blocks": {}}}
    current = {"name": "v1"}

    def live(locked):
        contract = json.loads(json.dumps(contracts[current["name"]]))
        missing = set(locked) - set(contract["operations"]) - {"GET /b"}
        if missing:
            raise KeyError(f"locked operations missing from the application: {sorted(missing)}")
        if "GET /b" in locked:
            contract["operations"]["GET /b"] = {"deprecated": False}
        return contract

    monkeypatch.setattr(cli, "LOCK_PATH", tmp_path / "lock.json")
    monkeypatch.setattr(cli, "live_contract", live)
    assert cli.main(["lock", "--reason", "r", "GET /a"]) == 0
    assert cli.main(["lock", "--reason", "r", "GET /nope"]) == 2
    current["name"] = "v2"
    assert cli.main(["check"]) == 1
    assert cli.main(["lock", "--reason", "r", "GET /b"]) == 2           # would absorb GET /a's change
    assert cli.main(["relock", "--reason", "r"]) == 2                    # a changed entry needs a decision
    assert cli.main(["relock", "--reason", "r", "--decision", "nonsense"]) == 2
    assert cli.main(["relock", "--reason", "r", "--decision",
                     ".agent/phase7/P7_M0_DECISIONS.md row X (2026-10-17)"]) == 0
    assert cli.main(["unlock", "--reason", "r", "GET /a"]) == 2           # needs a decision
    lock = json.loads((tmp_path / "lock.json").read_text())
    assert [r["command"] for r in lock["revisions"]] == ["lock", "relock"]
    assert lock["revisions"][1]["changed"] == ["/operations/GET /a/deprecated"]


def test_a_list_is_compared_whole_so_a_new_required_entry_is_a_change():
    """Conservative by design: a changed list (e.g. a schema's `required`) is a change to a locked leaf, which
    needs a recorded decision, even when the change only adds an entry."""
    before = {"required": ["a"], "properties": {"a": {"type": "integer"}}}
    after = {"required": ["a", "b"], "properties": {"a": {"type": "integer"}, "b": {"type": "integer"}}}
    assert differences(before, after)["changed"] == ["/required"]
