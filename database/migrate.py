"""Apply database/migrations/*.sql, guarded so that only an isolated local test database can be migrated.

    python database/migrate.py                                               # report only: target and pending files
    python database/migrate.py --apply --confirm-database stratai_test_x     # apply, after every check passes

**Guard (2026-11-07; database/target_guard.py).** It refuses, before connecting:
- Render and every other remote host;
- the serving `stratai`;
- any database that is not `stratai_test_<suffix>`.

After connecting, the server itself must confirm the database name and a socket or loopback address.

**There is no production override.** The hosted database is loaded from a dump (docs/DEPLOYMENT.md) and is never
migrated by this script.

**History checks, before anything is applied:**
- **Missing history.** No `migrations_applied` table while application tables exist: refused.
- **Incomplete history.** The recorded files must be exactly the first N migration files, with no gap and no unknown
  name: refused otherwise.
- **Destructive pending migrations.** A pending migration that drops a table or schema, truncates, or deletes rows,
  on a database that already has application tables: refused. On an empty database the whole sequence may run;
  0005's drops then touch tables created moments earlier in the same transaction.

**Confirmation.** `--apply` also needs `--confirm-database` equal to the target's name. Without it, the script only
reports the target and what is pending.

**Atomicity.** All pending files apply in one transaction, with the checks, so a failure leaves nothing applied.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from data.config import Settings  # noqa: E402
from database.connection import Database, DatabaseConfig  # noqa: E402
from database.target_guard import Target, TargetRefused, check_target, verify_server  # noqa: E402

MIGRATIONS_DIR = Path(__file__).resolve().parent / "migrations"
HISTORY_TABLE = "migrations_applied"
DESTRUCTIVE = re.compile(r"\b(DROP\s+TABLE|DROP\s+SCHEMA|DROP\s+DATABASE|TRUNCATE|DELETE\s+FROM)\b", re.IGNORECASE)


class MigrationRefused(TargetRefused):
    """The database's state makes applying the pending migrations unsafe."""


@dataclass(frozen=True)
class MigrationPlan:
    target: Target
    server: dict
    recorded: tuple[str, ...]
    pending: tuple[str, ...]
    application_tables: int

    def report(self) -> dict:
        return {"target": self.target.describe(), "server": self.server, "recorded": list(self.recorded),
                "pending": list(self.pending), "application_tables": self.application_tables}


def _migration_files() -> Iterable[Path]:
    """Return migration SQL files in application order."""
    return sorted(MIGRATIONS_DIR.glob("*.sql"))


def _without_comments(sql: str) -> str:
    return re.sub(r"--[^\n]*", "", sql)


def destructive(sql: str) -> bool:
    """True when the SQL (comments ignored) drops a table or schema, truncates, or deletes rows."""
    return bool(DESTRUCTIVE.search(_without_comments(sql)))


def plan_pending(files: Sequence[Path], recorded: Sequence[str] | None, application_tables: int) -> tuple[str, ...]:
    """The pending file names, or MigrationRefused when the history is missing, incomplete or unsafe to extend.
    `recorded` is None when the history table does not exist."""
    names = [f.name for f in files]
    if recorded is None:
        if application_tables:
            raise MigrationRefused("missing_history", f"{application_tables} application table(s) exist but "
                                                      f"{HISTORY_TABLE} does not: the history is missing")
        recorded = []
    unknown = sorted(set(recorded) - set(names))
    if unknown:
        raise MigrationRefused("unknown_history", f"{HISTORY_TABLE} records files this checkout lacks: {unknown}")
    if sorted(recorded) != names[:len(recorded)]:
        missing = [n for n in names[:max((names.index(r) for r in recorded), default=-1) + 1] if n not in recorded]
        raise MigrationRefused("incomplete_history", f"{HISTORY_TABLE} is not a complete prefix; missing {missing}")
    pending = names[len(recorded):]
    if application_tables:
        risky = [f.name for f in files if f.name in pending and destructive(f.read_text(encoding="utf-8"))]
        if risky:
            raise MigrationRefused("destructive_pending", f"pending migration(s) {risky} drop, truncate or delete on "
                                                          "a database that already has application tables")
    return tuple(pending)


def _state(cursor) -> tuple[tuple[str, ...] | None, int]:
    cursor.execute("SELECT to_regclass(%s) IS NOT NULL", (f"public.{HISTORY_TABLE}",))
    exists = cursor.fetchone()[0]
    cursor.execute("SELECT count(*) FROM information_schema.tables WHERE table_schema = 'public' "
                   "AND table_type = 'BASE TABLE' AND table_name <> %s", (HISTORY_TABLE,))
    tables = int(cursor.fetchone()[0])
    if not exists:
        return None, tables
    cursor.execute(f"SELECT migration_file FROM {HISTORY_TABLE} ORDER BY migration_file")
    return tuple(r[0] for r in cursor.fetchall()), tables


def inspect(database: Database, target: Target, cursor=None) -> MigrationPlan:
    """The plan for `target` (every check, nothing applied)."""
    def run(cur) -> MigrationPlan:
        server = verify_server(cur, target)
        recorded, tables = _state(cur)
        pending = plan_pending(list(_migration_files()), recorded, tables)
        return MigrationPlan(target, server, recorded or (), pending, tables)

    if cursor is not None:
        return run(cursor)
    with database.cursor() as cur:
        return run(cur)


def run_migrations(settings: Settings) -> MigrationPlan:
    """Apply every pending migration in one transaction, after the guard and the history checks pass."""
    target = check_target(str(settings.database_url))  # before any connection
    database = Database(DatabaseConfig(settings.database_url))
    with database.cursor() as cursor:
        plan = inspect(database, target, cursor)
        cursor.execute(f"CREATE TABLE IF NOT EXISTS {HISTORY_TABLE} (migration_file TEXT PRIMARY KEY, "
                       "applied_at TIMESTAMPTZ NOT NULL DEFAULT NOW())")
        for name in plan.pending:
            cursor.execute((MIGRATIONS_DIR / name).read_text(encoding="utf-8"))
            cursor.execute(f"INSERT INTO {HISTORY_TABLE} (migration_file) VALUES (%s)", (name,))
    return plan


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Apply StratAI migrations to an isolated local test database only.")
    parser.add_argument("--apply", action="store_true", help="apply the pending migrations (default: report only)")
    parser.add_argument("--confirm-database", help="required with --apply: the target database's exact name")
    args = parser.parse_args(argv)
    settings = Settings()
    try:
        target = check_target(str(settings.database_url))
        if not args.apply:
            plan = inspect(Database(DatabaseConfig(settings.database_url)), target)
            print(json.dumps({"mode": "report_only", **plan.report()}, indent=1))
            return 0
        if args.confirm_database != target.dbname:
            raise TargetRefused("not_confirmed", "--apply needs --confirm-database equal to the target's name")
        plan = run_migrations(settings)
    except TargetRefused as exc:
        print(json.dumps({"status": "refused", "code": exc.code, "message": exc.message}, indent=1))
        return 2
    print(json.dumps({"mode": "applied", **plan.report()}, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
