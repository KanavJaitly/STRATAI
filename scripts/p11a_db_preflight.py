"""P11A: check that the effective database is an isolated, ready copy before any P11A database test (read-only).

    python -m scripts.p11a_db_preflight            # prints a JSON report; exit 0 ready, 1 not ready, 2 refused

**Order of checks:**
1. **Before connecting:**
   - Resolve the effective DATABASE_URL exactly as `data.config.Settings` does (environment, then `.env`).
   - Print host, port and database name, never the password.
   - Refuse (exit 2) through `database.target_guard.check_target`, the migration runner's own guard: only a database
     on this machine (socket or loopback) named `stratai_test_<suffix>`. The serving `stratai`, Render and every other
     remote host are refused.
2. **Connect inside one READ ONLY transaction** (`database.connection.read_snapshot`).
   - The server must confirm the database name and a socket or loopback address (`verify_server`; exit 2 otherwise).
   - It must report `transaction_read_only = on`. Nothing here can write.
3. **Readiness:**
   - the migration history, judged as `database/migrate.py` judges it:
     - a missing `migrations_applied` on a populated database, or an incomplete history, is reported, not crashed on;
     - the pending files are listed, and the copy is `ready` only when none is pending;
   - per season 2023–2027: events, qualification matches, played qualification matches with a landed TBA score
     breakdown, and landed rankings;
   - team_metrics rows;
   - the live-draft tables.
4. **The 2027 holdout:**
   - Any 2027 row is reported, because the P11A database tests and E5 never read 2027.
   - Today none should exist: the 2027 season has not been played.

It never runs migrations and never creates or copies a database. See docs/p11a_verification.md for those steps.
"""

from __future__ import annotations

import json
import sys
from typing import Any

SEASONS = (2023, 2024, 2025, 2026, 2027)


def refuse_unless_isolated(url: str):
    """The checked target, or SystemExit(2) when it is not a local stratai_test_<suffix> database. No connection."""
    from database.target_guard import TargetRefused, check_target

    try:
        return check_target(url)
    except TargetRefused as exc:
        print(json.dumps({"status": "refused", "code": exc.code, "reason": exc.message}, indent=1))
        raise SystemExit(2) from None


def _scalar(cursor: Any, sql: str, params: tuple = ()) -> Any:
    cursor.execute(sql, params)
    row = cursor.fetchone()
    return None if row is None else row[0]


DATA_TABLES = ("events", "matches", "raw_source_payloads", "team_metrics")


def inspect(database: Any, target: Any) -> dict[str, Any]:
    """The readiness report (read-only). TargetRefused when the server is not the checked local test database."""
    from database.migrate import MigrationRefused, _migration_files, _state, plan_pending
    from database.target_guard import verify_server

    report: dict[str, Any] = {}
    with database.cursor() as c:
        report["server"] = verify_server(c, target)
        report["transaction_read_only"] = _scalar(c, "SELECT current_setting('transaction_read_only')")
        recorded, tables = _state(c)
        report["migration_history"] = "missing" if recorded is None else "present"
        report["migrations_recorded"] = list(recorded or ())
        report["application_tables"] = tables
        try:
            report["migrations_pending"] = list(plan_pending(list(_migration_files()), recorded, tables))
            report["migration_problem"] = None
        except MigrationRefused as exc:
            report["migrations_pending"] = None
            report["migration_problem"] = f"{exc.code}: {exc.message}"
        present = {t for t in DATA_TABLES if _scalar(c, "SELECT to_regclass(%s) IS NOT NULL", (f"public.{t}",))}
        report["data_tables_missing"] = sorted(set(DATA_TABLES) - present)
        seasons: dict[int, Any] = {}
        if not report["data_tables_missing"]:
            for season in SEASONS:
                seasons[season] = {
                    "events": _scalar(c, "SELECT count(*) FROM events WHERE season = %s", (season,)),
                    "qualification_matches": _scalar(
                        c, "SELECT count(*) FROM matches WHERE season = %s AND competition_level = 'qualification'",
                        (season,)),
                    "played_with_breakdown": _scalar(
                        c, "SELECT count(*) FROM matches m WHERE m.season = %s AND m.competition_level = "
                           "'qualification' AND m.score_red IS NOT NULL AND EXISTS (SELECT 1 FROM raw_source_payloads "
                           "p WHERE p.source_object_id = m.match_key AND p.is_current)", (season,)),
                    "landed_rankings": _scalar(
                        c, "SELECT count(DISTINCT p.source_object_id) FROM raw_source_payloads p JOIN events e ON "
                           "e.event_key = p.source_object_id WHERE e.season = %s AND p.source_object_type = "
                           "'event_ranking' AND p.is_current", (season,)),
                }
            report["team_metrics_rows"] = _scalar(c, "SELECT count(*) FROM team_metrics")
        report["seasons"] = seasons
        report["live_draft_tables"] = _scalar(
            c, "SELECT count(*) FROM information_schema.tables WHERE table_schema = 'public' "
               "AND table_name IN ('draft_records', 'draft_actions')")
    return report


def problems_of(report: dict[str, Any]) -> list[str]:
    problems = []
    if report["transaction_read_only"] != "on":
        problems.append("the inspection transaction is not read-only")
    if report["migration_problem"]:
        problems.append(f"migration history: {report['migration_problem']}")
    elif report["migrations_pending"]:
        problems.append(f"migrations pending: {report['migrations_pending']}")
    if report["data_tables_missing"]:
        problems.append(f"data tables missing: {report['data_tables_missing']}")
    elif not any((report["seasons"][s]["played_with_breakdown"] or 0) > 0 for s in (2024, 2025, 2026)):
        problems.append("no played 2024-2026 qualification match with a landed breakdown (not a real-data copy)")
    if report["live_draft_tables"] != 2:
        problems.append("live-draft tables missing (migration 0013)")
    holdout = report["seasons"].get(2027) or {}
    if any(holdout.values()):
        problems.append(f"2027 rows exist {holdout}: the 2027 holdout must not be read by P11A tests or E5")
    return problems


def main() -> int:
    import psycopg

    from data.config import Settings
    from database.connection import Database, DatabaseConfig, read_snapshot
    from database.target_guard import TargetRefused

    url = str(Settings().database_url)
    target = refuse_unless_isolated(url)
    try:
        with read_snapshot(Database(DatabaseConfig(url))) as database:
            report = inspect(database, target)
    except TargetRefused as exc:
        print(json.dumps({"target": target.describe(), "status": "refused", "code": exc.code,
                          "reason": exc.message}, indent=1))
        return 2
    except psycopg.OperationalError as exc:
        print(json.dumps({"target": target.describe(), "status": "database_unavailable",
                          "reason": str(exc).splitlines()[0]}, indent=1))
        return 1
    problems = problems_of(report)
    print(json.dumps({"target": target.describe(), "status": "ready" if not problems else "not_ready",
                      "problems": problems, **report}, indent=1, default=str))
    return 0 if not problems else 1


if __name__ == "__main__":
    sys.exit(main())
