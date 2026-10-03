"""P5-M2 loader and refresh cycle for the live EPA provider (LIVE_EPA_REFRESH_DESIGN.md §1, §2, §4, §6).

* ``load_live_provider`` builds ml.ratings.live_epa.LiveStatboticsEpa from a snapshot log (live mode) or from the
  root snapshot alone under a simulated-retrieval schedule. It re-reads canonical facts on every call (§3.2).
* ``LiveEpaRefresher.refresh`` runs one refresh cycle (§4):
  - fetch the due events through the existing Statbotics client, at least 0.25 s apart;
  - write each response as an immutable raw file and verify its sha256;
  - land it through the Phase 2 path (orchestrator.sync_event, as D17 did);
  - confirm each normalized `epa.total_points` equals its `team_event_stats` row (S1, per event);
  - commit a copy-on-write manifest.
  A cycle that fails any fetch or check writes **no manifest**, and the previous snapshot stays in service.
  Every cycle, failed or not, is a log entry.
* ``due_events`` applies §1's cadence:
  - an ended event is fetched at +1 h, then every 2 h until processed;
  - at least once after +72 h;
  - once a day while it ended within the last 14 days (the daily sweep, for L5).
* ``ProviderHolder`` swaps providers atomically. A request keeps the provider it started with.

The live provider is not production's provider. Adoption is a recorded human decision (P5-D3), and the A1/A2
policy is open decision Q1 (.agent/phase5/M02_DECISION_REQUIRED.md).
"""

from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable

from data import pipeline
from data.landing.raw_writer import RawPayloadRecord
from database.connection import Database
from ml.ratings.live_epa import (
    A1A2Policy,
    LiveRetrieval,
    LiveStatboticsEpa,
    Schedule,
    SimulatedRetrieval,
    week_one_and_season_end,
)
from ml.ratings.live_snapshots import SnapshotLog, processed_flags
from ml.ratings.provider import StrataiPointInTimeEpa, read_team_event_facts

logger = logging.getLogger(__name__)

SCHEMA_VERSION = "statbotics-v3"
PIPELINE_NAME = "p5_live_epa_refresh"
MIN_REQUEST_INTERVAL = 0.25  # §1
FIRST_FETCH, RETRY_EVERY, FALLBACK_CHECK = timedelta(hours=1), timedelta(hours=2), timedelta(hours=72)
SWEEP_WINDOW, SWEEP_EVERY = timedelta(days=14), timedelta(days=1)

EVENT_LAST_MATCH_SQL = """
SELECT m.event_key, e.season, MAX(m.scheduled_time)
FROM matches m JOIN events e ON e.event_key = m.event_key
WHERE m.scheduled_time IS NOT NULL AND m.score_red IS NOT NULL AND m.score_blue IS NOT NULL
GROUP BY m.event_key, e.season
"""
# §1 "ended": end_date has passed and every scheduled match is completed.
ENDED_EVENTS_SQL = """
SELECT e.event_key FROM events e
WHERE e.end_date IS NOT NULL AND e.end_date < %(today)s
  AND EXISTS (SELECT 1 FROM matches m WHERE m.event_key = e.event_key)
  AND NOT EXISTS (SELECT 1 FROM matches m WHERE m.event_key = e.event_key
                  AND (m.score_red IS NULL OR m.score_blue IS NULL))
ORDER BY e.event_key
"""
TABLE_TOTAL_SQL = "SELECT team_number, epa_total FROM team_event_stats WHERE event_key = %(event)s"


def read_event_ends(database: Database) -> tuple[dict[str, datetime], dict[str, int]]:
    """§1 event_end (the last completed match) and each event's season, from canonical tables."""
    ends, seasons = {}, {}
    with database.cursor() as cursor:
        cursor.execute(EVENT_LAST_MATCH_SQL)
        for event_key, season, last in cursor.fetchall():
            ends[event_key], seasons[event_key] = last, season
    return ends, seasons


def stratai_source(database: Database, chain: Path) -> tuple[dict, dict[str, Any]]:
    """STRATAI team-event values (with their available_at) and the replay's identity, from a chain manifest."""
    fallback = StrataiPointInTimeEpa.from_chain_manifest(database, chain)
    return fallback.values, {"chain_manifest": chain.name, **fallback.provenance_info}


