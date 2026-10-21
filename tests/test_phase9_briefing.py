"""P9-M2: briefing facts and the deterministic briefing. Synthetic reports only (tests/phase9_fixtures.py); pure."""

from __future__ import annotations

import re
from typing import Any

import pytest

from briefing.facts import NOT_PRODUCED_TITLES, TEMPLATE_CONSTANTS, Fact, number, percent, report_facts
from briefing.render import as_text, briefing_for_report, deterministic_briefing
from tests.phase9_fixtures import BLUE, RED, local_report, report_with_models, unvalidated_win_report

ALL_REPORTS = [local_report, report_with_models, unvalidated_win_report]

# Reference outputs of the dashboard's formatNumber (Intl `toLocaleString`, en-US, maximumFractionDigits = digits,
# grouping on, as the dashboard calls it), produced with Node 24 on 2026-10-20. `number` must state the same digits an
# en-US dashboard shows. (The dashboard uses the browser's locale; the briefing is en-US. P9-R9.)
INTL_REFERENCE = [
    ((8.25, 1), "8.3"), ((61.25, 1), "61.3"), ((4.25, 1), "4.3"), ((0.125, 1), "0.1"), ((0.125, 2), "0.13"),
    ((2.675, 1), "2.7"), ((2.675, 2), "2.68"), ((1.005, 2), "1.01"), ((150, 1), "150"), ((268.94, 1), "268.9"),
    ((-2.25, 1), "-2.3"), ((0, 1), "0"), ((3.5, 2), "3.5"), ((0.45, 1), "0.5"), ((1.45, 1), "1.5"), ((2.5, 0), "3"),
    ((0.1234567, 2), "0.12"), ((99.95, 1), "100"), ((1e-7, 2), "0"), ((123456.789, 1), "123,456.8"),
    ((0.615, 2), "0.62"), ((5.015, 2), "5.02"), ((19.999, 1), "20"), ((1234.5, 1), "1,234.5"), ((1000, 1), "1,000"),
    ((-0.04, 1), "-0"), ((0.4251, 3), "0.425"), ((12.5, 1), "12.5"),
]


NUMBER_TOKEN = re.compile(r"\d[\d,:.\-TZ]*\d|\d")


def resolve(report: dict[str, Any], path: str) -> Any:
    node: Any = report
    for part in re.findall(r"[^.\[\]]+|\[\d+\]", path):
        node = node[int(part[1:-1])] if part.startswith("[") else node[part]
    return node


@pytest.mark.parametrize("value_digits, expected", INTL_REFERENCE)
def test_numbers_read_exactly_as_the_dashboard_shows_them(value_digits, expected):
    assert number(*value_digits) == expected


@pytest.mark.parametrize("build", ALL_REPORTS)
def test_every_fact_has_a_unique_id_and_traces_to_a_real_report_field(build):
    report = build()
    facts = report_facts(report)
    assert len({f.id for f in facts}) == len(facts)
    for fact in facts:
        resolve(report, fact.source)  # raises if the path does not exist


@pytest.mark.parametrize("build", ALL_REPORTS)
def test_every_report_section_is_covered(build):
    facts = report_facts(build())
    sections = {f.section for f in facts}
    assert {"match", "red", "blue", "forecast", "strategy", "not_produced", "source"} <= sections
    for team in RED + BLUE:  # every robot has facts
        assert any(f.id.startswith(f"red.{team}.") or f.id.startswith(f"blue.{team}.") for f in facts), team
    assert {f.id for f in facts if f.kind == "not_produced"} == {f"not_produced.{k}" for k in NOT_PRODUCED_TITLES}
    assert {"red.synergy", "blue.synergy", "forecast.win_probability"} <= {f.id for f in facts}


