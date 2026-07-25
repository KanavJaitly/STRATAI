from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date
from typing import Any, Callable


@dataclass(frozen=True)
class ValidationIssue:
    """A single, structured validation failure.

    Carries enough context on its own to be logged or displayed usefully --
    which kind of entity, which field, why, and (best-effort) which raw
    payload it came from -- without needing to reconstruct that from a
    generic exception message.
    """

    entity_type: str
    field: str
    message: str
    source_object_id: str | None = None


class PayloadValidationError(Exception):
    """Raised when a raw payload fails validation and cannot be normalized."""

    def __init__(self, issues: list[ValidationIssue]) -> None:
        self.issues = list(issues)
        summary = "; ".join(f"{issue.entity_type}.{issue.field}: {issue.message}" for issue in self.issues)
        super().__init__(f"Validation failed with {len(self.issues)} issue(s): {summary}")


_TBA_EVENT_KEY_PATTERN = re.compile(r"^\d{4}")
# TBA team keys are normally "frc<number>", but off-season events use a
# trailing letter for a team's second robot (e.g. "frc254b") -- confirmed via
# TBA's own "B teams" support for off-season events. Rejecting these outright
# would fail validation on real, legitimate TBA data, not just malformed input.
_TBA_TEAM_KEY_PATTERN = re.compile(r"^frc\d+[a-zA-Z]?$")
_VALID_RAW_WINNING_ALLIANCES = ("", "red", "blue")
_STRICT_ISO_DATE_PATTERN = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def tba_alliance_team_keys(alliance: Any) -> Any:
    """Return a TBA alliance's roster field, accepting both names it appears under.

    TBA's real field is `team_keys`. It is read here with a `teams` fallback
    because both forms exist in the landing layer: raw response bodies use
    `team_keys`, while payloads landed before raw bodies were preserved were
    projections through MatchAllianceResult, which renamed the field to its
    alias `teams` on the way out. Reading only `teams` against a raw body
    silently yields an empty roster -- a real score with nobody on the field --
    and empty alliances are legitimately not flagged by the quality layer
    (an unplayed playoff match has no roster yet), so the whole match_teams
    junction would be pruned while the run reported success.

    Returns the value unconverted, including non-list values, so each caller's
    own type checking still applies.
    """
    if not isinstance(alliance, dict):
        return []
    if "team_keys" in alliance:
        return alliance["team_keys"]
    return alliance.get("teams", [])


def _is_iso_date_string(value: Any) -> bool:
    """Check a date string against TBA's actual "YYYY-MM-DD" format exactly.

    Deliberately stricter than date.fromisoformat() alone: Python 3.11+
    accepts other ISO 8601 variants too (confirmed: "20250314" and even
    "2025-W11-5" both parse successfully), and pydantic's own date field does
    NOT accept those same variants. Using fromisoformat's leniency here would
    let the validator report a date as "valid" that then fails at
    construction anyway -- an inconsistency that undermines the validator's
    whole purpose of giving an accurate answer before normalization proceeds.
    """
    if not isinstance(value, str) or not _STRICT_ISO_DATE_PATTERN.match(value):
        return False
    try:
        date.fromisoformat(value)
        return True
    except ValueError:
        return False


def validate_tba_event_payload(payload: Any) -> list[ValidationIssue]:
    """Validate a raw TBA event payload. Returns an empty list if valid."""
    if not isinstance(payload, dict):
        return [ValidationIssue("event", "<payload>", f"Expected an object, got {type(payload).__name__}")]

    key = payload.get("key")
    issues: list[ValidationIssue] = []

    if not isinstance(key, str) or not key:
        issues.append(ValidationIssue("event", "key", "Missing or empty required field 'key'"))

    name = payload.get("name")
    if not isinstance(name, str) or not name:
        issues.append(ValidationIssue("event", "name", "Missing or empty required field 'name'", key))

    year = payload.get("year")
    if not isinstance(year, int) or isinstance(year, bool):
        issues.append(ValidationIssue("event", "year", f"Missing or non-integer required field 'year' (got {year!r})", key))

    for date_field in ("start_date", "end_date"):
        value = payload.get(date_field)
        if value is not None and not _is_iso_date_string(value):
            issues.append(ValidationIssue("event", date_field, f"Expected an ISO date string (YYYY-MM-DD), got {value!r}", key))

    return issues


