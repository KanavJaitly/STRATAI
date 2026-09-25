"""Temporal backtesting harness and model interface: the single gate every
Phase 4 model validates through.

Phase 4 Milestone 3 (authoritative plan, docs/P4Milestones.md). See
ml.backtest.harness for the Model protocol, split functions, and backtest
runners, and ml.backtest.metrics for the underlying pure statistical
functions.
"""

from ml.backtest.harness import (
    MODE_RANKING,
    MODE_WIN_PROB,
    SPLIT_HOLD_OUT_SEASON,
    SPLIT_WALK_FORWARD,
    BacktestResult,
    Fold,
    FoldMetrics,
    Model,
    hold_out_season_split,
    run_ranking_backtest,
    run_win_prob_backtest,
    walk_forward_splits,
)
from ml.backtest.metrics import (
    accuracy,
    brier_score,
    expected_calibration_error,
    log_loss,
    roc_auc,
    spearman_correlation,
    top_k_recall,
)

__all__ = [
    "MODE_RANKING",
    "MODE_WIN_PROB",
    "SPLIT_HOLD_OUT_SEASON",
    "SPLIT_WALK_FORWARD",
    "BacktestResult",
    "Fold",
    "FoldMetrics",
    "Model",
    "hold_out_season_split",
    "run_ranking_backtest",
    "run_win_prob_backtest",
    "walk_forward_splits",
    "accuracy",
    "brier_score",
    "expected_calibration_error",
    "log_loss",
    "roc_auc",
    "spearman_correlation",
    "top_k_recall",
]
