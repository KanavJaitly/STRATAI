"""Data quality checks over normalized staging entities, and the recorder that
persists what they find into data_quality_issues.

This sits *above* the structural validation in data.staging.validator, which
already rejects malformed raw payloads (missing required fields, wrong types,
impossible rosters) before normalization. What that layer cannot judge is
whether a structurally valid record is *believable*, or whether it references
things that will actually exist. Those are this module's two jobs:

  * plausibility -- a season of 1776, a team number of 4 million, a score of
    50,000: individually well-formed, collectively impossible.
  * referential sanity -- a match whose roster names a team no teams row will
    contain. Left alone this surfaces as a foreign-key violation partway
    through the serving stage, aborting the whole load; caught here it rejects
    one match and lets the rest of the event through.

Severity is policy, not decoration. It maps directly onto what the pipeline
does with the record:

  * 'error' / 'critical' -- the entity is rejected and never reaches the
    canonical tables. Reserved for records that are meaningless or unloadable:
    a negative score, a win/loss/tie breakdown that contradicts its own total,
    an end date before its start date, a reference that does not exist.
  * 'warning' -- recorded, but loaded anyway. Everything judgemental lives
    here. A plausibility rule that discards data is worse than no rule at all:
    FRC scoring rules change every season, so a ceiling that looks generous
    today will eventually be exceeded by a real match, and silently dropping
    that match would corrupt an event's record while looking like success.

Deliberately NOT implemented: checking epa_total against
epa_auto + epa_teleop + epa_endgame. Statbotics does not document those as
summing exactly, so any tolerance chosen here would be invented statistics
generating false alarms about real data.

Rejection reuses the pipeline's existing mechanism rather than adding a second
one -- see data.pipeline.stage_batch, where a fatal issue takes exactly the
path a validation failure takes: skipped, watermark held short of it, retried
on the next run.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from typing import Any, Iterable, Sequence

from data.staging.schemas import (
    StagingEvent,
    StagingMatch,
    StagingTeam,
    StagingTeamEventStats,
)
from data.staging.validator import (
    TBA_UNPLAYED_ALLIANCE_SCORE,
    PayloadValidationError,
    tba_alliance_team_keys,
)
from database.connection import Database

logger = logging.getLogger(__name__)

SEVERITY_WARNING = "warning"
SEVERITY_ERROR = "error"
SEVERITY_CRITICAL = "critical"
_FATAL_SEVERITIES = frozenset({SEVERITY_ERROR, SEVERITY_CRITICAL})

ISSUE_VALIDATION_FAILURE = "validation_failure"
ISSUE_OUT_OF_RANGE = "out_of_range"
ISSUE_IMPLAUSIBLE_VALUE = "implausible_value"
ISSUE_INCONSISTENT_VALUES = "inconsistent_values"
ISSUE_MISSING_REFERENCE = "missing_reference"
ISSUE_EXTRACTION_FAILURE = "extraction_failure"

# FRC's first season. Nothing in this domain predates it.
FIRST_FRC_SEASON = 1992
# Team numbers are assigned sequentially and are around 10,000 as of 2026;
# 100,000 is a deliberately distant ceiling that only catches corruption.
MAX_PLAUSIBLE_TEAM_NUMBER = 100_000
# No FRC game has ever come close to a four-digit alliance score. A future game
# could, which is exactly why exceeding this is a warning and not a rejection.
MAX_PLAUSIBLE_ALLIANCE_SCORE = 1_000
# Statbotics EPA is roughly 0-100 but can go modestly negative for weak teams,
# so only a far-below-zero value indicates corruption rather than a bad team.
MIN_PLAUSIBLE_EPA = -50.0
EXPECTED_ALLIANCE_SIZE = 3
# A schedule more than this far in the future is corruption, not a schedule.
MAX_SCHEDULE_LOOKAHEAD = timedelta(days=730)

# Mirrors the team-key parsing in data.staging.normalizer and data.pipeline,
# including the documented collapse of an off-season B-team onto its parent.
_TBA_TEAM_KEY_DIGITS = re.compile(r"^frc(\d+)")


@dataclass(frozen=True)
class QualityIssue:
    """One detected data quality problem, ready to be written to data_quality_issues.

    Deliberately run-agnostic: the pipeline_run_id is stamped by
    DataQualityRecorder at write time, so checks can be run and reasoned about
    without a run existing at all.
    """

    source: str
    object_type: str
    object_id: str
    issue_type: str
    severity: str
    description: str
    field: str | None = None
    raw_payload_id: int | None = None

    @property
    def is_fatal(self) -> bool:
        """True when this issue must keep the record out of the canonical tables."""
        return self.severity in _FATAL_SEVERITIES


@dataclass(frozen=True)
class QualityContext:
    """The referential facts a check needs but a single entity cannot know.

    Holds the team numbers and event keys that will exist in the canonical
    tables once this run's load completes -- everything staged by this run plus
    everything already persisted by an earlier one. A reference outside these
    sets is an error, since the load would fail on it.
    """

    known_team_numbers: frozenset[int] = frozenset()
    known_event_keys: frozenset[str] = frozenset()


# ---------------------------------------------------------------------------
# Issue construction from existing failure paths
# ---------------------------------------------------------------------------


def issues_from_validation_error(
    error: PayloadValidationError,
    *,
    source: str,
    object_type: str,
    object_id: str,
    raw_payload_id: int | None = None,
) -> list[QualityIssue]:
    """Convert a structural validation failure into one issue per underlying problem.

    The staging validator already produces precise, field-level
    ValidationIssues; this preserves that granularity instead of collapsing
    them into one row, so a payload failing three checks is auditable as three
    findings. Always fatal: the payload could not be normalized at all, so
    there is no entity to load.
    """
    return [
        QualityIssue(
            source=source,
            object_type=object_type,
            object_id=object_id,
            issue_type=ISSUE_VALIDATION_FAILURE,
            severity=SEVERITY_ERROR,
            description=issue.message,
            field=issue.field,
            raw_payload_id=raw_payload_id,
        )
        for issue in error.issues
    ]


def issues_from_extraction_errors(errors: Iterable[str], *, event_key: str) -> list[QualityIssue]:
    """Record non-fatal extraction failures (missing Statbotics data, failed roster backfill).

    These are warnings by construction: extraction already decided to continue
    without the data. Recording them turns "this event's stats look thin" into
    an answerable question rather than something only visible in a log file.
    """
    return [
        QualityIssue(
            source="pipeline",
            object_type="extraction",
            object_id=event_key,
            issue_type=ISSUE_EXTRACTION_FAILURE,
            severity=SEVERITY_WARNING,
            description=message,
        )
        for message in errors
    ]


# ---------------------------------------------------------------------------
# Entity checks
# ---------------------------------------------------------------------------


def _max_plausible_season() -> int:
    """Next year's season is legitimately publishable; anything beyond is not."""
    return date.today().year + 1


