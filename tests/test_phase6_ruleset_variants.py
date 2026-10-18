"""P6-M1 schema v2 (Kanav's P1 decision, 2026-10-05): per-event selection variants, their provenance, the
deterministic precedence, explicit event exclusions, and the consumers' refusal of a bare season ruleset.

Pure tests on SYNTHETIC fixtures (not rulesets entered from any manual, not evidence).
"""

from __future__ import annotations

import copy

import pytest
from pydantic import ValidationError

from data.rulesets import EventRules, RulesetError, SeasonRuleset
from ml.playoffs.selection import (DraftState, SelectionEngine, available_for_pick, best_available,
                                   pick_prediction_accuracy, run_draft)
from tests.phase6_bracket_fixtures import ruleset, variant_event, with_three_pick_variant

SEASON = 2099
VARIANT_EVENT, DEFAULT_EVENT = "2099div", "2099std"
TEAMS = list(range(101, 117))  # 16 teams: the synthetic roster rule gives 4 alliances
RANKS = {t: i for i, t in enumerate(TEAMS, start=1)}


def _variant_ruleset() -> SeasonRuleset:
    return SeasonRuleset.model_validate(with_three_pick_variant(ruleset(SEASON), [VARIANT_EVENT]))


def _invalid(data) -> None:
    with pytest.raises(ValidationError):
        SeasonRuleset.model_validate(data)


# --- precedence --------------------------------------------------------------------------------------------


def test_listed_event_uses_its_variant_and_every_other_event_the_season_default():
    rules = _variant_ruleset()
    listed, other = rules.for_event(VARIANT_EVENT), rules.for_event(DEFAULT_EVENT)
    assert isinstance(listed, EventRules) and listed.variant == "three_picks"
    assert listed.selection.picks_per_alliance == 3 and listed.selection.backup_robots is False
    assert other.variant is None and other.selection == rules.selection
    assert other.selection.picks_per_alliance == 2 and other.selection.backup_robots is True


def test_a_ruleset_without_variants_gives_every_event_the_default():
    rules = SeasonRuleset.model_validate(ruleset(SEASON))
    assert rules.for_event(VARIANT_EVENT).variant is None


def test_the_draft_follows_the_events_own_rules():
    rules = _variant_ruleset()
    three = run_draft(DraftState.empty(4), rules.for_event(VARIANT_EVENT), RANKS, best_available(TEAMS))
    two = run_draft(DraftState.empty(4), rules.for_event(DEFAULT_EVENT), RANKS, best_available(TEAMS))
    assert all(len(a) == 4 for a in three.alliances)  # captain + 3 picks
    assert all(len(a) == 3 for a in two.alliances)  # captain + 2 picks
    # Serpentine: seed 1 picks first in round 1 (102), last in round 2 (112) and first again in round 3 (113).
    assert three.alliances[0] == (101, 102, 112, 113)


def test_selection_consumers_refuse_a_bare_season_ruleset():
    """The season default can never be applied to an event by accident."""
    rules = _variant_ruleset()
    calls = [lambda: run_draft(DraftState.empty(4), rules, RANKS, best_available(TEAMS)),
             lambda: available_for_pick(DraftState.empty(4), TEAMS, rules),
             lambda: pick_prediction_accuracy([(DraftState.empty(4), 1, 102)], TEAMS, rules, TEAMS),
             lambda: SelectionEngine(rules, RANKS, TEAMS, lambda *a: 0.5, probability_status="synthetic")]
    for call in calls:
        with pytest.raises(RulesetError) as refused:
            call()
        assert refused.value.code == "event_rules_required"


def test_for_event_refuses_another_season_and_a_malformed_key():
    rules = _variant_ruleset()
    with pytest.raises(RulesetError) as other_season:
        rules.for_event("2098div")
    assert other_season.value.code == "wrong_season"
    with pytest.raises(ValueError):
        rules.for_event("not a key")


# --- variants: explicit, complete, cited ---------------------------------------------------------------------


def test_v2_fields_are_required_keys():
    for key in ("selection_variants", "event_exclusions"):
        data = ruleset(SEASON)
        del data[key]
        _invalid(data)


def test_a_variant_needs_events_and_a_complete_selection():
    data = with_three_pick_variant(ruleset(SEASON), [VARIANT_EVENT])
    no_events = copy.deepcopy(data)
    no_events["selection_variants"][0]["events"] = []
    _invalid(no_events)
    partial = copy.deepcopy(data)
    del partial["selection_variants"][0]["selection"]["backup_robots"]
    _invalid(partial)


@pytest.mark.parametrize("field", ["event_key", "rule", "document", "version", "team_update", "section", "url"])
def test_every_listed_event_needs_its_provenance(field):
    data = with_three_pick_variant(ruleset(SEASON), [VARIANT_EVENT])
    missing = copy.deepcopy(data)
    del missing["selection_variants"][0]["events"][0][field]
    _invalid(missing)
    blank = copy.deepcopy(data)
    blank["selection_variants"][0]["events"][0][field] = ""
    _invalid(blank)