@pytest.mark.parametrize("build", ALL_REPORTS)
def test_every_stated_number_comes_from_the_report(build):
    """Each number a fact's statement contains is exactly one of the numbers of its own declared values (never a
    substring of one), and every declared numeric value is the served value at the fact's source, formatted as the
    dashboard formats it."""
    report = build()
    for fact in report_facts(report):
        statement = fact.statement
        for constant in TEMPLATE_CONSTANTS:  # fixed template wording, not data
            statement = statement.replace(constant, " ")
        allowed = {token for v in fact.values for token in NUMBER_TOKEN.findall(v)}
        for token in NUMBER_TOKEN.findall(statement):
            assert token in allowed, (fact.id, token, fact.values)
        if fact.kind == "value" and fact.source.endswith(("total", "auto", "teleop", "endgame", "average_score",
                                                          "consistency_rating", "reliability_score")):
            served = resolve(report, fact.source)["value"]
            assert number(served) in fact.values, fact.id


def test_absences_are_stated_with_their_served_reason_never_as_zero():
    facts = {f.id: f for f in report_facts(local_report())}
    blue_epa = facts[f"blue.{BLUE[0]}.epa"]
    assert blue_epa.kind == "absence" and "no_prior_concluded_event_epa" in blue_epa.statement
    feeding = facts[f"red.{RED[0]}.feeding"]
    assert feeding.kind == "absence" and "insufficient_data: fewer than 2 scouting observations" in feeding.statement
    assert "not_validated" in feeding.statement  # the served label, verbatim
    assert facts["forecast.win_probability"].kind == "absence" and "model_not_loaded" in facts["forecast.win_probability"].statement
    assert facts["strategy"].kind == "absence" and "model_not_loaded" in facts["strategy"].statement
    assert facts["blue.synergy"].kind == "absence" and "alliance_incomplete" in facts["blue.synergy"].statement
    for fact in facts.values():
        if fact.kind == "absence":
            assert not re.search(r"\b0(\.0+)?\b", fact.statement.replace("0-5", "")), fact.statement


def test_the_six_unproduced_items_are_explicit_absences_with_their_served_semantics():
    report = local_report()
    facts = {f.id: f for f in report_facts(report)}
    for key, title in NOT_PRODUCED_TITLES.items():
        fact = facts[f"not_produced.{key}"]
        assert fact.statement.startswith(f"{title}: not produced by any engine.")
        assert report["not_produced"][key]["semantics"] in fact.statement
        assert not any(re.search(r"\d", v) for v in fact.values)  # no number may be stated about them


def test_a_validated_win_probability_is_a_percentage_with_its_label():
    fact = {f.id: f for f in report_facts(report_with_models())}["forecast.win_probability"]
    assert fact.kind == "value" and "60%" in fact.statement and "approximately_calibrated_qualification" in fact.statement


def test_an_unvalidated_win_probability_never_states_its_number():
    fact = {f.id: f for f in report_facts(unvalidated_win_report())}["forecast.win_probability"]
    assert fact.kind == "label"
    assert "unvalidated" in fact.statement and "not a validated probability" in fact.statement
    assert not re.search(r"0\.75|75\s*%|\b75\b", fact.statement)
    assert not any(re.fullmatch(r"[\d.,%]+", v) for v in fact.values)  # codes such as m7_gate_failed aside


def test_strategy_odds_and_labels_are_served_verbatim_and_kept_apart_from_the_win_probability():
    facts = {f.id: f for f in report_facts(report_with_models())}
    red = facts["strategy.red"]
    assert "65%" in red.statement and "not_validated" in red.statement
    assert "separate model from the match win probability" in red.statement
    assert "defense on 9905" in red.statement and "feeding 9901" in red.statement


@pytest.mark.parametrize("build", ALL_REPORTS)
def test_the_deterministic_briefing_is_byte_stable_and_states_every_fact_once(build):
    first, second = briefing_for_report(build()), briefing_for_report(build())
    assert as_text(first[1]) == as_text(second[1])
    facts, sections = first
    cited = [fid for s in sections for sentence in s.sentences for fid in sentence.fact_ids]
    assert sorted(cited) == sorted(f.id for f in facts)  # each fact exactly once
    assert [s.heading for s in sections][:1] == ["Match"]


def test_a_duplicate_fact_id_is_refused():
    from briefing import facts as module
    duplicate = [Fact("x", "context", "match", "a"), Fact("x", "context", "match", "b")]
    with pytest.raises(ValueError, match="duplicate fact ids"):
        module._assert_unique(duplicate)
    assert deterministic_briefing([Fact("x", "context", "match", "a")])[0].heading == "Match"


