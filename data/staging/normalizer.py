from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Any, Callable

from pydantic import BaseModel
from pydantic import ValidationError as PydanticValidationError

from data.clients.schemas import StatboticsTeamEventMetrics
from data.staging.schemas import (
    StagingEvent,
    StagingMatch,
    StagingTeam,
    StagingTeamEventStats,
)
from data.staging.validator import (
    PayloadValidationError,
    ValidationIssue,
    validate_event,
    validate_match,
    validate_team,
)

# TBA's raw competition-level codes, mapped to StratAI's canonical vocabulary.
# An unrecognized code is preserved as its own lowercased string rather than
# rejected -- losing knowledge of *what kind* of match this was is worse than
# not having it fit the known vocabulary exactly.
_TBA_COMPETITION_LEVEL_MAP = {
    "qm": "qualification",
    "ef": "eighthfinal",
    "qf": "quarterfinal",
    "sf": "semifinal",
    "f": "final",
}

_EVENT_KEY_SEASON_PATTERN = re.compile(r"^(\d{4})")
_TEAM_KEY_DIGITS_PATTERN = re.compile(r"^frc(\d+)")


def _raise_if_invalid(issues: list[ValidationIssue]) -> None:
    if issues:
        raise PayloadValidationError(issues)


def _build_or_raise(entity_type: str, model_cls: type[BaseModel], source_object_id: str | None, **fields: Any) -> Any:
    """Construct a canonical staging model, converting any pydantic failure
    into our own structured PayloadValidationError.

    This is the safety net behind the hand-written validate_tba_* checks, not
    a replacement for them: those give precise, field-specific messages for
    the checks we've explicitly written (event_key format, team key format,
    roster integrity, ...). But the validator can't enumerate every field the
    canonical model enforces a type on forever -- every time StagingEvent/
    Match/Team gains a new field, forgetting to add a matching manual check
    would otherwise let a raw pydantic.ValidationError leak out instead of a
    PayloadValidationError, silently breaking the "no generic exceptions"
    guarantee this whole layer exists to provide. Wrapping construction here
    means that guarantee holds automatically as the models evolve.
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


def _normalize_competition_level(raw: str | None) -> str:
    if raw is None:
        return "unknown"
    return _TBA_COMPETITION_LEVEL_MAP.get(raw.lower(), raw.lower())


def _season_from_event_key(event_key: str) -> int:
    """Extract the 4-digit season year from the leading digits of a TBA event key.

    Safe to assume this matches: validate_tba_match_payload already rejects
    any event_key that doesn't start with 4 digits before this ever runs.
    """
    match = _EVENT_KEY_SEASON_PATTERN.match(event_key)
    return int(match.group(1))


def _parse_team_number(team_key: str) -> int:
    """Extract the numeric team number from a TBA team key like 'frc1114'.

    Off-season events use a trailing letter for a team's second robot (e.g.
    'frc254b' for team 254's "B" team) -- confirmed real via TBA's own
    off-season support, not hypothetical. There's no separate identity for a
    second robot in the canonical model (team_number is a plain int, joinable
    with StagingTeam.team_number), so a B-team deliberately collapses to its
    parent team's number here. Off-season second-robot matches are rare and
    don't affect competition-season records, so losing that distinction is an
    acceptable, documented simplification rather than expanding team_number
    into a more complex identity for a case this system doesn't need to
    distinguish yet.
    """
    match = _TEAM_KEY_DIGITS_PATTERN.match(team_key)
    return int(match.group(1))


def _unix_to_datetime(timestamp: int | None) -> datetime | None:
    # 0 (the Unix epoch, 1970-01-01) is never a real FRC match time -- FRC
    # didn't exist yet. Treating it as "not set" rather than a literal date
    # is a safe, meaningful interpretation regardless of whether a given
    # source uses 0 as an explicit "unscheduled" sentinel or just omits the
    # field; either way, 1970 is never the intended value.
    if not timestamp:
        return None
    return datetime.fromtimestamp(timestamp, tz=timezone.utc)


def _derive_winning_alliance(raw_winning_alliance: str | None, red_score: int | None, blue_score: int | None) -> str | None:
    """Determine the canonical winner, resolving TBA's ambiguous empty-string convention.

    TBA uses "" for both "not yet played" and "genuine tie", which are not the
    same thing. If TBA reports an explicit winner, trust it. Otherwise, if
    both scores are present, derive the outcome directly from them (also
    covers the case where TBA's field is stale relative to posted scores).
    Only when neither gives an answer is the match considered undecided.
    """
    if raw_winning_alliance in ("red", "blue"):
        return raw_winning_alliance
    if red_score is not None and blue_score is not None:
        if red_score == blue_score:
            return "tie"
        return "red" if red_score > blue_score else "blue"
    return None


def normalize_tba_event(payload: dict[str, Any]) -> StagingEvent:
    """Validate and normalize a raw TBA event payload into a canonical StagingEvent."""
    _raise_if_invalid(validate_event("tba", payload))
    return _build_or_raise(
        "event", StagingEvent, payload.get("key"),
        event_key=payload["key"],
        name=payload["name"],
        season=payload["year"],
        event_code=payload.get("event_code"),
        start_date=payload.get("start_date"),
        end_date=payload.get("end_date"),
        city=payload.get("city"),
        state_province=payload.get("state_prov"),
        country=payload.get("country"),
    )


def normalize_tba_match(payload: dict[str, Any]) -> StagingMatch:
    """Validate and normalize a raw TBA match payload into a canonical StagingMatch."""
    _raise_if_invalid(validate_match("tba", payload))

    alliances = payload.get("alliances") or {}
    red = alliances.get("red") or {}
    blue = alliances.get("blue") or {}
    red_score = red.get("score")
    blue_score = blue.get("score")

    return _build_or_raise(
        "match", StagingMatch, payload.get("key"),
        match_key=payload["key"],
        event_key=payload["event_key"],
        season=_season_from_event_key(payload["event_key"]),
        competition_level=_normalize_competition_level(payload.get("comp_level")),
        match_number=payload.get("match_number"),
        set_number=payload.get("set_number"),
        scheduled_time=_unix_to_datetime(payload.get("time")),
        red_teams=[_parse_team_number(k) for k in red.get("teams", [])],
        blue_teams=[_parse_team_number(k) for k in blue.get("teams", [])],
        red_score=red_score,
        blue_score=blue_score,
        winning_alliance=_derive_winning_alliance(payload.get("winning_alliance") or None, red_score, blue_score),
    )


def normalize_tba_team(payload: dict[str, Any]) -> StagingTeam:
    """Validate and normalize a raw TBA team payload into a canonical StagingTeam."""
    _raise_if_invalid(validate_team("tba", payload))
    return _build_or_raise(
        "team", StagingTeam, payload.get("key"),
        team_number=payload["team_number"],
        name=payload.get("nickname") or payload.get("name"),
        city=payload.get("city"),
        state_province=payload.get("state_prov"),
        country=payload.get("country"),
        rookie_year=payload.get("rookie_year"),
    )


def normalize_statbotics_team_event_stats(payload: dict[str, Any]) -> StagingTeamEventStats:
    """Validate and normalize a raw Statbotics team-event payload into a canonical StagingTeamEventStats.

    Unlike the TBA normalizers, there is no hand-written validator for this
    source (the validator module targets TBA payload shapes); the
    StatboticsTeamEventMetrics model is the validation boundary, so a malformed
    payload surfaces as a PayloadValidationError here just as the TBA path does.
    That model also flattens Statbotics's nested `epa`/`record` structure, so
    this function works in flat fields and accepts either shape.
    """
    try:
        metrics = StatboticsTeamEventMetrics.model_validate(payload)
    except PydanticValidationError as exc:
        issues = [
            ValidationIssue(
                entity_type="team_event_stats",
                field=".".join(str(part) for part in error["loc"]) or "<unknown>",
                message=error["msg"],
                source_object_id=payload.get("event") if isinstance(payload, dict) else None,
            )
            for error in exc.errors()
        ]
        raise PayloadValidationError(issues) from exc

    source_object_id = f"{metrics.team}_{metrics.event}"
    if not _EVENT_KEY_SEASON_PATTERN.match(metrics.event):
        raise PayloadValidationError([
            ValidationIssue(
                "team_event_stats", "event",
                f"Expected an event key starting with a 4-digit season, got {metrics.event!r}",
                source_object_id,
            )
        ])

    # Statbotics does report a played-match count (record.total.count in the v3
    # payload, flattened to `count` by StatboticsTeamEventMetrics), contrary to
    # what this pipeline assumed while the client was pointed at an unresolvable
    # host and no real response had ever been seen. Prefer the sourced count and
    # fall back to summing the W/L/T breakdown, which is only meaningful when all
    # three components are present.
    #
    # Preferring the sourced value also gives the data-quality layer something
    # real to check: while matches_played was always derived from W/L/T, the
    # quality rule comparing the two could never fire.
    matches_played = metrics.count
    if matches_played is None and None not in (metrics.wins, metrics.losses, metrics.ties):
        matches_played = metrics.wins + metrics.losses + metrics.ties

    return _build_or_raise(
        "team_event_stats", StagingTeamEventStats, source_object_id,
        team_number=metrics.team,
        event_key=metrics.event,
        season=_season_from_event_key(metrics.event),
        epa_total=metrics.epa_total,
        epa_auto=metrics.epa_auto,
        epa_teleop=metrics.epa_teleop,
        epa_endgame=metrics.epa_endgame,
        wins=metrics.wins,
        losses=metrics.losses,
        ties=metrics.ties,
        matches_played=matches_played,
    )


EventNormalizerFunc = Callable[[dict[str, Any]], StagingEvent]
MatchNormalizerFunc = Callable[[dict[str, Any]], StagingMatch]
TeamNormalizerFunc = Callable[[dict[str, Any]], StagingTeam]
TeamEventStatsNormalizerFunc = Callable[[dict[str, Any]], StagingTeamEventStats]

# Registries keyed by source name. Adding a new source (Statbotics,
# ScoutRadioz, ...) that exposes one of these concepts means writing one
# normalize_<source>_<entity> function and registering it here -- the
# canonical StagingEvent/StagingMatch/StagingTeam models never change.
_EVENT_NORMALIZERS: dict[str, EventNormalizerFunc] = {"tba": normalize_tba_event}
_MATCH_NORMALIZERS: dict[str, MatchNormalizerFunc] = {"tba": normalize_tba_match}
_TEAM_NORMALIZERS: dict[str, TeamNormalizerFunc] = {"tba": normalize_tba_team}
_TEAM_EVENT_STATS_NORMALIZERS: dict[str, TeamEventStatsNormalizerFunc] = {
    "statbotics": normalize_statbotics_team_event_stats,
}


def _dispatch(registry: dict[str, Callable[[dict[str, Any]], Any]], source: str, entity_type: str, payload: dict[str, Any]) -> Any:
    try:
        normalizer = registry[source]
    except KeyError:
        raise ValueError(f"No {entity_type} normalizer registered for source '{source}'") from None
    return normalizer(payload)


def normalize_event(source: str, payload: dict[str, Any]) -> StagingEvent:
    """Normalize a raw event payload from any registered source into a StagingEvent."""
    return _dispatch(_EVENT_NORMALIZERS, source, "event", payload)


def normalize_match(source: str, payload: dict[str, Any]) -> StagingMatch:
    """Normalize a raw match payload from any registered source into a StagingMatch."""
    return _dispatch(_MATCH_NORMALIZERS, source, "match", payload)


def normalize_team(source: str, payload: dict[str, Any]) -> StagingTeam:
    """Normalize a raw team payload from any registered source into a StagingTeam."""
    return _dispatch(_TEAM_NORMALIZERS, source, "team", payload)


def normalize_team_event_stats(source: str, payload: dict[str, Any]) -> StagingTeamEventStats:
    """Normalize a raw team-event-stats payload from any registered source into a StagingTeamEventStats."""
    return _dispatch(_TEAM_EVENT_STATS_NORMALIZERS, source, "team_event_stats", payload)
