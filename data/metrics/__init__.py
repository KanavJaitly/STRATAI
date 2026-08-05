"""Metrics layer: statistical scoring metrics and scouting-observed qualities.

Phase 3 Milestone 1 provides models (data.metrics.schemas). Phase 3 Milestone 3
provides pure statistical functions over match score history
(data.metrics.statistics). Phase 3 Milestone 4 provides the read path that
supplies those functions with real data (data.metrics.history). Phase 3
Milestone 5 provides structural validation of raw scouting submissions
(data.metrics.validator), reusing data.staging.validator's ValidationIssue/
PayloadValidationError directly rather than re-exporting them a third way here.
Phase 3 Milestone 6 provides validate-then-build normalization of a validated
raw submission into a canonical ScoutingObservation (data.metrics.normalizer).
Phase 3 Milestone 7 provides the end-to-end submission path itself
(data.metrics.submission) -- gate, validate, land, stage, load. Phase 3
Milestone 8 provides pure aggregation of a team's scouting observations into
a DefenseFeedingProfile (data.metrics.aggregation). The metrics computation
pipeline (Milestone 10) is a later milestone and is not exported here yet.

data.metrics.submission is deliberately NOT imported here, unlike every other
Milestone's module: it reaches back out to data.pipeline/data.orchestrator (to
reuse read_pending/stage_batch and PipelineRunRecorder/WatermarkStore), and
those modules import data.metrics.normalizer -- which requires importing this
very package first. Re-exporting submission's names here would make importing
data.pipeline (or data.metrics.normalizer, or this package) on its own, before
data.orchestrator has been loaded some other way first, fail with an
ImportError on a partially-initialized data.pipeline module (confirmed by
triggering it, not just reasoned about). data.pipeline itself already imports
data.metrics.normalizer directly rather than through this package for the same
underlying reason. Import from data.metrics.submission directly.
"""

from data.metrics.aggregation import MIN_OBSERVATIONS_FOR_SCORE, aggregate_defense_feeding
from data.metrics.history import TeamMatchHistory, get_team_match_history
from data.metrics.normalizer import (
    normalize_human_scout_observation,
    normalize_scouting_observation,
    scouting_observation_natural_key,
)
from data.metrics.schemas import (
    BAD_DAY_ZSCORE_THRESHOLD,
    DEFENSE_RATING_DESCRIPTIONS,
    FEEDING_RATING_DESCRIPTIONS,
    GOOD_DAY_ZSCORE_THRESHOLD,
    MAX_RATING,
    MIN_MATCHES_FOR_STDDEV,
    MIN_RATING,
    DefenseFeedingProfile,
    ScoringProfile,
    ScoutingObservation,
    TeamMetrics,
)
from data.metrics.statistics import (
    average_score,
    classify_match_days,
    consistency_rating,
    reliability_score,
    score_stddev,
)
from data.metrics.validator import (
    validate_human_scout_observation_payload,
    validate_scouting_observation,
)

__all__ = [
    "BAD_DAY_ZSCORE_THRESHOLD",
    "DEFENSE_RATING_DESCRIPTIONS",
    "FEEDING_RATING_DESCRIPTIONS",
    "GOOD_DAY_ZSCORE_THRESHOLD",
    "MAX_RATING",
    "MIN_MATCHES_FOR_STDDEV",
    "MIN_OBSERVATIONS_FOR_SCORE",
    "MIN_RATING",
    "DefenseFeedingProfile",
    "ScoringProfile",
    "ScoutingObservation",
    "TeamMatchHistory",
    "TeamMetrics",
    "aggregate_defense_feeding",
    "average_score",
    "classify_match_days",
    "consistency_rating",
    "get_team_match_history",
    "normalize_human_scout_observation",
    "normalize_scouting_observation",
    "reliability_score",
    "score_stddev",
    "scouting_observation_natural_key",
    "validate_human_scout_observation_payload",
    "validate_scouting_observation",
]
