"""Staging layer for normalized domain payloads."""

from data.staging.normalizer import (
    normalize_event,
    normalize_match,
    normalize_team,
    normalize_team_event_stats,
    parse_tba_team_number,
)
from data.staging.quality import (
    DataQualityRecorder,
    QualityContext,
    QualityIssue,
    build_quality_context,
    check_entity,
)
from data.staging.schemas import (
    StagingEvent,
    StagingMatch,
    StagingTeam,
    StagingTeamEventStats,
)
from data.staging.validator import (
    PayloadValidationError,
    ValidationIssue,
    tba_alliance_team_keys,
    validate_event,
    validate_match,
    validate_team,
)

__all__ = [
    "StagingEvent",
    "StagingMatch",
    "StagingTeam",
    "StagingTeamEventStats",
    "ValidationIssue",
    "PayloadValidationError",
    "validate_event",
    "validate_match",
    "validate_team",
    "tba_alliance_team_keys",
    "normalize_event",
    "normalize_match",
    "normalize_team",
    "normalize_team_event_stats",
    "parse_tba_team_number",
    "QualityIssue",
    "QualityContext",
    "DataQualityRecorder",
    "check_entity",
    "build_quality_context",
]
