"""Phase 4 Milestone 8: the bias/leakage audit script, scripts/ml_bias_audit.py.

The milestone's own brief names the audit itself as the deliverable, and
requires proof it "has teeth" -- a deliberately-broken model must actually
get caught, not merely a suite that always reports PASS. This file does
both: confirms the real M5/M6 models pass every check, and confirms a
deliberately-broken fixture model fails the specific checks it violates.
"""

from __future__ import annotations

from pathlib import Path

from ml.backtest.harness import Model
from ml.dataset.builder import TrainingRow
from ml.features.assembler import MatchFeatureRow, TeamFeatures
from ml.models.ranking_xgb import RankingXGBModel
from ml.models.win_prob import WinProbXGBModel
from scripts.ml_bias_audit import (
    check_as_of_feature_integrity,
    check_label_shuffle_leakage_ranking,
    check_label_shuffle_leakage_win_prob,
    check_no_strategy_leakage,
    check_order_invariance_rating,
    check_order_invariance_win_prob,
    check_win_prob_symmetry,
    run_full_audit,
)


class _ConstantAsymmetricWinProbModel:
    """Deliberately broken: always predicts a fixed 0.9 regardless of the
    alliances passed in, violating symmetry outright (p(R,B) + p(B,R) = 1.8,
    not 1) and carrying zero real signal (violating the label-shuffle
    leakage check's floor, since it can never favor a genuinely stronger
    alliance). Exists only to prove the audit's checks actually fail when
    they should.
    """

    def fit(self, training_rows) -> None:
        return

    def predict_win_prob(self, match_features: MatchFeatureRow) -> float:
        return 0.9

    def predict_rating(self, team_features: TeamFeatures) -> float:
        raise NotImplementedError

    def save(self, path: Path) -> None:
        raise NotImplementedError

    @classmethod
    def load(cls, path: Path):
        raise NotImplementedError


class _ConstantRatingModel:
    """Deliberately broken: always predicts the same rating regardless of
    team identity, carrying zero signal -- fails the ranking label-shuffle
    leakage check's correlation floor (a constant has no correlation with
    anything, real or shuffled)."""

    def fit(self, training_rows) -> None:
        return

    def predict_win_prob(self, match_features: MatchFeatureRow) -> float:
        raise NotImplementedError

    def predict_rating(self, team_features: TeamFeatures) -> float:
        return 42.0

    def save(self, path: Path) -> None:
        raise NotImplementedError

    @classmethod
    def load(cls, path: Path):
        raise NotImplementedError


def test_real_ranking_model_conforms_to_protocol():
    assert isinstance(RankingXGBModel(), Model)


def test_real_win_prob_model_conforms_to_protocol():
    assert isinstance(WinProbXGBModel(), Model)


# ---------------------------------------------------------------------------
# Real models: every check must pass
# ---------------------------------------------------------------------------


def test_symmetry_check_passes_for_the_real_win_prob_model():
    assert check_win_prob_symmetry(WinProbXGBModel).passed


def test_order_invariance_passes_for_the_real_win_prob_model():
    assert check_order_invariance_win_prob(WinProbXGBModel).passed


def test_order_invariance_passes_for_the_real_ranking_model():
    assert check_order_invariance_rating(RankingXGBModel).passed


def test_no_strategy_leakage_check_passes():
    assert check_no_strategy_leakage().passed


def test_as_of_feature_integrity_check_passes():
    assert check_as_of_feature_integrity().passed


def test_label_shuffle_leakage_check_passes_for_the_real_ranking_model():
    assert check_label_shuffle_leakage_ranking(RankingXGBModel).passed


def test_label_shuffle_leakage_check_passes_for_the_real_win_prob_model():
    assert check_label_shuffle_leakage_win_prob(WinProbXGBModel).passed


def test_run_full_audit_passes_for_the_real_models():
    report = run_full_audit()
    assert report.passed
    assert len(report.checks) == 7


# ---------------------------------------------------------------------------
# Deliberately-broken fixtures: the audit must catch them (proves it has teeth)
# ---------------------------------------------------------------------------


def test_symmetry_check_fails_for_a_constant_asymmetric_model():
    check = check_win_prob_symmetry(_ConstantAsymmetricWinProbModel)
    assert not check.passed


def test_label_shuffle_leakage_check_fails_for_a_constant_win_prob_model():
    check = check_label_shuffle_leakage_win_prob(_ConstantAsymmetricWinProbModel)
    assert not check.passed


def test_label_shuffle_leakage_check_fails_for_a_constant_rating_model():
    check = check_label_shuffle_leakage_ranking(_ConstantRatingModel)
    assert not check.passed


def test_run_full_audit_fails_when_given_a_broken_win_prob_model():
    report = run_full_audit(win_prob_model_factory=_ConstantAsymmetricWinProbModel)
    assert not report.passed
    failed_names = {check.name for check in report.checks if not check.passed}
    assert "symmetry" in failed_names


def test_run_full_audit_fails_when_given_a_broken_ranking_model():
    report = run_full_audit(ranking_model_factory=_ConstantRatingModel)
    assert not report.passed
    failed_names = {check.name for check in report.checks if not check.passed}
    assert "label_shuffle_leakage_ranking" in failed_names


def test_audit_report_summary_mentions_every_check():
    report = run_full_audit()
    summary = report.summary()
    for check in report.checks:
        assert check.name in summary
