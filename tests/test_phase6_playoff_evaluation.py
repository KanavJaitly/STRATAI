"""P6-M1 (a) reproduction, the P6-Q3/Q5 paired gate and the P6-Q1 DM1 rule, on SYNTHETIC data (not evidence)."""

from __future__ import annotations

from data.rulesets import BracketFormat
from ml.playoffs.evaluation import (PlayoffMatch, PredictedAlliance, dm1_result, identifies, paired_log_loss_gate,
                                    reproduce_bracket)
from tests.phase6_bracket_fixtures import single_elimination_4

BRACKET = BracketFormat.model_validate(single_elimination_4())


def test_reproduced_bracket_gives_winner_and_finalist():
    matches = [PlayoffMatch("s1", "semifinal", 1, 1, 1, 4, "red"), PlayoffMatch("s2", "semifinal", 2, 1, 2, 3, "blue"),
               PlayoffMatch("f1", "final", 1, 1, 1, 3, "blue"), PlayoffMatch("f2", "final", 1, 2, 1, 3, "red"),
               PlayoffMatch("f3", "final", 1, 3, 1, 3, "red")]
    result = reproduce_bracket(BRACKET, matches)
    assert result.reproduced and result.winner_seed == 1 and result.finalist_seed == 3


def test_structural_disagreements_are_reported():
    matches = [PlayoffMatch("s1", "semifinal", 1, 1, 1, 3, "red"), PlayoffMatch("s2", "semifinal", 2, 1, 2, 4, "red"),
               PlayoffMatch("x", "semifinal", 9, 1, 1, 2, "red"), PlayoffMatch("f1", "final", 1, 1, 1, 2, "red"),
               PlayoffMatch("f2", "final", 1, 2, 1, 2, "red")]
    problems = reproduce_bracket(BRACKET, matches).problems
    assert any("no slot" in p for p in problems) and any("slot S1" in p for p in problems)


def test_paired_gate_requires_the_whole_ci_below_zero():
    labels = [True, False] * 50
    events = [f"e{i // 10}" for i in range(100)]
    better = [0.8 if y else 0.2 for y in labels]
    worse = [0.6 if y else 0.4 for y in labels]
    assert paired_log_loss_gate(better, worse, labels, events, seed=1)["passed"]
    assert not paired_log_loss_gate(worse, better, labels, events, seed=1)["passed"]
    assert not paired_log_loss_gate(better, better, labels, events, seed=1)["passed"]


def test_identifies_follows_the_frozen_definition():
    predicted = [PredictedAlliance((1, 2, 3), 0.4), PredictedAlliance((4, 5, 6), 0.3), PredictedAlliance((7, 8, 9), 0.2)]
    assert identifies((1, 3, 10), predicted)  # captain 1 and actual pick 3 are on the top contender
    assert not identifies((1, 9, 10), predicted)  # the captain alone, with no actual pick, does not count
    assert not identifies((7, 8, 9), predicted)  # not among the top 2
    assert not identifies((1, 10, 11), predicted)  # captain without any actual pick


def test_dm1_requires_more_than_half_pooled():
    assert dm1_result({"a": [True, True], "b": [True, False]}, seed=2)["met"]
    assert not dm1_result({"a": [True, False], "b": [False, True]}, seed=2)["met"]
