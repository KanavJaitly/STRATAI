"""Run bookkeeping and incremental state for the StratAI ingestion pipeline.

`data.pipeline` defines the stages; this module owns the durable state around
them and drives one end-to-end sync:

  * `PipelineRunRecorder` writes a row per run into `pipeline_runs` -- opened as
    'running' before any work starts, closed as 'succeeded' or 'failed' with a
    stage-by-stage breakdown, so an interrupted run is visibly stuck at
    'running' rather than leaving no trace at all.
  * `WatermarkStore` persists per-source progress in `source_watermarks`, keyed
    on (source, object_type, scope_key) -- the unique index migration 0003
    already provides.
  * `DataQualityRecorder` and `LineageStore` persist what the staging stage
    found (`data_quality_issues`) and where every loaded row came from
    (`canonical_lineage`). Issues are written *before* the load, so a run that
    then fails still leaves its quality evidence behind; lineage is written
    *after* it, since a lineage row asserts that a canonical row exists.
  * `sync_event` wires extraction -> landing -> staging -> serving for a single
    event.
  * `sync_season` and `watch_event` are thin wrappers over it: one sweeps a
    whole season once, the other re-runs a single event on an interval so a
    live competition stays fresh without anyone re-triggering it.

The idempotence guarantee: a watermark is the highest `raw_source_payloads.id`
already promoted into the canonical tables for that (source, object_type,
event). Watermarks are advanced at exactly one point -- after the serving stage
returns successfully -- so a failure anywhere leaves them untouched and the
next run reprocesses that ground rather than skipping it. Re-running an
unchanged sync lands no new raw rows, which leaves nothing above the watermark,
so the staging and serving stages are genuine no-ops rather than deduplicated
work. And because every canonical write is an upsert, a run that fails *after*
loading some records but before advancing the watermark is still safe to repeat:
the repeat updates those rows in place instead of duplicating them.

Watermarks are scoped per event, including for teams. A team attending two
events is tracked independently under each, so one event's progress can never
be advanced by another event's run; the cost is that such a team's payload may
be re-upserted once per event, which is idempotent and cheap.
"""

from __future__ import annotations

import argparse
import json
import logging
import re
import signal
import time
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Iterable, Sequence

from psycopg.types.json import Jsonb

from data import pipeline
from data.clients.statbotics import StatboticsClient
from data.clients.tba import TBAClient
from data.config import Settings
from data.landing.raw_writer import RawPayloadWriter
from data.lineage import LineageStore
from data.pipeline import ExtractionResult, SkippedRecord, StagedBatch
from data.serving.repository import CanonicalRepository
from data.staging.quality import (
    DataQualityRecorder,
    QualityIssue,
    build_quality_context,
    issues_from_extraction_errors,
    summarize,
)
from database.connection import Database, DatabaseConfig

logger = logging.getLogger(__name__)

DEFAULT_PIPELINE_NAME = "event_sync"

# TBA's numeric event types for *official* competition. Offseason (99) and
# preseason (100) events are deliberately excluded from a season sync: they run
# modified rules with mixed, ad-hoc rosters, so their results are not comparable
# to official play and would distort any season-level metric computed over them.
# The numbers, in order: Regional, District, District Championship,
# Championship Division, Championship Finals, District Championship Division.
OFFICIAL_EVENT_TYPES = frozenset({0, 1, 2, 3, 4, 5})

# Pause between events in a season sync. A season sync issues only ~3 TBA
# requests per event, so this is not needed to stay inside any advertised rate
# limit (TBA publishes none, and sends no X-RateLimit headers); it is cheap
# insurance against looking like a hostile client over a several-hundred-request
# run. At 190 events it costs about 95 seconds.
DEFAULT_EVENT_DELAY_SECONDS = 0.5


@dataclass
class PipelineRunRecorder:
    """Records the lifecycle of one pipeline run in the pipeline_runs table."""

    database: Database

    def start(self, pipeline_name: str, *, source: str | None = None, scope_key: str | None = None) -> int:
        """Open a run row with status 'running' and return its id.

        Committed immediately, before any extraction happens, so a process that
        dies mid-run leaves an auditable 'running' row behind.
        """
        with self.database.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO pipeline_runs (pipeline_name, source, scope_key, status, started_at)
                VALUES (%s, %s, %s, 'running', NOW())
                RETURNING id
                """,
                (pipeline_name, source, scope_key),
            )
            row = cursor.fetchone()
            # A plain INSERT with no ON CONFLICT clause always inserts and
            # returns exactly one row -- unlike raw_writer.py's ON CONFLICT DO
            # NOTHING RETURNING, there is no legitimate zero-row outcome here.
            assert row is not None
            return int(row[0])

    def succeed(self, run_id: int, *, records_processed: int, stage_counts: dict[str, Any] | None = None) -> None:
        """Close a run row as succeeded, recording its per-stage counts."""
        self._finish(run_id, "succeeded", records_processed, stage_counts, None)

    def fail(
        self,
        run_id: int,
        error_message: str,
        *,
        records_processed: int = 0,
        stage_counts: dict[str, Any] | None = None,
    ) -> None:
        """Close a run row as failed, recording the error and any partial progress.

        Uses its own connection, so it still commits after the failing work's
        transaction has been rolled back.
        """
        self._finish(run_id, "failed", records_processed, stage_counts, error_message)

    def _finish(
        self,
        run_id: int,
        status: str,
        records_processed: int,
        stage_counts: dict[str, Any] | None,
        error_message: str | None,
    ) -> None:
        with self.database.cursor() as cursor:
            cursor.execute(
                """
                UPDATE pipeline_runs
                SET status = %s,
                    finished_at = NOW(),
                    records_processed = %s,
                    stage_counts = %s,
                    error_message = %s
                WHERE id = %s
                """,
                (
                    status,
                    records_processed,
                    Jsonb(stage_counts) if stage_counts is not None else None,
                    error_message,
                    run_id,
                ),
            )


@dataclass
class WatermarkStore:
    """Durable per-source incremental state, backed by source_watermarks.

    A watermark value is the highest raw_source_payloads.id already promoted to
    the canonical layer for that (source, object_type, scope_key). It is stored
    in the existing `watermark_value` TEXT column -- the column is deliberately
    source-agnostic (a future source could watermark on a timestamp or an
    opaque cursor), so this store owns the int<->text conversion rather than the
    schema.
    """

    database: Database

    def get(self, source: str, object_type: str, scope_key: str) -> int:
        """Return the stored watermark, or 0 when this scope has never been synced.

        0 is a safe floor rather than a sentinel: raw_source_payloads.id is a
        BIGSERIAL starting at 1, so "everything newer than 0" is exactly
        "everything".
        """
        with self.database.cursor() as cursor:
            cursor.execute(
                """
                SELECT watermark_value FROM source_watermarks
                WHERE source = %s AND object_type = %s AND scope_key = %s
                """,
                (source, object_type, scope_key),
            )
            row = cursor.fetchone()

        if row is None or row[0] is None:
            return 0
        return int(row[0])

    def advance(self, source: str, object_type: str, scope_key: str, watermark_id: int | None) -> None:
        """Move a watermark forward and stamp the scope as synced now.

        Never moves a watermark backwards: GREATEST keeps the stored value if it
        is already higher, so a replayed or out-of-order run cannot cause
        already-processed payloads to be reprocessed forever. Passing None
        records the sync attempt (last_synced_at) without changing the position,
        which is the correct outcome for a run that found nothing new.
        """
        with self.database.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO source_watermarks (
                    source, object_type, scope_key, watermark_value, last_synced_at, last_updated
                ) VALUES (%s, %s, %s, %s, NOW(), NOW())
                ON CONFLICT (source, object_type, scope_key) DO UPDATE SET
                    watermark_value = GREATEST(
                        source_watermarks.watermark_value::bigint,
                        EXCLUDED.watermark_value::bigint
                    )::text,
                    last_synced_at = NOW(),
                    last_updated = NOW()
                """,
                (source, object_type, scope_key, None if watermark_id is None else str(watermark_id)),
            )


