"""Build the public-data-only database dump for the hosted deployment.

What is removed follows docs/deployment_render.md section 4 (in the deploy/render-prep worktree, 2026-10-22).

The hosted app carries public data only: TBA match results and Statbotics EPA. Scouting observations, scouting
access codes, every human-input row (game manuals and specs, season rulesets with their reviewer, capability
profiles, human review artifacts), every raw payload that is not TBA or Statbotics, and every metric derived from
scouting are removed, so defense and feeding show as unavailable.

Steps:
1. Stream pg_dump of the source, the sanctioned test copy `stratai_test`, into pg_restore of a disposable
   `stratai_test_deploy_public`, created empty here and dropped at the end. Nothing unscrubbed touches the disk.
2. Scrub every scouting and human-input row there, then verify none is left.
3. Optionally (--snapshot/--chain) run the D18 EPA source's own integrity check on the scrubbed copy.
4. pg_dump the scrubbed copy to `.deploy/stratai_public.dump`, with no owners or privileges, so it restores as the
   target database's own user, and refuse it if the database password or the TBA key appears in it.

Usage:
    python -m scripts.deploy_public_dump                       # from stratai_test (this machine's sanctioned copy)
    python -m scripts.deploy_public_dump --source stratai_test --pg-bin "C:/Program Files/PostgreSQL/18/bin" \
        --snapshot DIR --chain FILE                           # the D18 source copy, run by its owner

Reads DATABASE_URL from the environment or .env and uses only its server and credentials. The source database is
only read. With --snapshot and --chain, the scrubbed copy must also pass the D18 EPA source's own integrity check
(ml.ratings.d18_source.load_d18_provider) before it is written, which proves both that the source is the database the
D18 artifacts were built from and that the scrub did not disturb the public data.

Every scratch statement runs under a statement timeout and the whole run under a time budget (CLAUDE.md's
verification runtime limit), so a stalled client or query fails instead of holding the scratch database for hours.
"""

from __future__ import annotations

import argparse
import os
import re
import subprocess
import sys
import time
from pathlib import Path

import psycopg
from dotenv import load_dotenv
from psycopg.conninfo import conninfo_to_dict, make_conninfo

SOURCE_DB = "stratai_test"
SOURCE_NAME = re.compile(r"^stratai_test(?:_[a-z0-9]+)*$")  # the test-database guard's naming rule
SCRATCH_DB = "stratai_test_deploy_public"
OUTPUT = Path(".deploy/stratai_public.dump")
BUDGET_SECONDS = 30 * 60
STATEMENT_TIMEOUT_MS = 10 * 60 * 1000

PUBLIC_SOURCES = ("tba", "statbotics")
# Children before parents (game_spec_versions references game_manuals), so no delete needs to cascade.
EMPTIED_TABLES = ("game_spec_versions", "game_manuals", "season_rulesets", "capability_profiles",
                  "human_review_artifacts", "scouting_observations", "scouting_access_codes")
# Team workspaces (migration 0012): every account, session, membership, invitation, log and team scouting row is
# private. All are emptied; each must be empty afterwards.
WORKSPACE_TABLES = ("workspace_scouting_reports", "scouting_assignments", "activity_logs", "auth_sessions",
                    "password_reset_tokens", "invitations", "workspace_role_permissions", "team_memberships",
                    "workspaces", "users", "auth_attempts")
WORKSPACE_SCRUB_ORDER = ("workspace_scouting_reports", "scouting_assignments", "workspaces", "users",
                         "auth_attempts")