def check_entity(
    entity: Any,
    *,
    source: str,
    raw_payload_id: int | None = None,
    context: QualityContext | None = None,
    raw_payload: dict[str, Any] | None = None,
) -> list[QualityIssue]:
    """Run every applicable quality check against one normalized staging entity.

    Dispatches on the entity's type. With `context` omitted only the
    self-contained plausibility checks run; referential checks are skipped
    rather than guessed at, so calling this without a context can never produce
    a false 'missing reference' rejection.

    `raw_payload` is optional on the same terms and for the same reason: a few
    anomalies are only visible *before* normalization resolves them, so the
    normalized entity cannot carry the evidence. Currently one check needs it
    (a one-sided unplayed sentinel on a match). Omitted, that check is skipped
    rather than guessed at, exactly as the referential ones are.
    """
    if isinstance(entity, StagingTeam):
        return _check_team(entity, source, raw_payload_id)
    if isinstance(entity, StagingEvent):
        return _check_event(entity, source, raw_payload_id)
    if isinstance(entity, StagingMatch):
        return _check_match(entity, source, raw_payload_id, context, raw_payload)
    if isinstance(entity, StagingTeamEventStats):
        return _check_team_event_stats(entity, source, raw_payload_id, context)
    raise TypeError(f"No quality checks defined for {type(entity).__name__}")


def _issue_builder(source: str, object_type: str, object_id: str, raw_payload_id: int | None):
    def build(issue_type: str, severity: str, field_name: str, description: str) -> QualityIssue:
        return QualityIssue(
            source=source, object_type=object_type, object_id=object_id,
            issue_type=issue_type, severity=severity, description=description,
            field=field_name, raw_payload_id=raw_payload_id,
        )

    return build