def test_every_caveat_the_dashboard_shows_is_part_of_its_value_fact():
    """Review R1 (C6): a stated value carries its caveats, so no briefing can state one without the other."""
    facts = {f.id: f for f in report_facts(report_with_models())}
    forecast = facts["forecast.win_probability"].statement
    assert "60%" in forecast and "calibration status m7_gate_failed" in forecast
    red = facts["strategy.red"].statement
    assert "qualifiers strategy_effect_unmeasured" in red
    assert "maximum of many model estimates" in red and "versus the baseline: within one display step" in red
    assert facts["strategy.coach_observations"].statement == "Coach observations applied to the strategy inputs: 2."
    assert "± 12.5 (n = 6)" in facts[f"red.{RED[0]}.average_score"].statement
    assert "(the requested moment)" in facts["match"].statement
    labels = facts[f"red.{RED[0]}.labels"]
    assert labels.kind == "label" and labels.statement == (
        f"Team {RED[0]} (red): EPA label descriptive (source: statbotics, from 2099prior, current); scoring label "
        "descriptive; overall label descriptive, with the qualifiers reliability_interim.")
    assert "with the qualifiers" not in facts[f"blue.{BLUE[0]}.labels"].statement  # none served, none stated
    defense = facts[f"red.{RED[0]}.defense"].statement
    assert "3.5 (n = 3); scout agreement 0.5 (n = 3); label descriptive_definition_pending" in defense
    assert "confidence 0.5 (the share of each term's possible evidence that is present)" in facts["red.synergy"].statement
    assert f"{RED[1]}: defense on {BLUE[1]}, scores in auto, endgame" in red
    assert "INTERIM" in facts[f"red.{RED[0]}.reliability_score"].statement
    # R2 C4: an unvalidated output keeps its label, qualifiers, calibration status and scope (never its number)
    unvalidated = {f.id: f for f in report_facts(unvalidated_win_report())}["forecast.win_probability"].statement
    assert "(qualification scope; label not_validated; calibration status m7_gate_failed; qualifiers playoff_scope)" \
        in unvalidated


def test_a_baseline_only_side_keeps_the_reasons_it_has_no_probability():
    """R2 C4: the dashboard shows "The engine gives no probability: {reasons}" beside a baseline-only plan."""
    report = report_with_models()
    side = report["strategy"]["sides"][0]
    side["recommended"] = None
    side["baseline"]["odds"] = {"display": None, "validation": {"status": "not_validated", "reasons": []}}
    side["unavailable_reasons"] = ["odds_out_of_range", "candidate_set_empty"]
    red = {f.id: f for f in report_facts(report)}["strategy.red"].statement
    assert red.startswith("Red baseline: ")
    assert "The engine gives no probability: odds_out_of_range, candidate_set_empty." in red


def test_a_scoring_robot_without_components_is_stated_as_none():
    report = report_with_models()
    report["strategy"]["sides"][0]["recommended"]["strategy"]["robots"][0]["components"] = []
    assert f"{RED[0]}: scoring (none)" in {f.id: f for f in report_facts(report)}["strategy.red"].statement


@pytest.mark.parametrize("value, shown", [(0.125, "13%"), (0.625, "63%"), (0.025, "3%"), (0.005, "1%"), (0.6, "60%"),
                                          (0.95, "95%"), (0.05, "5%"), (0.0, "0%"), (1.0, "100%")])
def test_win_percentages_round_half_up_as_the_dashboards_math_round(value, shown):
    """R2 C3: Python's round() is half-to-even (0.125 -> 12); the dashboard's Math.round gives 13."""
    assert percent(value) == shown


def test_numbers_never_overflow():
    assert number(1e27) == "1,000,000,000,000,000,000,000,000,000" and number(1.5e300, 1).startswith("1,5")


def test_synergy_is_stated_at_the_dashboards_precision():
    report = report_with_models()
    report["synergy"][0]["score"]["overall_score"] = 0.4251
    fact = {f.id: f for f in report_facts(report)}["red.synergy"]
    assert "overall score 0.425 " in fact.statement
