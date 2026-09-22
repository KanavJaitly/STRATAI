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

from ml.features.assembler import (
    EPA_WITHHELD_NO_PRIOR_EVENT,
    MatchFeatureRow,
    TeamFeatures,
    build_match_feature_row,
)

__all__ = [
    "EPA_WITHHELD_NO_PRIOR_EVENT",
    "MatchFeatureRow",
    "TeamFeatures",
    "build_match_feature_row",
]
