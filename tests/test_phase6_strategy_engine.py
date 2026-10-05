"""P6-M11 optimization correctness on synthetic fixtures (not evidence for any real-data claim)."""

from __future__ import annotations

import itertools
from datetime import datetime, timezone

from ml.strategy.engine import SELECTION_NOTE, StrategyEngine, candidate_strategies, robot_options
from ml.strategy.outcome import ComponentOutcomeModel, MatchContext
from ml.strategy.representation import CoachObservation, RobotPlan, Strategy
from tests.phase6_fixtures import FIXTURE_BETA, FIXTURE_SIGMA, team

RED, BLUE = [1, 2, 3], [4, 5, 6]


def engine() -> StrategyEngine:
    return StrategyEngine(ComponentOutcomeModel(FIXTURE_BETA, FIXTURE_SIGMA, fit_info={}, spec_sha256="0" * 64))


def ctx(**kwargs) -> MatchContext:
    return MatchContext(tuple(team(n, 6.0, 25.0, 4.0) for n in RED), tuple(team(n, 5.0, 24.0, 6.0) for n in BLUE),
                        **kwargs)


def test_strategy_space_is_complete():
    options = robot_options(1, RED, BLUE)
    assert len(options) == 8 + 3 * 4 + 2 * 4  # scoring subsets; defend each opponent; feed each ally
    assert len(candidate_strategies(RED, BLUE)) == len(options) ** 3


def test_independent_brute_force_equals_the_optimizer():
    e = engine()
    context = ctx()
    best_p, best = -1.0, None
    for combo in itertools.product(*(robot_options(t, RED, BLUE) for t in RED)):
        strategy = Strategy(robots=combo)
        p = e.model.evaluate(context, strategy, Strategy.baseline(BLUE)).p_red
        if p > best_p:
            best_p, best = p, strategy
    recommendation = e.recommend(context, "red")
    assert recommendation.recommended.p_ours == best_p
    assert recommendation.candidates_evaluated == 28 ** 3
    # with no measured defense/feeding effect, withholding capability can only lower the odds: baseline is optimal
    assert recommendation.recommended.strategy.is_baseline() and best.is_baseline()


def test_recommendation_is_deterministic_and_bit_identical_to_a_fresh_evaluation():
    e = engine()
    context = ctx()
    first, second = e.recommend(context, "blue"), e.recommend(context, "blue")
    assert first.recommended.strategy == second.recommended.strategy
    assert [a.strategy for a in first.alternatives] == [a.strategy for a in second.alternatives]
    fresh = e.model.evaluate(context, Strategy.baseline(RED), first.recommended.strategy)
    assert first.recommended.p_ours == fresh.p_blue
    coach = e.assess(context, "blue", first.recommended.strategy)
    assert coach.evaluation == first.recommended.evaluation and coach.display_ours == first.recommended.display_ours


def test_alternatives_are_distinct_ordered_and_honestly_labelled():
    recommendation = engine().recommend(ctx(), "red")
    strategies = [recommendation.recommended.strategy, *(a.strategy for a in recommendation.alternatives)]
    assert len({s.sha256() for s in strategies}) == len(strategies) == 6
    odds = [recommendation.recommended.p_ours, *(a.p_ours for a in recommendation.alternatives)]
    assert odds == sorted(odds, reverse=True)
    assert recommendation.selection_note == SELECTION_NOTE.format(n=recommendation.candidates_evaluated)
    assert all(a.evaluation.validation_status == "not_validated" for a in recommendation.alternatives)


def test_observations_reach_every_candidate_through_the_context():
    observation = CoachObservation(event_key="e", team_number=1, kind="robot_unavailable",
                                   observed_at=datetime(2026, 3, 1, tzinfo=timezone.utc), observer="Coach")
    e = engine()
    plain = e.recommend(ctx(), "red").recommended.p_ours
    observed = e.recommend(ctx(observations=(observation,)), "red")
    assert observed.recommended.p_ours < plain
    assert "coach_observation_effect_unmeasured" in observed.recommended.evaluation.reasons


def test_coach_entered_opponent_strategy_is_used_for_every_candidate():
    opponent = Strategy(robots=(RobotPlan(team_number=4, role="defense", components=("auto",), defense_target=1),
                                RobotPlan(team_number=5), RobotPlan(team_number=6)))
    e = engine()
    against_defense = e.recommend(ctx(), "red", opponent_strategy=opponent)
    against_baseline = e.recommend(ctx(), "red")
    assert against_defense.recommended.p_ours > against_baseline.recommended.p_ours  # the defender stops scoring
    assert against_defense.recommended.opponent_strategy == opponent


def test_insufficient_data_gives_no_recommendation():
    red = (team(1, None, None, None, epa_scale=None), team(2), team(3))
    recommendation = engine().recommend(MatchContext(red, tuple(team(n) for n in BLUE)), "red")
    assert recommendation.recommended is None and "missing_input" in recommendation.unavailable_reason


def test_compare_uses_one_rule_for_both():
    defend = Strategy(robots=(RobotPlan(team_number=1, role="defense", components=("auto", "endgame"),
                                        defense_target=4), RobotPlan(team_number=2), RobotPlan(team_number=3)))
    result = engine().compare(ctx(), "red", Strategy.baseline(RED), defend)
    assert {"first", "second", "difference", "label"} <= set(result)
    assert "better" not in result["first"] and result["label"] in (
        "indistinguishable at model resolution",
        "differs by at least one display step under the model (not a claim that either strategy is better)")