def _season_issues(season: int, build) -> list[QualityIssue]:
    if FIRST_FRC_SEASON <= season <= _max_plausible_season():
        return []
    return [build(
        ISSUE_IMPLAUSIBLE_VALUE, SEVERITY_WARNING, "season",
        f"Season {season} is outside the plausible range "
        f"{FIRST_FRC_SEASON}-{_max_plausible_season()}",
    )]


def _check_team(team: StagingTeam, source: str, raw_payload_id: int | None) -> list[QualityIssue]:
    build = _issue_builder(source, "team", str(team.team_number), raw_payload_id)
    issues: list[QualityIssue] = []

    if team.team_number <= 0:
        issues.append(build(
            ISSUE_OUT_OF_RANGE, SEVERITY_ERROR, "team_number",
            f"Team number must be positive, got {team.team_number}",
        ))
    elif team.team_number > MAX_PLAUSIBLE_TEAM_NUMBER:
        issues.append(build(
            ISSUE_IMPLAUSIBLE_VALUE, SEVERITY_WARNING, "team_number",
            f"Team number {team.team_number} exceeds the plausible ceiling "
            f"{MAX_PLAUSIBLE_TEAM_NUMBER}",
        ))

    if team.rookie_year is not None and not (FIRST_FRC_SEASON <= team.rookie_year <= _max_plausible_season()):
        issues.append(build(
            ISSUE_IMPLAUSIBLE_VALUE, SEVERITY_WARNING, "rookie_year",
            f"Rookie year {team.rookie_year} is outside the plausible range "
            f"{FIRST_FRC_SEASON}-{_max_plausible_season()}",
        ))

    return issues


def _check_event(event: StagingEvent, source: str, raw_payload_id: int | None) -> list[QualityIssue]:
    build = _issue_builder(source, "event", event.event_key, raw_payload_id)
    issues = _season_issues(event.season, build)

    if event.start_date is not None and event.end_date is not None and event.end_date < event.start_date:
        issues.append(build(
            ISSUE_INCONSISTENT_VALUES, SEVERITY_ERROR, "end_date",
            f"Event ends ({event.end_date}) before it starts ({event.start_date})",
        ))

    return issues


def _check_match(
    match: StagingMatch,
    source: str,
    raw_payload_id: int | None,
    context: QualityContext | None,
    raw_payload: dict[str, Any] | None = None,
) -> list[QualityIssue]:
    build = _issue_builder(source, "match", match.match_key, raw_payload_id)
    issues = _season_issues(match.season, build)

    for field_name, score in (("red_score", match.red_score), ("blue_score", match.blue_score)):
        # A None score means the match has not been played yet -- a normal,
        # valid state (and the state of most of the schedule during a live
        # event), so there is nothing to check and nothing to flag. TBA's -1
        # sentinel for exactly that condition is resolved to None by the
        # normalizer before it ever reaches here, which is why the negative
        # check below can stay fatal: anything still negative at this point is
        # genuine corruption, not an unplayed match.
        if score is None:
            continue
        if score < 0:
            issues.append(build(
                ISSUE_OUT_OF_RANGE, SEVERITY_ERROR, field_name,
                f"Alliance score cannot be negative, got {score}",
            ))
        elif score > MAX_PLAUSIBLE_ALLIANCE_SCORE:
            issues.append(build(
                ISSUE_IMPLAUSIBLE_VALUE, SEVERITY_WARNING, field_name,
                f"Alliance score {score} exceeds the plausible ceiling "
                f"{MAX_PLAUSIBLE_ALLIANCE_SCORE}",
            ))

    if raw_payload is not None:
        issues.extend(_check_unplayed_sentinel(raw_payload, build))

    issues.extend(_check_match_outcome(match, build))
    issues.extend(_check_match_roster(match, build, context))

    if match.scheduled_time is not None:
        issues.extend(_check_scheduled_time(match.scheduled_time, build))

    if context is not None and match.event_key not in context.known_event_keys:
        issues.append(build(
            ISSUE_MISSING_REFERENCE, SEVERITY_ERROR, "event_key",
            f"Match references event {match.event_key!r}, which will not exist in the canonical events table",
        ))

    return issues


