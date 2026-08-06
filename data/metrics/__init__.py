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
a DefenseFeedingProfile (data.metrics.aggregation). Phase 3 Milestone 9
provides ScoutRadioz CSV import (data.metrics.scoutradioz) -- ScoutRadioz has
no public API, so this maps a CSV export into the same canonical scouting-
observation pipeline human_scout submissions use. Phase 3 Milestone 10
provides the metrics computation pipeline itself (data.metrics.compute) --
compute_team_metrics composes Milestones 3+4+8 into the TeamMetrics object
Phase 3's Definition of Done names, and compute_event_team_metrics computes
and persists it for every team at an event, as a follow-on stage after
data.orchestrator.sync_event. Phase 3 Milestone 11 provides quality checks over
a computed TeamMetrics (data.metrics.quality) -- the confidence and
internal-consistency counterpart to data.staging.quality's checks on ingested
payloads, building that module's own QualityIssue and recorded through its own
DataQualityRecorder. It is exported here, unlike the three modules below,
because it depends only on data.metrics.schemas and data.staging.quality and
so reaches back out to nothing.

data.metrics.submission, data.metrics.scoutradioz, and data.metrics.compute
are deliberately NOT imported here, unlike every other Milestone's module: all
three reach back out to data.pipeline/data.orchestrator (to reuse
read_pending/stage_batch, PipelineRunRecorder, and/or WatermarkStore), and
those modules import data.metrics.normalizer -- which requires importing this
very package first. Re-exporting any of the three's names here would make
importing data.pipeline (or data.metrics.normalizer, or this package) on its
own, before data.orchestrator has been loaded some other way first, fail with
an ImportError on a partially-initialized data.pipeline module (confirmed for
submission during Milestone 7, re-confirmed for scoutradioz during Milestone
9, and re-confirmed again for compute during Milestone 10, each time by
triggering the identical failure, not just reasoning by analogy). data.pipeline
itself already imports data.metrics.normalizer directly rather than through
this package for the same underlying reason. Import from data.metrics.
submission, data.metrics.scoutradioz, or data.metrics.compute directly.
"""

from data.metrics.aggregation import MIN_OBSERVATIONS_FOR_SCORE, aggregate_defense_feeding
from data.metrics.history import TeamMatchHistory, get_team_match_history
from data.metrics.normalizer import (
    normalize_human_scout_observation,
    normalize_scouting_observation,
    scouting_observation_natural_key,
)
from data.metrics.quality import (
    OBJECT_TYPE_TEAM_METRICS,
    QUALITY_SOURCE,
    check_team_metrics,
    team_metrics_object_id,
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
    "OBJECT_TYPE_TEAM_METRICS",
    "QUALITY_SOURCE",
    "DefenseFeedingProfile",
    "ScoringProfile",
    "ScoutingObservation",
    "TeamMatchHistory",
    "TeamMetrics",
    "aggregate_defense_feeding",
    "average_score",
    "check_team_metrics",
    "classify_match_days",
    "consistency_rating",
    "get_team_match_history",
    "normalize_human_scout_observation",
    "normalize_scouting_observation",
    "reliability_score",
    "score_stddev",
    "scouting_observation_natural_key",
    "team_metrics_object_id",
    "validate_human_scout_observation_payload",
    "validate_scouting_observation",
]
