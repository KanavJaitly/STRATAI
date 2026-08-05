"""Structural validation of raw scouting observation submissions.

Phase 3 Milestone 5. This lives in data.metrics, not data.staging, per the
dependency-direction decision data/metrics/schemas.py already made and
documented in its own module docstring: ScoutingObservation lives in
data.metrics, so its validator (and its normalizer, Milestone 6,
data.metrics.normalizer) must too -- data.staging is a foundational layer
that nothing depends on today, and adding a ScoutingObservation-shaped
function there would invert that. This module reuses data.staging.validator's
ValidationIssue/PayloadValidationError directly rather than duplicating them,
the same way data.pipeline already imports data.staging's shared primitives.

Mirrors data.staging.validator's existing shape exactly: a validator function
per source returning `list[ValidationIssue]` (empty if valid, never raising
itself), collected into a per-source registry, dispatched by one small
function that raises ValueError for an unregistered source. "human_scout" and,
since Milestone 9 (2026-08-05), "scoutradioz" are both registered against the
identical validate_human_scout_observation_payload function: these rules
describe the canonical scouting-observation payload SHAPE, not who produced
it, so a genuinely separate "validate_scoutradioz..." function would only
duplicate logic that would inevitably drift the moment one copy was edited
and the other wasn't -- consistent with how data.staging.validator already
supports multiple sources per entity type without special-casing.

Scope: this validates exactly what a human scout's raw submission is expected
to contain -- match_key, event_key, team_number, scout_identifier,
submitted_at, and at least one of defense_rating/feeding_rating.

Correction (2026-08-04, Milestone 6): event_key and submitted_at were
originally left unchecked here, reasoned as "not something a scout submits,
derived elsewhere." That was wrong, found while designing Milestone 6's
normalizer: data.pipeline.stage_batch calls every normalizer as a pure
`normalizer(source, payload)` with no database access (verified by reading
stage_batch directly, not assumed), so a Milestone 6 normalizer built the same
way -- which it must be, to slot into that existing dispatch mechanism the way
Milestone 6's brief requires -- has no way to derive event_key from a match_key
DB lookup. event_key must therefore already be IN the raw payload, exactly as
TBA's own raw match payload carries its event_key directly rather than having
the normalizer derive it. submitted_at is the same story: stage_batch's
PendingPayload carries only (raw_id, source_object_id, payload) to the
normalizer, so a capture timestamp too has nowhere to come from except the
payload itself -- consistent with keeping normalization deterministic (no
wall-clock reads), which Milestone 6's own "determinism test" requirement
would otherwise be impossible to satisfy. source alone remains unchecked: it
is genuinely the dispatch parameter, not a payload field, exactly as it is for
every existing data.staging.validator function (e.g. validate_event("tba", ...)
never reads "tba" back out of the payload either).
"""

from __future__ import annotations

from typing import Any

from data.metrics.schemas import MAX_RATING, MIN_RATING
from data.staging.validator import (
    PayloadValidationError,
    ValidationIssue,
    ValidatorFunc,
)

__all__ = [
    "PayloadValidationError",
    "ValidationIssue",
    "validate_human_scout_observation_payload",
    "validate_scouting_observation",
]


def validate_human_scout_observation_payload(payload: Any) -> list[ValidationIssue]:
    """Validate a raw human-scout observation submission. Returns an empty list if valid."""
    if not isinstance(payload, dict):
        return [
            ValidationIssue(
                "scouting_observation", "<payload>", f"Expected an object, got {type(payload).__name__}"
            )
        ]

    issues: list[ValidationIssue] = []

    match_key = payload.get("match_key")
    if not isinstance(match_key, str) or not match_key:
        issues.append(
            ValidationIssue("scouting_observation", "match_key", "Missing or empty required field 'match_key'")
        )
        match_key_context = None
    else:
        match_key_context = match_key

    event_key = payload.get("event_key")
    if not isinstance(event_key, str) or not event_key:
        issues.append(
            ValidationIssue(
                "scouting_observation", "event_key", "Missing or empty required field 'event_key'", match_key_context
            )
        )
    elif isinstance(match_key, str) and match_key and not match_key.startswith(f"{event_key}_"):
        # Mirrors validate_tba_match_payload's identical check: a match_key
        # always embeds the event_key it belongs to (e.g. "2026casj_qm1"
        # belongs to "2026casj"). Disagreement here means the observation has
        # been attributed to the wrong event, exactly the corruption TBA's
        # own validator exists to catch for the same shape of field pair.
        issues.append(
            ValidationIssue(
                "scouting_observation", "event_key",
                f"match_key {match_key!r} does not belong to event_key {event_key!r}", match_key_context,
            )
        )

    submitted_at = payload.get("submitted_at")
    if not isinstance(submitted_at, str) or not submitted_at:
        issues.append(
            ValidationIssue(
                "scouting_observation", "submitted_at",
                "Missing or empty required field 'submitted_at'", match_key_context,
            )
        )

    # team_number must be a *positive* integer, not merely present: a scout
    # submission with team_number 0 or -5 is just as unusable as one missing
    # entirely, and ScoutingObservation itself enforces gt=0. Catching that
    # here, rather than only at model construction, is the whole reason this
    # validator exists ahead of normalization -- a structured, field-level
    # error now instead of a generic pydantic error later.
    team_number = payload.get("team_number")
    if not isinstance(team_number, int) or isinstance(team_number, bool) or team_number <= 0:
        issues.append(
            ValidationIssue(
                "scouting_observation", "team_number",
                f"Missing or invalid required field 'team_number' (expected a positive integer, got {team_number!r})",
                match_key_context,
            )
        )

    scout_identifier = payload.get("scout_identifier")
    if not isinstance(scout_identifier, str) or not scout_identifier:
        issues.append(
            ValidationIssue(
                "scouting_observation", "scout_identifier",
                "Missing or empty required field 'scout_identifier'", match_key_context,
            )
        )

    defense_rating = payload.get("defense_rating")
    feeding_rating = payload.get("feeding_rating")
    if defense_rating is None and feeding_rating is None:
        # Same wording as ScoutingObservation's own model_validator, so the
        # error reads identically whether it is caught here or (if this
        # validator were ever bypassed) at model construction.
        issues.append(
            ValidationIssue(
                "scouting_observation", "ratings",
                "At least one of defense_rating or feeding_rating must be provided", match_key_context,
            )
        )

    for rating_field, value in (("defense_rating", defense_rating), ("feeding_rating", feeding_rating)):
        if value is None:
            continue
        if not isinstance(value, int) or isinstance(value, bool) or not (MIN_RATING <= value <= MAX_RATING):
            issues.append(
                ValidationIssue(
                    "scouting_observation", rating_field,
                    f"Expected an integer between {MIN_RATING} and {MAX_RATING}, got {value!r}", match_key_context,
                )
            )

    notes = payload.get("notes")
    if notes is not None and not isinstance(notes, str):
        issues.append(
            ValidationIssue(
                "scouting_observation", "notes", f"Expected a string, got {type(notes).__name__}", match_key_context
            )
        )

    return issues


_SCOUTING_OBSERVATION_VALIDATORS: dict[str, ValidatorFunc] = {
    "human_scout": validate_human_scout_observation_payload,
    "scoutradioz": validate_human_scout_observation_payload,
}


def validate_scouting_observation(source: str, payload: Any) -> list[ValidationIssue]:
    """Validate a raw scouting observation payload from any registered source."""
    try:
        validator = _SCOUTING_OBSERVATION_VALIDATORS[source]
    except KeyError:
        raise ValueError(f"No scouting_observation validator registered for source '{source}'") from None
    return validator(payload)
