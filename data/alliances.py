"""Event playoff-alliance (seed / pick) ingestion and read-back.

Phase 5 needs alliance seeds and picks: ground truth for captain and alliance
predictions, and the seed/bracket information any future playoff model needs (the
D18 M07 diagnostic found the higher seed underestimated by ~15 points by a model
that has none). This module only lands and reads the data. It builds no model.

Same design as data.rankings: TBA's /event/{event_key}/alliances, landed raw through
RawPayloadWriter (source="tba", object_type=OBJECT_TYPE_EVENT_ALLIANCES, id=event
key, checksum-deduplicated), read back from raw_source_payloads. No canonical table.

Two readers, deliberately separate, because the payload mixes two kinds of data:

* read_event_alliances -> seed, captain, picks, backup, declines. Known once
  alliance selection ends, i.e. after the event's last qualification match and
  before its first playoff match. A consumer may use them only for an as_of after
  alliance selection (in practice: for playoff matches), never for qualification.
* read_event_alliance_outcomes -> each alliance's playoff record and result. These
  are outcomes: labels for evaluation only, never features.
"""

from __future__ import annotations

import argparse
import re
import sys
import time
from dataclasses import dataclass
from typing import Any

from data.clients.tba import TBAClient
from data.config import Settings
from data.landing.raw_writer import RawPayloadRecord, RawPayloadWriter
from data.pipeline import SOURCE_TBA
from data.staging.normalizer import parse_tba_team_number
from database.connection import Database, DatabaseConfig

__all__ = [
    "OBJECT_TYPE_EVENT_ALLIANCES",
    "Alliance",
    "AllianceOutcome",
    "main",
    "read_event_alliance_outcomes",
    "read_event_alliances",
    "sync_event_alliances",
    "sync_season_alliances",
]

OBJECT_TYPE_EVENT_ALLIANCES = "event_alliances"
DEFAULT_EVENT_DELAY_SECONDS = 0.5
_ALLIANCE_NAME = re.compile(r"^Alliance (\d+)$")


@dataclass(frozen=True)
class Alliance:
    seed: int
    captain: int | None
    picks: tuple[int, ...]  # in pick order, captain first
    backup: int | None
    declines: tuple[int, ...]


@dataclass(frozen=True)
class AllianceOutcome:
    seed: int
    status: str | None
    level: str | None
    wins: int | None
    losses: int | None
    ties: int | None


def sync_event_alliances(event_key: str, *, database: Database, tba: TBAClient) -> bool:
    """Fetch and land one event's alliances. True if a new raw payload was landed
    (an unchanged re-sync lands nothing: RawPayloadWriter's checksum dedup)."""
    response = tba.fetch_event_alliances(event_key)
    return RawPayloadWriter(database).write(RawPayloadRecord(
        source=SOURCE_TBA, source_object_type=OBJECT_TYPE_EVENT_ALLIANCES,
        source_object_id=event_key, payload=response.raw,
    ))


def sync_season_alliances(
    season: int, *, database: Database, tba: TBAClient, delay_seconds: float = DEFAULT_EVENT_DELAY_SECONDS,
) -> dict[str, int]:
    """Sync alliances for every event of `season` already in the canonical `events` table
    (the event set sync_season already filtered, as data.rankings does)."""
    with database.cursor() as cursor:
        cursor.execute("SELECT event_key FROM events WHERE season = %s ORDER BY event_key", (season,))
        event_keys = [row[0] for row in cursor.fetchall()]
    landed = 0
    for index, event_key in enumerate(event_keys):
        if sync_event_alliances(event_key, database=database, tba=tba):
            landed += 1
        if index + 1 < len(event_keys):
            time.sleep(delay_seconds)
    return {"events": len(event_keys), "landed": landed}


def _current_payloads(database: Database, season: int) -> list[tuple[str, Any]]:
    with database.cursor() as cursor:
        cursor.execute(
            """
            SELECT e.event_key, rsp.payload_json
            FROM events e
            JOIN raw_source_payloads rsp
              ON rsp.source = %s AND rsp.source_object_type = %s AND rsp.source_object_id = e.event_key
              AND rsp.is_current
            WHERE e.season = %s
            ORDER BY rsp.id
            """,
            (SOURCE_TBA, OBJECT_TYPE_EVENT_ALLIANCES, season),
        )
        return cursor.fetchall()