SCRUB = [
    *(f"DELETE FROM {table}" for table in EMPTIED_TABLES),
    # canonical_lineage and data_quality_issues rows of a deleted payload go with it (ON DELETE CASCADE).
    "DELETE FROM raw_source_payloads WHERE source <> ALL(%(public)s)",
    "DELETE FROM canonical_lineage WHERE source <> ALL(%(public)s)",
    "DELETE FROM data_quality_issues WHERE source <> ALL(%(public)s) AND source <> 'pipeline'",
    "DELETE FROM source_watermarks WHERE source <> ALL(%(public)s)",
    """UPDATE team_metrics SET
           defense_score = NULL, defense_observation_count = 0, defense_agreement = NULL,
           defense_insufficient_data = TRUE,
           feeding_score = NULL, feeding_observation_count = 0, feeding_agreement = NULL,
           feeding_insufficient_data = TRUE,
           contributing_sources = ARRAY(SELECT s FROM unnest(contributing_sources) s WHERE s = ANY(%(public)s))""",
]
CHECKS = [
    *(f"SELECT count(*) FROM {table}" for table in EMPTIED_TABLES),
    "SELECT count(*) FROM raw_source_payloads WHERE source <> ALL(%(public)s)",
    "SELECT count(*) FROM canonical_lineage WHERE source <> ALL(%(public)s)",
    # data quality issues are recorded by the public sources or by the pipeline itself
    "SELECT count(*) FROM data_quality_issues WHERE source <> ALL(%(public)s) AND source <> 'pipeline'",
    "SELECT count(*) FROM source_watermarks WHERE source <> ALL(%(public)s)",
    "SELECT count(*) FROM team_metrics WHERE defense_score IS NOT NULL OR feeding_score IS NOT NULL "
    "OR defense_observation_count > 0 OR feeding_observation_count > 0 "
    "OR NOT contributing_sources <@ %(public)s::text[]",
]


def conninfo_for(base: str, dbname: str, **extra: str) -> str:
    params = conninfo_to_dict(base)
    params.update(dbname=dbname, **extra)
    return make_conninfo(**params)


def drop_scratch(admin: str) -> None:
    """Drop the scratch copy, ending only sessions connected to it (a stalled earlier run's included)."""
    with psycopg.connect(admin, autocommit=True) as conn:
        conn.execute(f"DROP DATABASE IF EXISTS {SCRATCH_DB} WITH (FORCE)")


def copy_source(pg_dump: str, pg_restore: str, source: str, scratch: str, timeout: float) -> None:
    """Stream the source's dump straight into the scratch copy, never holding it in memory or on disk."""
    dumper = subprocess.Popen([pg_dump, "--format=custom", "--no-owner", "--no-privileges", "--dbname", source],
                              stdout=subprocess.PIPE)
    try:
        subprocess.run([pg_restore, "--no-owner", "--no-privileges", "--exit-on-error", "--dbname", scratch],
                       stdin=dumper.stdout, check=True, timeout=timeout)
        dumper.stdout.close()
        if dumper.wait(timeout=timeout) != 0:
            raise subprocess.CalledProcessError(dumper.returncode, "pg_dump")
    finally:
        if dumper.poll() is None:
            dumper.kill()