@dataclass
class SyncResult:
    """Outcome of one end-to-end event sync."""

    run_id: int
    event_key: str
    landed: dict[str, int] = field(default_factory=dict)
    loaded: dict[str, int] = field(default_factory=dict)
    watermarks: dict[str, int | None] = field(default_factory=dict)
    skipped: list[SkippedRecord] = field(default_factory=list)
    extraction_errors: list[str] = field(default_factory=list)
    issues: list[QualityIssue] = field(default_factory=list)
    lineage_recorded: int = 0

    @property
    def records_loaded(self) -> int:
        """Total canonical records written across every entity type."""
        return sum(self.loaded.values())

    @property
    def fatal_issues(self) -> list[QualityIssue]:
        """Issues severe enough to have kept their record out of the canonical tables."""
        return [issue for issue in self.issues if issue.is_fatal]


@contextmanager
def _event_sync_lock(database: Database, event_key: str):
    """Serialize sync_event calls for the same event_key.

    Found by direct reproduction, not speculation: two concurrent syncs of the
    same event with overlapping-but-different match rosters (e.g. TBA corrects
    a schedule mid-event while a previous poll is still finishing) do not
    silently corrupt match_teams -- Postgres's own row lock on the
    (match_key, team_number) unique key prevents that -- but they can block
    each other indefinitely on those row locks, and forcing the two
    transactions' insert/delete steps to interleave (rather than relying on
    thread-scheduling luck) reproduced exactly that hang. A genuine lock-order
    cycle between two such runs would surface as a Postgres deadlock error
    that aborts the whole run instead of just waiting.

    A session-scoped advisory lock -- held on one dedicated connection for the
    entire sync_event call, not just one of its internal transactions -- makes
    two overlapping syncs of the same event queue cleanly one after the other
    instead of fighting over row locks. This matters specifically because
    "real-time updates must sync during an event as matches are played" is a
    stated goal: a live-sync scheduler firing before the previous poll of the
    same event finished is exactly the scenario this closes off.
    """
    lock_key = json.dumps(["sync_event", event_key])
    with database.connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute("SELECT pg_advisory_lock(hashtextextended(%s, 0))", (lock_key,))
        try:
            yield
        finally:
            with conn.cursor() as cursor:
                cursor.execute("SELECT pg_advisory_unlock(hashtextextended(%s, 0))", (lock_key,))


def sync_event(
    event_key: str,
    *,
    database: Database,
    tba: TBAClient | None,
    statbotics: StatboticsClient | None = None,
    repository: CanonicalRepository | None = None,
    writer: RawPayloadWriter | None = None,
    recorder: PipelineRunRecorder | None = None,
    watermarks: WatermarkStore | None = None,
    quality: DataQualityRecorder | None = None,
    lineage: LineageStore | None = None,
    pipeline_name: str = DEFAULT_PIPELINE_NAME,
    extraction: ExtractionResult | None = None,
) -> SyncResult:
    """Run extraction -> landing -> staging -> serving for one event, end to end.

    Records the run in pipeline_runs and advances source_watermarks only once
    the serving stage has succeeded, so re-running this for an unchanged event
    performs no redundant work and creates no duplicate canonical rows.

    On failure the run row is closed as 'failed' with the error message, every
    watermark is left where it was, and the exception is re-raised -- a caller
    (scheduler, CLI, future live-sync loop) must be able to see that a sync
    failed, not infer it from a returned status. Records already loaded before
    the failure stay in place and are safely re-upserted next run.

    The collaborator arguments exist so the flow can be driven with test
    doubles; each defaults to the real implementation over `database`.

    `extraction`, when given, replaces the TBA extraction step: the prebuilt
    batches (e.g. a Statbotics-only snapshot, scripts/sync_statbotics_snapshot.py)
    go through exactly the same landing, staging, quality, loading, lineage and
    watermark steps, and TBA is not contacted. The run is recorded with the
    source of those batches.
    """
    if extraction is None and tba is None:
        raise ValueError("sync_event needs a TBA client unless a prebuilt extraction is given")
    writer = writer or RawPayloadWriter(database)
    repository = repository or CanonicalRepository(database)
    recorder = recorder or PipelineRunRecorder(database)
    watermarks = watermarks or WatermarkStore(database)
    quality = quality or DataQualityRecorder(database)
    lineage = lineage or LineageStore(database)

    with _event_sync_lock(database, event_key):
        run_source = (extraction.batches[0].source if extraction is not None and extraction.batches
                      else pipeline.SOURCE_TBA)
        run_id = recorder.start(pipeline_name, source=run_source, scope_key=event_key)
        logger.info("Pipeline run %d started: %s for event %s", run_id, pipeline_name, event_key)

        try:
            if extraction is None:
                assert tba is not None
                extraction = pipeline.extract_event(event_key, tba=tba, statbotics=statbotics)
            landed = pipeline.land(writer, extraction.batches)

            # Referential facts for the quality checks: what will exist canonically
            # once this run loads, which is everything extracted now plus everything
            # an earlier run already persisted.
            context = build_quality_context(database, extraction)

            staged_batches: list[StagedBatch] = []
            for batch in extraction.batches:
                after_raw_id = watermarks.get(batch.source, batch.object_type, event_key)
                pending = pipeline.read_pending(
                    database, batch.source, batch.object_type, batch.object_ids, after_raw_id,
                )
                staged_batches.append(pipeline.stage_batch(
                    batch.source, batch.object_type, pending, after_raw_id, context=context,
                ))

            issues = issues_from_extraction_errors(extraction.errors, event_key=event_key)
            issues += [issue for batch in staged_batches for issue in batch.issues]
            # Recorded before the load, so the findings survive even if loading then
            # fails -- a failed run's quality evidence is exactly when it is wanted.
            quality.record(issues, run_id)

            loaded = pipeline.load(repository, staged_batches)

            # Lineage asserts that a canonical row exists and came from this
            # payload, so it is only true once the load has succeeded.
            lineage_recorded = lineage.record(
                [entry for batch in staged_batches for entry in batch.lineage], run_id,
            )

            # Single advance point, reached only once every stage above succeeded.
            # Named `staged`, not `batch` like the ExtractionBatch loop above it in
            # this same function: same variable name, two different types across
            # two sequential loops in one scope is legal Python but reads as
            # ambiguous and defeats a type checker's ability to narrow either one.
            for staged in staged_batches:
                watermarks.advance(staged.source, staged.object_type, event_key, staged.watermark_id)

            result = SyncResult(
                run_id=run_id,
                event_key=event_key,
                landed=landed,
                loaded=loaded,
                watermarks={f"{b.source}.{b.object_type}": b.watermark_id for b in staged_batches},
                skipped=[record for batch in staged_batches for record in batch.skipped],
                extraction_errors=extraction.errors,
                issues=issues,
                lineage_recorded=lineage_recorded,
            )
            recorder.succeed(
                run_id,
                records_processed=result.records_loaded,
                stage_counts=_stage_counts(result),
            )
            logger.info(
                "Pipeline run %d succeeded: %d canonical record(s), %d skipped, "
                "%d quality issue(s) (%d fatal), %d extraction error(s)",
                run_id, result.records_loaded, len(result.skipped),
                len(result.issues), len(result.fatal_issues), len(result.extraction_errors),
            )
            return result
        except Exception as exc:
            recorder.fail(run_id, f"{type(exc).__name__}: {exc}")
            logger.error("Pipeline run %d failed for event %s: %s", run_id, event_key, exc)
            raise


