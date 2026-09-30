"""Replay STRATAI's own EPA for one or more seasons from its stored data.

Reads canonical tables and raw TBA payloads (read-only), runs the pure EPA
engine (ml.ratings.epa), verifies determinism and snapshot/resume, and writes
a write-once artifact directory per season under --out. Never calls
Statbotics, never writes to the database.

Usage:

    python -m scripts.run_epa_replay --season 2024 --season 2025 --season 2026 --out ../StratAI-artifacts/ratings/epa
    python -m scripts.run_epa_replay --season 2025 --out DIR --prior prior_2025.json   # explicit prior history
"""

from __future__ import annotations

import argparse
import logging
from pathlib import Path

from data.config import Settings
from database.connection import Database, DatabaseConfig
from ml.ratings.epa.inputs import PriorSeasonInput
from ml.ratings.runner import replay_season, write_artifacts


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--season", type=int, action="append", required=True)
    parser.add_argument("--out", type=Path, required=True, help="artifact root; one subdirectory per season run")
    parser.add_argument("--prior", type=Path, help="PriorSeasonInput JSON; omitted = no prior-season history")
    parser.add_argument("--event", action="append", help="limit to these event keys (smoke runs)")
    parser.add_argument("--no-verify", action="store_true", help="skip the determinism and resume checks")
    parser.add_argument("--no-norm", action="store_true", help="skip the scipy norm-EPA fit")
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")

    prior = None if args.prior is None else PriorSeasonInput.model_validate_json(args.prior.read_text(encoding="utf-8"))
    database = Database(DatabaseConfig(Settings().database_url))
    exit_code = 0
    for season in args.season:
        replay = replay_season(database, season, prior=prior, compute_norm=not args.no_norm,
                               verify=not args.no_verify, event_keys=args.event)
        directory, written = write_artifacts(args.out, replay)
        verification = replay.report["verification"]
        ok = not verification["performed"] or (verification["determinism"]["ok"] and verification["resume"]["ok"])
        exit_code = exit_code or (0 if ok else 1)
        print(f"{season}: {'written' if written else 'identical artifact already present'} {directory}"
              f" | results {replay.result.results_fingerprint()[:16]} | verification {'ok' if ok else 'FAILED'}")
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
