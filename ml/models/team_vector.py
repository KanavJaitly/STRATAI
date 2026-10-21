"""Shared team-level feature vector construction, used by both Milestone 5's
ranking model and Milestone 6's win-probability model.

Split out of ml/models/ranking_xgb.py (M5's original home for this logic)
specifically so M6 does not duplicate it -- CLAUDE.md's "avoid duplicated
logic" applied to the one piece of vector-construction both models
genuinely share: turning one TeamFeatures snapshot into a fixed-order numeric
row, float("nan") for every absent optional value rather than an imputed
0.0. See ml.models.ranking_xgb's own module docstring for the fuller
rationale (XGBoost's native missing-value handling is what actually honors
CLAUDE.md's "insufficient_data propagates" rule here, not a manual fill).
"""

from __future__ import annotations

import numpy as np

from ml.features.assembler import TeamFeatures

__all__ = [
    "TEAM_FEATURE_NAMES",
    "team_features_to_vector",
]

# Exact order matters -- also the order handed to xgboost.DMatrix's own
# feature_names in both consuming models, each of which refuses to load a
# model saved with a different list (an early version of Milestone 10's own
# named registry guarantee). matches_considered/matches_used/
# *_observation_count carry no presence flag on TeamFeatures (always known,
# never absent) so they are fed directly, unlike the value fields above them.
TEAM_FEATURE_NAMES: tuple[str, ...] = (
    "epa_total", "epa_auto", "epa_teleop", "epa_endgame",
    "average_score", "score_stddev", "consistency_rating", "reliability_score",
    "average_auto_points",  # Milestone 11 (ml/features/score_breakdown.py)
    "matches_considered", "matches_used",
    "defense_score", "defense_agreement", "defense_observation_count",
    "feeding_score", "feeding_agreement", "feeding_observation_count",
)


def team_features_to_vector(team_features: TeamFeatures) -> np.ndarray:
    """One team's feature row in TEAM_FEATURE_NAMES order -- float("nan") for
    every field whose presence flag is False, the real value otherwise.
    """
    values = [
        team_features.epa_total if team_features.epa_total_present else float("nan"),
        team_features.epa_auto if team_features.epa_auto_present else float("nan"),
        team_features.epa_teleop if team_features.epa_teleop_present else float("nan"),
        team_features.epa_endgame if team_features.epa_endgame_present else float("nan"),
        team_features.average_score if team_features.average_score_present else float("nan"),
        team_features.score_stddev if team_features.score_stddev_present else float("nan"),
        team_features.consistency_rating if team_features.consistency_rating_present else float("nan"),
        team_features.reliability_score if team_features.reliability_score_present else float("nan"),
        team_features.average_auto_points if team_features.average_auto_points_present else float("nan"),
        float(team_features.matches_considered),
        float(team_features.matches_used),
        team_features.defense_score if team_features.defense_score_present else float("nan"),
        team_features.defense_agreement if team_features.defense_agreement_present else float("nan"),
        float(team_features.defense_observation_count),
        team_features.feeding_score if team_features.feeding_score_present else float("nan"),
        team_features.feeding_agreement if team_features.feeding_agreement_present else float("nan"),
        float(team_features.feeding_observation_count),
    ]
    return np.array(values, dtype=np.float64)
