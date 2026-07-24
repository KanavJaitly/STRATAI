"""Staging layer for normalized domain payloads."""

from data.staging.normalizer import (
    normalize_event,
    normalize_match,
    normalize_team,
    normalize_team_event_stats,
)
from data.staging.schemas import (
    StagingEvent,
    StagingMatch,
    StagingTeam,
    StagingTeamEventStats,
)
from data.staging.validator import PayloadValidationError, ValidationIssue, validate_event, validate_match, validate_team

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
    "normalize_event",
    "normalize_match",
    "normalize_team",
    "normalize_team_event_stats",
]