def test_team_update_is_an_explicit_null_or_a_named_update():
    data = with_three_pick_variant(ruleset(SEASON), [VARIANT_EVENT])
    assert SeasonRuleset.model_validate(data)  # null: the person states no Team Update applies
    data["selection_variants"][0]["events"][0]["team_update"] = "Team Update 19 (2025-03-25)"
    assert SeasonRuleset.model_validate(data)


@pytest.mark.parametrize("url", ["http://www.firstinspires.org/x", "https://example.com/manual.pdf",
                                 "https://firstinspires.org.example.com/x", "https://notfirstinspires.org/x",
                                 "firstinspires.org/x"])
def test_provenance_must_be_a_first_url(url):
    data = with_three_pick_variant(ruleset(SEASON), [VARIANT_EVENT])
    data["selection_variants"][0]["events"][0]["url"] = url
    _invalid(data)


@pytest.mark.parametrize("url", ["https://firstfrc.blob.core.windows.net/frc2025/Manual/2025GameManual.pdf",
                                 "https://frc-events.firstinspires.org/2025/ARCHIMEDES",
                                 "https://www.firstinspires.org/resources/library/frc/archived-games"])
def test_first_urls_are_accepted(url):
    data = with_three_pick_variant(ruleset(SEASON), [VARIANT_EVENT])
    data["selection_variants"][0]["events"][0]["url"] = url
    assert SeasonRuleset.model_validate(data)


def test_an_event_is_in_at_most_one_variant():
    data = with_three_pick_variant(ruleset(SEASON), [VARIANT_EVENT])
    second = copy.deepcopy(data["selection_variants"][0])
    second["name"] = "another"
    second["selection"]["backup_robots"] = True
    data["selection_variants"].append(second)
    _invalid(data)


def test_duplicate_variant_names_and_duplicate_events_within_a_variant_are_refused():
    data = with_three_pick_variant(ruleset(SEASON), [VARIANT_EVENT, VARIANT_EVENT])
    _invalid(data)
    data = with_three_pick_variant(ruleset(SEASON), [VARIANT_EVENT])
    other = copy.deepcopy(data["selection_variants"][0])
    other["events"] = [variant_event("2099other")]
    data["selection_variants"].append(other)
    _invalid(data)


def test_variant_events_must_belong_to_the_season():
    _invalid(with_three_pick_variant(ruleset(SEASON), ["2025arc"]))
    _invalid(with_three_pick_variant(ruleset(SEASON), ["2099 ARC"]))


def test_a_variant_identical_to_the_default_is_refused():
    data = with_three_pick_variant(ruleset(SEASON), [VARIANT_EVENT])
    data["selection_variants"][0]["selection"] = dict(data["selection"], citation="a different citation only")
    _invalid(data)


def test_the_content_hash_covers_variants():
    assert _variant_ruleset().sha256() != SeasonRuleset.model_validate(ruleset(SEASON)).sha256()


# --- exclusions: unexplained behaviour is excluded and counted, never approximated ----------------------------


def _with_exclusion(reason: str = "backup_before_first_match") -> dict:
    data = ruleset(SEASON)
    data["event_exclusions"] = [{"event_key": "2099odd", "reason": reason,
                                 "finding": "synthetic: the 4th listed team played the alliance's first match"}]
    return data


def test_an_excluded_event_has_no_rules():
    rules = SeasonRuleset.model_validate(_with_exclusion())
    with pytest.raises(RulesetError) as excluded:
        rules.for_event("2099odd")
    assert excluded.value.code == "event_excluded"
    assert excluded.value.details == {"reason": "backup_before_first_match"}
    assert rules.exclusion("2099odd").reason == "backup_before_first_match"
    assert rules.for_event(DEFAULT_EVENT).variant is None


def test_an_exclusion_needs_a_reason_code_and_a_finding():
    for reason in ("", "Not A Code", "1bad"):
        _invalid(_with_exclusion(reason))
    data = _with_exclusion()
    data["event_exclusions"][0]["finding"] = ""
    _invalid(data)
    data = _with_exclusion()
    data["event_exclusions"].append(dict(data["event_exclusions"][0]))
    _invalid(data)
    data = _with_exclusion()
    data["event_exclusions"][0]["event_key"] = "2024isde2"
    _invalid(data)  # another season's event


def test_fresh_template_variant_and_exclusion_entries_fail_validation():
    from scripts.phase6_rulesets import SKELETON

    with pytest.raises(ValidationError) as error:
        SeasonRuleset.model_validate(SKELETON)
    failed = {".".join(str(p) for p in e["loc"]) for e in error.value.errors()}
    for name in ("name", "selection.picks_per_alliance", "selection.backup_robots", "events.0.event_key",
                 "events.0.team_update", "events.0.url"):
        assert f"selection_variants.0.{name}" in failed, name
    for name in ("event_key", "reason", "finding"):
        assert f"event_exclusions.0.{name}" in failed, name
