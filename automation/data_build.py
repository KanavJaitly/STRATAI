"""Resumable, deadline-bounded rebuild of the Phase 4 dataset in an ephemeral
database: `python -m automation.data_build`.

Uses only the existing production path -- database.migrate.run_migrations,
data.orchestrator.sync_season (with Statbotics), data.rankings.sync_event_rankings
-- and then runs the readiness gate. It adds no ingestion logic of its own; it
only decides *which* events to hand to sync_season and *when to stop*.

Resumable: an event is re-synced only if its data is still incomplete (no
matches yet, a rostered team without a valid team_event_stats row, or -- for
the held-out season -- no ranking payload). Restoring a previous partial dump
and running again therefore continues where the last run stopped; landing-layer
dedup and upserts make re-syncing an event idempotent.

Bounded: it stops cleanly before its deadline so the caller can dump the
database, and it stops early when Statbotics degrades mid-sync (most of a chunk
still incomplete after syncing it) instead of spending minutes on failures.
Nothing is fabricated for events it could not complete; the readiness gate
reports them.
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Callable, Sequence

from automation.data_readiness import HELD_OUT_SEASON, REQUIRED_SEASONS, assess_readiness
from database.connection import Database

logger = logging.getLogger(__name__)

DEFAULT_CHUNK_SIZE = 20
# Minutes kept free after the last chunk for the readiness gate and the dump.
DEFAULT_FINISH_RESERVE_SECONDS = 20 * 60
# A chunk that is mostly still incomplete right after being synced means
# Statbotics is failing per request; continuing would only burn minutes.
DEGRADED_CHUNK_FRACTION = 0.5

STOP_DEADLINE = "deadline"
STOP_STATBOTICS_UNAVAILABLE = "statbotics_unavailable"
STOP_STATBOTICS_DEGRADED = "statbotics_degraded"

_INCOMPLETE_EVENTS_SQL = """
SELECT k.event_key
FROM unnest(%(keys)s::text[]) WITH ORDINALITY AS k(event_key, position)
WHERE NOT EXISTS (SELECT 1 FROM matches m WHERE m.event_key = k.event_key)
   OR EXISTS (
        SELECT 1
        FROM match_teams mt
        JOIN matches m ON m.match_key = mt.match_key
        LEFT JOIN team_event_stats tes
               ON tes.team_number = mt.team_number AND tes.event_key = m.event_key
        WHERE m.event_key = k.event_key
          AND (tes.team_number IS NULL OR tes.epa_total IS NULL
               OR tes.matches_played IS NULL OR tes.matches_played <= 0)
   )
ORDER BY k.position
"""

_EVENTS_WITHOUT_RANKING_SQL = """
SELECT e.event_key FROM events e
WHERE e.season = %(season)s
  AND NOT EXISTS (
      SELECT 1 FROM raw_source_payloads r
      WHERE r.source = 'tba' AND r.source_object_type = 'event_ranking'
        AND r.source_object_id = e.event_key AND r.is_current
  )
