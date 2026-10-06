"""Kanav's 2026-10-06 decisions D-PX1-1..5 (`.agent/phase6/decisions/P6_PX1_COMPOSITION_DECISIONS.md`).

Covers selection-time members (backups never in the composition), the four-member exclusion with its accounting,
PX-1's three-team domain guard, M8's actual picks, the C1/C2 populations, and the schema-v3 null rules
(`not_established` only where a null would decide an outcome).

SYNTHETIC events, teams and rulesets: test fixtures, not evidence.
"""

from __future__ import annotations

import copy
from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

from data.alliances import Alliance
from data.rulesets import RulesetError, SeasonRuleset
from ml.playoffs.data import EventPlayoffs, RawPlayoffMatch, event_members, playoff_rows, selection_members
from ml.playoffs.evaluation import PredictedAlliance, identifies
from ml.playoffs.px1 import OutsidePX1Domain, alliance_match_probability
from ml.playoffs.selection import DraftState, SelectionEngine, best_available, run_draft
from tests.phase6_bracket_fixtures import ruleset, unresolved, with_three_pick_variant
from tests.phase6_fixtures import team

SEASON = 2099
STANDARD, CHAMPIONSHIP = "2099std", "2099div"
WHEN = datetime(2099, 3, 1, 12, tzinfo=timezone.utc)


def _rules() -> SeasonRuleset:
    return SeasonRuleset.model_validate(with_three_pick_variant(ruleset(SEASON), [CHAMPIONSHIP]))


def _alliance(seed: int, picks: tuple[int, ...]) -> Alliance:
    return Alliance(seed=seed, position=seed, name=f"Alliance {seed}", captain=picks[0], picks=picks, backup=None,
                    declines=())


def _standard_event() -> EventPlayoffs:
    """8 alliances of 3; seed 1 also lists backup 104 (TBA's representation), who played sf1 instead of 103."""
    alliances = [_alliance(s, (100 * s + 1, 100 * s + 2, 100 * s + 3)) for s in range(1, 9)]
    alliances[0] = _alliance(1, (101, 102, 103, 104))
    matches = (RawPlayoffMatch(f"{STANDARD}_sf1m1", "semifinal", 1, 1, WHEN, "red", (101, 102, 104), (801, 802, 803)),
               RawPlayoffMatch(f"{STANDARD}_sf2m1", "semifinal", 2, 1, WHEN, "blue", (401, 402, 403), (501, 502, 503)))
    return EventPlayoffs(STANDARD, SEASON, tuple(alliances), matches, WHEN, 40)


def _championship_event() -> EventPlayoffs:
    alliances = [_alliance(s, (100 * s + 1, 100 * s + 2, 100 * s + 3, 100 * s + 4)) for s in range(1, 9)]
    matches = (RawPlayoffMatch(f"{CHAMPIONSHIP}_sf1m1", "semifinal", 1, 1, WHEN, "red", (101, 102, 103),
                               (801, 802, 804)),
               RawPlayoffMatch(f"{CHAMPIONSHIP}_sf2m1", "semifinal", 2, 1, WHEN, "red", (401, 402, 404),
                               (501, 503, 504)))
    return EventPlayoffs(CHAMPIONSHIP, SEASON, tuple(alliances), matches, WHEN, 70)


def _features(event: EventPlayoffs, *, without_epa: set[int] = frozenset()):
    teams = {t for a in event.alliances for t in a.picks}
    return {t: (team(t, None, None, None, epa_scale=None) if t in without_epa else team(t)) for t in teams}


# --- D-PX1-1: selection-time members ------------------------------------------------------------------------


def test_a_listed_backup_is_never_a_member():
    rules = _rules().for_event(STANDARD)
    assert selection_members(_alliance(1, (101, 102, 103, 104)), rules) == (101, 102, 103)
    assert selection_members(_alliance(2, (201, 202, 203)), rules) == (201, 202, 203)


def test_championship_variant_members_are_four():
    rules = _rules().for_event(CHAMPIONSHIP)
    assert selection_members(_alliance(1, (101, 102, 103, 104)), rules) == (101, 102, 103, 104)