def _stage_counts(result: SyncResult) -> dict[str, Any]:
    """Build the per-stage breakdown stored in pipeline_runs.stage_counts."""
    return {
        "landed": result.landed,
        "loaded": result.loaded,
        "watermarks": {key: value for key, value in result.watermarks.items()},
        "skipped": [
            {"raw_id": record.raw_id, "object_id": record.source_object_id, "reason": record.reason}
            for record in result.skipped
        ],
        "extraction_errors": result.extraction_errors,
        "quality_issues": summarize(result.issues),
        "lineage_recorded": result.lineage_recorded,
    }


# ---------------------------------------------------------------------------
# Season sync
# ---------------------------------------------------------------------------


@dataclass
class SeasonResult:
    """Outcome of syncing a whole season, event by event.

    Holds the successful `SyncResult`s and, separately, the events that raised.
    A season sync deliberately does not fail as a whole when one event does:
    with ~190 events, one unavailable event must not discard the other 189.
    """

    year: int
    event_keys: list[str] = field(default_factory=list)
    results: list[SyncResult] = field(default_factory=list)
    failures: list[tuple[str, str]] = field(default_factory=list)
    statbotics_skipped_reason: str | None = None
    elapsed_seconds: float = 0.0

    @property
    def events_succeeded(self) -> int:
        return len(self.results)

    @property
    def events_failed(self) -> int:
        return len(self.failures)

    @property
    def landed(self) -> dict[str, int]:
        """New raw payload rows per "source.object_type", summed over every event."""
        return _sum_counts(result.landed for result in self.results)

    @property
    def loaded(self) -> dict[str, int]:
        """Canonical rows written per entity type, summed over every event."""
        return _sum_counts(result.loaded for result in self.results)

    @property
    def issues(self) -> list[QualityIssue]:
        return [issue for result in self.results for issue in result.issues]

    @property
    def skipped(self) -> list[SkippedRecord]:
        return [record for result in self.results for record in result.skipped]

    @property
    def extraction_errors(self) -> list[str]:
        return [error for result in self.results for error in result.extraction_errors]

    @property
    def records_loaded(self) -> int:
        return sum(result.records_loaded for result in self.results)


def _sum_counts(dicts: Iterable[dict[str, int]]) -> dict[str, int]:
    totals: dict[str, int] = {}
    for counts in dicts:
        for key, value in counts.items():
            totals[key] = totals.get(key, 0) + value
    return totals


def official_event_keys(tba: TBAClient, year: int) -> list[str]:
    """Return every official event key for a season, in chronological order.

    Filters on the raw response body rather than the parsed model: `event_type`
    is not a field on `EventSummary`, but it is present on every event payload
    TBA sends, and since connectors hand back the untouched body there is no
    need to widen the model just to read it.

    Chronological order matters for more than tidiness. Championship divisions
    must load before the Championship Finals, whose roster is drawn from them,
    and district championships after their districts -- ordering by start_date
    puts every event after the ones it depends on.
    """
    responses = tba.fetch_event_list(year)
    official = [
        response for response in responses
        if isinstance(response.raw, dict) and response.raw.get("event_type") in OFFICIAL_EVENT_TYPES
    ]
    official.sort(key=lambda response: (response.raw.get("start_date") or "", response.parsed.key))
    logger.info(
        "Season %d: %d official event(s) of %d total", year, len(official), len(responses),
    )
    return [response.parsed.key for response in official]


def statbotics_probe_failure(
    statbotics: StatboticsClient, tba: TBAClient, event_key: str
) -> str | None:
    """Check that Statbotics answers at all; return None if it does, else why not.

    Statbotics is a *supplementary* source: it enriches team_event_stats and
    nothing else depends on it. Extraction requests it once per team per event,
    so across a season that is thousands of calls -- and when the service is
    down, every one of them burns the client's full retry ladder before failing.
    Measured against a real outage that is ~1.7s each, which turns a 20-minute
    season sync into a 4-hour one that produces no rows and floods
    data_quality_issues with thousands of identical extraction failures.

    So a season sync probes once and, on failure, skips Statbotics for the whole
    run. This is deliberately a *probe*, not a health endpoint: it calls the
    exact endpoint extraction uses, with a real team from a real event, so a
    pass means the thing we are about to do thousands of times actually works.
    """
    try:
        teams = tba.fetch_event_teams(event_key)
    except Exception as exc:
        return f"could not read a probe team from {event_key}: {type(exc).__name__}: {exc}"

    team_numbers = [
        response.parsed.team_number for response in teams if response.parsed.team_number is not None
    ]
    if not team_numbers:
        return f"{event_key} lists no teams, so Statbotics could not be probed"

    probe_team = team_numbers[0]
    try:
        statbotics.fetch_team_event_metrics(probe_team, event_key)
    except Exception as exc:
        return f"probe for team {probe_team} at {event_key} failed: {type(exc).__name__}: {exc}"
    return None


