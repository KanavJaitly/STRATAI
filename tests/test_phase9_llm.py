"""P9-M3: the LLM formatter is fail closed. A stubbed SDK client is used throughout: no network, no credential.

The LLM only arranges facts (groups, order, short lead-ins); every fact's statement is printed verbatim. Every
validator rule has a case that must be rejected (with its own reason), the attacks of review R1 are kept as
regression cases, and every failure path must serve the deterministic briefing. Synthetic reports only
(tests/phase9_fixtures.py).
"""

from __future__ import annotations

import json
import logging
from types import SimpleNamespace
from typing import Any

import pytest

from briefing.facts import report_facts
from briefing.llm import (
    FALLBACK_BETA,
    LEAD_INS,
    MAX_RETRIES,
    OUTPUT_SCHEMA,
    SYSTEM_PROMPT,
    credential_available,
    facts_payload,
    make_briefing,
    request_params,
)
from briefing.render import SECTION_TITLES, deterministic_briefing
from tests.phase9_fixtures import BLUE, RED, local_report, report_with_models, unvalidated_win_report

SECRET = "sk-ant-test-THIS-MUST-NEVER-APPEAR-ANYWHERE"
USAGE = SimpleNamespace(input_tokens=4000, output_tokens=900, cache_read_input_tokens=0,
                        cache_creation_input_tokens=1200)


class StubClient:
    """Records the request; returns a canned response (content blocks and usage can be given), or raises."""

    def __init__(self, text: str | None = None, stop: str = "end_turn", raises: Exception | None = None,
                 content: Any = "default", usage: Any = USAGE):
        self.calls: list[dict[str, Any]] = []
        self._text, self._stop, self._raises, self._content, self._usage = text, stop, raises, content, usage
        self.beta = SimpleNamespace(messages=SimpleNamespace(create=self._create))

    def _create(self, **kwargs: Any) -> Any:
        self.calls.append(kwargs)
        if self._raises:
            raise self._raises
        content = self._content
        if content == "default":
            content = [SimpleNamespace(type="thinking", thinking="")]
            if self._text is not None:
                content.append(SimpleNamespace(type="text", text=self._text))
        return SimpleNamespace(content=content, stop_reason=self._stop, model="claude-opus-5-5", usage=self._usage)


def arrangement(facts, leads: dict[str, str] | None = None) -> dict[str, Any]:
    """A faithful arrangement: one item per team (with a lead-in), one item per other fact, every fact once, under
    its own heading, in reading order."""
    leads = leads or {}
    sections: dict[str, list[dict[str, Any]]] = {}
    groups: dict[str, list[str]] = {}
    for fact in facts:
        parts = fact.id.split(".")
        key = ".".join(parts[:2]) if fact.section in ("red", "blue") and parts[1].isdigit() else fact.id
        if key not in groups:
            groups[key] = []
            sections.setdefault(SECTION_TITLES[fact.section], []).append({"key": key})
        groups[key].append(fact.id)
    out = []
    for heading in SECTION_TITLES.values():
        if heading in sections:
            out.append({"heading": heading, "items": [
                {"lead": leads.get(i["key"], "Team record:" if i["key"].count(".") == 1 and
                                   i["key"].split(".")[1].isdigit() else ""), "fact_ids": groups[i["key"]]}
                for i in sections[heading]]})
    return {"sections": out}


def faithful_output(facts, leads: dict[str, str] | None = None) -> str:
    return json.dumps(arrangement(facts, leads))


def run(facts, client: StubClient, **gates: Any):
    params = dict(enabled=True, egress_approved=True, model="claude-opus-5-5", max_tokens=16000, timeout=30.0)
    params.update(gates)
    return make_briefing(facts, client_factory=lambda: client, **params)


def rendered_text(result) -> str:
    return "\n".join(x.text for s in result.sections for x in s.sentences)


# --- the gates (P9-Q3, P9-Q4): nothing is sent unless every one opens --------------------------------------------


