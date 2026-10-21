"""P9-M4: GET /matches/{match_key}/briefing on the isolated test database.

The report route's synthetic event (tests/test_phase7_pre_match_report_api.py: 9977zzz*) is reused, with its stub
strategy and win-probability models, so the briefing is exercised on a model-populated report through the real code
path. The LLM is always a stub (no network, no credential).
"""

from __future__ import annotations

import json
from typing import Any, Generator

import pytest
from fastapi.testclient import TestClient

from api import create_app
from api.dependencies import get_database, get_strategy_model, get_win_prob_model
from api.routes.briefing import get_briefing_client_factory
from briefing.facts import report_facts
from briefing.render import deterministic_briefing
from data.config import Settings
from tests.test_live_epa import _isolated_db_name
from tests.test_phase7_pre_match_report_api import (  # noqa: F401  (pytest fixtures, used by name)
    QM1,
    TOKEN,
    UNSCHEDULED,
    _reference_epa_source,
    _strategy_model,
    _win_prob_model,
    database,
)
from tests.test_phase9_llm import StubClient, arrangement, faithful_output

pytestmark = pytest.mark.skipif(_isolated_db_name() is None, reason="needs an isolated stratai_* database copy")
AS_OF = "2026-03-01T09:00:00Z"  # before QM1, so the report (and so the briefing) is reproducible
BRIEFING, REPORT = "/matches/{}/briefing", "/matches/{}/pre-match-report"


def _app(database, client: StubClient | None = None, **settings: Any):
    application = create_app(Settings(human_inputs_write_token=TOKEN, **settings))
    application.dependency_overrides[get_database] = lambda: database
    application.dependency_overrides[get_strategy_model] = _strategy_model
    application.dependency_overrides[get_win_prob_model] = _win_prob_model
    if client is not None:
        application.dependency_overrides[get_briefing_client_factory] = lambda: (lambda: client)
    return application


@pytest.fixture
def client(database) -> Generator[TestClient, None, None]:
    with TestClient(_app(database)) as test_client:
        yield test_client


def _report(client: TestClient, match: str = QM1) -> dict[str, Any]:
    response = client.get(REPORT.format(match), params={"as_of": AS_OF})
    assert response.status_code == 200, response.text
    return response.json()


def test_the_default_is_the_deterministic_briefing_of_the_report(client):
    response = client.get(BRIEFING.format(QM1), params={"as_of": AS_OF})
    assert response.status_code == 200, response.text
    body = response.json()
    report = _report(client)
    facts = report_facts(report)
    assert (body["mode"], body["fallback_reason"], body["model"], body["usage"]) == ("deterministic", "disabled", None, None)
    assert (body["match_key"], body["event_key"], body["as_of"]) == (report["match_key"], report["event_key"], report["as_of"])
    assert [f["id"] for f in body["facts"]] == [f.id for f in facts]
    expected = deterministic_briefing(facts)
    assert [s["heading"] for s in body["sections"]] == [s.heading for s in expected]
    assert [x["text"] for s in body["sections"] for x in s["sentences"]] == [x.text for s in expected for x in s.sentences]
    assert "nothing here is a new prediction" in body["disclaimer"]
    # the report here is model-populated (stub models): the forecast and the strategy are stated, not absent
    kinds = {f["id"]: f["kind"] for f in body["facts"]}
    assert kinds["forecast.win_probability"] in {"value", "label"} and kinds["strategy.red"] == "value"


def test_enabled_without_approval_never_calls_the_llm(database):
    stub = StubClient("{}")
    with TestClient(_app(database, stub, briefing_llm_enabled=True)) as c:
        body = c.get(BRIEFING.format(QM1), params={"as_of": AS_OF}).json()
    assert (body["mode"], body["fallback_reason"], stub.calls) == ("deterministic", "egress_not_approved", [])


def test_with_every_gate_open_a_faithful_llm_briefing_is_served_with_its_usage(database):
    with TestClient(_app(database)) as c:
        facts = report_facts(_report(c))
    stub = StubClient(faithful_output(facts))
    with TestClient(_app(database, stub, briefing_llm_enabled=True, briefing_data_egress_approved=True)) as c:
        body = c.get(BRIEFING.format(QM1), params={"as_of": AS_OF}).json()
    assert (body["mode"], body["fallback_reason"], body["model"]) == ("llm", None, "claude-opus-5-5")
    assert body["usage"]["output_tokens"] == 900 and body["usage"]["attempts"] is None
    statements = {f["id"]: f["statement"] for f in body["facts"]}
    text = " ".join(x["text"] for s in body["sections"] for x in s["sentences"])
    assert all(text.count(statement) == 1 for statement in statements.values())  # every fact, verbatim, once
    [call] = stub.calls
    assert call["model"] == "claude-opus-5-5"  # the default model setting (P9-Q5)
    assert json.loads(call["messages"][0]["content"])["facts"][0]["id"] == "match"


def test_an_unfaithful_llm_briefing_is_replaced_by_the_deterministic_one(database):
    with TestClient(_app(database)) as c:
        facts = report_facts(_report(c))
    payload = arrangement(facts)
    payload["sections"][1]["items"][0]["lead"] = "The stronger alliance:"  # outside the closed label list
    stub = StubClient(json.dumps(payload))
    with TestClient(_app(database, stub, briefing_llm_enabled=True, briefing_data_egress_approved=True)) as c:
        body = c.get(BRIEFING.format(QM1), params={"as_of": AS_OF}).json()
    assert (body["mode"], body["fallback_reason"]) == ("deterministic", "validation_failed:lead_not_allowed")
    assert "stronger" not in json.dumps(body["sections"])


@pytest.mark.parametrize("match, params, status, code", [
    ("9977zzzevent_qm99", {}, 404, "match_not_found"),
    (UNSCHEDULED, {}, 422, "match_not_scheduled"),
    (QM1, {"as_of": "not-a-time"}, 422, "invalid_as_of"),
])
def test_refusals_are_exactly_the_report_routes(client, match, params, status, code):
    briefing = client.get(BRIEFING.format(match), params=params)
    report = client.get(REPORT.format(match), params=params)
    assert (briefing.status_code, briefing.json()["error"]["code"]) == (status, code)
    assert (report.status_code, report.json()["error"]["code"]) == (status, code)


def test_the_report_is_identical_with_the_llm_layer_on_off_or_used(database):
    """P9-DM1 at the report: enabling (and calling) the LLM layer changes nothing the engines serve."""
    with TestClient(_app(database)) as off:
        before = _report(off)
    facts = report_facts(before)
    stub = StubClient(faithful_output(facts))
    with TestClient(_app(database, stub, briefing_llm_enabled=True, briefing_data_egress_approved=True)) as on:
        assert on.get(BRIEFING.format(QM1), params={"as_of": AS_OF}).json()["mode"] == "llm"
        during = _report(on)
    with TestClient(_app(database)) as off_again:
        after = _report(off_again)
    assert before == during == after
