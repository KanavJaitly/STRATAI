"""ML layer: machine learning models, metrics, predictions, and optimization.

Phase 4 (authoritative 13-milestone plan, docs/P4Milestones.md). Milestone 1
provides the leakage-safe feature assembly layer (ml.features.assembler) every
later milestone builds on -- the labeled dataset builder (Milestone 2), the
backtesting harness (Milestone 3), the locked naive baselines (Milestone 4),
the rating and win probability models (Milestones 5-7), the bias/leakage audit
(Milestone 8), alliance synergy scoring (Milestone 9), the model registry
(Milestone 10), the cross-season generalization guard (Milestone 11), the API
layer (Milestone 12), and documentation + sign-off (Milestone 13).
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
from ml.dataset.builder import (
    DATASET_BUILDER_VERSION,
    EXCLUSION_REASON_DQ_AFFECTED,
    EXCLUSION_REASON_DQ_STATUS_UNKNOWN,
    EXCLUSION_REASON_NO_SCHEDULED_TIME,
    EXCLUSION_REASON_UNPLAYED,
    EXCLUSION_REASON_WINNING_ALLIANCE_MISSING,
    LABEL_BLUE_WIN,
    LABEL_RED_WIN,
    LABEL_TIE,
    DatasetManifest,
    ExcludedMatch,
    PersistedDataset,
    TrainingFrameResult,
    TrainingRow,
    build_training_frame,
    persist_training_frame,
)
from ml.features.assembler import (
    EPA_WITHHELD_NO_PRIOR_EVENT,
    MatchFeatureRow,
    TeamFeatures,
    build_match_feature_row,
    build_team_features,
)
from ml.features.roster import (
    event_exists,
    get_event_season,
    list_teams_at_event,
)
from ml.models.baselines import (
    BASELINE_VERSION,
    EpaWinProbBaseline,
    RawEpaRankingBaseline,
)
from ml.models.ranking_xgb import (
    RANKING_MODEL_VERSION,
    RankingXGBModel,
)
from ml.models.win_prob import (
    WIN_PROB_MODEL_VERSION,
    WinProbXGBModel,
)
from ml.calibration.calibrator import (
    CALIBRATOR_VERSION,
    BandCheckResult,
    Calibrator,
    IsotonicCalibrator,
    PlattCalibrator,
    ReliabilityBin,
    apply_calibrated_model,
    check_calibration_band,
    compute_reliability_bins,
    fit_calibrated_win_prob_model,
)
from ml.synergy.score import (
    DEFAULT_SYNERGY_WEIGHTS,
    AllianceSynergyScore,
    SynergyWeights,
    alliance_synergy,
)
from ml.registry import (
    MANIFEST_FILENAME,
    MODEL_FILENAME,
    REGISTRY_MANIFEST_VERSION,
    ModelManifest,
    list_registered_versions,
    load_registered_model,
    register_model,
)

__all__ = [
    "EPA_WITHHELD_NO_PRIOR_EVENT",
    "MatchFeatureRow",
    "TeamFeatures",
    "build_match_feature_row",
    "build_team_features",
    "event_exists",
    "get_event_season",
    "list_teams_at_event",
    "DATASET_BUILDER_VERSION",
    "EXCLUSION_REASON_DQ_AFFECTED",
    "EXCLUSION_REASON_DQ_STATUS_UNKNOWN",
    "EXCLUSION_REASON_NO_SCHEDULED_TIME",
    "EXCLUSION_REASON_UNPLAYED",
    "EXCLUSION_REASON_WINNING_ALLIANCE_MISSING",
    "LABEL_BLUE_WIN",
    "LABEL_RED_WIN",
    "LABEL_TIE",
    "DatasetManifest",
    "ExcludedMatch",
    "PersistedDataset",
    "TrainingFrameResult",
    "TrainingRow",
    "build_training_frame",
    "persist_training_frame",
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
    "BASELINE_VERSION",
    "EpaWinProbBaseline",
    "RawEpaRankingBaseline",
    "RANKING_MODEL_VERSION",
    "RankingXGBModel",
    "WIN_PROB_MODEL_VERSION",
    "WinProbXGBModel",
    "CALIBRATOR_VERSION",
    "BandCheckResult",
    "Calibrator",
    "IsotonicCalibrator",
    "PlattCalibrator",
    "ReliabilityBin",
    "apply_calibrated_model",
    "check_calibration_band",
    "compute_reliability_bins",
    "fit_calibrated_win_prob_model",
    "DEFAULT_SYNERGY_WEIGHTS",
    "AllianceSynergyScore",
    "SynergyWeights",
    "alliance_synergy",
    "MANIFEST_FILENAME",
    "MODEL_FILENAME",
    "REGISTRY_MANIFEST_VERSION",
    "ModelManifest",
    "list_registered_versions",
    "load_registered_model",
    "register_model",
]