def test_disabled_is_the_default_and_sends_nothing():
    facts = report_facts(report_with_models())
    client = StubClient(faithful_output(facts))
    result = run(facts, client, enabled=False)
    assert (result.mode, result.reason, client.calls) == ("deterministic", "disabled", [])
    assert result.sections == deterministic_briefing(facts)


def test_enabled_without_the_egress_approval_sends_nothing():
    facts = report_facts(report_with_models())
    client = StubClient(faithful_output(facts))
    result = run(facts, client, egress_approved=False)
    assert (result.mode, result.reason, client.calls) == ("deterministic", "egress_not_approved", [])


def test_no_credential_serves_the_deterministic_briefing_without_building_a_client(tmp_path):
    facts = report_facts(local_report())
    result = make_briefing(facts, enabled=True, egress_approved=True, model="claude-opus-5-5", max_tokens=16000,
                           timeout=30.0, environ={"ANTHROPIC_CONFIG_DIR": str(tmp_path / "none")})
    assert (result.mode, result.reason) == ("deterministic", "no_credential")
    assert credential_available({"ANTHROPIC_API_KEY": "x"}) is True
    assert credential_available({"ANTHROPIC_CONFIG_DIR": str(tmp_path / "none")}) is False


def test_the_sdk_authentication_type_error_is_reported_as_no_credential():
    facts = report_facts(local_report())
    client = StubClient(raises=TypeError("Could not resolve authentication method. Expected one of api_key"))
    assert run(facts, client).reason == "no_credential"


# --- the request ------------------------------------------------------------------------------------------------


def test_the_request_is_the_cached_frozen_prompt_plus_the_facts_and_nothing_else():
    facts = report_facts(report_with_models())
    client = StubClient(faithful_output(facts))
    run(facts, client)
    [call] = client.calls
    assert call["model"] == "claude-opus-5-5" and call["max_tokens"] == 16000
    assert call["system"] == [{"type": "text", "text": SYSTEM_PROMPT, "cache_control": {"type": "ephemeral"}}]
    assert call["messages"] == [{"role": "user", "content": facts_payload(facts)}]
    assert call["output_config"]["format"] == {"type": "json_schema", "schema": OUTPUT_SCHEMA}
    assert call["betas"] == [FALLBACK_BETA] and call["fallbacks"] == "default"
    assert "temperature" not in call
    sent = json.loads(call["messages"][0]["content"])["facts"]
    assert [f["id"] for f in sent] == [f.id for f in facts] and all(set(f) == {"id", "kind", "section", "statement"}
                                                                    for f in sent)


def test_the_system_prompt_is_byte_stable_across_matches_so_it_can_be_cached():
    a = request_params(report_facts(local_report()), "claude-opus-5-5", 16000)
    b = request_params(report_facts(report_with_models()), "claude-opus-5-5", 16000)
    assert a["system"] == b["system"] and a["output_config"] == b["output_config"]
    assert a["messages"] != b["messages"]
    for team in RED:  # no match data in the cached prefix
        assert str(team) not in SYSTEM_PROMPT


def test_the_credential_never_reaches_the_request_result_or_logs(monkeypatch, caplog):
    """The real client path (no client_factory): the env credential is present, the SDK class is replaced by a
    recorder, so the key's only route is through the code under test. It must appear in nothing it produces."""
    import anthropic

    built: list[dict[str, Any]] = []
    facts = report_facts(report_with_models())
    for behaviour in ("ok", "raises", "bad json"):
        def fake_anthropic(**kwargs: Any) -> StubClient:
            built.append(kwargs)
            return {"ok": StubClient(faithful_output(facts)), "raises": StubClient(raises=RuntimeError(SECRET)),
                    "bad json": StubClient("{not json " + SECRET)}[behaviour]
        monkeypatch.setattr(anthropic, "Anthropic", fake_anthropic)
        monkeypatch.setenv("ANTHROPIC_API_KEY", SECRET)
        caplog.set_level(logging.DEBUG)
        result = make_briefing(facts, enabled=True, egress_approved=True, model="claude-opus-5-5", max_tokens=16000,
                               timeout=30.0)
        assert SECRET not in repr(result)
    assert built == [{"timeout": 30.0, "max_retries": MAX_RETRIES}] * 3  # the key is left to the SDK, never passed
    assert SECRET not in caplog.text


