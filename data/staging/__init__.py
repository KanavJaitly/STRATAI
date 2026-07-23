"""Staging layer for normalized domain payloads."""

from data.staging.normalizer import normalize_event, normalize_match, normalize_team
from data.staging.schemas import StagingEvent, StagingMatch, StagingTeam
from data.staging.validator import PayloadValidationError, ValidationIssue, validate_event, validate_match, validate_team

__all__ = [
    "StagingEvent",
    "StagingMatch",
    "StagingTeam",
    "ValidationIssue",
    "PayloadValidationError",
    "validate_event",
    "validate_match",
    "validate_team",
    "normalize_event",
    "normalize_match",
    "normalize_team",
]
