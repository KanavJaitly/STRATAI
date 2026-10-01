"""Snapshot Statbotics team-event EPA for Phase 4, with provenance (decision D17).

    Statbotics API -> cached raw response (artifact + raw_source_payloads)
      -> team_event_stats (the existing Phase 2 staging and loading path)
      -> Phase 4 features

One request per event (``GET /v3/team_events?event=<key>&limit=1000``). Each
returned record is the same body ``/team_event/{team}/{event}`` returns (verified
2026-10-01). It lands as source='statbotics', type='team_event',
id='{team}_{event}', exactly as the per-team path lands it, and then goes
through orchestrator.sync_event's own landing, staging, quality, loading,
lineage and watermark steps. TBA is never contacted, so the TBA raw snapshot
that every earlier artifact is fingerprinted to does not change.

Writes a write-once snapshot directory under --out:
  raw/<event>.json.gz   each event's response, canonically re-serialized
  team_event_stats.json.gz  the loaded rows for the seasons (the normalized artifact)
  manifest.json         endpoint, parameters, retrieval times, sha256 of every file, the
                        commit that produced it, and the team_event_stats fingerprint

Usage:
    python -m scripts.sync_statbotics_snapshot --season 2024 --season 2025 --season 2026 --out DIR
"""

from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import logging
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from data import pipeline
from data.clients.statbotics import StatboticsClient
from data.config import Settings
from data.landing.raw_writer import RawPayloadRecord
from data.orchestrator import sync_event
from database.connection import Database, DatabaseConfig

ENDPOINT = "/team_events"
SCHEMA_VERSION = "statbotics-v3"
PIPELINE_NAME = "statbotics_snapshot"

TEAM_EVENT_STATS_SQL = """
SELECT team_number, event_key, season, epa_total, epa_auto, epa_teleop, epa_endgame, matches_played
FROM team_event_stats WHERE season = ANY(%(seasons)s) ORDER BY event_key, team_number
"""


def _canonical(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("utf-8")


def _write_gz(path: Path, data: bytes) -> str:
    path.write_bytes(gzip.compress(data, mtime=0))
    return hashlib.sha256(data).hexdigest()


def table_fingerprint(database: Database, seasons: list[int]) -> tuple[list[list[Any]], str]:
    with database.cursor() as cursor:
        cursor.execute(TEAM_EVENT_STATS_SQL, {"seasons": seasons})
        rows = [[None if v is None else (float(v) if not isinstance(v, (int, str)) else v) for v in row]
                for row in cursor.fetchall()]
    return rows, hashlib.sha256(_canonical(rows)).hexdigest()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--season", type=int, action="append", required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--sleep", type=float, default=0.25, help="pause between requests (politeness)")
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.WARNING, format="%(asctime)s %(levelname)s %(name)s: %(message)s")

    settings = Settings()
    database = Database(DatabaseConfig(settings.database_url))
    client = StatboticsClient(settings)
    seasons = sorted(set(args.season))
    with database.cursor() as cursor:
        cursor.execute("SELECT event_key FROM events WHERE season = ANY(%s) ORDER BY event_key", (seasons,))
        events = [row[0] for row in cursor.fetchall()]

    started = datetime.now(timezone.utc)
    directory = args.out / f"statbotics_snapshot_{started.strftime('%Y%m%dT%H%M%SZ')}"
    (directory / "raw").mkdir(parents=True)
    entries, failures = [], []
    for number, event_key in enumerate(events, start=1):
        retrieved_at = datetime.now(timezone.utc)
        try:
            body, responses = client.fetch_event_team_metrics(event_key)
        except Exception as exc:  # recorded, never silently dropped
            failures.append({"event_key": event_key, "error": f"{type(exc).__name__}: {exc}"})
            print(f"[{number}/{len(events)}] {event_key}: FAILED {exc}", flush=True)
            continue
        raw_bytes = _canonical(body or [])
        sha = _write_gz(directory / "raw" / f"{event_key}.json.gz", raw_bytes)
        batch = pipeline.ExtractionBatch(pipeline.SOURCE_STATBOTICS, pipeline.OBJECT_TYPE_TEAM_EVENT, [
            RawPayloadRecord(pipeline.SOURCE_STATBOTICS, pipeline.OBJECT_TYPE_TEAM_EVENT,
                             f"{r.raw['team']}_{event_key}", r.raw, source_schema_version=SCHEMA_VERSION,
                             fetch_timestamp=retrieved_at)
            for r in responses
        ])
        result = sync_event(event_key, database=database, tba=None, pipeline_name=PIPELINE_NAME,
                            extraction=pipeline.ExtractionResult(event_key, [batch]))
        entries.append({
            "event_key": event_key, "endpoint": ENDPOINT, "params": {"event": event_key, "limit": 1000},
            "retrieved_at": retrieved_at.isoformat(), "records": len(responses), "raw_file": f"raw/{event_key}.json.gz",
            "raw_sha256": sha, "pipeline_run_id": result.run_id, "landed": result.landed, "loaded": result.loaded,
            "skipped": len(result.skipped), "fatal_quality_issues": len(result.fatal_issues),
        })
        if number % 50 == 0 or number == len(events):
            print(f"[{number}/{len(events)}] {event_key}: {len(responses)} records", flush=True)
        time.sleep(args.sleep)

    rows, fingerprint = table_fingerprint(database, seasons)
    stats_sha = _write_gz(directory / "team_event_stats.json.gz", _canonical(rows))
    commit = subprocess.run(["git", "rev-parse", "HEAD"], capture_output=True, text=True).stdout.strip()
    manifest = {
        "decision": "D17", "source": "statbotics", "base_url": client.base_url, "endpoint": ENDPOINT,
        "params_template": {"event": "<event_key>", "limit": 1000}, "schema_version": SCHEMA_VERSION,
        "seasons": seasons, "events_requested": len(events), "events_fetched": len(entries),
        "failures": failures, "started_at": started.isoformat(),
        "finished_at": datetime.now(timezone.utc).isoformat(), "producing_commit": commit,
        "transformations": [
            "raw/<event>.json.gz: the parsed response body re-serialized with sorted keys (no value changed)",
            "each record landed to raw_source_payloads as source=statbotics, type=team_event, id={team}_{event}",
            "staged by data.staging.normalizer.normalize_statbotics_team_event_stats; loaded to team_event_stats",
        ],
        "team_event_stats": {"rows": len(rows), "sha256": fingerprint, "file": "team_event_stats.json.gz",
                             "file_sha256": stats_sha},
        "events": entries,
    }
    (directory / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    print(f"snapshot: {len(entries)}/{len(events)} events, {len(rows)} team_event_stats rows, "
          f"{len(failures)} failures -> {directory}")
    return 0 if not failures else 1


if __name__ == "__main__":
    sys.exit(main())