# --- accepted output ------------------------------------------------------------------------------------------------


@pytest.mark.parametrize("build", [local_report, report_with_models, unvalidated_win_report])
def test_a_faithful_arrangement_prints_every_statement_verbatim_exactly_once(build):
    facts = report_facts(build())
    result = run(facts, StubClient(faithful_output(facts)))
    assert result.mode == "llm" and result.reason is None, result.reason
    assert result.usage == {"input_tokens": 4000, "output_tokens": 900, "cache_read_input_tokens": 0,
                            "cache_creation_input_tokens": 1200}
    cited = [i for s in result.sections for x in s.sentences for i in x.fact_ids]
    assert sorted(cited) == sorted(f.id for f in facts)
    text = rendered_text(result)
    for fact in facts:
        assert text.count(fact.statement) == 1, fact.id
    assert "Team record: Team 9901 (red): EPA total 31.5 (n = 1)." in text
    assert [s.heading for s in result.sections] == [s.heading for s in deterministic_briefing(facts)]


def test_an_item_is_its_lead_in_then_its_facts_in_the_order_given():
    facts = report_facts(report_with_models())
    payload = arrangement(facts)
    red = payload["sections"][1]["items"][0]
    red["fact_ids"] = list(reversed(red["fact_ids"]))
    red["lead"] = "Scoring record:"
    result = run(facts, StubClient(json.dumps(payload)))
    by_id = {f.id: f for f in facts}
    sentence = result.sections[1].sentences[0]
    assert sentence.text == " ".join(["Scoring record:"] + [by_id[i].statement for i in red["fact_ids"]])


# --- rejected output: each rule has its own case ------------------------------------------------------------------


def _with(facts, edit) -> str:
    payload = arrangement(facts)
    edit(payload)
    return json.dumps(payload)


def _lead(text: str):
    def edit(payload: dict[str, Any]) -> None:
        payload["sections"][1]["items"][0]["lead"] = text
    return edit


def _move_all_to_match(payload: dict[str, Any]) -> None:
    ids = [i for s in payload["sections"] for item in s["items"] for i in item["fact_ids"]]
    payload["sections"] = [{"heading": "Match", "items": [{"lead": "", "fact_ids": ids}]}]


def _drop(fact_id: str):
    def edit(payload: dict[str, Any]) -> None:
        for s in payload["sections"]:
            for item in s["items"]:
                item["fact_ids"] = [i for i in item["fact_ids"] if i != fact_id]
            s["items"] = [i for i in s["items"] if i["fact_ids"]]
        payload["sections"] = [s for s in payload["sections"] if s["items"]]
    return edit


def _cite_twice(payload: dict[str, Any]) -> None:
    payload["sections"][0]["items"][0]["fact_ids"].append(payload["sections"][0]["items"][0]["fact_ids"][0])


def _swap_forecast_into_red(payload: dict[str, Any]) -> None:
    _drop("forecast.win_probability")(payload)
    payload["sections"][1]["items"][0]["fact_ids"].append("forecast.win_probability")


REJECTIONS = [
    # structure (review R1 C2, C3)
    ("all facts in one item", _move_all_to_match, "wrong_section"),
    ("a fact under another section", _swap_forecast_into_red, "wrong_section"),
    ("a fact dropped", _drop("forecast.win_probability"), "fact_not_cited"),
    ("an unproduced item dropped", _drop("not_produced.key_risks"), "fact_not_cited"),
    ("a fact cited twice", _cite_twice, "fact_cited_twice"),
    ("an unknown fact", lambda p: p["sections"][0]["items"][0]["fact_ids"].append("red.9999.made_up"), "unknown_fact"),
    ("an invented heading", lambda p: p["sections"][0].update(heading="RED WILL WIN 99% - bet on 9901"), "heading"),
    ("a heading twice", lambda p: p["sections"].insert(1, p["sections"][0]), "heading"),
    ("headings out of order", lambda p: p["sections"].reverse(), "heading"),
    # any lead-in outside the closed label list (P9-D1)
    ("a free lead-in", _lead("Team record, scoring summary:"), "lead_not_allowed"),
    ("a label with a space added", _lead(" Team record:"), "lead_not_allowed"),
    ("a label in other case", _lead("team record:"), "lead_not_allowed"),
]