def load_live_provider(database: Database, *, root_dir: Path, chain: Path, a1a2_policy: A1A2Policy,
                       concluded_seasons: set[int], log: SnapshotLog | None = None,
                       schedule: Schedule | None = None,
                       stratai: tuple[dict, dict[str, Any]] | None = None) -> LiveStatboticsEpa:
    """Live mode (``log``) or simulated retrieval over the root snapshot (``schedule``); exactly one."""
    if (log is None) == (schedule is None):
        raise ValueError("pass exactly one of log (live mode) or schedule (simulated retrieval)")
    if log is not None:
        retrieval: LiveRetrieval | SimulatedRetrieval = LiveRetrieval(log)
        records = retrieval.all_records()
        mode = "live"
    else:
        root_log = SnapshotLog(Path("<unused>"), root_dir)
        root_records, root_id = _root_records(root_log, root_dir)
        retrieval = SimulatedRetrieval(root_id, root_records, schedule)  # type: ignore[arg-type]
        records = root_records
        mode = f"simulated:{getattr(schedule, '__name__', 'schedule')}"
    ends, seasons = read_event_ends(database)
    week_one, season_end = week_one_and_season_end(records, ends, seasons, concluded_seasons)
    values, info = stratai if stratai is not None else stratai_source(database, chain)
    return LiveStatboticsEpa(retrieval, read_team_event_facts(database), ends, week_one, season_end, values, info,
                             a1a2_policy, provenance_info={"retrieval_mode": mode, "root_snapshot": root_dir.name,
                                                           "concluded_seasons": sorted(concluded_seasons)})


def _root_records(log: SnapshotLog, root_dir: Path) -> tuple[dict, str]:
    """The root snapshot's records and id, built in memory exactly as SnapshotLog.create_from_root writes it."""
    import json

    from ml.ratings.live_snapshots import MANIFEST_SCHEMA, ROOT_PREFIX, snapshot_id_of

    source = json.loads((root_dir / "manifest.json").read_text(encoding="utf-8"))
    events, records = {}, {}
    for entry in source["events"]:
        raw = json.loads(log._read_raw(ROOT_PREFIX + entry["raw_file"], entry["raw_sha256"]))
        events[entry["event_key"]] = {"raw_file": ROOT_PREFIX + entry["raw_file"], "raw_sha256": entry["raw_sha256"],
                                      "retrieved_at": entry["retrieved_at"], "processed": processed_flags(raw)}
        for team, record in log.event_records(events[entry["event_key"]]).items():
            records[(team, entry["event_key"])] = record
    manifest = {"schema": MANIFEST_SCHEMA, "parent": None, "origin": "d18_root", "root_snapshot": root_dir.name,
                "created_at": source["finished_at"], "events": events}
    return records, snapshot_id_of(manifest)


# --- refresh cycle -------------------------------------------------------------------------------


@dataclass
class RefreshOutcome:
    started_at: datetime
    parent: str
    snapshot_id: str | None
    fetched: list[str]
    failures: list[dict[str, str]]
    check_failures: list[dict[str, Any]]

    @property
    def ok(self) -> bool:
        return not self.failures and not self.check_failures