def test_unexplained_listings_are_refused_not_interpreted():
    standard, championship = _rules().for_event(STANDARD), _rules().for_event(CHAMPIONSHIP)
    for rules, picks, code in ((standard, (101, 102, 103, 104, 105), "unexpected_listed_team"),  # two extras
                               (championship, (101, 102, 103, 104, 105), "unexpected_listed_team"),  # no backups
                               (standard, (101, 102), "incomplete_alliance")):
        with pytest.raises(RulesetError) as refused:
            selection_members(_alliance(1, picks), rules)
        assert refused.value.code == code


def test_px1_rows_compose_from_members_and_a_backup_never_enters():
    event, rules = _standard_event(), _rules()
    rows, excluded = playoff_rows(event, rules.bracket(8), _features(event), rules.for_event(STANDARD))
    sf1 = next(r for r in rows if r.match_key.endswith("sf1m1"))
    assert [t.team_number for t in sf1.red_teams] == [101, 102, 103]  # 104 played but is a backup
    assert all(len(r.red_teams) == 3 and len(r.blue_teams) == 3 for r in rows)  # also the M6/M7 baseline input
    assert not excluded


def test_a_backup_without_epa_no_longer_excludes_the_row():
    event, rules = _standard_event(), _rules()
    rows, excluded = playoff_rows(event, rules.bracket(8), _features(event, without_epa={104}),
                                  rules.for_event(STANDARD))
    assert len(rows) == 2 and not excluded.get("epa_incomplete")


# --- D-PX1-2: four-member rows excluded and counted --------------------------------------------------------------


def test_four_member_rows_are_excluded_before_the_epa_check_and_counted():
    event, rules = _championship_event(), _rules()
    rows, excluded = playoff_rows(event, rules.bracket(8), _features(event, without_epa={101}),
                                  rules.for_event(CHAMPIONSHIP))
    assert rows == []
    assert excluded == {"four_member_alliance": 2}  # never counted as epa_incomplete


def test_px1_refuses_an_alliance_that_is_not_three_teams():
    p = alliance_match_probability(None, {})  # the guard runs before the model is consulted
    with pytest.raises(OutsidePX1Domain):
        p((1, 2, 3, 4), (5, 6, 7), 1, 8, 1)


def test_c1_c2_population_keeps_intended_and_validated_apart():
    from scripts.phase6_playoff_track import representable_events

    events = [_standard_event(), _championship_event()]
    m1 = {"events": {STANDARD: {"status": "reproduced"}, CHAMPIONSHIP: {"status": "reproduced"}}}
    population = representable_events({SEASON: _rules()}, m1, events)
    assert population["intended_events"] == 2 and population["validated_events"] == 1
    assert [e.event_key for e in population["validated"]] == [STANDARD]
    assert population["excluded_events"] == {CHAMPIONSHIP: {"reason": "four_member_alliance",
                                                            "selection_variant": "three_picks", "alliances": 8}}
    assert population["excluded_alliances"] == 8
    assert population["members"][STANDARD][1] == (101, 102, 103)


def test_m8_actual_pick_cannot_be_satisfied_by_a_backup():
    members = event_members(_standard_event(), _rules().for_event(STANDARD))
    predicted = [PredictedAlliance((101, 104, 999), 0.9), PredictedAlliance((201, 202, 203), 0.8)]
    assert not identifies(members[1], predicted)  # only the backup 104 matches a non-captain
    assert identifies((101, 102, 103, 104), predicted)  # what listing-based code would have accepted


# --- D-PX1-4/5: schema v3 null rules -----------------------------------------------------------------------------


def _null(data: dict, *fields: str) -> dict:
    for field in fields:
        data["selection"][field] = None
    data["selection"]["unresolved"] = [unresolved(f) for f in fields]
    return data


def test_null_is_allowed_only_with_an_unresolved_note():
    assert SeasonRuleset.model_validate(_null(ruleset(SEASON), "captain_rule", "declined_team_may_become_captain"))
    bare = ruleset(SEASON)
    bare["selection"]["declined_team_may_become_captain"] = None
    with pytest.raises(ValidationError):
        SeasonRuleset.model_validate(bare)  # null without a note
    noted = ruleset(SEASON)
    noted["selection"]["unresolved"] = [unresolved("captain_rule")]
    with pytest.raises(ValidationError):
        SeasonRuleset.model_validate(noted)  # a note for a field that is not null
    twice = _null(ruleset(SEASON), "captain_rule")
    twice["selection"]["unresolved"].append(unresolved("captain_rule"))
    with pytest.raises(ValidationError):
        SeasonRuleset.model_validate(twice)


