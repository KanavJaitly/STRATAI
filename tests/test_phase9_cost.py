"""P9-M6: the cost tool's parts that need no credential and no database. Synthetic reports only."""

from __future__ import annotations

import json

import pytest

from briefing.facts import report_facts
from briefing.llm import parse, validate
from scripts.phase9_briefing_cost import PRICES, cost_per_event, measure_tokens, reference_arrangement
from tests.phase9_fixtures import local_report, report_with_models


@pytest.mark.parametrize("build", [local_report, report_with_models])
def test_the_reference_output_is_a_faithful_arrangement(build):
    """The output size stands for what a faithful model returns, so it must itself pass the validator."""
    facts = report_facts(build())
    validate(parse(json.loads(reference_arrangement(facts))), facts)


def test_without_a_credential_no_token_is_counted_or_invented(monkeypatch, tmp_path):
    for name in ("ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN", "ANTHROPIC_PROFILE", "ANTHROPIC_FEDERATION_RULE_ID"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("ANTHROPIC_CONFIG_DIR", str(tmp_path / "none"))
    measured = measure_tokens([], list(PRICES))
    assert measured == {"status": "BLOCKED", "reason": "no_credential (P9-R1)"}
    assert cost_per_event(measured, 80)["status"] == "BLOCKED"


def test_the_cost_per_event_arithmetic_against_hand_computed_figures():
    """Worked by hand, not with the module's constants (review R2 C9): Opus 5.5 at $4 / $20 per million tokens,
    cache writes at 1.25x and reads at 0.05x ($0.20). 10 briefings of 4,000 input tokens (1,000 of them the system
    prompt) and 600 output tokens.
    - output: 10 x 600 x $20 / 1e6 = $0.12
    - warm: (1,000 x 1.25 + 9 x 1,000 x 0.05 + 10 x 3,000) x $4 / 1e6 = 31,700 x 4 / 1e6 = $0.1268, + 0.12 = $0.2468
    - every call writes: 10 x (1,250 + 3,000) x $4 / 1e6 = $0.17, + 0.12 = $0.29
    - no caching: 10 x 4,000 x $4 / 1e6 = $0.16, + 0.12 = $0.28"""
    measured = {"status": "measured", "models": {"claude-opus-5-5": {
        "system_prompt_tokens_approx": 1000,
        "per_match": [{"match": "m1", "input_tokens": 4000, "output_tokens_estimate": 600},
                      {"match": "m2", "input_tokens": 4000, "output_tokens_estimate": 600}]}}}
    result = cost_per_event(measured, 10)
    assert result["lower_bound"] is True
    assert result["costs"]["claude-opus-5-5"] == {"usd_per_event_cache_warm": 0.2468,
                                                  "usd_per_event_every_call_writes_cache": 0.29,
                                                  "usd_per_event_no_caching": 0.28}