@dataclass
class LiveEpaRefresher:
    """One log, one database to land into, one Statbotics client (see the module docstring)."""

    log: SnapshotLog
    database: Database
    client: Any  # data.clients.statbotics.StatboticsClient or a test double with fetch_event_team_metrics
    sleep: Callable[[float], None] = time.sleep
    land: bool = True
    # §6: rerun the STRATAI season replay when a fallback first becomes needed and after each later sync while
    # any fallback is in use; returns the new replay's identity (logged). None = not configured.
    stratai_rerun: Callable[[], dict[str, Any]] | None = None

    def fallback_events(self, now: datetime) -> list[str]:
        """Head-snapshot events with an unprocessed team that ended more than 72 h before now."""
        ends, _ = read_event_ends(self.database)
        head = self.log.manifest(self.log.head())["events"]
        return sorted(e for e, entry in head.items()
                      if not all(entry["processed"].values()) and e in ends and ends[e] + FALLBACK_CHECK < now)

    def _fetch_history(self) -> dict[str, list[datetime]]:
        history: dict[str, list[datetime]] = {}
        for entry in self.log.entries():
            if entry["kind"] == "refresh":
                for event_key in entry["attempted"]:
                    history.setdefault(event_key, []).append(datetime.fromisoformat(entry["started_at"]))
        return history

    def due_events(self, now: datetime) -> list[str]:
        """§1 cadence over the canonical events that have ended."""
        with self.database.cursor() as cursor:
            cursor.execute(ENDED_EVENTS_SQL, {"today": now.date()})
            ended = [row[0] for row in cursor.fetchall()]
        ends, _ = read_event_ends(self.database)
        head = self.log.manifest(self.log.head())["events"]
        history = self._fetch_history()
        due = []
        for event_key in ended:
            end = ends.get(event_key)
            if end is None or now < end + FIRST_FETCH:
                continue
            entry = head.get(event_key)
            processed = entry is not None and entry["processed"] and all(entry["processed"].values())
            last = max(history.get(event_key, []), default=None)
            if not processed and (last is None or now - last >= RETRY_EVERY):
                due.append(event_key)
            elif now >= end + FALLBACK_CHECK and not any(t >= end + FALLBACK_CHECK for t in history.get(event_key, [])):
                due.append(event_key)  # at least once more after 72 h
            elif now - end <= SWEEP_WINDOW and (last is None or now - last >= SWEEP_EVERY):
                due.append(event_key)  # daily sweep (late corrections, L5)
        return due

    def refresh(self, events: list[str], *, now: datetime | None = None) -> RefreshOutcome:
        started = now or datetime.now(timezone.utc)
        parent = self.log.head()
        changed: dict[str, dict[str, Any]] = {}
        failures: list[dict[str, str]] = []
        checks: list[dict[str, Any]] = []
        for index, event_key in enumerate(events):
            if index:
                self.sleep(MIN_REQUEST_INTERVAL)
            retrieved_at = now or datetime.now(timezone.utc)
            try:
                body, responses = self.client.fetch_event_team_metrics(event_key)
            except Exception as exc:  # 5xx, timeouts, malformed bodies: recorded, never silently dropped
                failures.append({"event_key": event_key, "error": f"{type(exc).__name__}: {exc}"})
                continue
            ref, sha = self.log.write_raw(event_key, body)
            records = list(body or [])
            try:
                self.log._read_raw(ref, sha)  # the file on disk is the one recorded
                if self.land:
                    self._land(event_key, responses, retrieved_at)
                    checks.extend(self._s1_check(event_key, records))
            except Exception as exc:
                checks.append({"event_key": event_key, "check": "land_or_verify", "error": f"{type(exc).__name__}: {exc}"})
                continue
            changed[event_key] = {"raw_file": ref, "raw_sha256": sha, "retrieved_at": retrieved_at.isoformat(),
                                  "processed": processed_flags(records)}
        outcome = RefreshOutcome(started, parent, None, sorted(changed), failures, checks)
        if outcome.ok and changed:
            outcome.snapshot_id = self.log.commit_snapshot(parent, changed, started)
        stratai = None
        if outcome.ok and self.stratai_rerun is not None and self.fallback_events(started):
            stratai = self.stratai_rerun()
        self.log.append_log({"kind": "refresh", "started_at": started.isoformat(), "ok": outcome.ok,
                             "attempted": list(events), "fetched": outcome.fetched, "failures": failures,
                             "check_failures": checks, "parent": parent, "snapshot_id": outcome.snapshot_id,
                             "stratai_rerun": stratai})
        if not outcome.ok:
            logger.warning("live EPA refresh failed (%d fetch failures, %d check failures); %s stays in service",
                           len(failures), len(checks), parent)
        return outcome

    def _land(self, event_key: str, responses: list[Any], retrieved_at: datetime) -> None:
        from data.orchestrator import sync_event

        batch = pipeline.ExtractionBatch(pipeline.SOURCE_STATBOTICS, pipeline.OBJECT_TYPE_TEAM_EVENT, [
            RawPayloadRecord(pipeline.SOURCE_STATBOTICS, pipeline.OBJECT_TYPE_TEAM_EVENT,
                             f"{r.raw['team']}_{event_key}", r.raw, source_schema_version=SCHEMA_VERSION,
                             fetch_timestamp=retrieved_at)
            for r in responses
        ])
        sync_event(event_key, database=self.database, tba=None, pipeline_name=PIPELINE_NAME,
                   extraction=pipeline.ExtractionResult(event_key, [batch]))

    def _s1_check(self, event_key: str, records: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """D18's S1 per event: normalized epa.total_points equals the team_event_stats row."""
        from data.staging.normalizer import normalize_statbotics_team_event_stats

        with self.database.cursor() as cursor:
            cursor.execute(TABLE_TOTAL_SQL, {"event": event_key})
            table = {team: (None if total is None else float(total)) for team, total in cursor.fetchall()}
        problems = []
        for record in records:
            staged = normalize_statbotics_team_event_stats(record)
            stored = table.get(staged.team_number, "missing")
            if stored == "missing" or (stored is None) != (staged.epa_total is None) or (
                    stored is not None and abs(stored - staged.epa_total) > 1e-9):  # type: ignore[operator]
                problems.append({"event_key": event_key, "check": "S1", "team": staged.team_number,
                                 "normalized": staged.epa_total, "table": stored})
        return problems


@dataclass
class ProviderHolder:
    """Atomic provider swap (§4): readers take ``current`` once per request and keep it."""

    current: LiveStatboticsEpa
    _lock: threading.Lock = field(default_factory=threading.Lock)

    def swap(self, provider: LiveStatboticsEpa) -> LiveStatboticsEpa:
        with self._lock:
            previous, self.current = self.current, provider
        return previous
