"""Phase 4 Milestone 11's generalization test.

The comparison logic is unit-tested here on SYNTHETIC FoldMetrics (labeled as
such; they are not evidence of anything). The real test -- the one M11's
acceptance requires -- runs scripts/run_m11_generalization against the real
database and is enabled only with PHASE4_REAL_DATA_TESTS=1, which the Phase 4
execution attempt sets once the readiness gate is COMPLETE. A skip is never
acceptance evidence.
"""

from __future__ import annotations

import math
import os

import pytest

from ml.backtest.harness import FoldMetrics
from scripts import run_m11_generalization as gen


def metrics(**values) -> FoldMetrics:
    return FoldMetrics(fold_label="synthetic", season=2026, row_count=100, excluded_count=0, **values)


def checks(model_ll=0.60, base_ll=0.65, model_brier=0.21, base_brier=0.23, model_rho=0.55, base_rho=0.50, present=10):
    return gen.generalization_checks(
        model_win_prob=metrics(log_loss=model_ll, brier_score=model_brier),
        baseline_win_prob=metrics(log_loss=base_ll, brier_score=base_brier),
        model_ranking=metrics(spearman=model_rho), baseline_ranking=metrics(spearman=base_rho),
        held_out_auto_points_present=present,
    )


def test_synthetic_all_above_baseline_and_chance_passes():
    assert all(check.passed for check in checks())


@pytest.mark.parametrize("overrides", [
    {"model_ll": 0.66},                   # worse than baseline
    {"model_ll": 0.65},                   # equal is not "above"
    {"model_ll": 0.70, "base_ll": 0.75},  # beats baseline but not chance (ln 2 ~ 0.693)
    {"model_brier": 0.24},
    {"model_brier": 0.26, "base_brier": 0.30},
    {"model_rho": 0.50},
    {"model_rho": -0.1, "base_rho": -0.2},
    {"present": 0},                       # the M11 feature never resolved in the unseen season
])
def test_synthetic_any_shortfall_fails(overrides):
    assert not all(check.passed for check in checks(**overrides))


def test_undefined_metrics_never_pass():
    result = gen.generalization_checks(
        model_win_prob=metrics(), baseline_win_prob=metrics(log_loss=0.6, brier_score=0.2),
        model_ranking=metrics(spearman=0.5), baseline_ranking=metrics(),
        held_out_auto_points_present=5)
    assert [c.passed for c in result] == [False, False, False, True]


def test_chance_levels_and_split_are_the_documented_ones():
    assert gen.CHANCE_LOG_LOSS == pytest.approx(math.log(2))
    assert gen.CHANCE_BRIER == 0.25 and gen.CHANCE_SPEARMAN == 0.0
    assert gen.TRAIN_SEASONS == (2024, 2025) and gen.HELD_OUT_SEASON == 2026


@pytest.mark.skipif(os.environ.get("PHASE4_REAL_DATA_TESTS") != "1",
                    reason="real-data acceptance evidence: run by the Phase 4 attempt with PHASE4_REAL_DATA_TESTS=1")
def test_real_held_out_generalization():
    assert gen.main() == 0