@pytest.mark.parametrize("case, edit, rule", REJECTIONS, ids=[c[0] for c in REJECTIONS])
def test_an_unfaithful_arrangement_is_rejected_and_the_deterministic_briefing_served(case, edit, rule):
    facts = report_facts(report_with_models())
    result = run(facts, StubClient(_with(facts, edit)))
    assert result.mode == "deterministic"
    assert result.reason == f"validation_failed:{rule}"
    assert result.sections == deterministic_briefing(facts)
    assert result.usage["output_tokens"] == 900  # the spend is still recorded


@pytest.mark.parametrize("lead", ["", *LEAD_INS])
def test_every_listed_label_and_no_label_is_accepted(lead):
    facts = report_facts(report_with_models())
    assert run(facts, StubClient(_with(facts, _lead(lead)))).mode == "llm"


# Every free-text lead-in attack of reviews R1 and R2: each was, or could have been, served in llm mode by a
# filtered free-text design. Under the closed list none can be expressed.
LEAD_ATTACKS = [
    # R1: values, codes, markup, outcomes, comparisons, probability, quality, negation, advice, unproduced items
    "Team record, sixty points:", "Team 9904 has an EPA total of", "Sixtyfour points:", "Record LXIV:",
    "Record \u2465\u2463:", "label validated_playoff:", "<img src=x onerror=alert(document.cookie)>",
    "See https://evil.example/", "Red should prevail and take this match:", "The favoured alliance:",
    "Higher than every blue robot:", "A good chance for red:", "Reliable in practice:", "This isn't what it seems:",
    "Ignore the label here:", "Key risks for red:",
    # R2: prefixed negations, missing words, dismissals, inversion, smuggled numbers, side misattribution
    "Unlikely:", "Improbable:", "Uncalibrated:", "Untrustworthy:", "Red alliance is dominant.", "Victorious:",
    "Lopsided match:", "Fabricated:", "Obsolete:", "Treat as a dependable figure anyway:", "The opposite holds for",
    "Read as the blue side's figure:", "Strategy for the blue alliance:", "Team twofivefour:", "Team xxv:",
    "Zwei, drei:", "Invalid, improbable placeholders:",
]


@pytest.mark.parametrize("lead", LEAD_ATTACKS)
def test_no_free_text_lead_in_can_be_served(lead):
    facts = report_facts(unvalidated_win_report())
    for section in range(len(arrangement(facts)["sections"])):
        payload = arrangement(facts)
        payload["sections"][section]["items"][0]["lead"] = lead
        result = run(facts, StubClient(json.dumps(payload)))
        assert (result.mode, result.reason) == ("deterministic", "validation_failed:lead_not_allowed"), lead


def test_value_laundering_by_citing_extra_facts_cannot_change_any_statement():
    """R1 C1: a value was moved to another subject by citing an extra fact. Here an item groups facts from one
    section in an adversarial order and under an unrelated label: still accepted, and each fact is still printed
    whole, beside its own subject, exactly once. Nothing in the served text is not a statement or a listed label."""
    facts = report_facts(report_with_models())
    payload = arrangement(facts)
    red = payload["sections"][1]
    ids = [i for item in red["items"] for i in item["fact_ids"]]
    red["items"] = [{"lead": "Sources:", "fact_ids": list(reversed(ids))}]
    result = run(facts, StubClient(json.dumps(payload)))
    assert result.mode == "llm"
    by_id = {f.id: f for f in facts}
    [sentence] = result.sections[1].sentences
    assert sentence.text == " ".join(["Sources:"] + [by_id[i].statement for i in reversed(ids)])


# --- malformed output never raises (review R1 C5) ----------------------------------------------------------------


