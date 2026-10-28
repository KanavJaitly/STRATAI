"""Build the public-data-only database dump for the hosted deployment (docs/DEPLOYMENT.md).

The hosted app carries public data only: TBA match results and Statbotics EPA. Scouting observations, scouting
access codes, human-input artifacts and every metric derived from scouting are removed, so defense and feeding show
as unavailable.

Steps:
1. pg_dump the source, by default the sanctioned test copy `stratai_test` (never scripts/phase5_isolated_db.py).
2. Restore it into a disposable `stratai_test_deploy_public`, created empty here and dropped at the end.
3. Scrub every scouting and human-input row there, then verify none is left.
4. pg_dump the scrubbed copy to `.deploy/stratai_public.dump` (gitignored), with no owners or privileges, so it
   restores into a Render database as that database's own user.

Usage:
    python -m scripts.deploy_public_dump                       # from stratai_test (this machine's sanctioned copy)
    python -m scripts.deploy_public_dump --source stratai_test --pg-bin "C:/Program Files/PostgreSQL/18/bin" \
        --snapshot DIR --chain FILE                           # the D18 source copy, run by its owner

Reads DATABASE_URL from the environment or .env and uses only its server and credentials. The source database is
only read. With --snapshot and --chain, the scrubbed copy must also pass the D18 EPA source's own integrity check
(ml.ratings.d18_source.load_d18_provider) before it is written, which proves both that the source is the database the
D18 artifacts were built from and that the scrub did not disturb the public data.
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path

import psycopg
from dotenv import load_dotenv
from psycopg.conninfo import conninfo_to_dict, make_conninfo

SOURCE_DB = "stratai_test"
SCRATCH_DB = "stratai_test_deploy_public"
OUTPUT = Path(".deploy/stratai_public.dump")

SCOUTING_SOURCES = ("scoutradioz", "human_scout")
EMPTIED_TABLES = ("scouting_observations", "scouting_access_codes", "human_review_artifacts",
                  "capability_profiles", "game_manuals")
SCRUB = [
    *(f"TRUNCATE {table} CASCADE" for table in EMPTIED_TABLES),
    # Rows that reference a raw payload go before the payloads themselves.
    "DELETE FROM canonical_lineage WHERE source = ANY(%(sources)s) OR raw_payload_id IN "
    "(SELECT id FROM raw_source_payloads WHERE source = ANY(%(sources)s))",
    "DELETE FROM data_quality_issues WHERE source = ANY(%(sources)s) OR raw_payload_id IN "
    "(SELECT id FROM raw_source_payloads WHERE source = ANY(%(sources)s))",
    "DELETE FROM raw_source_payloads WHERE source = ANY(%(sources)s)",
    "DELETE FROM source_watermarks WHERE source = ANY(%(sources)s)",
    """UPDATE team_metrics SET
           defense_score = NULL, defense_observation_count = 0, defense_agreement = NULL,
           defense_insufficient_data = TRUE,
           feeding_score = NULL, feeding_observation_count = 0, feeding_agreement = NULL,
           feeding_insufficient_data = TRUE,
           contributing_sources = ARRAY(SELECT s FROM unnest(contributing_sources) s WHERE s <> ALL(%(sources)s))""",
]
CHECKS = [
    *(f"SELECT count(*) FROM {table}" for table in EMPTIED_TABLES),
    "SELECT count(*) FROM raw_source_payloads WHERE source = ANY(%(sources)s)",
    "SELECT count(*) FROM data_quality_issues WHERE source = ANY(%(sources)s)",
    "SELECT count(*) FROM source_watermarks WHERE source = ANY(%(sources)s)",
    "SELECT count(*) FROM team_metrics WHERE defense_score IS NOT NULL OR feeding_score IS NOT NULL "
    "OR defense_observation_count > 0 OR feeding_observation_count > 0 "
    "OR contributing_sources && %(sources)s::text[]",
]


def conninfo_for(base: str, dbname: str) -> str:
    params = conninfo_to_dict(base)
    params["dbname"] = dbname
    return make_conninfo(**params)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--source", default=SOURCE_DB, help="database to copy (read only)")
    parser.add_argument("--pg-bin", default="", help="directory holding pg_dump/pg_restore, if not on PATH")
    parser.add_argument("--snapshot", type=Path, help="D18 Statbotics snapshot directory, to verify the copy")
    parser.add_argument("--chain", type=Path, help="D18 EPA chain manifest, to verify the copy")
    args = parser.parse_args(argv)
    if (args.snapshot is None) != (args.chain is None):
        parser.error("--snapshot and --chain go together")
    pg_dump, pg_restore = (str(Path(args.pg_bin) / tool) if args.pg_bin else tool for tool in ("pg_dump", "pg_restore"))
    load_dotenv()
    base = os.environ.get("DATABASE_URL")
    if not base:
        print("DATABASE_URL is not set", file=sys.stderr)
        return 2
    source, scratch, admin = (conninfo_for(base, name) for name in (args.source, SCRATCH_DB, "postgres"))
    with psycopg.connect(admin, autocommit=True) as conn:
        conn.execute(f"DROP DATABASE IF EXISTS {SCRATCH_DB}")
        conn.execute(f"CREATE DATABASE {SCRATCH_DB}")
    try:
        dump = subprocess.run([pg_dump, "--format=custom", "--no-owner", "--no-privileges", "--dbname", source],
                              check=True, capture_output=True).stdout
        subprocess.run([pg_restore, "--no-owner", "--no-privileges", "--exit-on-error", "--dbname", scratch],
                       input=dump, check=True)
        params = {"sources": list(SCOUTING_SOURCES)}
        with psycopg.connect(scratch) as conn:
            for statement in SCRUB:
                conn.execute(statement, params)
            left = {check: conn.execute(check, params).fetchone()[0] for check in CHECKS}
        dirty = {check: count for check, count in left.items() if count}
        if dirty:
            for check, count in dirty.items():
                print(f"NOT SCRUBBED ({count} rows): {check}", file=sys.stderr)
            return 1
        if args.snapshot is not None:
            from database.connection import Database, DatabaseConfig
            from ml.ratings.d18_source import load_d18_provider

            _, integrity = load_d18_provider(Database(DatabaseConfig(scratch)), args.snapshot, args.chain)
            print(f"D18 EPA source check passed on the scrubbed copy: {integrity}")
        OUTPUT.parent.mkdir(exist_ok=True)
        subprocess.run([pg_dump, "--format=custom", "--no-owner", "--no-privileges", "--file", str(OUTPUT),
                        "--dbname", scratch], check=True)
        with psycopg.connect(scratch) as conn:
            counts = {table: conn.execute(f"SELECT count(*) FROM {table}").fetchone()[0]
                      for table in ("teams", "events", "matches", "match_teams", "team_event_stats", "team_metrics")}
    finally:
        with psycopg.connect(admin, autocommit=True) as conn:
            conn.execute(f"DROP DATABASE IF EXISTS {SCRATCH_DB}")
    print(f"wrote {OUTPUT} ({OUTPUT.stat().st_size // 1024} KiB); scouting checks all 0")
    for table, count in counts.items():
        print(f"  {table}: {count}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
