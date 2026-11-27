"""Create the local development database `stratai_dev_fresh` (audit 2026-11-26, workstream 6).

    python -m scripts.local_dev_db --create             # copy stratai_test, then apply every current migration
    python -m scripts.local_dev_db --create --replace   # drop and recreate it (only stratai_dev_fresh is ever dropped)
    python -m scripts.local_dev_db --status             # its migration level and account count
    python -m scripts.local_test_env --serve            # then run the API on it (the default database)

**Why it exists.** `stratai_test` stops at migration 0014 and holds records that must be kept (the 2024njfla live
draft replay, the Phase 11 evidence), while the current sign-in code needs 0015 and 0016. Migrating `stratai_test`
would delete every account in it (0015 does that by design). So local development gets its own copy instead.

**What it does.**
1. `CREATE DATABASE stratai_dev_fresh TEMPLATE stratai_test`. A template copy only reads its source, and it refuses
   when anything is connected to `stratai_test`.
2. Runs `database.migrate` against the copy only, after checking `current_database()` is `stratai_dev_fresh`. Its
   accounts start empty (0015), with team 11's workspace ready for sign-up.

It never writes to `stratai` (serving) or to `stratai_test`, and it can drop only `stratai_dev_fresh`. Tests never
run against it: the test-database guard (tests/db_guard.py) admits only `stratai_test` and `stratai_test_<suffix>`.
"""

from __future__ import annotations

import argparse
import sys

import psycopg
from psycopg import sql

from data.config import Settings
from scripts.phase5_isolated_db import isolated_url

DEV_DATABASE = "stratai_dev_fresh"
SOURCE_DATABASE = "stratai_test"
PROTECTED = frozenset({"stratai", SOURCE_DATABASE})


def dev_url() -> str:
    """The configured server's URL, pointed at the development copy."""
    return isolated_url(str(Settings().database_url), DEV_DATABASE)


def create(*, replace: bool = False) -> None:
    """Copy stratai_test into stratai_dev_fresh by template (refusing if it exists, unless replace)."""
    assert DEV_DATABASE not in PROTECTED
    admin_url = isolated_url(str(Settings().database_url), "postgres")
    with psycopg.connect(admin_url, autocommit=True) as admin:
        exists = admin.execute("SELECT 1 FROM pg_database WHERE datname = %s", (DEV_DATABASE,)).fetchone()
        if exists and not replace:
            raise SystemExit(f"{DEV_DATABASE} exists; pass --replace to recreate it")
        busy = admin.execute("SELECT count(*) FROM pg_stat_activity WHERE datname = %s",
                             (SOURCE_DATABASE,)).fetchone()[0]
        if busy:
            raise SystemExit(f"{SOURCE_DATABASE} has {busy} open connection(s); a template copy needs none")
        if exists:
            admin.execute(sql.SQL("DROP DATABASE {}").format(sql.Identifier(DEV_DATABASE)))
        admin.execute(sql.SQL("CREATE DATABASE {} TEMPLATE {}").format(sql.Identifier(DEV_DATABASE),
                                                                       sql.Identifier(SOURCE_DATABASE)))


def migrate() -> None:
    """Apply every current migration to stratai_dev_fresh, after confirming that is the database connected to."""
    from database.migrate import run_migrations

    url = dev_url()
    with psycopg.connect(url) as conn:
        name = conn.execute("SELECT current_database()").fetchone()[0]
    if name != DEV_DATABASE or name in PROTECTED:
        raise SystemExit(f"refusing: connected to {name!r}, not {DEV_DATABASE}")
    run_migrations(Settings(database_url=url))


def status() -> dict[str, object]:
    with psycopg.connect(dev_url()) as conn:
        latest, count = conn.execute("SELECT max(migration_file), count(*) FROM migrations_applied").fetchone()
        accounts = conn.execute("SELECT count(*) FROM users").fetchone()[0]
        drafts = conn.execute("SELECT count(*) FROM draft_records").fetchone()[0]
    return {"database": DEV_DATABASE, "latest_migration": latest, "migrations_applied": count,
            "accounts": accounts, "draft_records": drafts}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--create", action="store_true")
    parser.add_argument("--replace", action="store_true")
    parser.add_argument("--status", action="store_true")
    args = parser.parse_args(argv)
    if args.create:
        create(replace=args.replace)
        migrate()
        print(f"created {DEV_DATABASE} from {SOURCE_DATABASE} and applied every migration")
    if args.status or args.create:
        print(status())
    return 0


if __name__ == "__main__":
    sys.exit(main())