def sync_season(
    year: int,
    *,
    database: Database,
    tba: TBAClient,
    statbotics: StatboticsClient | None = None,
    event_keys: Sequence[str] | None = None,
    delay_seconds: float = DEFAULT_EVENT_DELAY_SECONDS,
    pipeline_name: str = DEFAULT_PIPELINE_NAME,
) -> SeasonResult:
    """Sync every official event of a season, one at a time, in chronological order.

    A thin wrapper over `sync_event`: it enumerates the season, decides once
    whether Statbotics is usable, and owns the policy that one failing event
    must not abort the rest. Each event remains an independent sync with its own
    pipeline_runs row and its own watermarks -- watermarks are scoped per
    (source, object_type, event), so no event's progress can be advanced by
    another's, and re-running a season is a no-op event by event exactly as
    re-running a single event is.

    `event_keys` overrides enumeration, for syncing a chosen subset in season
    order without hitting the event-list endpoint.

    Failures are collected, not raised. `sync_event` has already recorded the
    failed run in pipeline_runs by the time it re-raises, so continuing here
    loses no audit trail -- it just declines to let one event end the season.
    """
    started = time.monotonic()
    keys = list(event_keys) if event_keys is not None else official_event_keys(tba, year)
    season = SeasonResult(year=year, event_keys=keys)

    if statbotics is not None and keys:
        reason = statbotics_probe_failure(statbotics, tba, keys[0])
        if reason is not None:
            season.statbotics_skipped_reason = reason
            statbotics = None
            logger.warning(
                "Statbotics unavailable, skipping it for the whole season: %s. "
                "team_event_stats will not be populated by this run.", reason,
            )

    # Shared collaborators, built once rather than per event. Each is a thin
    # dataclass over `database`, so this is tidiness rather than a real cost.
    collaborators: dict[str, Any] = {
        "writer": RawPayloadWriter(database),
        "repository": CanonicalRepository(database),
        "recorder": PipelineRunRecorder(database),
        "watermarks": WatermarkStore(database),
        "quality": DataQualityRecorder(database),
        "lineage": LineageStore(database),
    }

    for index, event_key in enumerate(keys, start=1):
        if index > 1 and delay_seconds > 0:
            time.sleep(delay_seconds)
        try:
            result = sync_event(
                event_key,
                database=database,
                tba=tba,
                statbotics=statbotics,
                pipeline_name=pipeline_name,
                **collaborators,
            )
        except Exception as exc:
            season.failures.append((event_key, f"{type(exc).__name__}: {exc}"))
            logger.error("[%d/%d] %s FAILED: %s", index, len(keys), event_key, exc)
            continue

        season.results.append(result)
        logger.info(
            "[%d/%d] %s: landed=%s loaded=%s skipped=%d issues=%d (fatal=%d)",
            index, len(keys), event_key, result.landed, result.loaded,
            len(result.skipped), len(result.issues), len(result.fatal_issues),
        )

    season.elapsed_seconds = time.monotonic() - started
    logger.info(
        "Season %d complete in %.1fs: %d event(s) succeeded, %d failed, %d canonical record(s)",
        year, season.elapsed_seconds, season.events_succeeded, season.events_failed,
        season.records_loaded,
    )
    return season


# ---------------------------------------------------------------------------
# Live event watch
# ---------------------------------------------------------------------------

# One poll costs exactly three TBA requests (event, matches, teams), so 120s is
# ~90 requests/hour. FRC qualification cycles run roughly 7-8 minutes, which
# makes this 3-4 polls per match -- responsive without being noisy. TBA
# publishes no rate limit and returns no X-RateLimit headers, so the budget here
# is politeness rather than a documented ceiling.
DEFAULT_WATCH_INTERVAL_SECONDS = 120.0
DEFAULT_WATCH_MAX_INTERVAL_SECONDS = 600.0

# Statbotics is one request *per team*, so a 40-team regional costs ~40 requests
# per poll -- 1,200/hour at the TBA cadence. It therefore runs on its own much
# slower clock (~80 requests/hour), and every poll in between is TBA-only.
DEFAULT_STATBOTICS_INTERVAL_SECONDS = 1800.0

# Back off only after several consecutive idle polls, not the first one. A
# 7-minute match cycle produces 2-3 no-op polls during perfectly normal play,
# and backing off immediately would slow detection exactly when the event is
# live. Overnight the interval still walks up to the maximum.
DEFAULT_IDLE_POLLS_BEFORE_BACKOFF = 3
WATCH_BACKOFF_FACTOR = 1.5

# Extra polls after the event first looks complete, to catch the score
# corrections TBA posts in the minutes after finals.
DEFAULT_SETTLE_POLLS = 2

# Consecutive failures tolerated before the watch gives up. Venue wifi drops and
# TBA blips must not end a watch, but a mistyped event key 404s forever, and
# with backoff this is over an hour of continuous failure before exiting.
DEFAULT_MAX_FAILURES = 20

# `events.end_date` is a *local* calendar date, so a venue west of UTC is still
# playing finals when UTC has already rolled over -- 7pm Saturday in Houston is
# Sunday 00:00 UTC. One day of grace covers every FRC timezone.
DEFAULT_CALENDAR_GRACE_DAYS = 1

# The wait between polls is slept in slices this long, so a Ctrl-C is noticed
# within about a second instead of at the end of a 10-minute interval.
_WATCH_SLEEP_SLICE_SECONDS = 1.0

_DURATION_UNITS = {"s": 1.0, "m": 60.0, "h": 3600.0, "d": 86400.0}
_DURATION_PATTERN = re.compile(r"^(\d+(?:\.\d+)?)\s*([smhd]?)$", re.IGNORECASE)


@dataclass(frozen=True)
class EventProgress:
    """How far along one event is, read from the canonical tables.

    Every field comes from data the poll that just ran has already loaded, so
    determining whether an event is over costs no extra API requests.
    """

    event_key: str
    end_date: date | None
    matches_total: int
    matches_played: int
    finals_total: int
    finals_played: int

    @property
    def finals_complete(self) -> bool:
        """True once a finals bracket exists and none of it is still unplayed."""
        return self.finals_total > 0 and self.finals_played == self.finals_total

    @property
    def matches_unplayed(self) -> int:
        return self.matches_total - self.matches_played