def _check_unplayed_sentinel(raw_payload: dict[str, Any], build) -> list[QualityIssue]:
    """Flag a raw match where only ONE alliance carries TBA's unplayed sentinel.

    An unplayed match carries -1 on both alliances and is entirely normal --
    it is not flagged at all. One alliance sentinel and one real score is a
    different thing: a match half-played, which cannot be true. The normalizer
    resolves it by treating the whole match as unplayed (both scores NULL),
    which is the safest reading but does discard a posted score, so the anomaly
    is recorded here rather than disappearing silently.

    A warning, not an error, per this module's severity policy: the record is
    still meaningful and loadable as a scheduled match with a real roster, and
    the judgement being made -- that a one-sided sentinel means "unplayed"
    rather than "the other alliance scored zero" -- is an interpretation, not a
    certainty. Rejecting the match would discard a real, correctly-scheduled
    row over it.

    Reads the raw payload rather than the entity because normalization has
    deliberately erased the asymmetry by this point; nothing on StagingMatch
    can distinguish this from an ordinary unplayed match.
    """
    alliances = raw_payload.get("alliances") or {}
    scores = {}
    for color, field_name in (("red", "red_score"), ("blue", "blue_score")):
        alliance = alliances.get(color)
        if isinstance(alliance, dict):
            scores[field_name] = alliance.get("score")

    sentinels = [name for name, score in scores.items() if score == TBA_UNPLAYED_ALLIANCE_SCORE]
    if len(sentinels) != 1 or len(scores) != 2:
        return []

    unplayed_field = sentinels[0]
    scored_field = next(name for name in scores if name != unplayed_field)
    return [build(
        ISSUE_INCONSISTENT_VALUES, SEVERITY_WARNING, unplayed_field,
        f"{unplayed_field} is TBA's unplayed sentinel ({TBA_UNPLAYED_ALLIANCE_SCORE}) but "
        f"{scored_field} is {scores[scored_field]}; a match cannot be half-played, so both "
        f"scores were recorded as unplayed (NULL)",
    )]


def _check_match_outcome(match: StagingMatch, build) -> list[QualityIssue]:
    """Flag a declared winner that scored strictly less than the other alliance.

    Equal scores with a declared winner are NOT flagged: playoff tiebreakers
    legitimately advance one alliance from a tied match. Only a winner who was
    genuinely outscored indicates the source's own fields disagree.
    """
    if match.winning_alliance not in ("red", "blue"):
        return []
    if match.red_score is None or match.blue_score is None:
        return []

    winner_score = match.red_score if match.winning_alliance == "red" else match.blue_score
    loser_score = match.blue_score if match.winning_alliance == "red" else match.red_score
    if winner_score >= loser_score:
        return []
    return [build(
        ISSUE_INCONSISTENT_VALUES, SEVERITY_WARNING, "winning_alliance",
        f"Declared winner {match.winning_alliance!r} scored {winner_score} "
        f"but the other alliance scored {loser_score}",
    )]


def _check_match_roster(match: StagingMatch, build, context: QualityContext | None) -> list[QualityIssue]:
    """Check alliance sizes and that every rostered team will exist canonically.

    An entirely empty alliance is not flagged: TBA publishes playoff brackets
    before alliances are selected, so no roster yet is a normal state. A
    partially-filled alliance is genuinely suspicious and is flagged as a
    warning -- the match is still loadable and its scores still meaningful.
    """
    issues: list[QualityIssue] = []
    for field_name, roster in (("red_teams", match.red_teams), ("blue_teams", match.blue_teams)):
        if roster and len(roster) != EXPECTED_ALLIANCE_SIZE:
            issues.append(build(
                ISSUE_IMPLAUSIBLE_VALUE, SEVERITY_WARNING, field_name,
                f"Alliance has {len(roster)} team(s), expected {EXPECTED_ALLIANCE_SIZE}: {roster}",
            ))
        if context is None:
            continue
        missing = [number for number in roster if number not in context.known_team_numbers]
        if missing:
            issues.append(build(
                ISSUE_MISSING_REFERENCE, SEVERITY_ERROR, field_name,
                f"Roster references team(s) {missing} that will not exist in the canonical teams table",
            ))
    return issues


def _check_scheduled_time(scheduled_time: datetime, build) -> list[QualityIssue]:
    now = datetime.now(timezone.utc)
    if scheduled_time.year < FIRST_FRC_SEASON:
        return [build(
            ISSUE_IMPLAUSIBLE_VALUE, SEVERITY_WARNING, "scheduled_time",
            f"Scheduled time {scheduled_time.isoformat()} predates FRC's first season",
        )]
    if scheduled_time - now > MAX_SCHEDULE_LOOKAHEAD:
        return [build(
            ISSUE_IMPLAUSIBLE_VALUE, SEVERITY_WARNING, "scheduled_time",
            f"Scheduled time {scheduled_time.isoformat()} is more than "
            f"{MAX_SCHEDULE_LOOKAHEAD.days} days in the future",
        )]
    return []


