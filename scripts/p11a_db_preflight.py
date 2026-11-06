"""P11A: check that the effective database is an isolated, ready copy before any P11A database test (read-only).

    python -m scripts.p11a_db_preflight            # prints a JSON report; exit 0 ready, 1 not ready, 2 refused

**Order of checks:**
1. **Before connecting:**
   - Resolve the effective DATABASE_URL exactly as `data.config.Settings` does (environment, then `.env`).
   - Print host, port and database name, never the password.
   - Refuse (exit 2) unless the name is an isolated test copy (`stratai_test` or `stratai_test_<suffix>`, the rule
     in tests/db_guard.py). The serving `stratai` is refused by name.
2. **Connect inside one READ ONLY transaction** (`database.connection.read_snapshot`) and confirm the server reports
   `transaction_read_only = on`. Nothing here can write.
3. **Readiness:**
   - migrations 0001–0013 recorded in `migrations_applied`;
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
MIGRATIONS = tuple(f"{n:04d}" for n in range(1, 14))


def destination(url: str) -> dict[str, Any]:
    from psycopg.conninfo import conninfo_to_dict

    parts = conninfo_to_dict(url)
    return {"host": parts.get("host", "localhost"), "port": parts.get("port", "5432"), "dbname": parts.get("dbname")}


def refuse_unless_isolated(url: str) -> dict[str, Any]:
    """The destination, or SystemExit(2) when it is not an isolated test copy. Runs before any connection."""
    from tests.db_guard import SERVING_DATABASE, is_allowed_test_database

    where = destination(url)
    if where["dbname"] == SERVING_DATABASE or not is_allowed_test_database(where["dbname"]):
        print(json.dumps({"destination": where, "status": "refused",
                          "reason": "not an isolated stratai_test / stratai_test_<suffix> database"}, indent=1))
        raise SystemExit(2)
    return where


def _scalar(cursor: Any, sql: str, params: tuple = ()) -> Any:
    cursor.execute(sql, params)
    row = cursor.fetchone()
    return None if row is None else row[0]


def inspect(database: Any) -> dict[str, Any]:
    report: dict[str, Any] = {}
    with database.cursor() as c:
        report["transaction_read_only"] = _scalar(c, "SELECT current_setting('transaction_read_only')")
        report["server_version"] = _scalar(c, "SHOW server_version")
        c.execute("SELECT migration_file FROM migrations_applied")
        applied = {r[0][:4] for r in c.fetchall()}
        report["migrations_missing"] = [m for m in MIGRATIONS if m not in applied]
        seasons = {}
        for season in SEASONS:
            seasons[season] = {
                "events": _scalar(c, "SELECT count(*) FROM events WHERE season = %s", (season,)),
                "qualification_matches": _scalar(
                    c, "SELECT count(*) FROM matches WHERE season = %s AND competition_level = 'qualification'",
                    (season,)),
                "played_with_breakdown": _scalar(
                    c, "SELECT count(*) FROM matches m WHERE m.season = %s AND m.competition_level = 'qualification' "
                       "AND m.score_red IS NOT NULL AND EXISTS (SELECT 1 FROM raw_source_payloads p WHERE "
                       "p.source_object_id = m.match_key AND p.is_current)", (season,)),
                "landed_rankings": _scalar(
                    c, "SELECT count(DISTINCT p.source_object_id) FROM raw_source_payloads p JOIN events e ON "
                       "e.event_key = p.source_object_id WHERE e.season = %s AND p.source_object_type = "
                       "'event_ranking' AND p.is_current", (season,)),
            }
        report["seasons"] = seasons
        report["team_metrics_rows"] = _scalar(c, "SELECT count(*) FROM team_metrics")
        report["live_draft_tables"] = _scalar(
            c, "SELECT count(*) FROM information_schema.tables WHERE table_name IN ('draft_records', 'draft_actions')")
    return report


def main() -> int:
    from data.config import Settings
    from database.connection import Database, DatabaseConfig, read_snapshot

    url = str(Settings().database_url)
    where = refuse_unless_isolated(url)
    import psycopg

    try:
        with read_snapshot(Database(DatabaseConfig(url))) as database:
            report = inspect(database)
    except psycopg.OperationalError as exc:
        print(json.dumps({"destination": where, "status": "database_unavailable",
                          "reason": str(exc).splitlines()[0]}, indent=1))
        return 1
    problems = []
    if report["transaction_read_only"] != "on":
        problems.append("the inspection transaction is not read-only")
    if report["migrations_missing"]:
        problems.append(f"migrations not applied: {report['migrations_missing']}")
    if not any((report["seasons"][s]["played_with_breakdown"] or 0) > 0 for s in (2024, 2025, 2026)):
        problems.append("no played 2024-2026 qualification match with a landed breakdown (not a real-data copy)")
    if report["live_draft_tables"] != 2:
        problems.append("live-draft tables missing (migration 0013)")
    holdout = report["seasons"][2027]
    if any(holdout.values()):
        problems.append(f"2027 rows exist {holdout}: the 2027 holdout must not be read by P11A tests or E5")
    print(json.dumps({"destination": where, "status": "ready" if not problems else "not_ready",
                      "problems": problems, **report}, indent=1, default=str))
    return 0 if not problems else 1


if __name__ == "__main__":
    sys.exit(main())
