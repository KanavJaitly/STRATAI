"""P6-M6 / P6-M7 implementation correctness on SYNTHETIC rulesets, teams and probability functions (not evidence)."""

from __future__ import annotations

import math

import pytest

from data.rulesets import RulesetError, SeasonRuleset
from ml.playoffs.selection import (DraftState, SelectionEngine, available_for_pick, best_available,
                                   candidate_profile, field_outcome, pick_prediction_accuracy, run_draft, turn_order)
from tests.phase6_bracket_fixtures import ruleset
from tests.phase6_fixtures import team

RULES = SeasonRuleset.model_validate(ruleset())
TEAMS = list(range(101, 113))  # 12 teams -> 4 alliances in the synthetic ruleset
RANKS = {t: i for i, t in enumerate(TEAMS, start=1)}


def strength_probability(strength):
    def p(red, blue, red_seed, blue_seed, round_):
        return 1.0 / (1.0 + math.exp(-(sum(strength[t] for t in red) - sum(strength[t] for t in blue))))
    return p


def test_serpentine_turn_order():
    assert turn_order(4, 2) == [1, 2, 3, 4, 4, 3, 2, 1]


def test_deterministic_best_available_draft():
    ordering = list(reversed(TEAMS))  # the ordering disagrees with the rankings
    final = run_draft(DraftState.empty(4), RULES, RANKS, best_available(ordering))
    assert final.alliances[0][0] == 101  # captain 1 = highest ranked
    assert final.alliances[0][1] == 112  # picks the best available by ordering
    assert sorted(t for a in final.alliances for t in a) == sorted(TEAMS)
    assert all(len(a) == 3 for a in final.alliances)


def test_declined_team_is_not_picked_later_when_the_rules_say_so():
    state = DraftState.empty(4)._replace if False else DraftState(((), (), (), ()), frozenset({112}))
    assert 112 not in available_for_pick(state, TEAMS, RULES)


def test_unsupported_rules_are_refused():
    data = ruleset()
    data["selection"]["captain_may_accept_higher_alliance"] = False
    with pytest.raises(RulesetError):
        run_draft(DraftState.empty(4), SeasonRuleset.model_validate(data), RANKS, best_available(TEAMS))


def test_profiles_report_n_and_never_impute():
    profile = candidate_profile(team(5, 3.0, 10.0, 2.0))
    assert profile.defense.value is None and profile.defense.validation_status == "insufficient_data"
    assert profile.feeding.value is None and profile.synergy.reason == "alliance incomplete"
    complete = candidate_profile(team(5), [team(5), team(6), team(7)])
    assert complete.synergy.validation_status == "not_validated_against_outcomes"


def _brute_force_best(rules, ordering, strength, seed):
    """Independent reference: for every (first pick, second pick) of `seed`, everyone else best-available."""
    p = strength_probability(strength)
    position = {t: i for i, t in enumerate(ordering)}
    best = {}
    order = turn_order(4, 2)
    for first in TEAMS:
        for second in TEAMS:
            alliances = [[] for _ in range(4)]
            used = set()
            ok = True
            plan = {order.index(seed): first, len(order) - 1 - order[::-1].index(seed): second}
            for turn, s in enumerate(order):
                if not alliances[s - 1]:
                    captain = min((t for t in TEAMS if t not in used), key=lambda t: RANKS[t])
                    alliances[s - 1].append(captain)
                    used.add(captain)
                if turn in plan:
                    choice = plan[turn]
                    if choice in used:
                        ok = False
                        break
                else:
                    choice = min((t for t in TEAMS if t not in used), key=lambda t: position[t])
                alliances[s - 1].append(choice)
                used.add(choice)
            if not ok:
                continue
            outcome = field_outcome(tuple(tuple(a) for a in alliances), rules.bracket(4), p, seed)
            best[first] = max(best.get(first, (-1, -1)), (outcome.p_win_event, outcome.p_reach_finals))
    return best


def test_engine_equals_independent_brute_force():
    strength = {t: 0.1 * (113 - t) + (0.9 if t == 108 else 0.0) for t in TEAMS}
    ordering = sorted(TEAMS, key=lambda t: -strength[t])
    engine = SelectionEngine(RULES, RANKS, ordering, strength_probability(strength), probability_status="synthetic")
    state = _assign_first_captain()
    recommendation = engine.recommend(state, 1)
    reference = _brute_force_best(RULES, ordering, strength, 1)
    for pick in recommendation.ranked:
        assert math.isclose(pick.p_win_event, reference[pick.team_number][0], abs_tol=1e-12)
    assert recommendation.ranked[0].team_number == max(reference, key=lambda t: reference[t])


def _assign_first_captain():
    return DraftState.empty(4)


def test_engine_does_not_rank_by_raw_scoring_alone():
    """The ordering (raw scoring) puts 102 first, but the model's playoff strength makes 109 the best pick."""
    strength = {t: 0.0 for t in TEAMS}
    strength[109] = 3.0
    ordering = TEAMS[1:] + TEAMS[:1]  # 102 is first by "scoring"
    engine = SelectionEngine(RULES, RANKS, ordering, strength_probability(strength), probability_status="synthetic")
    top = engine.recommend(DraftState.empty(4), 1).ranked[0]
    assert top.team_number == 109 and ordering[0] != 109


def test_alternatives_are_distinct_feasible_and_never_padded():
    strength = {t: 0.05 * (113 - t) for t in TEAMS}
    engine = SelectionEngine(RULES, RANKS, TEAMS, strength_probability(strength), probability_status="synthetic")
    recommendation = engine.recommend(DraftState.empty(4), 1)
    configurations = [tuple(sorted(a.alliances[0])) for a in recommendation.alternatives]
    assert len(configurations) == len(set(configurations)) <= 5
    best_configuration = tuple(sorted(recommendation.ranked[0].configuration))
    assert best_configuration not in configurations
    odds = [a.p_win_event for a in recommendation.alternatives]
    assert odds == sorted(odds, reverse=True)


def test_last_pick_has_few_alternatives_and_says_so():
    strength = {t: 0.05 * (113 - t) for t in TEAMS}
    engine = SelectionEngine(RULES, RANKS, TEAMS, strength_probability(strength), probability_status="synthetic")
    state = run_draft_until_last(engine)
    recommendation = engine.recommend(state, 1)
    assert len(recommendation.ranked) >= 1
    if len(recommendation.alternatives) < 3:
        assert "distinct feasible alternative" in recommendation.alternatives_note


def run_draft_until_last(engine):
    from ml.playoffs.selection import run_draft_until

    return run_draft_until(DraftState.empty(4), RULES, RANKS, best_available(TEAMS), 7)


def test_pick_prediction_accuracy_counts():
    state = DraftState(((101,), (), (), ()), frozenset(), 0)
    accuracy = pick_prediction_accuracy([(state, 1, 102), (state, 1, 105)], TEAMS, RULES, TEAMS)
    assert accuracy["top1"] == 1 and accuracy["top3"] == 1 and accuracy["picks"] == 2


def test_engine_refuses_out_of_turn():
    engine = SelectionEngine(RULES, RANKS, TEAMS, strength_probability({t: 0 for t in TEAMS}),
                             probability_status="synthetic")
    with pytest.raises(RulesetError):
        engine.recommend(DraftState.empty(4), 2)