def secret_occurrences(pg_restore: str, dump: Path, secrets: dict[str, str]) -> dict[str, int]:
    """Occurrences of each secret in the dump's SQL text. Values are never printed."""
    text = subprocess.run([pg_restore, "--file=-", str(dump)], capture_output=True, check=True).stdout
    return {label: text.count(value.encode()) for label, value in secrets.items() if value}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--source", default=SOURCE_DB, help="database to copy (read only)")
    parser.add_argument("--pg-bin", default="", help="directory holding pg_dump/pg_restore, if not on PATH")
    parser.add_argument("--snapshot", type=Path, help="D18 Statbotics snapshot directory, to verify the copy")
    parser.add_argument("--chain", type=Path, help="D18 EPA chain manifest, to verify the copy")
    args = parser.parse_args(argv)
    if (args.snapshot is None) != (args.chain is None):
        parser.error("--snapshot and --chain go together")
    if not SOURCE_NAME.match(args.source) or args.source == SCRATCH_DB:
        parser.error(f"refusing source {args.source!r}: only the isolated stratai_test copies may be exported")
    pg_dump, pg_restore = (str(Path(args.pg_bin) / tool) if args.pg_bin else tool for tool in ("pg_dump", "pg_restore"))
    load_dotenv()
    base = os.environ.get("DATABASE_URL")
    if not base:
        print("DATABASE_URL is not set", file=sys.stderr)
        return 2
    deadline = time.monotonic() + BUDGET_SECONDS

    def remaining(step: str) -> float:
        left = deadline - time.monotonic()
        if left <= 0:
            raise TimeoutError(f"time budget of {BUDGET_SECONDS}s exhausted before {step}")
        return left

    source, admin = (conninfo_for(base, name) for name in (args.source, "postgres"))
    scratch = conninfo_for(base, SCRATCH_DB, options=f"-c statement_timeout={STATEMENT_TIMEOUT_MS}")
    drop_scratch(admin)
    with psycopg.connect(admin, autocommit=True) as conn:
        conn.execute(f"CREATE DATABASE {SCRATCH_DB}")
    try:
        copy_source(pg_dump, pg_restore, source, conninfo_for(base, SCRATCH_DB), remaining("the copy"))
        params = {"public": list(PUBLIC_SOURCES)}
        with psycopg.connect(scratch) as conn:
            if conn.execute("SELECT current_database()").fetchone()[0] != SCRATCH_DB:
                raise RuntimeError(f"refusing to scrub: not connected to {SCRATCH_DB}")
            for statement in SCRUB:
                conn.execute(statement, params)
            # Accounts, sessions and team scouting (migration 0012), on a source new enough to have them. Deleting
            # the workspaces cascades their memberships, sessions, invitations and logs in one statement.
            present = [t for t in WORKSPACE_TABLES
                       if conn.execute("SELECT to_regclass(%s)", (f"public.{t}",)).fetchone()[0] is not None]
            for table in WORKSPACE_SCRUB_ORDER:
                if table in present:
                    conn.execute(f"DELETE FROM {table}")
            left = {check: conn.execute(check, params).fetchone()[0] for check in CHECKS}
            left.update({f"SELECT count(*) FROM {t}": conn.execute(f"SELECT count(*) FROM {t}").fetchone()[0]
                         for t in present})
        dirty = {check: count for check, count in left.items() if count}
        if dirty:
            for check, count in dirty.items():
                print(f"NOT SCRUBBED ({count} rows): {check}", file=sys.stderr)
            return 1
        with psycopg.connect(scratch, autocommit=True) as conn:
            conn.execute("ANALYZE")  # the restored copy has no planner statistics yet
        if args.snapshot is not None:
            from database.connection import Database, DatabaseConfig
            from ml.ratings.d18_source import load_d18_provider

            remaining("the D18 check")
            started = time.monotonic()
            _, integrity = load_d18_provider(Database(DatabaseConfig(scratch)), args.snapshot, args.chain)
            print(f"D18 EPA source check passed on the scrubbed copy in {time.monotonic() - started:.1f}s: "
                  f"{integrity}")
        OUTPUT.parent.mkdir(exist_ok=True)
        subprocess.run([pg_dump, "--format=custom", "--no-owner", "--no-privileges", "--file", str(OUTPUT),
                        "--dbname", scratch], check=True, timeout=remaining("the dump"))
        with psycopg.connect(scratch) as conn:
            counts = {table: conn.execute(f"SELECT count(*) FROM {table}").fetchone()[0]
                      for table in ("teams", "events", "matches", "match_teams", "team_event_stats", "team_metrics",
                                    "raw_source_payloads")}
    finally:
        drop_scratch(admin)
    found = secret_occurrences(pg_restore, OUTPUT, {"database password": conninfo_to_dict(base).get("password", ""),
                                                    "TBA API key": os.environ.get("TBA_API_KEY", "")})
    if any(found.values()):
        OUTPUT.unlink()
        print(f"a secret appears in the dump, so it was deleted: {found}", file=sys.stderr)
        return 1
    print(f"wrote {OUTPUT} ({OUTPUT.stat().st_size // 1024} KiB); scouting and human-input checks all 0; "
          f"secret scan {found}")
    for table, count in counts.items():
        print(f"  {table}: {count}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
