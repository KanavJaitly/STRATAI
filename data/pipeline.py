"""Stage definitions for the StratAI ingestion pipeline.

This module holds the four stages of the flow as independent, individually
testable functions:

    extraction  -> land -> stage (read_pending + stage_batch) -> load
    (source API)   (raw)   (validate/normalize)                 (canonical)

The staging stage also quality-screens what it normalizes (see
data.staging.quality) and pairs each accepted entity with the raw payload it
came from (see data.lineage), so records that would be meaningless or
unloadable are rejected before serving and everything that is loaded stays
traceable to its source.

It deliberately knows nothing about run bookkeeping, watermark persistence, or
where issues and lineage are written -- `data.orchestrator` owns that and drives
these stages. Keeping the dependency one-directional means a stage can be
exercised in isolation without any pipeline_runs / source_watermarks state
existing.

Incremental processing is built on `raw_source_payloads.id`. The landing layer
already deduplicates identical payloads, so an unchanged object lands no new
row and keeps its existing id; a changed object lands a new row with a higher
id and its predecessor is demoted out of `is_current`. That makes "the highest
raw id already promoted into the canonical tables" a complete description of
what has been processed, which is exactly what the orchestrator stores as a
watermark.

What lands is the **untouched response body**. Connectors return a
`SourceResponse` carrying both `raw` (exactly what the API sent) and `parsed`
(the validated model); this module lands `raw` and uses `parsed` only for
control flow. Every field the source sends is therefore persisted and included
in the landing checksum, so a change in any field -- including ones no client
model declares -- is detected as a new payload version.

This replaced landing `model_dump(mode="json", by_alias=True)`, a projection
through the client models that silently dropped every undeclared field before
landing (TBA match payloads lost `score_breakdown` entirely, roughly 11x the
data) and left those fields invisible to change detection. Capturing a new
field no longer requires widening a model first.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import Any, Callable, Iterable, Sequence

from data.clients.statbotics import StatboticsClient
from data.clients.tba import TBAClient
from data.landing.raw_writer import RawPayloadRecord, RawPayloadWriter
from data.lineage import LineageEntry, entity_key_of
from data.metrics.normalizer import normalize_scouting_observation
from data.serving.repository import CanonicalRepository
from data.staging import (
    PayloadValidationError,
    StagingEvent,
    StagingMatch,
    StagingTeam,
    StagingTeamEventStats,
    normalize_event,
    normalize_match,
    normalize_team,
    normalize_team_event_stats,
)
from data.staging.quality import (
    QualityContext,
    QualityIssue,
    check_entity,
    issues_from_validation_error,
)
from data.staging.validator import is_unassigned_team_key, tba_alliance_team_keys
from database.connection import Database

logger = logging.getLogger(__name__)

SOURCE_TBA = "tba"
SOURCE_STATBOTICS = "statbotics"
# Phase 3 Milestone 7: the human scouting submission path. Unlike TBA/Statbotics,
# this source's raw payloads are landed directly by a submission service
# (data.metrics.submission), never by an extraction poll against an external API.
SOURCE_HUMAN_SCOUT = "human_scout"

# Object-type names double as raw_source_payloads.source_object_type values and
# as source_watermarks.object_type values, so the run history, the landed rows,
# and the incremental state all describe the same thing with the same word.
OBJECT_TYPE_EVENT = "event"
OBJECT_TYPE_MATCH = "match"
OBJECT_TYPE_TEAM = "team"
OBJECT_TYPE_TEAM_EVENT = "team_event"
OBJECT_TYPE_SCOUTING_OBSERVATION = "scouting_observation"

# Mirrors data.staging.normalizer's team-key parsing, including its documented
# collapse of an off-season B-team ("frc254b") onto its parent team number.
# Two lines of regex duplicated in preference to importing a private symbol
# across module boundaries.
_TBA_TEAM_KEY_DIGITS = re.compile(r"^frc(\d+)")

# Dispatch by object type into the staging layer's own source registries, so
# adding a source means registering a normalizer there, not editing this table.
# scouting_observation is the one entry that dispatches into data.metrics
# (Milestone 6's own source-dispatch registry) rather than data.staging --
# stage_batch's job is to orchestrate whichever package owns an object type's
# normalizer, and data.metrics.normalizer already has its own "human_scout"/
# future-"scoutradioz" registry one level down, exactly like this one.
_STAGING_DISPATCH: dict[str, Callable[[str, dict[str, Any]], Any]] = {
    OBJECT_TYPE_EVENT: normalize_event,
    OBJECT_TYPE_MATCH: normalize_match,
    OBJECT_TYPE_TEAM: normalize_team,
    OBJECT_TYPE_TEAM_EVENT: normalize_team_event_stats,
    OBJECT_TYPE_SCOUTING_OBSERVATION: normalize_scouting_observation,
}


# ---------------------------------------------------------------------------
# Stage result types
# ---------------------------------------------------------------------------


@dataclass
class ExtractionBatch:
    """Raw payload records extracted from one source for one object type."""

    source: str
    object_type: str
    records: list[RawPayloadRecord] = field(default_factory=list)

    @property
    def object_ids(self) -> list[str]:
        """The source_object_ids in this batch, deduplicated, in extraction order."""
        seen: dict[str, None] = {}
        for record in self.records:
            seen.setdefault(record.source_object_id, None)
        return list(seen)


@dataclass
class ExtractionResult:
    """Everything one event's extraction produced, plus any non-fatal failures.

    `errors` carries per-object failures that were deliberately not allowed to
    abort the run (currently Statbotics lookups, which are supplementary: a
    team with no EPA record yet must not block that event's TBA data from
    reaching the canonical tables).
    """

    event_key: str
    batches: list[ExtractionBatch] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class PendingPayload:
    """A landed raw payload that has not yet been promoted to the canonical layer."""

    raw_id: int
    source_object_id: str
    payload: dict[str, Any]


@dataclass(frozen=True)
class SkippedRecord:
    """A pending payload that could not be normalized, and why."""

    raw_id: int
    source_object_id: str
    reason: str


@dataclass
class StagedBatch:
    """Validated staging entities for one (source, object_type), with its new watermark.

    `watermark_id` is the highest raw id whose *entire preceding run* of
    payloads was accepted cleanly -- the contiguous good prefix, not the maximum
    id seen. Entities after a rejection are still loaded (canonical writes are
    upserts, so re-processing them is harmless), but the watermark stops short
    of the rejection so the bad payload is retried on the next run instead of
    being skipped permanently.

    `issues` holds every quality finding for this batch, including warnings on
    entities that were accepted; `lineage` pairs each accepted entity with the
    raw payload it came from, for the audit trail.
    """

    source: str
    object_type: str
    entities: list[Any] = field(default_factory=list)
    watermark_id: int | None = None
    skipped: list[SkippedRecord] = field(default_factory=list)
    issues: list[QualityIssue] = field(default_factory=list)
    lineage: list[LineageEntry] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Extraction
# ---------------------------------------------------------------------------


def _team_number_from_key(team_key: str) -> int | None:
    match = _TBA_TEAM_KEY_DIGITS.match(team_key)
    return int(match.group(1)) if match else None


def _roster_team_keys(match_payloads: Iterable[dict[str, Any]]) -> list[str]:
    """Collect every real team key appearing on any alliance, deduplicated, in order.

    TBA's unassigned-roster placeholder (frc0) is excluded: it names no team, so
    backfilling it can only ever 404. Left in, it did exactly that on every
    single run of an affected event, recording a fresh extraction_failure
    warning each time for a team that does not exist and never will.
    """
    seen: dict[str, None] = {}
    for payload in match_payloads:
        alliances = payload.get("alliances") or {}
        for color in ("red", "blue"):
            alliance = alliances.get(color) or {}
            for team_key in tba_alliance_team_keys(alliance) or []:
                if isinstance(team_key, str) and not is_unassigned_team_key(team_key):
                    seen.setdefault(team_key, None)
    return list(seen)


def _backfill_roster_teams(
    tba: TBAClient,
    team_payloads: list[dict[str, Any]],
    match_payloads: Sequence[dict[str, Any]],
    errors: list[str],
) -> None:
    """Fetch any team that plays a match but is missing from the event team list.

    The canonical match_teams junction has a real foreign key onto
    teams(team_number), so a rostered team with no teams row fails the whole
    load. TBA's event team list is normally complete, but it is a separate
    endpoint from the match schedule and nothing guarantees they agree, so the
    gap is closed here rather than discovered as a foreign-key violation
    partway through the serving stage. Appends in place; a failed individual
    lookup is recorded in `errors` and left for the load to surface if that
    team really is required.
    """
    known_keys = {payload.get("key") for payload in team_payloads}
    missing_keys = [key for key in _roster_team_keys(match_payloads) if key not in known_keys]
    if not missing_keys:
        return

    logger.warning(
        "Roster backfill: %d team(s) play matches but are absent from the event team list: %s",
        len(missing_keys), ", ".join(missing_keys),
    )
    for team_key in missing_keys:
        team_number = _team_number_from_key(team_key)
        if team_number is None:
            errors.append(f"Unparseable team key on a match roster: {team_key!r}")
            continue
        try:
            team_payloads.append(tba.fetch_team_info(team_number).raw)
        except Exception as exc:
            errors.append(f"Roster backfill failed for {team_key}: {exc}")
            logger.warning("Roster backfill failed for %s: %s", team_key, exc)


def extract_event(
    event_key: str,
    *,
    tba: TBAClient,
    statbotics: StatboticsClient | None = None,
) -> ExtractionResult:
    """Fetch one event's event/match/team payloads from TBA, plus Statbotics EPA metrics.

    Extraction is always a full fetch: neither source exposes a
    "changed since" endpoint that this pipeline uses, so incrementality is
    achieved downstream (the landing layer discards unchanged payloads and the
    staging read-back only sees what is new). Passing `statbotics=None` runs a
    TBA-only sync, which leaves team_event_stats untouched.

    Every batch carries the sources' untouched response bodies (`SourceResponse.raw`),
    so nothing is dropped before landing; the parsed models are used only where
    typed access is needed, such as reading a team number to look up its metrics.
    """
    event_payload = tba.fetch_event(event_key).raw
    match_payloads = [response.raw for response in tba.fetch_event_matches(event_key)]
    team_payloads = [response.raw for response in tba.fetch_event_teams(event_key)]

    errors: list[str] = []
    _backfill_roster_teams(tba, team_payloads, match_payloads, errors)

    batches = [
        ExtractionBatch(SOURCE_TBA, OBJECT_TYPE_EVENT, [
            RawPayloadRecord(SOURCE_TBA, OBJECT_TYPE_EVENT, event_key, event_payload),
        ]),
        ExtractionBatch(SOURCE_TBA, OBJECT_TYPE_TEAM, [
            RawPayloadRecord(SOURCE_TBA, OBJECT_TYPE_TEAM, payload["key"], payload)
            for payload in team_payloads if payload.get("key")
        ]),
        ExtractionBatch(SOURCE_TBA, OBJECT_TYPE_MATCH, [
            RawPayloadRecord(SOURCE_TBA, OBJECT_TYPE_MATCH, payload["key"], payload)
            for payload in match_payloads if payload.get("key")
        ]),
    ]

    if statbotics is not None:
        batches.append(_extract_statbotics_team_events(
            statbotics, event_key, team_payloads, errors,
        ))


    logger.info(
        "Extracted event %s: %s",
        event_key,
        ", ".join(f"{batch.object_type}={len(batch.records)}" for batch in batches),
    )
    return ExtractionResult(event_key=event_key, batches=batches, errors=errors)


def _extract_statbotics_team_events(
    statbotics: StatboticsClient,
    event_key: str,
    team_payloads: Sequence[dict[str, Any]],
    errors: list[str],
) -> ExtractionBatch:
    """Fetch each attending team's EPA metrics for this event, one request per team.

    Statbotics exposes team-event metrics only per (team, event), so this is
    inherently N requests. An individual failure is recorded and skipped rather
    than raised: a team with no Statbotics record yet (common early in an event)
    is a normal condition, not a reason to fail the event's whole sync.
    """
    batch = ExtractionBatch(SOURCE_STATBOTICS, OBJECT_TYPE_TEAM_EVENT)
    for payload in team_payloads:
        team_number = payload.get("team_number")
        if team_number is None:
            continue
        try:
            response = statbotics.fetch_team_event_metrics(team_number, event_key)
        except Exception as exc:
            errors.append(f"Statbotics metrics unavailable for team {team_number} at {event_key}: {exc}")
            logger.warning("Statbotics metrics unavailable for team %s at %s: %s", team_number, event_key, exc)
            continue
        # Lands Statbotics's nested body as sent; the staging normalizer flattens
        # it through the same model validator the client used.
        batch.records.append(RawPayloadRecord(
            SOURCE_STATBOTICS, OBJECT_TYPE_TEAM_EVENT,
            f"{team_number}_{event_key}", response.raw,
        ))
    return batch


# ---------------------------------------------------------------------------
# Landing
# ---------------------------------------------------------------------------


def land(writer: RawPayloadWriter, batches: Iterable[ExtractionBatch]) -> dict[str, int]:
    """Persist every extracted batch into raw_source_payloads.

    Returns the number of genuinely new rows per "source.object_type" -- zero
    for a batch whose payloads are all byte-identical to what already landed,
    which is the signal that a re-sync found nothing new.
    """
    landed: dict[str, int] = {}
    for batch in batches:
        landed[f"{batch.source}.{batch.object_type}"] = writer.write_many(batch.records)
    logger.info("Landed new raw payloads: %s", landed)
    return landed


# ---------------------------------------------------------------------------
# Staging
# ---------------------------------------------------------------------------


def read_pending(
    database: Database,
    source: str,
    object_type: str,
    object_ids: Sequence[str],
    after_raw_id: int,
) -> list[PendingPayload]:
    """Read the current landed payloads for these objects that are newer than the watermark.

    `is_current` keeps a superseded payload version from being reprocessed, and
    `id > after_raw_id` excludes everything an earlier run already promoted.
    Ordered by id so the caller can reason about a contiguous processed prefix.
    """
    if not object_ids:
        return []

    with database.cursor() as cursor:
        cursor.execute(
            """
            SELECT id, source_object_id, payload_json
            FROM raw_source_payloads
            WHERE source = %s
              AND source_object_type = %s
              AND source_object_id = ANY(%s::text[])
              AND is_current
              AND id > %s
            ORDER BY id
            """,
            (source, object_type, list(object_ids), after_raw_id),
        )
        return [PendingPayload(row[0], row[1], row[2]) for row in cursor.fetchall()]


def stage_batch(
    source: str,
    object_type: str,
    pending: Sequence[PendingPayload],
    after_raw_id: int,
    *,
    context: QualityContext | None = None,
    entity_key_fn: Callable[[Any], str] = entity_key_of,
    quality_check_fn: Callable[..., list[QualityIssue]] = check_entity,
) -> StagedBatch:
    """Validate, normalize, and quality-screen pending raw payloads into staging entities.

    Two kinds of rejection flow through one mechanism. A payload that fails
    structural validation cannot be normalized at all; a payload that normalizes
    but trips a fatal quality check (a negative score, a reference that will not
    exist) is a record that would be meaningless or unloadable. Both are skipped
    with the finding recorded, and both hold the watermark short of themselves,
    so neither reaches the serving layer and both are retried next run --
    superseded automatically if the source later corrects them, since a
    correction lands as the new `is_current` row.

    One malformed record must not stop an event's remaining good records, so
    staging continues past a rejection; only the watermark stops there.

    `context` supplies the referential facts (which teams and events will exist)
    that quality checks need. Omitted, the referential checks are skipped and
    only self-contained plausibility checks run, which is what makes this safe
    to call without a database.

    `entity_key_fn`/`quality_check_fn` default to data.lineage's and
    data.staging.quality's own dispatchers, which is exact zero-behavior-change
    for every existing TBA/Statbotics caller. They exist as parameters (added
    Milestone 7) because both defaults raise TypeError for any entity type
    outside their own closed sets (the four Staging* models), and
    ScoutingObservation is deliberately not one of them -- teaching either
    dispatcher about data.metrics would invert the dependency direction
    data/metrics/schemas.py's module docstring already decided to protect.
    data.metrics.submission passes data.metrics.normalizer's own
    scouting_observation_natural_key here, and its own
    _check_scouting_observation_references as quality_check_fn -- a real
    referential-integrity check (does the referenced match/team/event exist
    canonically), added after a no-op version was found, during Milestone 7's
    own bug hunt, to let a submission for a not-yet-synced match reach
    CanonicalRepository.load_scouting_observation and fail as a raw
    foreign-key violation instead of a clean rejection. Rating-plausibility
    and submission-pattern checks remain out of scope and unassigned to any
    milestone; adding them means writing the check function, not touching
    this signature again.
    """
    normalizer = _STAGING_DISPATCH[object_type]
    staged = StagedBatch(source=source, object_type=object_type, watermark_id=after_raw_id or None)
    prefix_intact = True

    for item in pending:
        try:
            entity = normalizer(source, item.payload)
        except PayloadValidationError as exc:
            prefix_intact = False
            staged.skipped.append(SkippedRecord(item.raw_id, item.source_object_id, str(exc)))
            staged.issues.extend(issues_from_validation_error(
                exc, source=source, object_type=object_type,
                object_id=item.source_object_id, raw_payload_id=item.raw_id,
            ))
            logger.warning(
                "Skipping invalid %s.%s payload %s (raw id %d): %s",
                source, object_type, item.source_object_id, item.raw_id, exc,
            )
            continue

        issues = quality_check_fn(
            entity, source=source, raw_payload_id=item.raw_id,
            context=context, raw_payload=item.payload,
        )
        staged.issues.extend(issues)
        fatal = [issue for issue in issues if issue.is_fatal]
        if fatal:
            prefix_intact = False
            reason = "; ".join(f"{issue.field}: {issue.description}" for issue in fatal)
            staged.skipped.append(SkippedRecord(item.raw_id, item.source_object_id, reason))
            logger.warning(
                "Rejecting %s.%s payload %s (raw id %d) on quality checks: %s",
                source, object_type, item.source_object_id, item.raw_id, reason,
            )
            continue

        staged.entities.append(entity)
        staged.lineage.append(LineageEntry(
            entity_type=object_type,
            entity_key=entity_key_fn(entity),
            raw_payload_id=item.raw_id,
            source=source,
        ))
        if prefix_intact:
            staged.watermark_id = item.raw_id

    return staged


# ---------------------------------------------------------------------------
# Serving
# ---------------------------------------------------------------------------


def load(repository: CanonicalRepository, staged_batches: Iterable[StagedBatch]) -> dict[str, int]:
    """Load every staged batch into the canonical tables in foreign-key-safe order.

    Batches are regrouped by entity type and handed to
    CanonicalRepository.load_all, which orders teams and events ahead of
    matches and team_event_stats. Every write is an upsert, so loading an
    entity that is already present updates it in place instead of duplicating
    it -- the property that makes re-running a sync safe.

    TBA/Statbotics-only: unlike stage_batch (which dispatches any object_type
    _STAGING_DISPATCH knows, including "scouting_observation"), this function
    only ever handles the four Phase 2 entity types load_all accepts.
    ScoutingObservation is loaded via CanonicalRepository.load_scouting_observation
    directly (see data.metrics.submission), never through this function, because
    it needs a per-entity raw_payload_id that load_all's batched signature has
    no room for. Passing a "scouting_observation" StagedBatch here raises a
    clear error rather than the raw KeyError a plain dict lookup would give --
    found during a full-codebase audit as a trap for whoever wires Milestone 10,
    since stage_batch's now-generic signature makes it easy to assume this
    function is equally generic.
    """
    teams: list[StagingTeam] = []
    events: list[StagingEvent] = []
    matches: list[StagingMatch] = []
    team_event_stats: list[StagingTeamEventStats] = []
    buckets: dict[str, list[Any]] = {
        OBJECT_TYPE_TEAM: teams,
        OBJECT_TYPE_EVENT: events,
        OBJECT_TYPE_MATCH: matches,
        OBJECT_TYPE_TEAM_EVENT: team_event_stats,
    }

    for batch in staged_batches:
        if batch.object_type not in buckets:
            raise ValueError(
                f"pipeline.load() only handles {sorted(buckets)}; got {batch.object_type!r}. "
                "Scouting observations are loaded via "
                "CanonicalRepository.load_scouting_observation directly "
                "(see data.metrics.submission), not through this function."
            )
        buckets[batch.object_type].extend(batch.entities)

    counts = repository.load_all(
        teams=teams, events=events, matches=matches, team_event_stats=team_event_stats,
    )
    logger.info("Loaded canonical records: %s", counts)
    return counts