def _check_team_event_stats(
    stats: StagingTeamEventStats,
    source: str,
    raw_payload_id: int | None,
    context: QualityContext | None,
) -> list[QualityIssue]:
    object_id = f"{stats.team_number}_{stats.event_key}"
    build = _issue_builder(source, "team_event", object_id, raw_payload_id)
    issues = _season_issues(stats.season, build)

    record = {"wins": stats.wins, "losses": stats.losses, "ties": stats.ties}
    for field_name, value in record.items():
        if value is not None and value < 0:
            issues.append(build(
                ISSUE_OUT_OF_RANGE, SEVERITY_ERROR, field_name,
                f"Match record cannot be negative, got {field_name}={value}",
            ))

    if stats.matches_played is not None and all(value is not None for value in record.values()):
        expected = stats.wins + stats.losses + stats.ties
        if stats.matches_played != expected:
            issues.append(build(
                ISSUE_INCONSISTENT_VALUES, SEVERITY_ERROR, "matches_played",
                f"matches_played={stats.matches_played} contradicts "
                f"wins+losses+ties={expected}",
            ))

    if stats.epa_total is not None and stats.epa_total < MIN_PLAUSIBLE_EPA:
        issues.append(build(
            ISSUE_IMPLAUSIBLE_VALUE, SEVERITY_WARNING, "epa_total",
            f"EPA total {stats.epa_total} is far below the plausible floor {MIN_PLAUSIBLE_EPA}",
        ))

    if context is not None:
        if stats.team_number not in context.known_team_numbers:
            issues.append(build(
                ISSUE_MISSING_REFERENCE, SEVERITY_ERROR, "team_number",
                f"Stats reference team {stats.team_number}, which will not exist in the canonical teams table",
            ))
        if stats.event_key not in context.known_event_keys:
            issues.append(build(
                ISSUE_MISSING_REFERENCE, SEVERITY_ERROR, "event_key",
                f"Stats reference event {stats.event_key!r}, which will not exist in the canonical events table",
            ))

    return issues


# ---------------------------------------------------------------------------
# Referential context
# ---------------------------------------------------------------------------


def build_quality_context(database: Database, extraction: Any) -> QualityContext:
    """Assemble the referential facts for one extraction, from staged and canonical state.

    An entity referenced by this run either arrives with it (extracted now) or
    is already persisted from an earlier run -- a team that attended a previous
    event, for instance, is a perfectly valid reference even though this run did
    not extract it. Only references in neither place are errors, so the
    canonical tables are queried for exactly the referenced ids not already
    accounted for, rather than being loaded wholesale.

    Takes the ExtractionResult structurally (batches of RawPayloadRecords) to
    avoid importing data.pipeline, which imports this module.
    """
    staged_team_numbers: set[int] = set()
    staged_event_keys: set[str] = set()
    referenced_team_numbers: set[int] = set()
    referenced_event_keys: set[str] = set()

    for batch in extraction.batches:
        for record in batch.records:
            payload = record.payload if isinstance(record.payload, dict) else {}
            if batch.object_type == "team":
                number = payload.get("team_number")
                if isinstance(number, int):
                    staged_team_numbers.add(number)
            elif batch.object_type == "event":
                staged_event_keys.add(record.source_object_id)
            elif batch.object_type == "match":
                event_key = payload.get("event_key")
                if isinstance(event_key, str):
                    referenced_event_keys.add(event_key)
                referenced_team_numbers |= _roster_numbers(payload)
            elif batch.object_type == "team_event":
                number, event_key = payload.get("team"), payload.get("event")
                if isinstance(number, int):
                    referenced_team_numbers.add(number)
                if isinstance(event_key, str):
                    referenced_event_keys.add(event_key)

    unresolved_teams = referenced_team_numbers - staged_team_numbers
    unresolved_events = referenced_event_keys - staged_event_keys

    return QualityContext(
        known_team_numbers=frozenset(
            staged_team_numbers | _existing_team_numbers(database, unresolved_teams)
        ),
        known_event_keys=frozenset(
            staged_event_keys | _existing_event_keys(database, unresolved_events)
        ),
    )