@pytest.mark.parametrize("client, reason", [
    (StubClient("{not json"), "invalid_json"),
    (StubClient('{"sections": []}'), "validation_failed:schema"),
    (StubClient("[1, 2]"), "validation_failed:schema"),
    (StubClient("null"), "validation_failed:schema"),
    (StubClient('{"sections": [1]}'), "validation_failed:schema"),
    (StubClient('{"sections": [{"heading": "Match", "items": ["x"]}]}'), "validation_failed:schema"),
    (StubClient('{"sections": [{"heading": "Match", "items": [{"lead": 1, "fact_ids": ["match"]}]}]}'),
     "validation_failed:schema"),
    (StubClient('{"sections": [], "extra": 1}'), "validation_failed:schema"),
    (StubClient("[" * 100000 + "]" * 100000), "invalid_json"),
    (StubClient('{"sections": ' + "1" * 5000 + "}"), "invalid_json"),  # beyond the int digit limit (R2 C2)
    (StubClient('{"sections": [], "sections": []}'), "validation_failed:schema"),  # duplicate keys (R2 C2)
    (StubClient(None), "no_text"),
    (StubClient(content=None), "no_text"),
    (StubClient(content="not a list"), "no_text"),
    (StubClient("{}", stop="refusal"), "refusal"),
    (StubClient("{}", stop="max_tokens"), "truncated"),
    (StubClient(raises=ConnectionError("network down")), "api_error:ConnectionError"),
    (StubClient(raises=TimeoutError("slow")), "api_error:TimeoutError"),
], ids=["invalid json", "empty", "a list", "null", "a non-object section", "a non-object item", "a non-string lead",
        "an extra key", "deep nesting", "a huge integer", "duplicate keys", "no text", "no content", "content not a list", "refusal", "truncated", "network",
        "timeout"])
def test_every_failure_path_serves_the_deterministic_briefing(client, reason):
    facts = report_facts(report_with_models())
    result = run(facts, client)
    assert (result.mode, result.reason) == ("deterministic", reason)
    assert result.sections == deterministic_briefing(facts)


def test_text_before_a_fallback_block_is_ignored_and_every_attempt_is_counted():
    facts = report_facts(report_with_models())
    content = [SimpleNamespace(type="text", text='{"partial": '),
               SimpleNamespace(type="fallback", **{"from": {"model": "claude-opus-5-5"}}, to={"model": "x"}),
               SimpleNamespace(type="text", text=faithful_output(facts))]
    usage = SimpleNamespace(input_tokens=10, output_tokens=5, iterations=[
        {"type": "message", "input_tokens": 4000, "output_tokens": 20},
        {"type": "fallback_message", "input_tokens": 4100, "output_tokens": 900, "cache_read_input_tokens": 0}])
    result = run(facts, StubClient(content=content, usage=usage))
    assert result.mode == "llm"
    assert result.usage == {"input_tokens": 8100, "output_tokens": 920, "cache_read_input_tokens": 0, "attempts": 2}


def test_real_sdk_errors_are_caught_by_class_name():
    import anthropic
    import httpx2

    request = httpx2.Request("POST", "https://example.invalid/v1/messages")
    facts = report_facts(local_report())
    errors = [anthropic.APIConnectionError(request=request),
              anthropic.APITimeoutError(request=request),
              anthropic.RateLimitError("rate limited", response=httpx2.Response(429, request=request), body=None)]
    for error in errors:
        assert run(facts, StubClient(raises=error)).reason == f"api_error:{type(error).__name__}"


def test_rejections_are_logged_by_rule_only_never_with_model_text(caplog):
    caplog.set_level(logging.INFO)
    facts = report_facts(report_with_models())
    run(facts, StubClient(_with(facts, _lead("<script>exfiltrate()</script>"))))
    assert "lead_not_allowed" in caplog.text and "script" not in caplog.text


def test_blue_teams_are_grouped_too():
    facts = report_facts(local_report())
    result = run(facts, StubClient(faithful_output(facts)))
    blue = next(s for s in result.sections if s.heading == "Blue alliance")
    assert all(x.text.startswith("Team record: ") for x in blue.sentences if x.fact_ids[0].split(".")[1].isdigit())
    assert {x.fact_ids[0].split(".")[1] for x in blue.sentences} >= {str(t) for t in BLUE}
