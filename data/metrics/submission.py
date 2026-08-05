"""The human scouting submission path: gate -> validate -> land -> stage -> load.

Phase 3 Milestone 7. Lives in data.metrics for the same dependency-direction
reason data.metrics.validator/normalizer (Milestones 5-6) do: everything that
builds a ScoutingObservation lives here, not in data.staging or data.pipeline.

Submission surface decision: this milestone builds the JSON-payload service
function an HTTP endpoint would call, not an actual HTTP route. No `api/`
package exists yet in this codebase -- Phase 3 Milestone 12 ("API foundation")
is explicitly where that gets built, and standing up a route here would
preempt that milestone's own job and its own app-factory/error-shape/CORS
decisions. The documented contract for that future route is exactly this
function's signature: POST a JSON object matching
data.metrics.validator.validate_human_scout_observation_payload's expected
shape (match_key, event_key, team_number, scout_identifier, submitted_at, and
at least one of defense_rating/feeding_rating), plus an optional access_code.

Reuses RawPayloadWriter/raw_source_payloads for landing (source="human_scout",
source_object_type="scouting_observation") rather than a parallel storage
mechanism -- the landing layer is documented as "intentionally source-agnostic
so any connector... can reuse it without the landing layer knowing their
schemas" (data.landing.raw_writer), and a direct human submission is just
another source in that sense, not a special case. This is also what "Resubmission
dedupes; corrected resubmission creates a new version" comes from for free:
RawPayloadWriter's own checksum-based dedup and is_current versioning, unmodified.

Anti-abuse gate: a lightweight, no-full-auth, per-event access code
(scouting_access_codes, migration 0009). Absent a configured code, an event is
open; a scout at a gated event must supply the matching code. This does not
identify who is submitting (scout_identifier remains free text, a documented
Phase 3 MVP limitation) -- it only deters casual or accidental cross-event
noise, which is exactly the bar "no full auth yet" sets.

Staging wiring: data.pipeline.stage_batch already dispatches
object_type="scouting_observation" to data.metrics.normalizer.normalize_scouting_
observation (Milestone 6's registry). What stage_batch's *defaults* cannot do is
compute a lineage key or run quality checks for a ScoutingObservation --
entity_key_of and check_entity both raise TypeError outside their closed
Staging* type sets, by design, to avoid data.staging/data.lineage importing
data.metrics. Milestone 7 supplies its own entity_key_fn
(scouting_observation_natural_key) and quality_check_fn
(check_scouting_observation_references, below) through the optional
parameters stage_batch was extended with for exactly this purpose.

The one quality check this milestone does add -- confirming match_key/
team_number/event_key actually exist canonically -- is not scope creep: without
it, a submission for a not-yet-synced match would reach
CanonicalRepository.load_scouting_observation and fail as a raw foreign-key
violation, the exact kind of generic, unstructured exception this whole
validate-then-build architecture (data.staging.validator's PayloadValidationError,
data.metrics.normalizer/validator's identical pattern) exists to keep from
leaking through. Everything else scouting-observation-specific (implausible
ratings, submission-pattern anomalies) genuinely is out of scope and unassigned
to any milestone yet.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from functools import partial
from typing import Any

from data import pipeline
from data.landing.raw_writer import RawPayloadRecord, RawPayloadWriter
from data.lineage import LineageStore
from data.metrics.normalizer import (
    normalize_human_scout_observation,
    scouting_observation_natural_key,
)
from data.metrics.schemas import ScoutingObservation
from data.metrics.validator import PayloadValidationError
from data.orchestrator import PipelineRunRecorder, WatermarkStore
from data.pipeline import SkippedRecord
from data.serving.repository import CanonicalRepository
from data.staging.quality import ISSUE_MISSING_REFERENCE, SEVERITY_ERROR, QualityIssue
from database.connection import Database

__all__ = [
    "PIPELINE_NAME",
    "PayloadValidationError",
    "ScoutingAccessDeniedError",
    "SubmissionResult",
    "check_scouting_access_gate",
    "check_scouting_observation_references",
    "scouting_source_object_id",
    "submit_human_scout_observation",
]

PIPELINE_NAME = "scouting_submission"


class ScoutingAccessDeniedError(Exception):
    """Raised when a submission's access_code does not match its event's configured code."""


def scouting_source_object_id(observation: ScoutingObservation) -> str:
    """The raw_source_payloads.source_object_id for one scout's rating of one team in one match.

    Three parts, not data.metrics.normalizer.scouting_observation_natural_key's
    four: source is already a separate column in raw_source_payloads' own
    dedup key (source, source_object_type, source_object_id, payload_checksum),
    so embedding it again here would be redundant, not more precise. Colon-joined
    for the identical reason the natural key is: match_key already contains
    underscores and scout_identifier is unrestricted free text, so
    underscore-joining risks two different submissions rendering identically.

    Public (not source-specific despite this module's name): reused as-is by
    data.metrics.scoutradioz (Milestone 9) for the identical reason -- the
    logic here has nothing to do with *how* an observation arrived, only with
    what makes one canonically the same opinion as another.
    """
    return f"{observation.match_key}:{observation.team_number}:{observation.scout_identifier}"


def check_scouting_observation_references(
    entity: ScoutingObservation,
    *,
    database: Database,
    source: str,
    raw_payload_id: int | None = None,
    context: Any = None,
    raw_payload: dict[str, Any] | None = None,
) -> list[QualityIssue]:
    """stage_batch's quality_check_fn for scouting observations.

    Confirms match_key/team_number/event_key actually exist in the canonical
    tables before this observation is ever handed to
    CanonicalRepository.load_scouting_observation, which would otherwise fail
    on a raw foreign-key violation. Mirrors data.staging.quality's own
    _check_match_roster/_check_match "missing_reference" pattern -- same issue
    type and severity, same fatal-means-skipped-and-retried-next-time
    semantics -- but queries the database directly rather than consulting a
    prebuilt QualityContext: there is no upfront extraction batch here to
    build one from, and a human submission is infrequent enough that this is
    the right tradeoff over threading a context through a flow that doesn't
    otherwise need one. All three existence checks are one round trip (three
    EXISTS subqueries in a single SELECT), not three separate queries --
    submissions are low-frequency, so this was never a real latency concern,
    but there is no reason to pay three round trips when one query already
    says everything needed.

    `database` is bound via functools.partial by the caller (submit_human_
    scout_observation), not passed by stage_batch itself -- stage_batch's
    quality_check_fn contract only supplies (entity, source, raw_payload_id,
    context, raw_payload), matching check_entity's own signature exactly.

    Deliberately does not also check that match_key's event agrees with
    event_key: that is a raw-payload structural concern data.metrics.validator
    (Milestone 5) already enforces before normalization ever runs, not a
    referential-existence one.

    Public (promoted from a leading-underscore name during Milestone 9): the
    logic here is entirely about whether an *entity* references real
    canonical rows, never about which source produced it -- `source` is only
    used to label a QualityIssue, never branched on. data.metrics.scoutradioz
    binds its own `database` via the identical functools.partial pattern
    rather than duplicating this query, the same way scouting_source_object_id
    above is shared.
    """
    with database.cursor() as cursor:
        cursor.execute(
            """
            SELECT
                EXISTS(SELECT 1 FROM matches WHERE match_key = %s),
                EXISTS(SELECT 1 FROM teams WHERE team_number = %s),
                EXISTS(SELECT 1 FROM events WHERE event_key = %s)
            """,
            (entity.match_key, entity.team_number, entity.event_key),
        )
        row = cursor.fetchone()
        # A bare SELECT of three EXISTS(...) expressions -- no FROM/WHERE on
        # the outer query -- always returns exactly one row regardless of
        # whether any inner subquery matched; unlike the three individual
        # per-table queries this replaced, there is no scenario where this
        # cursor legitimately has zero rows to fetch.
        assert row is not None
        match_exists, team_exists, event_exists = row

    object_id = scouting_observation_natural_key(entity)
    issues: list[QualityIssue] = []
    for exists, field_name, value in (
        (match_exists, "match_key", entity.match_key),
        (team_exists, "team_number", entity.team_number),
        (event_exists, "event_key", entity.event_key),
    ):
        if not exists:
            issues.append(QualityIssue(
                source=source, object_type=pipeline.OBJECT_TYPE_SCOUTING_OBSERVATION, object_id=object_id,
                issue_type=ISSUE_MISSING_REFERENCE, severity=SEVERITY_ERROR,
                description=f"Observation references {field_name} {value!r}, which does not exist canonically",
                field=field_name, raw_payload_id=raw_payload_id,
            ))
    return issues


def check_scouting_access_gate(database: Database, event_key: str, access_code: str | None) -> None:
    """Raise ScoutingAccessDeniedError if event_key is gated and access_code doesn't match.

    No row in scouting_access_codes for this event means no gate is configured
    -- submissions are allowed through. This is deliberate, not a fallback for
    a missing feature: Phase 3 has no admin surface yet to let a coordinator
    set a code, so requiring one unconditionally would make every event
    unsubmittable out of the box.
    """
    with database.cursor() as cursor:
        cursor.execute(
            "SELECT access_code FROM scouting_access_codes WHERE event_key = %s", (event_key,)
        )
        row = cursor.fetchone()

    if row is None:
        return
    required_code = row[0]
    if access_code != required_code:
        raise ScoutingAccessDeniedError(f"Invalid or missing access code for event {event_key!r}")


@dataclass(frozen=True)
class SubmissionResult:
    """Outcome of one end-to-end human scouting submission."""

    run_id: int
    source_object_id: str
    landed: bool
    observation: ScoutingObservation
    raw_payload_id: int | None
    skipped: list[SkippedRecord] = field(default_factory=list)


def submit_human_scout_observation(
    payload: dict[str, Any],
    *,
    database: Database,
    writer: RawPayloadWriter | None = None,
    repository: CanonicalRepository | None = None,
    recorder: PipelineRunRecorder | None = None,
    watermarks: WatermarkStore | None = None,
    lineage: LineageStore | None = None,
    access_code: str | None = None,
) -> SubmissionResult:
    """Submit one human-scout observation end to end: gate, validate, land, stage, load.

    Validation happens twice by design, not by oversight: once here, eagerly,
    via normalize_human_scout_observation (so a malformed payload is rejected
    immediately and lands nothing at all -- it never reaches
    raw_source_payloads), and again inside stage_batch when it processes the
    just-landed payload (so the canonical row this milestone requires is built
    through the same validate-then-normalize path every other source uses, not
    a special-cased shortcut). The second pass is expected to always succeed
    given the first one did -- it is the exact same deterministic function on
    the exact same payload -- so staged.skipped is expected to stay empty;
    it is still surfaced on SubmissionResult rather than assumed silently, in
    case that expectation is ever violated by a future change to either layer.

    Raises PayloadValidationError for a malformed payload and
    ScoutingAccessDeniedError for a missing/incorrect access code on a gated
    event -- both before anything is landed, and before a pipeline_runs row is
    even opened: neither represents a system failure worth recording in the
    pipeline's own run history, just an ordinary rejected request.
    """
    observation = normalize_human_scout_observation(payload)
    check_scouting_access_gate(database, observation.event_key, access_code)

    writer = writer or RawPayloadWriter(database)
    repository = repository or CanonicalRepository(database)
    recorder = recorder or PipelineRunRecorder(database)
    watermarks = watermarks or WatermarkStore(database)
    lineage = lineage or LineageStore(database)

    source_object_id = scouting_source_object_id(observation)
    event_key = observation.event_key

    run_id = recorder.start(PIPELINE_NAME, source=pipeline.SOURCE_HUMAN_SCOUT, scope_key=event_key)
    try:
        after_raw_id = watermarks.get(
            pipeline.SOURCE_HUMAN_SCOUT, pipeline.OBJECT_TYPE_SCOUTING_OBSERVATION, event_key
        )

        record = RawPayloadRecord(
            source=pipeline.SOURCE_HUMAN_SCOUT,
            source_object_type=pipeline.OBJECT_TYPE_SCOUTING_OBSERVATION,
            source_object_id=source_object_id,
            payload=payload,
        )
        landed = writer.write(record)

        pending = pipeline.read_pending(
            database, pipeline.SOURCE_HUMAN_SCOUT, pipeline.OBJECT_TYPE_SCOUTING_OBSERVATION,
            [source_object_id], after_raw_id,
        )
        staged = pipeline.stage_batch(
            pipeline.SOURCE_HUMAN_SCOUT, pipeline.OBJECT_TYPE_SCOUTING_OBSERVATION, pending, after_raw_id,
            entity_key_fn=scouting_observation_natural_key,
            quality_check_fn=partial(check_scouting_observation_references, database=database),
        )

        raw_payload_id: int | None = None
        if staged.entities:
            staged_observation = staged.entities[0]
            raw_payload_id = staged.lineage[0].raw_payload_id
            repository.load_scouting_observation(staged_observation, raw_payload_id=raw_payload_id)
            lineage.record(staged.lineage, run_id)

        watermarks.advance(
            pipeline.SOURCE_HUMAN_SCOUT, pipeline.OBJECT_TYPE_SCOUTING_OBSERVATION, event_key, staged.watermark_id
        )
        recorder.succeed(
            run_id, records_processed=len(staged.entities),
            stage_counts={"landed": int(landed), "loaded": len(staged.entities), "skipped": len(staged.skipped)},
        )

        return SubmissionResult(
            run_id=run_id,
            source_object_id=source_object_id,
            landed=landed,
            observation=observation,
            raw_payload_id=raw_payload_id,
            skipped=list(staged.skipped),
        )
    except Exception as exc:
        recorder.fail(run_id, str(exc))
        raise