@pytest.mark.parametrize("field", ["order", "picks_per_alliance", "captain_may_accept_higher_alliance",
                                   "declined_team_may_be_picked_later", "backup_robots"])
def test_no_other_selection_field_may_be_null(field):
    data = ruleset(SEASON)
    data["selection"][field] = None
    with pytest.raises(ValidationError):
        SeasonRuleset.model_validate(data)


def test_an_unresolved_note_needs_text_and_sources():
    for key in ("note", "sources_checked"):
        data = _null(ruleset(SEASON), "captain_rule")
        data["selection"]["unresolved"][0][key] = ""
        with pytest.raises(ValidationError):
            SeasonRuleset.model_validate(data)


def test_older_schema_versions_are_refused():
    for version in ("p6-ruleset-v1", "p6-ruleset-v2"):
        data = copy.deepcopy(ruleset(SEASON))
        data["schema_version"] = version
        with pytest.raises(ValidationError):
            SeasonRuleset.model_validate(data)


TEAMS = list(range(101, 113))
RANKS = {t: i for i, t in enumerate(TEAMS, start=1)}


def _event_rules(*null_fields: str):
    return SeasonRuleset.model_validate(_null(ruleset(SEASON), *null_fields)).for_event(STANDARD)


def test_a_null_decline_rule_changes_nothing_when_no_declined_team_is_decisive():
    known = SeasonRuleset.model_validate(ruleset(SEASON)).for_event(STANDARD)
    unknown = _event_rules("declined_team_may_become_captain")
    baseline = run_draft(DraftState.empty(4), known, RANKS, best_available(TEAMS))
    assert run_draft(DraftState.empty(4), unknown, RANKS, best_available(TEAMS)) == baseline
    # a declined team that never becomes the best-ranked available one decides nothing (13 teams, 12 slots)
    teams = TEAMS + [113]
    ranks = {t: i for i, t in enumerate(teams, start=1)}
    state = DraftState(((), (), (), ()), frozenset({113}))
    drafted = run_draft(state, unknown, ranks, best_available(teams))
    assert drafted.alliances == run_draft(state, known, ranks, best_available(teams)).alliances
    assert 113 not in drafted.on_alliance()


def test_a_null_decline_rule_refuses_when_a_declined_team_would_be_the_next_captain():
    state = DraftState(((), (), (), ()), frozenset({101}))  # the best-ranked team has declined
    with pytest.raises(RulesetError) as refused:
        run_draft(state, _event_rules("declined_team_may_become_captain"), RANKS, best_available(TEAMS))
    assert refused.value.code == "not_established"


def test_a_null_captain_rule_refuses_every_draft_and_engine():
    rules = _event_rules("captain_rule")
    with pytest.raises(RulesetError) as draft:
        run_draft(DraftState.empty(4), rules, RANKS, best_available(TEAMS))
    with pytest.raises(RulesetError) as engine:
        SelectionEngine(rules, RANKS, TEAMS, lambda *a: 0.5, probability_status="synthetic")
    assert draft.value.code == engine.value.code == "not_established"


def test_m1_b_records_a_null_captain_rule_as_not_established():
    from types import SimpleNamespace

    from scripts.phase6_playoff_track import _captain_rule_violations

    event = SimpleNamespace(event_key=STANDARD, alliances=[_alliance(1, (101, 102, 103)),
                                                          _alliance(2, (104, 105, 106))])
    assert _captain_rule_violations(event, RANKS, _event_rules("captain_rule")) == (
        [], {"captain_rule_not_established": 2})
    declined = SimpleNamespace(event_key=STANDARD, alliances=[
        Alliance(1, 1, None, 102, (102, 103, 104), None, (101,)), _alliance(2, (105, 106, 107))])
    violations, unchecked = _captain_rule_violations(declined, RANKS,
                                                     _event_rules("declined_team_may_become_captain"))
    # 101 declined and joined no alliance, so it is the best-ranked available team at BOTH captain turns
    assert violations == [] and unchecked == {"decline_rule_not_established": 2}