def event_progress(database: Database, event_key: str) -> EventProgress | None:
    """Summarize an event's canonical state, or None if it has not been loaded yet.

    Read-only, one query, and deliberately expressed against the canonical
    columns rather than the raw payloads: `score_red IS NULL` is the documented
    reliable test for "not played yet" (the normalizer has already resolved
    TBA's -1 sentinel), so this asks the question in the vocabulary the rest of
    the project uses.
    """
    with database.cursor() as cursor:
        cursor.execute(
            """
            SELECT e.end_date,
                   count(m.match_key),
                   count(m.match_key) FILTER (WHERE m.score_red IS NOT NULL),
                   count(m.match_key) FILTER (WHERE m.competition_level = 'final'),
                   count(m.match_key) FILTER (
                       WHERE m.competition_level = 'final' AND m.score_red IS NOT NULL
                   )
            FROM events e
            LEFT JOIN matches m ON m.event_key = e.event_key
            WHERE e.event_key = %s
            GROUP BY e.end_date
            """,
            (event_key,),
        )
        row = cursor.fetchone()

    if row is None:
        return None
    return EventProgress(
        event_key=event_key,
        end_date=row[0],
        matches_total=int(row[1]),
        matches_played=int(row[2]),
        finals_total=int(row[3]),
        finals_played=int(row[4]),
    )


def completion_reason(
    progress: EventProgress | None,
    *,
    today: date,
    calendar_grace_days: int = DEFAULT_CALENDAR_GRACE_DAYS,
) -> str | None:
    """Return why the event is over, or None if it is still running.

    The primary signal is the finals bracket: an event is done when a finals
    match exists and none is still unplayed. Checked against the full 2024
    season, all 190 official events have a played final and *none* has an
    unplayed one, so the signal is neither premature (it waits out a
    double-elimination f1m2/f1m3) nor unreachable (an unneeded f1m3 is not
    published in advance).

    The obvious alternative -- "every scheduled match has a result" -- was
    rejected on the same evidence. Two of those 190 finished events
    (`2024gagwi`, `2024mdsev`) permanently hold unplayed matches, because TBA's
    -1/frc0 sentinel rows load with NULL scores and TBA never reissues a
    finished event's schedule. A watch keyed on that condition would never stop
    for them. It also false-positives mid-event, in the gap between the last
    qualification match and the playoff bracket being published.

    The calendar is the fallback, for an event that never produces finals at all
    (cancelled, abandoned, or an offseason format). See
    DEFAULT_CALENDAR_GRACE_DAYS for why the grace cannot be zero.
    """
    if progress is None:
        return None

    if progress.finals_complete:
        return (
            f"finals complete - {progress.matches_played}/{progress.matches_total} matches, "
            f"{progress.finals_played}/{progress.finals_total} finals played"
        )

    if progress.end_date is not None:
        expiry = progress.end_date + timedelta(days=calendar_grace_days)
        if today > expiry:
            return (
                f"event ended {progress.end_date.isoformat()} and no finals were published "
                f"({calendar_grace_days}-day grace expired {expiry.isoformat()})"
            )

    return None


@dataclass
class WatchResult:
    """Outcome of one live-event watch, aggregated over every poll.

    Holds running totals rather than each poll's `SyncResult`: a watch runs for
    days at a two-minute cadence, so retaining every result (and every quality
    issue inside it) would grow without bound to duplicate what `pipeline_runs`
    already records durably, one row per poll.
    """

    event_key: str
    polls: int = 0
    successes: int = 0
    failures: int = 0
    landed: dict[str, int] = field(default_factory=dict)
    loaded: dict[str, int] = field(default_factory=dict)
    matches_newly_played: int = 0
    progress: EventProgress | None = None
    stop_reason: str = ""
    last_error: str | None = None
    statbotics_skipped_reason: str | None = None
    statbotics_polls: int = 0
    interrupted: bool = False
    stopped_on_failures: bool = False
    elapsed_seconds: float = 0.0

    @property
    def records_loaded(self) -> int:
        """Total canonical records written across every poll."""
        return sum(self.loaded.values())


def _utc_today() -> date:
    return datetime.now(timezone.utc).date()


@contextmanager
def _graceful_stop():
    """Install SIGINT/SIGTERM handlers that request a stop instead of aborting.

    Yields a one-key dict the loop polls. The first signal asks the watch to
    stop at the next safe point; the handler then restores the previous
    disposition, so a second Ctrl-C aborts immediately the way an impatient
    operator expects.

    Interrupting between polls is always safe: `sync_event` is transactional,
    advances watermarks at exactly one point after serving succeeds, and holds
    its advisory lock for the whole call, so there is no half-written state to
    leave behind. A poll already in flight is therefore allowed to finish rather
    than being torn down mid-run.

    Handlers are restored on the way out, so importing and calling `watch_event`
    from a larger program does not permanently change that program's signal
    handling. Signal handlers can only be installed on the main thread; off it,
    this degrades to a no-op rather than failing the watch.
    """
    state = {"stop": False}
    previous: dict[int, Any] = {}

    def handle(signum: int, frame: Any) -> None:
        state["stop"] = True
        logger.warning(
            "Signal %s received: finishing the current poll, then stopping. "
            "Send it again to abort immediately.",
            signal.Signals(signum).name,
        )
        if signum in previous:
            signal.signal(signum, previous[signum])

    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            previous[sig] = signal.signal(sig, handle)
        except (ValueError, OSError):  # not the main thread, or unsupported
            logger.debug("Could not install a handler for %s; skipping", sig)

    try:
        yield state
    finally:
        for sig, handler in previous.items():
            try:
                signal.signal(sig, handler)
            except (ValueError, OSError):
                pass


def _wait_between_polls(
    seconds: float,
    *,
    sleep: Callable[[float], None],
    clock: Callable[[], float],
    interrupt: dict[str, bool],
) -> bool:
    """Sleep for `seconds`, in slices, returning False if a stop was requested.

    Slicing is what makes Ctrl-C feel immediate: the wait between polls can be
    ten minutes, and an operator packing up at the end of an event should not
    have to wait it out.
    """
    deadline = clock() + seconds
    while not interrupt["stop"]:
        remaining = deadline - clock()
        if remaining <= 0:
            return True
        sleep(min(remaining, _WATCH_SLEEP_SLICE_SECONDS))
    return False