def read_event_alliances(database: Database, season: int) -> dict[str, list[Alliance]]:
    """{event_key: [Alliance, ...] in seed order} for every landed event with alliances.
    Seeds and picks only -- see the module docstring for when they may be used."""
    out: dict[str, list[Alliance]] = {}
    for event_key, payload in _current_payloads(database, season):  # highest id wins, as in data.rankings
        alliances = parse_alliances_payload(payload)
        if alliances:
            out[event_key] = alliances
    return out


def read_event_alliance_outcomes(database: Database, season: int) -> dict[str, list[AllianceOutcome]]:
    """{event_key: [AllianceOutcome, ...]}: playoff results. Evaluation labels only."""
    out: dict[str, list[AllianceOutcome]] = {}
    for event_key, payload in _current_payloads(database, season):
        outcomes = parse_alliance_outcomes_payload(payload)
        if outcomes:
            out[event_key] = outcomes
    return out


def _team(key: Any) -> int | None:
    try:
        return parse_tba_team_number(key)
    except (AssertionError, TypeError, ValueError, AttributeError):
        return None


def _seed(entry: dict[str, Any], index: int) -> int:
    """The seed: from "Alliance N" when present (it must agree with list order), else list order."""
    match = _ALLIANCE_NAME.match(str(entry.get("name") or ""))
    return int(match.group(1)) if match else index + 1


def parse_alliances_payload(payload: Any) -> list[Alliance]:
    """Pure: seed-ordered alliances from one raw payload. Malformed entries are skipped;
    a payload whose names contradict their list order is rejected whole (empty)."""
    if not isinstance(payload, list):
        return []
    alliances = []
    for index, entry in enumerate(payload):
        if not isinstance(entry, dict) or not isinstance(entry.get("picks"), list):
            continue
        picks = tuple(t for t in (_team(k) for k in entry["picks"]) if t is not None)
        backup = entry.get("backup") if isinstance(entry.get("backup"), dict) else None
        declines = tuple(t for t in (_team(k) for k in entry.get("declines") or []) if t is not None)
        alliances.append(Alliance(seed=_seed(entry, index), captain=picks[0] if picks else None, picks=picks,
                                  backup=_team(backup.get("in")) if backup else None, declines=declines))
    seeds = [a.seed for a in alliances]
    if len(set(seeds)) != len(seeds) or seeds != sorted(seeds):
        return []
    return alliances


def parse_alliance_outcomes_payload(payload: Any) -> list[AllianceOutcome]:
    """Pure: each alliance's playoff result from one raw payload (labels only)."""
    if not isinstance(payload, list):
        return []
    out = []
    for index, entry in enumerate(payload):
        if not isinstance(entry, dict):
            continue
        status = entry.get("status") if isinstance(entry.get("status"), dict) else {}
        record = status.get("record") if isinstance(status.get("record"), dict) else {}
        out.append(AllianceOutcome(seed=_seed(entry, index), status=status.get("status"), level=status.get("level"),
                                   wins=record.get("wins"), losses=record.get("losses"), ties=record.get("ties")))
    return out


def main(argv: list[str] | None = None) -> int:
    """`python -m data.alliances --season YEAR [--season YEAR ...]`."""
    parser = argparse.ArgumentParser(description="Sync TBA playoff alliances for already-synced seasons.")
    parser.add_argument("--season", type=int, action="append", required=True, dest="seasons")
    parser.add_argument("--delay", type=float, default=DEFAULT_EVENT_DELAY_SECONDS, metavar="SECONDS")
    args = parser.parse_args(argv)
    settings = Settings()
    database = Database(DatabaseConfig(settings.database_url))
    with TBAClient(settings=settings) as tba:
        for season in args.seasons:
            summary = sync_season_alliances(season, database=database, tba=tba, delay_seconds=args.delay)
            print(f"season {season}: {summary}", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
