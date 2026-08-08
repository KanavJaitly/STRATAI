"""ScoutRadioz CSV import: field mapping, and the batch land->stage->load orchestration.

Phase 3 Milestone 9. Lives in data.metrics, not data.clients, for the same
dependency-direction reason data.metrics.validator/normalizer/submission do:
this module imports data.metrics.schemas.ScoutingObservation/MAX_RATING/
MIN_RATING and calls data.metrics.validator/normalizer/submission directly, so
it cannot live under data.clients -- a foundational layer nothing may import
data.metrics into (see data/metrics/schemas.py's module docstring). The
CSV-reading half that genuinely has no data.metrics dependency
(data.clients.scoutradioz.ScoutRadiozCsvImporter, which only needs
data.clients.schemas.ScoutRadiozMatchScoutingRow) stays there, mirroring
exactly where TBAClient/StatboticsClient live relative to data.pipeline.

Why this milestone builds a CSV importer, not an HTTP connector: ScoutRadioz
(github.com/FIRSTTeam102/scoutradioz) has no public API. Confirmed 2026-08-05
by reading its real GitHub repo, wiki, and TypeScript route source directly --
every data-bearing route, including its own CSV export (`/exportdata`), sits
behind an authenticated per-team login. A team exports this CSV from their own
instance and hands it to StratAI directly; that export is the supported
integration point.

Column mapping is deliberately configuration, not code. This module has zero
field names for any specific FRC game compiled into it -- no "qDefenseQuality",
no "FuelPoints", nothing tied to the 2026 game the reference export happens to
be from. A ScoutRadioz CSV export carries two kinds of columns:

  * ScoutRadioz's own stable, cross-season metadata (org_key, event_key,
    match_key, time, alliance, team_key, scouter) -- modeled once, by
    data.clients.schemas.ScoutRadiozMatchScoutingRow, and read the same way
    regardless of game.
  * Everything else -- StartPos, AutoScore, qDefenseQuality, superNotes, and
    however many more a given season's scouting FORM defines. Which of these
    (if any) represents a defense/feeding quality rating, and on what native
    scale, is a property of that form, not of this module. The caller supplies
    a ScoutRadiozFieldMapping naming which raw column (if any) maps to
    defense_rating/feeding_rating and on what native scale, plus which columns
    should be folded into `notes`. A future season with a differently-shaped
    form supplies its own mapping; nothing here changes.

Nothing is silently lost even for columns the mapping doesn't name: every raw
CSV row is embedded verbatim, under "_raw_csv_row", in the payload that
actually lands in raw_source_payloads (see
map_scoutradioz_row_to_observation_payload) -- the identical "land the
untouched response body, never a projection" principle data/pipeline.py's own
module docstring already establishes for TBA/Statbotics, applied the one way
it can be here: unlike TBA/Statbotics, this source's landed payload IS the
already-mapped canonical shape (stage_batch's normalizer dispatch expects to
receive it that way, and which raw column feeds defense_rating/feeding_rating
is this milestone's own runtime configuration, not something a registered
normalizer function can be handed per call), so full fidelity is preserved by
carrying the raw row alongside the mapped fields rather than landing the raw
row bare and mapping it during staging. The canonical ScoutingObservation row
only ever carries what the mapping explicitly names plus whatever
notes_columns fold in; the full row survives regardless, in the permanent,
versioned landing layer, and changes to it change the landing checksum even
when every mapped field stays the same.

Reuses the human-scout submission path's shared helpers
(scouting_source_object_id, check_scouting_observation_references, both
promoted from leading-underscore names in data.metrics.submission during this
milestone) rather than duplicating them: neither one's logic has anything to
do with *how* an observation arrived, only with what the observation itself
is and what it references.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from functools import partial
from pathlib import Path
from typing import Any

from data import pipeline
from data.clients.schemas import ScoutRadiozMatchScoutingRow
from data.clients.scoutradioz import ScoutRadiozCsvImporter
from data.landing.raw_writer import RawPayloadRecord, RawPayloadWriter
from data.lineage import LineageStore
from data.metrics.normalizer import normalize_scoutradioz_observation, scouting_observation_natural_key
from data.metrics.schemas import MAX_RATING, MIN_RATING
from data.metrics.submission import (
    PayloadValidationError,
    check_scouting_observation_references,
    scouting_source_object_id,
)
from data.orchestrator import PipelineRunRecorder, WatermarkStore
from data.pipeline import SkippedRecord
from data.serving.repository import CanonicalRepository
from database.connection import Database

__all__ = [
    "PIPELINE_NAME",
    "SOURCE_SCOUTRADIOZ",
    "ScoutRadiozFieldMapping",
    "ScoutRadiozImportResult",
    "ScoutRadiozRatingMapping",
    "import_scoutradioz_csv",
    "map_scoutradioz_row_to_observation_payload",
]

SOURCE_SCOUTRADIOZ = "scoutradioz"
PIPELINE_NAME = "scoutradioz_import"

# Mirrors data.pipeline._TBA_TEAM_KEY_DIGITS's own duplicated-not-imported
# regex (see that module's comment for the reasoning): a private symbol across
# a module boundary, and a two-line regex is cheaper than reaching for one.
_TEAM_KEY_DIGITS = re.compile(r"^frc(\d+)$")


@dataclass(frozen=True)
class ScoutRadiozRatingMapping:
    """One raw CSV column, on its own native numeric scale, mapped onto StratAI's
    canonical [MIN_RATING, MAX_RATING] rating scale.

    excluded_values names raw cell values on THIS column that do not express a
    rating at all. Empty by default: unless a caller opts in, every value is a
    rating, and in particular 0 stays a real, meaningful one everywhere.

    It exists because one scouting-form column can carry two different
    questions. 2026's qDefenseQuality uses 0 for "played no defense", not
    "defended badly" -- established for the 2026mrcmp export by cross-tabulating
    it against on-field participation, not assumed: all 33 zero-rated rows
    participated normally (0 of 33 scoreless, 33 of 33 active) and out-scored
    the rated defenders roughly 2:1, which is the opposite of what "defended
    badly" would produce. Rescaling that 0 as a rating would publish a
    confident defense_score of 0.0 for a team that never defended -- an
    inference from absence, which is exactly what CLAUDE.md's "defense/feeding
    = directly measured, NOT inferred" constraint forbids.

    Per-column configuration, like source_min/source_max, and inert for any
    column that does not set it.

    target_min is the bottom of the canonical range this column rescales ONTO,
    defaulting to MIN_RATING so every mapping written before it existed is
    unaffected. It is also opt-in and per-column, and it exists for a defect
    excluded_values does not cover: a source scale whose own bottom endpoint is
    a real rating. 2026's qDefenseQuality is 1-10, so raw 1 -- a genuine "barely
    defended at all" -- rescaled to canonical (1-1)/9 * 5 + 0 = 0.0 exactly, an
    endpoint artifact of the two scales sharing no common bottom. That published
    the same canonical 0 that excluded_values exists to prevent, by a completely
    different route: not an inference from absence, but a real low rating
    flattened into the value reserved for "no defense". Setting target_min=1
    maps raw 1 to canonical 1 and leaves 0 unreachable for the column, so the
    two facts stay distinguishable in storage.

    A column whose source scale genuinely starts at "none of this" (a 0-10
    scale where 0 means no defense) wants excluded_values, not target_min; a
    column whose bottom value is a real, weak rating wants target_min. They are
    independent and compose.
    """

    column: str
    source_min: int
    source_max: int
    excluded_values: tuple[str, ...] = ()
    target_min: int = MIN_RATING

    def __post_init__(self) -> None:
        # target_min == MAX_RATING is rejected rather than accepted as another
        # degenerate-but-coherent case: unlike source_min == source_max (a real
        # if unusual single-value source scale, handled in _rescale_rating), it
        # collapses the *target* range to a point, so every distinct raw value
        # would report the identical canonical rating. That is a configuration
        # mistake with no legitimate reading.
        if not MIN_RATING <= self.target_min < MAX_RATING:
            raise ValueError(
                f"target_min must be in [{MIN_RATING}, {MAX_RATING}); got {self.target_min}"
            )


@dataclass(frozen=True)
class ScoutRadiozFieldMapping:
    """Caller-supplied, season/game-specific column mapping for one ScoutRadioz import.

    Deliberately not hardcoded anywhere in this module (see the module
    docstring): which column, if any, represents defense/feeding quality, and
    on what native scale, is a property of one season's scouting form. Leaving
    either rating unmapped (None) is a legitimate choice, not an error -- a
    game whose form has no feeding-quality field at all simply produces
    ScoutingObservation rows with feeding_rating always absent, exactly as
    valid as a human_scout submission that only ever rates one metric.
    """

    defense_rating: ScoutRadiozRatingMapping | None = None
    feeding_rating: ScoutRadiozRatingMapping | None = None
    notes_columns: tuple[str, ...] = ()


@dataclass(frozen=True)
class ScoutRadiozImportResult:
    """Outcome of importing one ScoutRadioz CSV export end to end."""

    run_id: int
    event_key: str
    rows_read: int
    landed: int
    loaded: int
    skipped: list[SkippedRecord] = field(default_factory=list)
    malformed_rows: list[tuple[int, str]] = field(default_factory=list)
    # Rows the field mapping deliberately excluded (see _row_expresses_no_rating).
    # Defaulted, so every existing construction of this result is unaffected.
    excluded_rows: int = 0


def _rescale_rating(raw_value: str, mapping: ScoutRadiozRatingMapping) -> int | None:
    """Linearly rescale a raw numeric column value onto [mapping.target_min, MAX_RATING].

    target_min defaults to MIN_RATING, so the target range is the full canonical
    [MIN_RATING, MAX_RATING] scale unless a caller opts out of its bottom (see
    ScoutRadiozRatingMapping.target_min for why one would).

    An empty cell means "not recorded" and returns None -- the same absence a
    human_scout payload expresses by omitting the key entirely. This is NOT
    the same as a present "0": per this codebase's own established convention
    (docs/data_pipeline.md's scouting_observations section), 0 is always a
    real, meaningful rating, never a missing-data sentinel, so a present "0"
    cell rescales like any other value, not to None.

    The single exception is opt-in and per-column: a value listed in this
    mapping's own excluded_values is not a rating on this column and returns
    None. The default is an empty tuple, so the paragraph above remains the
    behaviour for every column that does not configure one.
    """
    if raw_value in mapping.excluded_values:
        return None
    if raw_value == "":
        return None
    raw_int = int(raw_value)
    span = mapping.source_max - mapping.source_min
    if span == 0:
        # A degenerate single-value scale (source_min == source_max): every
        # recorded value is definitionally the same point, which maps to the
        # bottom of the target range rather than raising over a mapping
        # that is unusual but not self-contradictory. target_min, not
        # MIN_RATING: a caller who has declared that this column's ratings do
        # not reach the bottom of the canonical scale means that here too.
        return mapping.target_min
    scaled = (raw_int - mapping.source_min) / span * (MAX_RATING - mapping.target_min) + mapping.target_min
    return round(scaled)


def _row_expresses_no_rating(raw_row: dict[str, str], mapping: ScoutRadiozFieldMapping) -> bool:
    """True when every rating column this mapping configures is excluded for this row.

    Such a row is not malformed and is not a data error: the form recorded it
    faithfully, and the mapping says none of its rating columns express a
    rating here. It carries no observation, so it is skipped before landing
    and counted in ScoutRadiozImportResult.excluded_rows rather than reported
    beside genuinely broken rows in malformed_rows -- a distinction that
    matters precisely because half of a real export can land in this bucket.

    Only configured rating columns count, so a mapping that sets no
    excluded_values can never exclude a row. That is what keeps this opt-in
    and default-off. An empty cell is deliberately NOT treated as exclusion:
    "not recorded" and "recorded as not applicable" are different facts, and
    the former keeps its existing behaviour (None rating -> the shared
    validator rejects a row with no rating at all).
    """
    configured = [m for m in (mapping.defense_rating, mapping.feeding_rating) if m is not None]
    if not configured:
        return False
    return all(raw_row[m.column] in m.excluded_values for m in configured)


def _team_number_from_key(team_key: str) -> int:
    """Parse ScoutRadioz's "frcNNNN" team_key into its bare team number.

    Mirrors data.pipeline._TBA_TEAM_KEY_DIGITS's own parsing exactly (ScoutRadioz
    sources its team keys from TBA in the first place), duplicated rather than
    imported for the same reason that module's own comment gives: reaching
    across a module boundary for a private symbol.
    """
    match = _TEAM_KEY_DIGITS.match(team_key)
    if match is None:
        raise ValueError(f"Not a recognized ScoutRadioz team key: {team_key!r}")
    return int(match.group(1))


def _parse_scheduled_time(raw_time: str) -> datetime:
    """Parse ScoutRadioz's exported "M/D/YYYY H:MM:SS AM/PM" match time.

    KNOWN LIMITATION, documented rather than hidden: the export carries no
    timezone. This is the event's local wall-clock scheduled match time,
    exactly like TBA's own event-local match times -- but unlike TBA (which
    also provides a Unix-epoch "time" field StratAI already uses, see
    data/clients/schemas.py's Match model), this CSV export has no epoch
    fallback. Treated as UTC here rather than guessed at a specific zone,
    since inventing one would be exactly the kind of unverified assumption
    this codebase has been burned by before (see the 2026-08-01 decisions on
    TBA's own local-vs-UTC handling in RUNNING_NOTES.md). submitted_at's job
    in this codebase -- an ordering/audit timestamp for one observation,
    never used to compute a cross-event duration -- tolerates this. Revisit if
    a future consumer needs the true wall-clock event time.
    """
    naive = datetime.strptime(raw_time, "%m/%d/%Y %I:%M:%S %p")
    return naive.replace(tzinfo=timezone.utc)


def map_scoutradioz_row_to_observation_payload(
    raw_row: dict[str, str],
    parsed: ScoutRadiozMatchScoutingRow,
    mapping: ScoutRadiozFieldMapping,
) -> dict[str, Any]:
    """Build a canonical scouting-observation payload dict from one raw CSV row.

    The result is shaped exactly like data.metrics.validator.
    validate_human_scout_observation_payload's expected input, so it validates
    and normalizes through the identical, already-tested pipeline every other
    scouting source uses, rather than a parallel one.

    scout_identifier combines org_key with scouter ("frc11:Matthew Paccione"),
    not scouter alone: a raw scouter name is only unique within the exporting
    team's own roster of scouts, and two different teams' exports could
    otherwise collide on a common name. When scouter is blank -- a real,
    observed gap in ScoutRadioz's own data (confirmed in the captured fixture,
    not assumed) -- scout_identifier is left as the empty string rather than
    silently substituting org_key alone or any other placeholder: we
    genuinely do not know who scouted this row, and validate_human_scout_
    observation_payload correctly rejects an empty required field for exactly
    that reason. Never fabricate an identity for a row that has none.

    Raises ValueError for a structurally malformed row (an unparseable
    team_key) -- distinct from a PayloadValidationError, which the shared
    validator/normalizer raise for a row that parses fine but fails a
    business rule (blank scout_identifier, out-of-range rating, missing
    rating entirely). import_scoutradioz_csv catches both per row.

    The returned payload also carries the complete, untouched raw_row under
    "_raw_csv_row" -- this is what actually lands in raw_source_payloads, not
    just the fields this function maps. Skipping this would silently
    contradict both this module's own docstring and data/pipeline.py's
    established "land the untouched response body, never a projection"
    principle (the 2026-07-25 fix that stopped TBA/Statbotics landing
    payloads from dropping every undeclared field): a game-specific column
    this mapping doesn't name -- FuelPoints, ClimbPoints, whatever a future
    season calls its own fields -- would otherwise never be persisted
    anywhere, permanently, the moment this function returned. The extra key
    is invisible to validate_human_scout_observation_payload and
    _build_or_raise, both of which only ever read specific named keys, never
    the whole dict, so it costs nothing at validation or construction time.
    It also means a row's landing checksum reflects the true source data, not
    just whichever fields this mapping happened to select -- a change to an
    unmapped column is still a change RawPayloadWriter must detect as a new
    version, exactly as it already must for TBA/Statbotics.
    """
    scout_identifier = f"{parsed.org_key}:{parsed.scouter}" if parsed.scouter else ""

    payload: dict[str, Any] = {
        "match_key": parsed.match_key,
        "event_key": parsed.event_key,
        "team_number": _team_number_from_key(parsed.team_key),
        "scout_identifier": scout_identifier,
        "submitted_at": _parse_scheduled_time(parsed.time).isoformat(),
        "source": SOURCE_SCOUTRADIOZ,
        "_raw_csv_row": raw_row,
    }

    if mapping.defense_rating is not None:
        payload["defense_rating"] = _rescale_rating(raw_row[mapping.defense_rating.column], mapping.defense_rating)
    if mapping.feeding_rating is not None:
        payload["feeding_rating"] = _rescale_rating(raw_row[mapping.feeding_rating.column], mapping.feeding_rating)

    notes_parts = [raw_row[column] for column in mapping.notes_columns if raw_row.get(column)]
    if notes_parts:
        payload["notes"] = " | ".join(notes_parts)

    return payload


def import_scoutradioz_csv(
    csv_path: Path,
    field_mapping: ScoutRadiozFieldMapping,
    *,
    database: Database,
    writer: RawPayloadWriter | None = None,
    repository: CanonicalRepository | None = None,
    recorder: PipelineRunRecorder | None = None,
    watermarks: WatermarkStore | None = None,
    lineage: LineageStore | None = None,
) -> ScoutRadiozImportResult:
    """Import one ScoutRadioz CSV export end to end: land every row, then
    stage+load the whole batch through the existing pipeline machinery.

    One CSV file is expected to describe exactly one event (ScoutRadioz's own
    export is always scoped to one event by construction) -- this is checked,
    not assumed, and raises ValueError up front if it does not hold, since
    every other part of this pipeline (watermarks, pipeline_runs.scope_key)
    is scoped per event throughout this codebase.

    A malformed row (unparseable team_key) or one that fails the shared
    scouting-observation validation rules (blank scout_identifier, no rating
    at all, an out-of-range rating) is skipped and recorded in
    ScoutRadiozImportResult.malformed_rows -- never landed, never fatal to
    the rest of the file, mirroring submission.py's own eager-validation
    philosophy (nothing invalid ever reaches raw_source_payloads) and this
    codebase's broader "one bad record never blocks the good ones" principle.
    A row that lands cleanly but is then rejected by stage_batch's own
    referential-integrity check (its match/team/event does not exist
    canonically yet) is reported the ordinary way, in `skipped`.

    Idempotent by construction, not by special-casing: RawPayloadWriter's
    checksum-based dedup means re-importing the byte-identical file a second
    time lands nothing new, and read_pending only ever considers payloads
    above this source's own watermark, so nothing downstream re-processes
    unchanged data either.
    """
    writer = writer or RawPayloadWriter(database)
    repository = repository or CanonicalRepository(database)
    recorder = recorder or PipelineRunRecorder(database)
    watermarks = watermarks or WatermarkStore(database)
    lineage = lineage or LineageStore(database)

    with ScoutRadiozCsvImporter(csv_path) as importer:
        rows = list(importer.read_rows())
    if not rows:
        raise ValueError(f"{csv_path} contained no data rows")

    event_key = rows[0].parsed.event_key
    for response in rows:
        if response.parsed.event_key != event_key:
            raise ValueError(
                f"{csv_path} contains more than one event_key "
                f"({event_key!r} and {response.parsed.event_key!r}); import one event's export at a time"
            )

    # A field_mapping naming a column absent from this file is a caller
    # configuration mistake, not a per-row data problem -- fail loudly and
    # immediately, the same way the multi-event check above does, rather than
    # letting it surface as a confusing KeyError on the first row processed
    # (or, worse, as every single row being reported "malformed").
    available_columns = set(rows[0].raw)
    for rating_mapping, label in (
        (field_mapping.defense_rating, "defense_rating"), (field_mapping.feeding_rating, "feeding_rating"),
    ):
        if rating_mapping is not None and rating_mapping.column not in available_columns:
            raise ValueError(
                f"field_mapping.{label}.column {rating_mapping.column!r} is not a column in {csv_path}"
            )
    for column in field_mapping.notes_columns:
        if column not in available_columns:
            raise ValueError(f"field_mapping.notes_columns names {column!r}, which is not a column in {csv_path}")

    run_id = recorder.start(PIPELINE_NAME, source=SOURCE_SCOUTRADIOZ, scope_key=event_key)
    try:
        after_raw_id = watermarks.get(SOURCE_SCOUTRADIOZ, pipeline.OBJECT_TYPE_SCOUTING_OBSERVATION, event_key)

        malformed_rows: list[tuple[int, str]] = []
        source_object_ids: list[str] = []
        landed_count = 0
        excluded_count = 0
        # Header is CSV row 1, so the first data row is row 2.
        for row_number, response in enumerate(rows, start=2):
            # Checked before mapping, not after: an excluded row's ratings are
            # all None, and the shared validator rejects a payload with no
            # rating at all, so mapping it first would file a deliberate
            # exclusion as a malformed row.
            if _row_expresses_no_rating(response.raw, field_mapping):
                excluded_count += 1
                continue
            try:
                payload = map_scoutradioz_row_to_observation_payload(response.raw, response.parsed, field_mapping)
                observation = normalize_scoutradioz_observation(payload)
            except (ValueError, PayloadValidationError) as exc:
                malformed_rows.append((row_number, str(exc)))
                continue

            source_object_id = scouting_source_object_id(observation)
            record = RawPayloadRecord(
                source=SOURCE_SCOUTRADIOZ,
                source_object_type=pipeline.OBJECT_TYPE_SCOUTING_OBSERVATION,
                source_object_id=source_object_id,
                payload=payload,
            )
            if writer.write(record):
                landed_count += 1
            if source_object_id not in source_object_ids:
                source_object_ids.append(source_object_id)

        pending = pipeline.read_pending(
            database, SOURCE_SCOUTRADIOZ, pipeline.OBJECT_TYPE_SCOUTING_OBSERVATION, source_object_ids, after_raw_id,
        )
        staged = pipeline.stage_batch(
            SOURCE_SCOUTRADIOZ, pipeline.OBJECT_TYPE_SCOUTING_OBSERVATION, pending, after_raw_id,
            entity_key_fn=scouting_observation_natural_key,
            quality_check_fn=partial(check_scouting_observation_references, database=database),
        )
        for entity, lineage_entry in zip(staged.entities, staged.lineage):
            repository.load_scouting_observation(entity, raw_payload_id=lineage_entry.raw_payload_id)
        if staged.lineage:
            lineage.record(staged.lineage, run_id)

        watermarks.advance(
            SOURCE_SCOUTRADIOZ, pipeline.OBJECT_TYPE_SCOUTING_OBSERVATION, event_key, staged.watermark_id
        )
        recorder.succeed(
            run_id, records_processed=len(staged.entities),
            stage_counts={
                "rows_read": len(rows), "landed": landed_count, "loaded": len(staged.entities),
                "skipped": len(staged.skipped), "malformed": len(malformed_rows),
                "excluded": excluded_count,
            },
        )
        return ScoutRadiozImportResult(
            run_id=run_id, event_key=event_key, rows_read=len(rows), landed=landed_count,
            loaded=len(staged.entities), skipped=list(staged.skipped), malformed_rows=malformed_rows,
            excluded_rows=excluded_count,
        )
    except Exception as exc:
        recorder.fail(run_id, str(exc))
        raise
