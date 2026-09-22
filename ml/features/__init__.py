"""Leakage-safe feature assembly: turning stored data into ML-ready rows.

Phase 4 Milestone 1 (authoritative plan, docs/P4Milestones.md). See
ml.features.assembler for the implementation and its extensive design-decision
docstrings.
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
