"""Validate-then-build normalization of raw scouting observation submissions.

Phase 3 Milestone 6. Lives in data.metrics, not data.staging, for the same
dependency-direction reason data.metrics.validator (Milestone 5) does:
ScoutingObservation and everything that builds one lives in data.metrics,
since data.staging is a foundational layer nothing may import data.metrics
into (see data/metrics/schemas.py's module docstring).

Mirrors data.staging.normalizer's shape exactly: validate first (raising
PayloadValidationError on any issue), then construct the canonical model via a
build-or-raise wrapper that converts a pydantic ValidationError into the same
structured exception, so a field the hand-written validator doesn't explicitly
check can never leak a raw pydantic error past this layer. _build_or_raise and
_raise_if_invalid are reimplemented here rather than imported from
data.staging.normalizer: both are private (leading-underscore) there, and
reaching across a module boundary for a private symbol is exactly what
Milestone 5 already declined to do for the equivalent _dispatch helper. This
is boilerplate wrapping, not business logic -- the actual validation rules
live once, in data.metrics.validator, imported and reused directly.

Design decision forced by how the normalizer is actually invoked (Milestone
5's validator docstring has the full trace): data.pipeline.stage_batch calls
every normalizer as a pure `normalizer(source, payload)`, no database, and
this module's normalize_scouting_observation must have that identical shape
to slot into the same "source-dispatch registry" mechanism Milestone 6's
brief calls for. That means event_key and submitted_at cannot be derived here
-- they must already be in the raw payload, exactly as TBA's own raw match
payload carries its event_key directly rather than having the normalizer look
it up. Milestone 5's validator already checks both are present (and that
match_key/event_key agree), so this module only has to read them.

Milestone 9 (2026-08-05) registered "scoutradioz" here for real: ScoutRadioz's
CSV import (data.metrics.scoutradioz) maps a raw CSV row into this exact
canonical payload shape before ever calling normalize_scouting_observation, so
normalize_scoutradioz_observation needed only its own `source` value, not a
parallel validation implementation.
"""

from __future__ import annotations

from typing import Any, Callable

from pydantic import BaseModel
from pydantic import ValidationError as PydanticValidationError

from data.metrics.schemas import ScoutingObservation
from data.metrics.validator import (
    PayloadValidationError,
    ValidationIssue,
    validate_human_scout_observation_payload,
)

NormalizerFunc = Callable[[dict[str, Any]], ScoutingObservation]

__all__ = [
    "PayloadValidationError",
    "normalize_human_scout_observation",
    "normalize_scoutradioz_observation",
    "normalize_scouting_observation",
    "scouting_observation_natural_key",
]


def _raise_if_invalid(issues: list[ValidationIssue]) -> None:
    if issues:
        raise PayloadValidationError(issues)


def _build_or_raise(entity_type: str, model_cls: type[BaseModel], source_object_id: str | None, **fields: Any) -> Any:
    """Construct a canonical model, converting any pydantic failure into a
    structured PayloadValidationError. See this module's docstring for why
    this is a reimplementation of data.staging.normalizer's identical helper,
    not an import of it.
    """
    try:
        return model_cls(**fields)
    except PydanticValidationError as exc:
        issues = [
            ValidationIssue(
                entity_type=entity_type,
                field=".".join(str(part) for part in error["loc"]) or "<unknown>",
                message=error["msg"],
                source_object_id=source_object_id,
            )
            for error in exc.errors()
        ]
        raise PayloadValidationError(issues) from exc


