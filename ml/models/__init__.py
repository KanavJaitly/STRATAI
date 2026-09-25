"""Concrete StratAI models: locked naive baselines (Milestone 4), the rating/
ranking model (Milestone 5), and the win-probability model (Milestone 6).
Every model here implements ml.backtest.harness.Model.
"""

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

__all__ = [
    "BASELINE_VERSION",
    "EpaWinProbBaseline",
    "RANKING_MODEL_VERSION",
    "RankingXGBModel",
    "RawEpaRankingBaseline",
    "WIN_PROB_MODEL_VERSION",
    "WinProbXGBModel",
]