ORDER BY e.event_key
"""


@dataclass
class BuildReport:
    seasons: list[int]
    events_considered: int = 0
    events_already_complete: int = 0
    events_synced: int = 0
    events_still_incomplete: list[str] = field(default_factory=list)
    event_failures: list[list[str]] = field(default_factory=list)
    rankings_synced: int = 0
    stop_reason: str | None = None
    elapsed_seconds: float = 0.0

    def to_dict(self) -> dict:
        return asdict(self)


def incomplete_events(database: Database, event_keys: Sequence[str]) -> list[str]:
    """The subset of event_keys, in the given order, whose data is not yet complete."""
    if not event_keys:
        return []
    with database.cursor() as cursor:
        cursor.execute(_INCOMPLETE_EVENTS_SQL, {"keys": list(event_keys)})
        return [row[0] for row in cursor.fetchall()]


def events_without_ranking(database: Database, season: int) -> list[str]:
    with database.cursor() as cursor:
        cursor.execute(_EVENTS_WITHOUT_RANKING_SQL, {"season": season})
        return [row[0] for row in cursor.fetchall()]


def build(
    database: Database,
    *,
    seasons: Sequence[int],
    held_out_season: int,
    list_events: Callable[[int], list[str]],
    sync_events: Callable[[int, list[str]], object],
    sync_ranking: Callable[[str], bool],
    deadline: float,
    clock: Callable[[], float] = time.monotonic,
    chunk_size: int = DEFAULT_CHUNK_SIZE,
    finish_reserve_seconds: float = DEFAULT_FINISH_RESERVE_SECONDS,
    find_incomplete: Callable[[Database, Sequence[str]], list[str]] = incomplete_events,
    find_unranked: Callable[[Database, int], list[str]] = events_without_ranking,
) -> BuildReport:
    """Sync what is missing, season by season in chronological order, until
    done, out of time, or Statbotics stops cooperating."""
    started = clock()
    report = BuildReport(seasons=list(seasons))

    def out_of_time() -> bool:
        return clock() + finish_reserve_seconds >= deadline

    for season in seasons:
        keys = list_events(season)
        report.events_considered += len(keys)
        pending = find_incomplete(database, keys)
        report.events_already_complete += len(keys) - len(pending)

        for start in range(0, len(pending), chunk_size):
            if out_of_time():
                report.stop_reason = STOP_DEADLINE
                break
            chunk = pending[start:start + chunk_size]
            result = sync_events(season, chunk)
            report.events_synced += len(chunk)
            report.event_failures.extend([list(pair) for pair in getattr(result, "failures", [])])

            if getattr(result, "statbotics_skipped_reason", None):
                logger.warning("Statbotics probe failed: %s", result.statbotics_skipped_reason)
                report.stop_reason = STOP_STATBOTICS_UNAVAILABLE
                break
            still = find_incomplete(database, chunk)
            if len(still) > DEGRADED_CHUNK_FRACTION * len(chunk):
                logger.warning("%d of %d events still incomplete after sync", len(still), len(chunk))
                report.stop_reason = STOP_STATBOTICS_DEGRADED
                break
        if report.stop_reason:
            break

        if season == held_out_season:
            for event_key in find_unranked(database, season):
                if out_of_time():
                    report.stop_reason = STOP_DEADLINE
                    break
                if sync_ranking(event_key):
                    report.rankings_synced += 1
        if report.stop_reason:
            break

    for season in seasons:
        report.events_still_incomplete.extend(find_incomplete(database, list_events(season)))
    report.elapsed_seconds = clock() - started
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--deadline-minutes", type=float, required=True,
                        help="Wall-clock minutes from now by which the build must have stopped.")
    parser.add_argument("--report", type=Path, required=True, help="Where to write the JSON build + readiness report.")
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    from data.clients.statbotics import StatboticsClient
    from data.clients.tba import TBAClient
    from data.config import Settings
    from data.orchestrator import official_event_keys, sync_season
    from data.rankings import sync_event_rankings
    from database.connection import DatabaseConfig
    from database.migrate import run_migrations

    deadline = time.monotonic() + args.deadline_minutes * 60
    settings = Settings()
    run_migrations(settings)
    database = Database(DatabaseConfig(settings.database_url))
    statbotics = StatboticsClient(settings=settings)
    event_lists: dict[int, list[str]] = {}
    try:
        with TBAClient(settings=settings) as tba:
            def list_events(season: int) -> list[str]:
                if season not in event_lists:
                    event_lists[season] = official_event_keys(tba, season)
                return event_lists[season]

            build_report = build(
                database, seasons=REQUIRED_SEASONS, held_out_season=HELD_OUT_SEASON,
                list_events=list_events,
                sync_events=lambda season, keys: sync_season(
                    season, database=database, tba=tba, statbotics=statbotics, event_keys=keys,
                ),
                sync_ranking=lambda key: sync_event_rankings(key, database=database, tba=tba),
                deadline=deadline,
            )
    finally:
        statbotics.close()

    readiness = assess_readiness(database)
    args.report.write_text(json.dumps(
        {"build": build_report.to_dict(), "readiness": readiness.to_dict()}, indent=2, default=str,
    ), encoding="utf-8")
    print(f"data build: stop_reason={build_report.stop_reason} synced={build_report.events_synced} "
          f"incomplete={len(build_report.events_still_incomplete)} readiness={readiness.status}")
    for reason in readiness.reasons:
        print(f"  readiness: {reason}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