def _normalize_scouting_observation_payload(payload: dict[str, Any], *, source: str) -> ScoutingObservation:
    """Shared validate-then-build logic for any source that produces this canonical payload shape.

    validate_human_scout_observation_payload's rules (required fields, at
    least one rating, range checks, match_key/event_key agreement) describe
    the CANONICAL payload shape itself, not who produced it or how -- reused
    here for Milestone 9's ScoutRadioz CSV import too, rather than duplicated
    under a "validate_scoutradioz..." name that would diverge from this one
    the moment either was edited. `source` is the one thing that genuinely
    differs per caller, so it stays a parameter, not baked into the payload.
    """
    _raise_if_invalid(validate_human_scout_observation_payload(payload))
    return _build_or_raise(
        "scouting_observation", ScoutingObservation, payload.get("match_key"),
        match_key=payload["match_key"],
        event_key=payload["event_key"],
        team_number=payload["team_number"],
        scout_identifier=payload["scout_identifier"],
        defense_rating=payload.get("defense_rating"),
        feeding_rating=payload.get("feeding_rating"),
        notes=payload.get("notes"),
        source=source,
        submitted_at=payload["submitted_at"],
    )


def normalize_human_scout_observation(payload: dict[str, Any]) -> ScoutingObservation:
    """Validate and normalize a raw human-scout submission into a canonical ScoutingObservation."""
    return _normalize_scouting_observation_payload(payload, source="human_scout")


def normalize_scoutradioz_observation(payload: dict[str, Any]) -> ScoutingObservation:
    """Validate and normalize an already-mapped ScoutRadioz CSV row into a canonical ScoutingObservation.

    `payload` here is NOT a raw ScoutRadioz CSV row -- it is the StratAI-canonical
    scouting-observation shape data.metrics.scoutradioz.map_scoutradioz_row_to_
    observation_payload builds from one first (match_key/event_key/team_number/
    scout_identifier/defense_rating/feeding_rating/notes/submitted_at). By the
    time a payload reaches this function, it is indistinguishable in shape from
    a human_scout submission, which is exactly why the validation rules are
    identical rather than a parallel "ScoutRadioz-flavored" copy.
    """
    return _normalize_scouting_observation_payload(payload, source="scoutradioz")


def scouting_observation_natural_key(observation: ScoutingObservation) -> str:
    """Render a ScoutingObservation's natural key, matching the DB unique
    constraint on (match_key, team_number, scout_identifier, source) exactly.

    A parallel implementation to data.lineage.entity_key_of, not an extension
    of it: entity_key_of lives in data.lineage, which today depends only on
    data.staging, and teaching it about ScoutingObservation would import
    data.metrics into that lower layer -- the same dependency-direction
    inversion data/metrics/schemas.py's module docstring already decided to
    avoid for the validator and normalizer themselves.

    Colon-joined, not underscore-joined like entity_key_of's own composite key
    for StagingTeamEventStats ("{team_number}_{event_key}"): match_key already
    contains underscores ("2026casj_qm1"), and scout_identifier is free text
    that could too, so two genuinely different tuples could underscore-join to
    the identical string (e.g. scout_identifier="b_2", source="c" vs
    scout_identifier="b", source="2_c"). A colon is not used by any of these
    four fields under this codebase's conventions, which makes a collision far
    less likely -- not proven impossible, since scout_identifier is
    unrestricted free text (see ScoutingObservation's own documented MVP
    limitation on that field). This key is used for lineage tracing only; the
    actual uniqueness guarantee is the database's own composite UNIQUE index
    on the four real columns, not this derived string.
    """
    return f"{observation.match_key}:{observation.team_number}:{observation.scout_identifier}:{observation.source}"


_SCOUTING_OBSERVATION_NORMALIZERS: dict[str, NormalizerFunc] = {
    "human_scout": normalize_human_scout_observation,
    "scoutradioz": normalize_scoutradioz_observation,
}


def normalize_scouting_observation(source: str, payload: dict[str, Any]) -> ScoutingObservation:
    """Normalize a raw scouting observation payload from any registered source."""
    try:
        normalizer = _SCOUTING_OBSERVATION_NORMALIZERS[source]
    except KeyError:
        raise ValueError(f"No scouting_observation normalizer registered for source '{source}'") from None
    return normalizer(payload)