def validate_tba_match_payload(payload: Any) -> list[ValidationIssue]:
    """Validate a raw TBA match payload. Returns an empty list if valid."""
    if not isinstance(payload, dict):
        return [ValidationIssue("match", "<payload>", f"Expected an object, got {type(payload).__name__}")]

    key = payload.get("key")
    issues: list[ValidationIssue] = []

    if not isinstance(key, str) or not key:
        issues.append(ValidationIssue("match", "key", "Missing or empty required field 'key'"))

    event_key = payload.get("event_key")
    if not isinstance(event_key, str) or not event_key:
        issues.append(ValidationIssue("match", "event_key", "Missing or empty required field 'event_key'", key))
    elif not _TBA_EVENT_KEY_PATTERN.match(event_key):
        issues.append(ValidationIssue(
            "match", "event_key", f"Expected event_key to start with a 4-digit season year, got {event_key!r}", key,
        ))
    elif isinstance(key, str) and key and not key.startswith(f"{event_key}_"):
        # A match's own key always embeds its event_key (e.g. "2025casj_qm1"
        # belongs to event "2025casj"). If they disagree, the match has been
        # attributed to the wrong event -- silently trusting event_key here
        # would corrupt that event's record with a match that isn't really
        # part of it (and derive the wrong season for it, too).
        issues.append(ValidationIssue(
            "match", "event_key", f"Match key {key!r} does not belong to event_key {event_key!r}", key,
        ))

    time_value = payload.get("time")
    if time_value is not None and (not isinstance(time_value, int) or isinstance(time_value, bool) or time_value < 0):
        issues.append(ValidationIssue("match", "time", f"Expected a non-negative Unix timestamp, got {time_value!r}", key))

    for int_field in ("match_number", "set_number"):
        value = payload.get(int_field)
        if value is not None and (not isinstance(value, int) or isinstance(value, bool)):
            issues.append(ValidationIssue("match", int_field, f"Expected an integer, got {value!r}", key))

    winning_alliance = payload.get("winning_alliance")
    if winning_alliance is not None and winning_alliance not in _VALID_RAW_WINNING_ALLIANCES:
        issues.append(ValidationIssue(
            "match", "winning_alliance", f"Expected one of {_VALID_RAW_WINNING_ALLIANCES!r}, got {winning_alliance!r}", key,
        ))

    alliances = payload.get("alliances")
    if alliances is not None:
        if not isinstance(alliances, dict):
            issues.append(ValidationIssue("match", "alliances", f"Expected an object, got {type(alliances).__name__}", key))
        else:
            teams_by_color: dict[str, list[str]] = {}
            for color in ("red", "blue"):
                alliance = alliances.get(color, {})
                if not isinstance(alliance, dict):
                    issues.append(ValidationIssue("match", f"alliances.{color}", f"Expected an object, got {type(alliance).__name__}", key))
                    continue
                score = alliance.get("score")
                if score is not None and (not isinstance(score, int) or isinstance(score, bool)):
                    issues.append(ValidationIssue("match", f"alliances.{color}.score", f"Expected an integer, got {score!r}", key))
                team_keys = tba_alliance_team_keys(alliance)
                if not isinstance(team_keys, list):
                    issues.append(ValidationIssue("match", f"alliances.{color}.teams", f"Expected a list, got {type(team_keys).__name__}", key))
                    continue
                valid_team_keys = []
                for team_key in team_keys:
                    if not isinstance(team_key, str) or not _TBA_TEAM_KEY_PATTERN.match(team_key):
                        issues.append(ValidationIssue(
                            "match", f"alliances.{color}.teams", f"Expected team keys like 'frc1114', got {team_key!r}", key,
                        ))
                    else:
                        valid_team_keys.append(team_key)
                if len(valid_team_keys) != len(set(valid_team_keys)):
                    issues.append(ValidationIssue(
                        "match", f"alliances.{color}.teams", f"A team cannot appear twice on the same alliance: {valid_team_keys!r}", key,
                    ))
                teams_by_color[color] = valid_team_keys

            overlap = set(teams_by_color.get("red", [])) & set(teams_by_color.get("blue", []))
            if overlap:
                issues.append(ValidationIssue(
                    "match", "alliances", f"Team(s) {sorted(overlap)!r} cannot be on both alliances in the same match", key,
                ))

    return issues


def validate_tba_team_payload(payload: Any) -> list[ValidationIssue]:
    """Validate a raw TBA team payload. Returns an empty list if valid."""
    if not isinstance(payload, dict):
        return [ValidationIssue("team", "<payload>", f"Expected an object, got {type(payload).__name__}")]

    key = payload.get("key")
    issues: list[ValidationIssue] = []

    if not isinstance(key, str) or not _TBA_TEAM_KEY_PATTERN.match(key or ""):
        issues.append(ValidationIssue("team", "key", f"Missing or invalid required field 'key' (expected e.g. 'frc1114', got {key!r})"))

    team_number = payload.get("team_number")
    if not isinstance(team_number, int) or isinstance(team_number, bool):
        issues.append(ValidationIssue("team", "team_number", f"Missing or non-integer required field 'team_number' (got {team_number!r})", key))

    rookie_year = payload.get("rookie_year")
    if rookie_year is not None and (not isinstance(rookie_year, int) or isinstance(rookie_year, bool)):
        issues.append(ValidationIssue("team", "rookie_year", f"Expected an integer, got {rookie_year!r}", key))

    return issues


ValidatorFunc = Callable[[Any], list[ValidationIssue]]

_EVENT_VALIDATORS: dict[str, ValidatorFunc] = {"tba": validate_tba_event_payload}
_MATCH_VALIDATORS: dict[str, ValidatorFunc] = {"tba": validate_tba_match_payload}
_TEAM_VALIDATORS: dict[str, ValidatorFunc] = {"tba": validate_tba_team_payload}


def _dispatch(registry: dict[str, ValidatorFunc], source: str, entity_type: str, payload: Any) -> list[ValidationIssue]:
    try:
        validator = registry[source]
    except KeyError:
        raise ValueError(f"No {entity_type} validator registered for source '{source}'") from None
    return validator(payload)


def validate_event(source: str, payload: Any) -> list[ValidationIssue]:
    """Validate a raw event payload from any registered source."""
    return _dispatch(_EVENT_VALIDATORS, source, "event", payload)


def validate_match(source: str, payload: Any) -> list[ValidationIssue]:
    """Validate a raw match payload from any registered source."""
    return _dispatch(_MATCH_VALIDATORS, source, "match", payload)


def validate_team(source: str, payload: Any) -> list[ValidationIssue]:
    """Validate a raw team payload from any registered source."""
    return _dispatch(_TEAM_VALIDATORS, source, "team", payload)
