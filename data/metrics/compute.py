"""The metrics computation pipeline: compute_team_metrics + the event-wide driver.

Phase 3 Milestone 10. Composes three already-built, independently-tested
layers into the object Phase 3's Definition of Done names -- "given a team
number and an event, return a complete metrics object":

  * Milestone 4 (data.metrics.history.get_team_match_history) for the match
    score history a team's ScoringProfile is built from.
  * Milestone 3 (data.metrics.statistics) for the pure statistical functions
    that turn that history into average_score/score_stddev/consistency_
    rating/reliability_score/the day counts.
  * Milestone 8 (data.metrics.aggregation.aggregate_defense_feeding) for the
    DefenseFeedingProfile built from a team's ScoutingObservation rows,
    fetched here for the first time -- both M3/M4 and M8's own module
    docstrings named this exact read as "a future milestone's job", and this
    is that milestone.

Lives in data.metrics, not data.pipeline or data.orchestrator, for the same
dependency-direction reason data.metrics.validator/normalizer/submission do:
everything that builds a TeamMetrics lives here. It reaches into
data.orchestrator for PipelineRunRecorder, exactly as data.metrics.submission
and data.metrics.scoutradioz already do, and needed the identical
"do not import this from data/metrics/__init__.py" exclusion, re-confirmed by
triggering the same circular-import failure those two modules already found
(data.orchestrator -> data.pipeline -> data.metrics.normalizer -> this
package's __init__ -> data.metrics.compute -> data.orchestrator, still
mid-initialization).

Design decision the milestone explicitly calls for: always fully recompute on
trigger, no incremental watermark. A watermark works for TBA/Statbotics
extraction because each object has one single, comparable "have we already
processed this raw_source_payloads.id" fact. A TeamMetrics row has no such
single fact -- its inputs span two entity types (matches, scouting_
observations) across three sources (tba, human_scout, scoutradioz), each
already independently watermarked for its OWN purpose. Reconstructing "has
anything this team's metrics depend on changed since we last computed" would
mean comparing against the max of several existing watermarks and getting
that comparison right for every future source this composes -- real
complexity bought for a marginal benefit, since recomputing is cheap (a
handful of indexed reads over already-canonical rows and pure-Python math,
nothing like TBA's network calls or the landing layer's checksum/dedup work).
Recomputing in full on every trigger is also the most literal way to satisfy
PROJECT_VISION.md's "calculated metrics should be reproducible from stored
source data" -- there is no partial, possibly-stale state to reason about,
ever.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from data.metrics.aggregation import aggregate_defense_feeding
from data.metrics.history import get_team_match_history
from data.metrics.quality import check_team_metrics
from data.metrics.schemas import DefenseFeedingProfile, ScoringProfile, ScoutingObservation, TeamMetrics
from data.metrics.statistics import (
    average_score,
    classify_match_days,
    consistency_rating,
    reliability_score,
    score_stddev,
)
from data.lineage import LineageEntry, LineageStore
from data.orchestrator import PipelineRunRecorder
from data.serving.repository import CanonicalRepository
from data.staging.quality import DataQualityRecorder, QualityIssue, summarize
from database.connection import Database

__all__ = [
    "ENTITY_TYPE_TEAM_METRICS",
    "PIPELINE_NAME",
    "MetricsComputeResult",
    "compute_event_team_metrics",
    "compute_team_metrics",
    "team_metrics_entity_key",
]

PIPELINE_NAME = "metrics_compute"

# Reuses the vocabulary data.lineage's own module docstring establishes
# (entity_type mirrors raw_source_payloads.source_object_type /
# source_watermarks.object_type) -- "team_metrics" names this row the same
# way every other entity type already names its own.
ENTITY_TYPE_TEAM_METRICS = "team_metrics"


def team_metrics_entity_key(team_number: int, event_key: str) -> str:
    """Render a team_metrics row's lineage key, matching its own (team_number, event_key) PK.

    Underscore-joined like data.lineage.entity_key_of's existing
    StagingTeamEventStats key ("{team_number}_{event_key}"), not colon-joined
    like data.metrics.normalizer.scouting_observation_natural_key: team_number
    is a clean, unambiguous digit string in a fixed leading position here too,
    the same reason entity_key_of's own convention is safe for that key.
    """
    return f"{team_number}_{event_key}"


def _season_for_event(database: Database, event_key: str) -> int:
    with database.cursor() as cursor:
        cursor.execute("SELECT season FROM events WHERE event_key = %s", (event_key,))
        row = cursor.fetchone()
    if row is None:
        raise ValueError(f"No event {event_key!r} exists canonically; sync it before computing metrics for it")
    return row[0]


def _teams_at_event(database: Database, event_key: str) -> list[int]:
    """Every team rostered into at least one match at this event, ascending.

    Sourced from match_teams (always populated by a TBA sync), not
    team_event_stats (Statbotics EPA, optional -- sync_event(statbotics=None)
    skips it entirely) -- match_teams is the one roster source every synced
    event actually has, matching data.metrics.history's own reliance on it.
    """
    with database.cursor() as cursor:
        cursor.execute(
            """
            SELECT DISTINCT mt.team_number
            FROM match_teams mt
            JOIN matches m ON m.match_key = mt.match_key
            WHERE m.event_key = %s
            ORDER BY mt.team_number
            """,
            (event_key,),
        )
        return [row[0] for row in cursor.fetchall()]


def _delete_orphaned_team_metrics(database: Database, event_key: str, current_team_numbers: list[int]) -> int:
    """Remove team_metrics (and its lineage) for a team no longer rostered at this event.

    Found during a full Phase 3 audit, not part of the original design: since
    compute_event_team_metrics only ever upserts a row for a team _teams_at_event
    currently returns, a team a schedule correction removes from every match at
    an event (TBA does occasionally republish a corrected roster -- see
    RUNNING_NOTES.md's frc0/roster-backfill history) would otherwise leave its
    team_metrics row behind forever, showing stale statistics for a team no
    longer relevant to this event. This is safe precisely because team_metrics
    is documented as a current-state snapshot, not an append-only history
    (data/metrics/schemas.py's TeamMetrics docstring) -- PROJECT_VISION.md's
    "historical data must never be overwritten" governs raw_source_payloads,
    which this never touches; nothing here removes or rewrites any raw payload
    or any other canonical table.

    `!= ALL(current_team_numbers)` is vacuously true for every row when
    current_team_numbers is empty (verified directly against Postgres, not
    assumed), which is exactly correct here: an event with zero currently
    rostered teams means every existing team_metrics row for it is orphaned.
    """
    with database.cursor() as cursor:
        cursor.execute(
            """
            DELETE FROM team_metrics
            WHERE event_key = %s AND team_number != ALL(%s::int[])
            RETURNING team_number
            """,
            (event_key, current_team_numbers),
        )
        removed = [row[0] for row in cursor.fetchall()]
        if removed:
            entity_keys = [team_metrics_entity_key(team_number, event_key) for team_number in removed]
            cursor.execute(
                "DELETE FROM canonical_lineage WHERE entity_type = %s AND entity_key = ANY(%s::text[])",
                (ENTITY_TYPE_TEAM_METRICS, entity_keys),
            )
    return len(removed)


@dataclass(frozen=True)
class _ObservedRow:
    """One scouting_observations row, paired with the raw payload it came from."""

    observation: ScoutingObservation
    raw_payload_id: int | None


def _fetch_team_scouting_observations(database: Database, team_number: int, event_key: str) -> list[_ObservedRow]:
    """Fetch every scouting observation for one team at one event, any source.

    The read this milestone's own module docstring (and data.metrics.
    aggregation's, and data.metrics.history's) already named as "a future
    milestone's job" -- aggregate_defense_feeding takes an already-fetched
    list and trusts the caller scoped it to one team/event; this is that
    fetch. raw_payload_id travels alongside each ScoutingObservation (not
    inside it -- the model has no such field) purely so this milestone's own
    lineage step can trace back to it without a second query.
    """
    with database.cursor() as cursor:
        cursor.execute(
            """
            SELECT match_key, event_key, team_number, scout_identifier,
                   defense_rating, feeding_rating, notes, source, submitted_at, raw_payload_id
            FROM scouting_observations
            WHERE team_number = %s AND event_key = %s
            ORDER BY submitted_at
            """,
            (team_number, event_key),
        )
        rows = cursor.fetchall()

    return [
        _ObservedRow(
            observation=ScoutingObservation(
                match_key=r[0], event_key=r[1], team_number=r[2], scout_identifier=r[3],
                defense_rating=r[4], feeding_rating=r[5], notes=r[6], source=r[7], submitted_at=r[8],
            ),
            raw_payload_id=r[9],
        )
        for r in rows
    ]


def _assemble_team_metrics(
    team_number: int, event_key: str, season: int, history, observed_rows: list[_ObservedRow],
) -> TeamMetrics:
    """Build a TeamMetrics from already-fetched history/observations. Pure, no DB.

    Split out from compute_team_metrics so compute_event_team_metrics's
    per-team loop (which also needs history/observed_rows for lineage) can
    reuse the exact same one fetch per team rather than querying twice.
    """
    day_counts = classify_match_days(history.scores)
    scoring = ScoringProfile(
        matches_scheduled=history.matches_scheduled,
        matches_used=history.matches_used,
        average_score=average_score(history.scores),
        score_stddev=score_stddev(history.scores),
        consistency_rating=consistency_rating(history.scores),
        reliability_score=reliability_score(history.matches_used, history.matches_scheduled),
        good_day_count=day_counts["good"] if day_counts is not None else None,
        average_day_count=day_counts["average"] if day_counts is not None else None,
        bad_day_count=day_counts["bad"] if day_counts is not None else None,
    )
    defense_feeding = aggregate_defense_feeding([row.observation for row in observed_rows])

    return TeamMetrics(
        team_number=team_number,
        event_key=event_key,
        season=season,
        computed_at=datetime.now(timezone.utc),
        scoring=scoring,
        defense_feeding=defense_feeding,
    )


def compute_team_metrics(database: Database, team_number: int, event_key: str) -> TeamMetrics:
    """Compute one team's complete TeamMetrics at one event from canonical + scouting data.

    Read-only: fetches match history and scouting observations, computes
    every statistic and the defense/feeding aggregation, and returns the
    assembled object. Never persists anything and never crashes on missing
    data -- a team with matches but zero observations gets a TeamMetrics
    whose defense_feeding is entirely insufficient_data=True (aggregate_
    defense_feeding's own contract for an empty observation list), never a
    partial or fabricated result. Persisting is compute_event_team_metrics's
    job, not this function's, mirroring how M3/M4/M8 stay pure computations
    and something else (this module) is the first thing to write anywhere.
    """
    history = get_team_match_history(database, team_number, event_key)
    observed_rows = _fetch_team_scouting_observations(database, team_number, event_key)
    season = _season_for_event(database, event_key)
    return _assemble_team_metrics(team_number, event_key, season, history, observed_rows)


def _lineage_entries_for_team(
    lineage: LineageStore,
    team_number: int,
    event_key: str,
    match_keys: list[str],
    observed_rows: list[_ObservedRow],
    match_lineage_cache: dict[str, Any],
) -> list[LineageEntry]:
    """Build this team's team_metrics lineage: every contributing match's
    current raw payload, plus every contributing observation's own landed
    payload (already known per-row -- scouting_observations.raw_payload_id is
    read directly, not looked up in canonical_lineage a second time).

    Traces every match this team is rostered into (all of matches_scheduled),
    not only the ones that contributed a score: an unplayed-but-scheduled
    match still feeds matches_scheduled and therefore reliability_score, so it
    is as much a contributing source as a played one. A match with no lineage
    row at all (theoretically possible only if it were loaded some other way
    than the standard land->stage->load path) contributes nothing traceable
    and is skipped rather than raising -- lineage is best-effort audit
    information, not a correctness gate on the computation itself.

    match_lineage_cache is shared across every team in one
    compute_event_team_metrics call: most matches at a real event have
    multiple rostered teams (typically six), and without this cache each of
    those teams' computations would re-query the identical match's lineage
    from scratch -- real, avoidable repeated work at event scale, not just a
    theoretical one. Caller-owned (not a module-level cache) so nothing
    persists stale results across separate compute_event_team_metrics calls.
    """
    key = team_metrics_entity_key(team_number, event_key)
    entries: list[LineageEntry] = []

    seen_match_keys: dict[str, None] = {}
    for match_key in match_keys:
        seen_match_keys.setdefault(match_key, None)
    for match_key in seen_match_keys:
        if match_key not in match_lineage_cache:
            match_lineage_cache[match_key] = lineage.latest("match", match_key)
        latest = match_lineage_cache[match_key]
        if latest is not None:
            entries.append(LineageEntry(
                entity_type=ENTITY_TYPE_TEAM_METRICS, entity_key=key,
                raw_payload_id=latest.raw_payload_id, source=latest.source,
            ))

    for row in observed_rows:
        if row.raw_payload_id is not None:
            entries.append(LineageEntry(
                entity_type=ENTITY_TYPE_TEAM_METRICS, entity_key=key,
                raw_payload_id=row.raw_payload_id, source=row.observation.source,
            ))

    return entries


@dataclass(frozen=True)
class MetricsComputeResult:
    """Outcome of computing (and persisting) every rostered team's metrics at one event."""

    run_id: int
    event_key: str
    teams_computed: int
    lineage_recorded: int
    orphaned_removed: int = 0
    metrics: list[TeamMetrics] = field(default_factory=list)
    # Phase 3 Milestone 11. Every finding is a warning by construction (see
    # data.metrics.quality), so unlike SyncResult this carries no fatal_issues
    # counterpart -- there is nothing here a caller could reject a metric over.
    issues: list[QualityIssue] = field(default_factory=list)


QUALITY_ISSUE_KEYS = "quality_issue_keys"
PREVIOUS_RUN_KEYS_SQL = """
SELECT stage_counts -> %(field)s FROM pipeline_runs
WHERE pipeline_name = %(pipeline)s AND scope_key = %(event)s AND status = 'succeeded' AND id < %(run)s
ORDER BY id DESC LIMIT 1
"""


def _issue_key(issue: QualityIssue) -> tuple:
    return (issue.object_type, issue.object_id, issue.field, issue.issue_type, issue.severity, issue.description)


def _new_since_previous_run(database: Database, event_key: str, run_id: int,
                            issues: list[QualityIssue]) -> list[QualityIssue]:
    """The issues this recompute must write: those the event's previous successful recompute did not detect.

    Phase 3 audit item (docs/metrics_pipeline.md §9.10): a recompute holds no watermark and re-detects every
    warning, so writing all of them on each run would add one row per warning per poll once the recompute runs
    during a watch (P5-M6). The previous run's complete detected set is kept in its stage_counts
    (QUALITY_ISSUE_KEYS), so an issue is written when it first appears, when it changes, or when it reappears
    after a run without it. A run with no previous key set (the first, or one predating this change) writes all.
    """
    with database.cursor() as cursor:
        cursor.execute(PREVIOUS_RUN_KEYS_SQL, {"field": QUALITY_ISSUE_KEYS, "pipeline": PIPELINE_NAME,
                                               "event": event_key, "run": run_id})
        row = cursor.fetchone()
    if row is None or row[0] is None:
        return list(issues)
    previous = {tuple(key) for key in row[0]}
    return [issue for issue in issues if _issue_key(issue) not in previous]


def compute_event_team_metrics(
    event_key: str,
    *,
    database: Database,
    repository: CanonicalRepository | None = None,
    recorder: PipelineRunRecorder | None = None,
    lineage: LineageStore | None = None,
    quality: DataQualityRecorder | None = None,
) -> MetricsComputeResult:
    """Compute and persist team_metrics for every team rostered at one event.

    Intended as a follow-on stage after sync_event (data.orchestrator.main
    calls this immediately after a single-event sync): by the time this runs,
    the event's matches and rosters are assumed already canonical, and
    whatever scouting observations exist for it (human-form or ScoutRadioz)
    are read as-is. Records its own pipeline_runs row (pipeline_name=
    "metrics_compute") independent of whatever run synced the underlying
    data -- source=None deliberately, since this computation is not tied to
    any single external source the way an extraction run is.

    Failure recovery mirrors sync_event: on any exception, the run is closed
    'failed' with the error message and re-raised. Nothing here uses a
    watermark (see this module's own docstring for why), so there is no
    partial-progress state to roll back -- team_metrics rows already upserted
    before a later team's computation fails simply stay correct, and a retry
    recomputes every team fresh regardless of what a previous partial run did.

    Phase 3 Milestone 11 added the quality step: every computed metric is
    checked (data.metrics.quality.check_team_metrics) before it is loaded, and
    the findings are written to data_quality_issues by the same
    DataQualityRecorder every ingestion issue goes through. The checks never
    block a load -- each one is a warning, and an untrustworthy metric is still
    a real one. Issues are recorded once after the loop rather than per team
    (one write, matching lineage.record's batching in this same function);
    unlike sync_event's record-before-load, a failure mid-loop therefore loses
    that run's findings, which costs nothing here because this function holds
    no watermark and the retry recomputes and re-detects everything from
    scratch.
    """
    repository = repository or CanonicalRepository(database)
    recorder = recorder or PipelineRunRecorder(database)
    lineage = lineage or LineageStore(database)
    quality = quality or DataQualityRecorder(database)

    run_id = recorder.start(PIPELINE_NAME, source=None, scope_key=event_key)
    try:
        season = _season_for_event(database, event_key)
        team_numbers = _teams_at_event(database, event_key)

        computed: list[TeamMetrics] = []
        lineage_entries: list[LineageEntry] = []
        issues: list[QualityIssue] = []
        match_lineage_cache: dict[str, Any] = {}
        for team_number in team_numbers:
            history = get_team_match_history(database, team_number, event_key)
            observed_rows = _fetch_team_scouting_observations(database, team_number, event_key)

            metrics = _assemble_team_metrics(team_number, event_key, season, history, observed_rows)
            # Checked after computation and before the load, the same position
            # stage_batch screens a staged entity in. Findings never gate the
            # load: they annotate a row that is about to be stored either way.
            issues.extend(check_team_metrics(metrics))
            repository.load_team_metrics(metrics)
            computed.append(metrics)

            lineage_entries.extend(_lineage_entries_for_team(
                lineage, team_number, event_key, history.match_keys, observed_rows, match_lineage_cache,
            ))

        issue_keys = sorted({_issue_key(issue) for issue in issues})
        quality.record(_new_since_previous_run(database, event_key, run_id, issues), run_id)
        lineage_recorded = lineage.record(lineage_entries, run_id)
        orphaned_removed = _delete_orphaned_team_metrics(database, event_key, team_numbers)

        recorder.succeed(
            run_id, records_processed=len(computed),
            stage_counts={
                "teams_computed": len(computed), "lineage_recorded": lineage_recorded,
                "orphaned_removed": orphaned_removed, "quality_issues": summarize(issues),
                QUALITY_ISSUE_KEYS: [list(key) for key in issue_keys],
            },
        )
        return MetricsComputeResult(
            run_id=run_id, event_key=event_key, teams_computed=len(computed),
            lineage_recorded=lineage_recorded, orphaned_removed=orphaned_removed, metrics=computed,
            issues=issues,
        )
    except Exception as exc:
        recorder.fail(run_id, f"{type(exc).__name__}: {exc}")
        raise
