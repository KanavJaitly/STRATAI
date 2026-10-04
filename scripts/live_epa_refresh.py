"""Operate the P5-M2 live EPA snapshot log (LIVE_EPA_REFRESH_DESIGN.md §1–§4).

    python -m scripts.live_epa_refresh init --log DIR --root STATBOTICS_SNAPSHOT_DIR
    python -m scripts.live_epa_refresh due --log DIR --root STATBOTICS_SNAPSHOT_DIR
    python -m scripts.live_epa_refresh refresh --log DIR --root STATBOTICS_SNAPSHOT_DIR [--event KEY ...]

* `init` starts a log whose root is the frozen D18 snapshot.
* `due` lists the events §1's cadence says to fetch now.
* `refresh` runs one cycle, over the due events or the given ones:
  - fetch through the Statbotics client, ≥ 0.25 s apart;
  - write immutable raw files;
  - land through the Phase 2 path into DATABASE_URL;
  - run the S1 check, then write a copy-on-write manifest.
  A failed cycle writes no manifest.

**This tool changes `team_event_stats` in DATABASE_URL**, after which the frozen D18 loader refuses that
database (`docs/ml_models.md` §9, limitation 1). Do not point it at the serving database until the live
provider has been adopted (P5-D3) and open decision Q1 is settled.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path


def main(argv: list[str] | None = None) -> int:
    from data.config import Settings
    from database.connection import Database, DatabaseConfig
    from ml.ratings.live_snapshots import SnapshotLog
    from ml.ratings.live_source import LiveEpaRefresher

    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("command", choices=("init", "due", "refresh"))
    parser.add_argument("--log", type=Path, required=True)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--event", action="append")
    args = parser.parse_args(argv)
    if args.command == "init":
        log = SnapshotLog.create_from_root(args.log, args.root)
        print(f"log started at {args.log}; root snapshot {log.head()}")
        return 0
    from data.clients.statbotics import StatboticsClient

    settings = Settings()
    log = SnapshotLog(args.log, args.root)
    refresher = LiveEpaRefresher(log, Database(DatabaseConfig(settings.database_url)), StatboticsClient(settings))
    now = datetime.now(timezone.utc)
    events = args.event or refresher.due_events(now)
    if args.command == "due":
        print(json.dumps(events))
        return 0
    if not events:
        print("nothing due")
        return 0
    outcome = refresher.refresh(events, now=now)
    print(json.dumps({"ok": outcome.ok, "snapshot_id": outcome.snapshot_id, "fetched": outcome.fetched,
                      "failures": outcome.failures, "check_failures": outcome.check_failures}, indent=1))
    return 0 if outcome.ok else 1


if __name__ == "__main__":
    sys.exit(main())
