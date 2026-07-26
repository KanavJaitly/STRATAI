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
import logging
import time
from dataclasses import dataclass, field
from typing import Any, Iterable, Sequence

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
            return int(cursor.fetchone()[0])

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


def sync_event(
    event_key: str,
    *,
    database: Database,
    tba: TBAClient,
    statbotics: StatboticsClient | None = None,
    repository: CanonicalRepository | None = None,
    writer: RawPayloadWriter | None = None,
    recorder: PipelineRunRecorder | None = None,
    watermarks: WatermarkStore | None = None,
    quality: DataQualityRecorder | None = None,
    lineage: LineageStore | None = None,
    pipeline_name: str = DEFAULT_PIPELINE_NAME,
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
    """
    writer = writer or RawPayloadWriter(database)
    repository = repository or CanonicalRepository(database)
    recorder = recorder or PipelineRunRecorder(database)
    watermarks = watermarks or WatermarkStore(database)
    quality = quality or DataQualityRecorder(database)
    lineage = lineage or LineageStore(database)

    run_id = recorder.start(pipeline_name, source=pipeline.SOURCE_TBA, scope_key=event_key)
    logger.info("Pipeline run %d started: %s for event %s", run_id, pipeline_name, event_key)

    try:
        extraction: ExtractionResult = pipeline.extract_event(event_key, tba=tba, statbotics=statbotics)
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
        for batch in staged_batches:
            watermarks.advance(batch.source, batch.object_type, event_key, batch.watermark_id)

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


def main(argv: list[str] | None = None) -> int:
    """Command-line entry point: sync one event, or a whole season, end to end."""
    parser = argparse.ArgumentParser(
        description="Run the StratAI ingestion pipeline for one event or a whole season.",
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
    args = parser.parse_args(argv)

    if (args.event_key is None) == (args.season is None):
        parser.error("give either an event_key or --season YEAR, not both and not neither")

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


if __name__ == "__main__":
    raise SystemExit(main())
