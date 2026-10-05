"""PX-3 (P6-M4) implementation correctness, on SYNTHETIC brackets and probability functions (not evidence)."""

from __future__ import annotations

import math
import random

import pytest

from data.rulesets import BracketFormat, SeasonRuleset
from ml.playoffs.simulator import monte_carlo, series_probability, simulate, simulate_recursive
from tests.phase6_bracket_fixtures import double_elimination_8, ruleset, single_elimination_4


def strength_model(strengths: dict[int, float]):
    def p(red: int, blue: int, round_: int) -> float:
        return 1.0 / (1.0 + math.exp(-(strengths[red] - strengths[blue])))
    return p


def test_fixture_ruleset_validates():
    rules = SeasonRuleset.model_validate(ruleset())
    assert rules.alliances_for(30) == 8 and rules.alliances_for(10) == 4
    assert rules.bracket(8).slot_by_tba()[("semifinal", 13)].slot == "M13"


@pytest.mark.parametrize("bracket", [double_elimination_8(), single_elimination_4()])
def test_probabilities_are_distributions(bracket):
    fmt = BracketFormat.model_validate(bracket)
    strengths = {s: random.Random(s).uniform(-1, 1) for s in range(1, fmt.alliances + 1)}
    result = simulate(fmt, strength_model(strengths))
    assert math.isclose(result.total(), 1.0, abs_tol=1e-12)
    assert math.isclose(sum(result.reach_finals.values()), 2.0, abs_tol=1e-12)
    for seed in result.win_event:
        eliminated = sum(result.eliminated_in[seed].values())
        assert math.isclose(eliminated + result.win_event[seed], 1.0, abs_tol=1e-12)
        assert result.win_event[seed] <= result.reach_finals[seed] + 1e-15


def test_equal_strength_closed_form():
    fmt = BracketFormat.model_validate(single_elimination_4())
    result = simulate(fmt, lambda r, b, k: 0.5)
    assert all(math.isclose(v, 0.25) for v in result.win_event.values())
    assert all(math.isclose(v, 0.5) for v in result.reach_finals.values())


def test_series_probability():
    assert math.isclose(series_probability(0.5, 2), 0.5)
    assert math.isclose(series_probability(0.6, 2), 0.6 ** 2 + 2 * 0.6 ** 2 * 0.4)
    assert series_probability(1.0, 3) == 1.0


def test_exact_equals_independent_monte_carlo():
    fmt = BracketFormat.model_validate(double_elimination_8())
    strengths = {s: 1.5 - 0.35 * s for s in range(1, 9)}
    p = strength_model(strengths)
    exact = simulate(fmt, p)
    sampled = monte_carlo(fmt, p, trials=60_000, seed=20261009)
    for seed in range(1, 9):
        se = math.sqrt(exact.win_event[seed] * (1 - exact.win_event[seed]) / 60_000)
        assert abs(exact.win_event[seed] - sampled.win_event[seed]) < 5 * se + 1e-9
        se_f = math.sqrt(exact.reach_finals[seed] * (1 - exact.reach_finals[seed]) / 60_000)
        assert abs(exact.reach_finals[seed] - sampled.reach_finals[seed]) < 5 * se_f + 1e-9


def test_relabelling_invariance():
    """Swapping two alliances' strengths swaps their probabilities only when they occupy symmetric slots."""
    fmt = BracketFormat.model_validate(single_elimination_4())
    base = {1: 0.9, 2: 0.4, 3: 0.1, 4: -0.2}
    swapped = {1: 0.4, 2: 0.9, 3: -0.2, 4: 0.1}  # mirror the two semifinals
    a, b = simulate(fmt, strength_model(base)), simulate(fmt, strength_model(swapped))
    for x, y in ((1, 2), (2, 1), (3, 4), (4, 3)):
        assert math.isclose(a.win_event[x], b.win_event[y], abs_tol=1e-12)


def test_round_reaches_the_probability_function():
    fmt = BracketFormat.model_validate(double_elimination_8())
    seen = set()
    simulate(fmt, lambda r, b, k: (seen.add(k), 0.5)[1])
    assert seen == {1, 2, 3, 4, 5, 6}


def test_invalid_graphs_are_refused():
    broken = double_elimination_8()
    broken["slots"][4]["red"] = {"kind": "loser", "slot": "M9"}  # depends on a later slot
    with pytest.raises(ValueError):
        BracketFormat.model_validate(broken)
    duplicated = double_elimination_8()
    duplicated["slots"][5]["red"] = {"kind": "loser", "slot": "M1"}  # M1's loser routed twice
    with pytest.raises(ValueError):
        BracketFormat.model_validate(duplicated)
    with pytest.raises(ValueError):
        simulate(BracketFormat.model_validate(single_elimination_4()), lambda r, b, k: 1.2)


@pytest.mark.parametrize("bracket", [double_elimination_8(), single_elimination_4()])
def test_vectorized_and_recursive_exact_implementations_agree(bracket):
    fmt = BracketFormat.model_validate(bracket)
    rng = random.Random(4)
    strengths = {s: rng.uniform(-2, 2) for s in range(1, fmt.alliances + 1)}

    def p(red, blue, round_):  # depends on the round too
        return 1.0 / (1.0 + math.exp(-(strengths[red] - strengths[blue]) * (1 + 0.1 * round_)))

    fast, slow = simulate(fmt, p), simulate_recursive(fmt, p)
    for seed in range(1, fmt.alliances + 1):
        assert math.isclose(fast.win_event[seed], slow.win_event[seed], abs_tol=1e-12)
        assert math.isclose(fast.reach_finals[seed], slow.reach_finals[seed], abs_tol=1e-12)
        assert fast.eliminated_in[seed].keys() == slow.eliminated_in[seed].keys()
        for slot, value in slow.eliminated_in[seed].items():
            assert math.isclose(fast.eliminated_in[seed][slot], value, abs_tol=1e-12)