def watch_event(
    event_key: str,
    *,
    database: Database,
    tba: TBAClient,
    statbotics: StatboticsClient | None = None,
    interval_seconds: float = DEFAULT_WATCH_INTERVAL_SECONDS,
    max_interval_seconds: float = DEFAULT_WATCH_MAX_INTERVAL_SECONDS,
    statbotics_interval_seconds: float = DEFAULT_STATBOTICS_INTERVAL_SECONDS,
    idle_polls_before_backoff: int = DEFAULT_IDLE_POLLS_BEFORE_BACKOFF,
    settle_polls: int = DEFAULT_SETTLE_POLLS,
    max_failures: int = DEFAULT_MAX_FAILURES,
    max_duration_seconds: float | None = None,
    calendar_grace_days: int = DEFAULT_CALENDAR_GRACE_DAYS,
    pipeline_name: str = DEFAULT_PIPELINE_NAME,
    sync: Callable[..., SyncResult] = sync_event,
    progress: Callable[[Database, str], EventProgress | None] = event_progress,
    sleep: Callable[[float], None] = time.sleep,
    clock: Callable[[], float] = time.monotonic,
    today: Callable[[], date] = _utc_today,
    after_sync: Callable[[Database, str, SyncResult], None] | None = None,
) -> WatchResult:
    """Keep one event's data fresh by re-running `sync_event` until the event ends.

    This is the automated half of "real-time updates must sync during an event
    as matches are played": start it once when the event opens and it needs no
    further triggering.

    A thin wrapper, exactly like `sync_season`. It reimplements no sync logic --
    every poll is an ordinary `sync_event` call with ordinary semantics (its own
    `pipeline_runs` row, its own watermarks, its own advisory lock) -- and owns
    only four policies of its own:

    * **Cadence.** Poll every `interval_seconds`. An unchanged poll is already a
      near no-op by construction: the landing layer discards identical payloads,
      so nothing sits above the watermark and the staging and serving stages do
      no work at all. Only the three HTTP fetches actually cost anything. After
      `idle_polls_before_backoff` consecutive polls that land nothing, the
      interval grows by `WATCH_BACKOFF_FACTOR` up to `max_interval_seconds`, and
      snaps back the moment anything lands.
    * **Statbotics on its own clock**, because it costs one request per team
      rather than three per event. It is probed once up front and circuit-broken
      for the whole watch if it is down -- the same reasoning, and the same
      helper, `sync_season` uses: 40 failing lookups per poll, each burning the
      client's full retry ladder, would turn a two-minute cadence into minutes
      of nothing but timeouts.
    * **Failure isolation.** TBA being briefly unreachable mid-event is normal
      at a venue. A failed poll is logged, counted, and followed by a backed-off
      retry; `sync_event` has already recorded the failed run and its quality
      evidence by the time it re-raises, so nothing is lost by carrying on. Only
      `max_failures` *consecutive* failures end the watch, and that exit is
      reported as a failure so a mistyped event key does not loop forever.
    * **Knowing when to stop.** See `completion_reason`. After completion is
      first seen the watch keeps polling `settle_polls` more times, then exits.

    `sync`, `progress`, `sleep`, `clock`, and `today` are injection points for
    tests, each defaulting to the real implementation; nothing else in the
    project passes them.

    `after_sync` (Phase 5, P5-M6) runs after every successful poll. The CLI
    passes `after_watch_sync`, which recomputes `team_metrics` whenever a poll
    loaded canonical rows (closing CLAUDE.md constraint 5's gap) and, when the
    live EPA source is configured, runs its refresh cycle. A follow-on failure
    is logged and counted like a failed poll; it never stops the data sync.
    """
    started = clock()
    result = WatchResult(event_key=event_key)

    if statbotics is not None:
        reason = statbotics_probe_failure(statbotics, tba, event_key)
        if reason is not None:
            result.statbotics_skipped_reason = reason
            statbotics = None
            logger.warning(
                "Statbotics unavailable, skipping it for this whole watch: %s. "
                "team_event_stats will not be updated; re-run a plain sync afterwards.", reason,
            )

    # Built once and shared by every poll, as in sync_season.
    collaborators: dict[str, Any] = {
        "writer": RawPayloadWriter(database),
        "repository": CanonicalRepository(database),
        "recorder": PipelineRunRecorder(database),
        "watermarks": WatermarkStore(database),
        "quality": DataQualityRecorder(database),
        "lineage": LineageStore(database),
    }

    logger.info(
        "Watching %s: polling every %.0fs (idle backoff to %.0fs), statbotics every %s",
        event_key, interval_seconds, max_interval_seconds,
        f"{statbotics_interval_seconds:.0f}s" if statbotics is not None else "never",
    )

    wait_seconds = interval_seconds
    idle_polls = 0
    consecutive_failures = 0
    settling: int | None = None
    last_played: int | None = None
    statbotics_due_at = started

    with _graceful_stop() as interrupt:
        while True:
            if interrupt["stop"]:
                result.stop_reason = "interrupted"
                result.interrupted = True
                break

            elapsed = clock() - started
            if max_duration_seconds is not None and elapsed >= max_duration_seconds:
                result.stop_reason = f"max duration reached ({max_duration_seconds:.0f}s)"
                break

            result.polls += 1
            use_statbotics = statbotics is not None and clock() >= statbotics_due_at
            if use_statbotics:
                statbotics_due_at = clock() + statbotics_interval_seconds
                result.statbotics_polls += 1

            try:
                sync_result = sync(
                    event_key,
                    database=database,
                    tba=tba,
                    statbotics=statbotics if use_statbotics else None,
                    pipeline_name=pipeline_name,
                    **collaborators,
                )
            except Exception as exc:
                consecutive_failures += 1
                result.failures += 1
                result.last_error = f"{type(exc).__name__}: {exc}"
                logger.error(
                    "poll %d FAILED (%d/%d consecutive): %s",
                    result.polls, consecutive_failures, max_failures, result.last_error,
                )
                if consecutive_failures >= max_failures:
                    result.stop_reason = (
                        f"{consecutive_failures} consecutive failures, last: {result.last_error}"
                    )
                    result.stopped_on_failures = True
                    break
                wait_seconds = min(wait_seconds * WATCH_BACKOFF_FACTOR, max_interval_seconds)
                logger.info("Retrying %s in %.0fs", event_key, wait_seconds)
                if not _wait_between_polls(
                    wait_seconds, sleep=sleep, clock=clock, interrupt=interrupt,
                ):
                    result.stop_reason = "interrupted"
                    result.interrupted = True
                    break
                continue

            consecutive_failures = 0
            result.successes += 1
            if after_sync is not None:
                try:
                    after_sync(database, event_key, sync_result)
                except Exception as exc:  # the data is synced; the follow-on is retried next poll
                    result.failures += 1
                    result.last_error = f"after_sync {type(exc).__name__}: {exc}"
                    logger.error("poll %d follow-on FAILED: %s", result.polls, result.last_error)
            result.landed = _sum_counts([result.landed, sync_result.landed])
            result.loaded = _sum_counts([result.loaded, sync_result.loaded])
            landed_now = sum(sync_result.landed.values())

            current = progress(database, event_key)
            result.progress = current
            newly_played = 0
            if current is not None:
                if last_played is not None:
                    newly_played = max(current.matches_played - last_played, 0)
                    result.matches_newly_played += newly_played
                last_played = current.matches_played

            if landed_now:
                idle_polls = 0
                wait_seconds = interval_seconds
            else:
                idle_polls += 1
                if idle_polls >= idle_polls_before_backoff:
                    wait_seconds = min(wait_seconds * WATCH_BACKOFF_FACTOR, max_interval_seconds)

            logger.info(
                "poll %d: %s | %s | next in %.0fs",
                result.polls,
                f"landed={sync_result.landed} loaded={sync_result.loaded}" if landed_now
                else "nothing new",
                _progress_line(current, newly_played),
                wait_seconds,
            )

            reason = completion_reason(
                current, today=today(), calendar_grace_days=calendar_grace_days,
            )
            if reason is None:
                # A new finals match appearing (or a score being retracted) puts
                # the event back in progress; the settle countdown restarts.
                settling = None
            else:
                if settling is None:
                    settling = settle_polls
                    logger.info(
                        "Event %s looks complete (%s); %d settle poll(s) before stopping",
                        event_key, reason, settle_polls,
                    )
                if settling <= 0:
                    result.stop_reason = reason
                    break
                settling -= 1

            if not _wait_between_polls(
                wait_seconds, sleep=sleep, clock=clock, interrupt=interrupt,
            ):
                result.stop_reason = "interrupted"
                result.interrupted = True
                break

    result.elapsed_seconds = clock() - started
    logger.info(
        "Watch of %s stopped after %d poll(s) in %.1fs: %s",
        event_key, result.polls, result.elapsed_seconds, result.stop_reason,
    )
    return result