def _roster_numbers(match_payload: dict[str, Any]) -> set[int]:
    """Team numbers on either alliance of a raw match payload ('frc1114' -> 1114)."""
    numbers: set[int] = set()
    alliances = match_payload.get("alliances") or {}
    for color in ("red", "blue"):
        alliance = alliances.get(color) or {}
        for team_key in tba_alliance_team_keys(alliance) or []:
            match = _TBA_TEAM_KEY_DIGITS.match(team_key) if isinstance(team_key, str) else None
            if match is not None:
                numbers.add(int(match.group(1)))
    return numbers


def _existing_team_numbers(database: Database, team_numbers: set[int]) -> set[int]:
    if not team_numbers:
        return set()
    with database.cursor() as cursor:
        cursor.execute(
            "SELECT team_number FROM teams WHERE team_number = ANY(%s::int[])",
            (list(team_numbers),),
        )
        return {row[0] for row in cursor.fetchall()}


def _existing_event_keys(database: Database, event_keys: set[str]) -> set[str]:
    if not event_keys:
        return set()
    with database.cursor() as cursor:
        cursor.execute(
            "SELECT event_key FROM events WHERE event_key = ANY(%s::text[])",
            (list(event_keys),),
        )
        return {row[0] for row in cursor.fetchall()}


# ---------------------------------------------------------------------------
# Persistence
# ---------------------------------------------------------------------------


@dataclass
class DataQualityRecorder:
    """Writes detected QualityIssues into data_quality_issues."""

    database: Database

    def record(self, issues: Sequence[QualityIssue], pipeline_run_id: int | None = None) -> int:
        """Persist every issue, stamped with the run that detected it. Returns the count written.

        One row per detection, not per distinct problem: a payload that stays
        invalid is re-detected on every run (the watermark deliberately holds
        short of it), and each detection is a real event with its own timestamp
        and run. Collapsing them would lose the answer to "how long has this
        been broken", which is the question the resolved/resolved_at columns
        exist to support.
        """
        if not issues:
            return 0

        with self.database.cursor() as cursor:
            for issue in issues:
                cursor.execute(
                    """
                    INSERT INTO data_quality_issues (
                        pipeline_run_id, source, object_type, object_id,
                        raw_payload_id, field, issue_type, severity, description
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                    """,
                    (
                        pipeline_run_id, issue.source, issue.object_type, issue.object_id,
                        issue.raw_payload_id, issue.field, issue.issue_type,
                        issue.severity, issue.description,
                    ),
                )

        fatal = sum(1 for issue in issues if issue.is_fatal)
        logger.info(
            "Recorded %d data quality issue(s) for run %s (%d fatal)",
            len(issues), pipeline_run_id, fatal,
        )
        return len(issues)

    def open_issues(
        self,
        *,
        object_type: str | None = None,
        object_id: str | None = None,
        severity: str | None = None,
    ) -> list[dict[str, Any]]:
        """Read unresolved issues, optionally narrowed by object or severity.

        A convenience for tests, the future dashboard, and anyone asking "what
        is wrong with this event right now" without writing SQL.
        """
        clauses = ["NOT resolved"]
        params: list[Any] = []
        for column, value in (("object_type", object_type), ("object_id", object_id), ("severity", severity)):
            if value is not None:
                clauses.append(f"{column} = %s")
                params.append(value)

        with self.database.cursor() as cursor:
            cursor.execute(
                f"""
                SELECT id, pipeline_run_id, source, object_type, object_id, raw_payload_id,
                       field, issue_type, severity, description, detected_at
                FROM data_quality_issues
                WHERE {" AND ".join(clauses)}
                ORDER BY id
                """,
                tuple(params),
            )
            columns = [description[0] for description in cursor.description]
            return [dict(zip(columns, row)) for row in cursor.fetchall()]


def summarize(issues: Sequence[QualityIssue]) -> dict[str, Any]:
    """Summarize issues for a run's stage_counts: totals, severity spread, and type spread."""
    by_severity: dict[str, int] = {}
    by_type: dict[str, int] = {}
    for issue in issues:
        by_severity[issue.severity] = by_severity.get(issue.severity, 0) + 1
        by_type[issue.issue_type] = by_type.get(issue.issue_type, 0) + 1
    return {
        "total": len(issues),
        "fatal": sum(1 for issue in issues if issue.is_fatal),
        "by_severity": by_severity,
        "by_type": by_type,
    }