def after_watch_sync(database: Database, event_key: str, result: SyncResult, *,
                     settings: Settings | None = None) -> None:
    """The watch follow-on (P5-M6): keep team_metrics and, if configured, the live EPA log current.

    * team_metrics is recomputed for the event whenever the poll loaded canonical rows, so the metrics
      the API serves move during a watch (CLAUDE.md constraint 5). An unchanged poll loads nothing and
      recomputes nothing.
    * When EPA_SOURCE is the P5-M2 live source (not the evaluated configuration; adoption is P5-D3) and
      LIVE_EPA_LOG_DIR is set, one refresh cycle runs over the events due under LIVE_EPA_REFRESH_DESIGN.md
      section 1. This is the "--watch detects due events" trigger.
    """
    if result.records_loaded:
        from data.metrics.compute import compute_event_team_metrics  # deferred: circular import (see main)

        compute_event_team_metrics(event_key, database=database)
    settings = settings or Settings()
    if settings.epa_source == "p5_live_statbotics" and settings.live_epa_log_dir and settings.statbotics_snapshot_dir:
        from ml.ratings.live_snapshots import SnapshotLog
        from ml.ratings.live_source import LiveEpaRefresher

        log = SnapshotLog(Path(settings.live_epa_log_dir), Path(settings.statbotics_snapshot_dir))
        refresher = LiveEpaRefresher(log, database, StatboticsClient(settings=settings))
        due = refresher.due_events(datetime.now(timezone.utc))
        if due:
            refresher.refresh(due)


def _progress_line(progress: EventProgress | None, newly_played: int) -> str:
    """Render the human-facing 'how far along is this event' half of a poll log."""
    if progress is None:
        return "event not loaded yet"
    line = f"matches {progress.matches_played}/{progress.matches_total} played"
    if newly_played:
        line += f" (+{newly_played} new)"
    if progress.finals_total:
        line += f", finals {progress.finals_played}/{progress.finals_total}"
    return line


def parse_duration(value: str) -> float:
    """Parse a duration such as '90', '30m', '8h', or '2d' into seconds.

    A bare number is seconds. Units exist because the one duration this CLI
    takes is a multi-hour runaway guard, where '8' meaning eight seconds would
    be a silent foot-gun.
    """
    match = _DURATION_PATTERN.match(value.strip())
    if match is None:
        raise argparse.ArgumentTypeError(
            f"invalid duration {value!r}: use seconds, or a number with s/m/h/d (e.g. 8h)"
        )
    amount, unit = match.groups()
    seconds = float(amount) * _DURATION_UNITS[(unit or "s").lower()]
    if seconds <= 0:
        raise argparse.ArgumentTypeError(f"duration must be positive, got {value!r}")
    return seconds


def main(argv: list[str] | None = None) -> int:
    """Command-line entry point: sync one event, a whole season, or watch a live event.

    The single-event path also recomputes team_metrics for every rostered team
    immediately afterward (data.metrics.compute.compute_event_team_metrics) --
    Phase 3 Milestone 10's follow-on stage. Deliberately not wired into the
    season/watch paths in that milestone (see compute_event_team_metrics's own
    docstring for why).
    """
    parser = argparse.ArgumentParser(
        description="Run the StratAI ingestion pipeline for one event, a whole season, "
                    "or continuously for one live event.",
    )
    parser.add_argument("event_key", nargs="?", help="TBA event key, e.g. 2025casj")
    parser.add_argument(
        "--season", type=int, metavar="YEAR",
        help="Sync every official event of a season in chronological order, e.g. --season 2024. "
             "Offseason and preseason events are excluded.",
    )
    parser.add_argument(
        "--no-statbotics", action="store_true",
        help="Skip Statbotics EPA metrics (TBA data only).",
    )
    parser.add_argument(
        "--delay", type=float, default=DEFAULT_EVENT_DELAY_SECONDS, metavar="SECONDS",
        help=f"Pause between events in a season sync (default {DEFAULT_EVENT_DELAY_SECONDS}). "
             "Ignored for a single event.",
    )
    parser.add_argument(
        "--watch", metavar="EVENT_KEY",
        help="Keep one event fresh during live play: re-sync it on an interval until the "
             "event is over, e.g. --watch 2025casj. Stops on its own once the finals are "
             "complete; Ctrl-C stops it cleanly at any time.",
    )
    watch_group = parser.add_argument_group("watch options (used with --watch)")
    watch_group.add_argument(
        "--interval", type=float, default=DEFAULT_WATCH_INTERVAL_SECONDS, metavar="SECONDS",
        help=f"Seconds between polls (default {DEFAULT_WATCH_INTERVAL_SECONDS:.0f}).",
    )
    watch_group.add_argument(
        "--max-interval", type=float, default=DEFAULT_WATCH_MAX_INTERVAL_SECONDS, metavar="SECONDS",
        help=f"Ceiling the interval backs off to while nothing is changing "
             f"(default {DEFAULT_WATCH_MAX_INTERVAL_SECONDS:.0f}).",
    )
    watch_group.add_argument(
        "--statbotics-interval", type=float, default=DEFAULT_STATBOTICS_INTERVAL_SECONDS,
        metavar="SECONDS",
        help=f"Seconds between Statbotics refreshes, which cost one request per team "
             f"(default {DEFAULT_STATBOTICS_INTERVAL_SECONDS:.0f}).",
    )
    watch_group.add_argument(
        "--settle-polls", type=int, default=DEFAULT_SETTLE_POLLS, metavar="N",
        help=f"Extra polls after the event first looks complete, to catch post-finals score "
             f"corrections (default {DEFAULT_SETTLE_POLLS}).",
    )
    watch_group.add_argument(
        "--max-failures", type=int, default=DEFAULT_MAX_FAILURES, metavar="N",
        help=f"Consecutive failed polls before giving up (default {DEFAULT_MAX_FAILURES}).",
    )
    watch_group.add_argument(
        "--max-duration", type=parse_duration, default=None, metavar="DURATION",
        help="Optional runaway guard, e.g. 8h or 90m. Off by default: the finals and "
             "calendar stop conditions already end the watch.",
    )
    args = parser.parse_args(argv)

    modes = [args.event_key is not None, args.season is not None, args.watch is not None]
    if sum(modes) != 1:
        parser.error("give exactly one of an event_key, --season YEAR, or --watch EVENT_KEY")

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    settings = Settings()
    database = Database(DatabaseConfig(settings.database_url))

    statbotics = None if args.no_statbotics else StatboticsClient(settings=settings)
    try:
        with TBAClient(settings=settings) as tba:
            if args.season is not None:
                season = sync_season(
                    args.season, database=database, tba=tba, statbotics=statbotics,
                    delay_seconds=args.delay,
                )
                _print_season_summary(season)
                return 0
            if args.watch is not None:
                watch = watch_event(
                    args.watch, database=database, tba=tba, statbotics=statbotics,
                    interval_seconds=args.interval,
                    max_interval_seconds=args.max_interval,
                    statbotics_interval_seconds=args.statbotics_interval,
                    settle_polls=args.settle_polls,
                    max_failures=args.max_failures,
                    max_duration_seconds=args.max_duration,
                    after_sync=after_watch_sync,
                )
                _print_watch_summary(watch)
                # Only a watch that gave up on repeated failures is an error; a
                # completed event and a Ctrl-C are both successful outcomes.
                return 1 if watch.stopped_on_failures else 0
            result = sync_event(args.event_key, database=database, tba=tba, statbotics=statbotics)
    finally:
        if statbotics is not None:
            statbotics.close()

    print(
        f"run {result.run_id}: landed={result.landed} loaded={result.loaded} "
        f"skipped={len(result.skipped)} issues={len(result.issues)} "
        f"(fatal={len(result.fatal_issues)}) lineage={result.lineage_recorded} "
        f"extraction_errors={len(result.extraction_errors)}"
    )

    # Phase 3 Milestone 10's follow-on stage: metrics are recomputed for every
    # team at this event immediately after its own sync, over whatever
    # canonical + scouting data now exists. A deferred import, not a
    # module-level one -- data.metrics.compute reaches back into this same
    # module for PipelineRunRecorder, so importing it at module level here
    # would reintroduce the identical circular import data/metrics/__init__.py's
    # own docstring already documents avoiding (confirmed by triggering it).
    # Deliberately not wired into sync_season/watch_event in this milestone:
    # a full-season backfill recomputing every team of every historical event
    # is a materially larger, unbounded-cost operation nobody has asked for
    # yet, and watch_event's own live poll loop is a bigger, separately-tested
    # state machine that deserves its own deliberate integration, not a
    # same-milestone add-on.
    from data.metrics.compute import compute_event_team_metrics

    metrics_result = compute_event_team_metrics(args.event_key, database=database)
    print(
        f"metrics run {metrics_result.run_id}: teams_computed={metrics_result.teams_computed} "
        f"lineage={metrics_result.lineage_recorded} orphaned_removed={metrics_result.orphaned_removed}"
    )
    return 0


def _print_season_summary(season: SeasonResult) -> None:
    """Print a season sync's totals, including what failed and what was skipped."""
    print(
        f"season {season.year}: {season.events_succeeded}/{len(season.event_keys)} event(s) "
        f"succeeded in {season.elapsed_seconds:.1f}s"
    )
    print(f"  landed={season.landed}")
    print(f"  loaded={season.loaded}  (total {season.records_loaded})")
    print(f"  skipped={len(season.skipped)}  extraction_errors={len(season.extraction_errors)}")
    print(f"  quality_issues={summarize(season.issues)}")
    if season.statbotics_skipped_reason:
        print(f"  statbotics SKIPPED for the whole season: {season.statbotics_skipped_reason}")
    if season.failures:
        print(f"  {len(season.failures)} event(s) FAILED:")
        for event_key, error in season.failures:
            print(f"    {event_key}: {error}")


def _print_watch_summary(watch: WatchResult) -> None:
    """Print a watch's totals and why it stopped."""
    print(
        f"watch {watch.event_key}: {watch.polls} poll(s) in {watch.elapsed_seconds:.1f}s "
        f"({watch.successes} ok, {watch.failures} failed)"
    )
    print(f"  landed={watch.landed}")
    print(f"  loaded={watch.loaded}  (total {watch.records_loaded})")
    if watch.progress is not None:
        print(
            f"  matches={watch.progress.matches_played}/{watch.progress.matches_total} played "
            f"(+{watch.matches_newly_played} while watching), "
            f"finals={watch.progress.finals_played}/{watch.progress.finals_total}"
        )
    if watch.statbotics_skipped_reason:
        print(f"  statbotics SKIPPED for the whole watch: {watch.statbotics_skipped_reason}")
    elif watch.statbotics_polls:
        print(f"  statbotics refreshed on {watch.statbotics_polls} of {watch.polls} poll(s)")
    print(f"  stopped: {watch.stop_reason}")
    if watch.last_error and not watch.stopped_on_failures:
        print(f"  last error seen (recovered): {watch.last_error}")


if __name__ == "__main__":
    raise SystemExit(main())
