"""P11A: copy one approved P5-M8 GameSpec row from one local test copy to another, byte-for-byte.

    python -m scripts.p11a_gamespec_copy export --season 2026 --out <file.json>        # DATABASE_URL = the source copy
    python -m scripts.p11a_gamespec_copy import --file <file.json> --confirm-database stratai_test_<suffix>
                                                                                      # DATABASE_URL = the target copy
    python -m scripts.p11a_gamespec_copy verify --file <file.json>                    # DATABASE_URL = any copy

**Why a copy, not a second entry.** The server fills `source.entered_by`, `entry_started_at` and `entry_completed_at`
into a spec when it is saved (`data/human_inputs.py` `_validate_spec`). Entering the same spec again on another
database gives another sha256, and a scoring configuration that references the first no longer matches. So a spec is
entered and reviewed once, through the web app, and then copied.

**What it does not do.** It never creates, edits, submits, reviews or approves a spec. It copies a row that a person
approved, and only an approved row (`status = 'approved'`).

**Databases (database/target_guard.py, checked before connecting and confirmed by the server):**
- **export** reads, in a READ ONLY transaction, from a local `stratai_test` or `stratai_test_<suffix>`. The bare
  `stratai_test` is allowed here because the web app's human-input pages run on it (`scripts/local_test_env.py`).
- **import** writes only to a local `stratai_test_<suffix>`, with `--confirm-database` equal to its name, in one
  transaction.
- The serving `stratai`, every other name and every remote host are refused by all three.

**Byte-for-byte.**
- The export file carries `spec_json` as PostgreSQL's own text form of the JSONB value. Every other column comes
  verbatim too: version, status, the reviewer, the timestamps to the microsecond, and the note.
- **Two exceptions:** `manual_id` and `based_on_id` point at rows of the source database. They are recorded in the
  file and imported as NULL.
- Checked at every step:
  - export: the row's `spec_sha256` equals `GameSpec.sha256()` of its `spec_json`;
  - import: the file's own `row_sha256` and the spec sha256, before writing;
  - after inserting: the stored `spec_json` text and the sha256 must equal the file's, or the transaction is rolled
    back.
- **Refused:** a target that already holds an approved spec for the season, or the same (season, version). The one
  exception is the identical row, which reports `already_present` and writes nothing.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

EXPORT_KIND = "p11a_game_spec_export"
EXPORT_FORMAT = 1
COLUMNS = ("season", "version", "spec_json", "complete", "validation_errors", "spec_sha256", "manual_id",
           "based_on_id", "status", "created_by", "created_at", "entry_started_at", "submitted_at", "reviewed_by",
           "reviewed_at", "review_note")
TEXT_COLUMNS = {"spec_json", "validation_errors"}  # read as PostgreSQL's text form of the JSONB value
TIME_COLUMNS = {"created_at", "entry_started_at", "submitted_at", "reviewed_at"}
_SELECT = ", ".join(f"{c}::text" if c in TEXT_COLUMNS else c for c in COLUMNS)


class CopyRefused(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


def row_sha256(row: dict[str, Any]) -> str:
    return hashlib.sha256(json.dumps(row, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()


def spec_sha256_of(spec_json_text: str) -> str:
    from data.game_spec import GameSpec

    return GameSpec.model_validate_json(spec_json_text).sha256()


def _row_from_db(values: tuple) -> dict[str, Any]:
    row = dict(zip(COLUMNS, values))
    for c in TIME_COLUMNS:  # the same instant, printed in UTC whatever the session's TimeZone
        if isinstance(row[c], datetime):
            row[c] = row[c].astimezone(timezone.utc).isoformat()
    return row


def build_export(row: dict[str, Any], source: dict[str, Any]) -> dict[str, Any]:
    """The export document for one approved row (pure). CopyRefused unless it is approved and its sha256 holds."""
    if row["status"] != "approved":
        raise CopyRefused("not_approved", f"spec {row['season']} v{row['version']} is {row['status']}, not approved")
    actual = spec_sha256_of(row["spec_json"])
    if actual != row["spec_sha256"]:
        raise CopyRefused("spec_sha256_mismatch", f"stored spec_sha256 {row['spec_sha256']} != computed {actual}")
    return {"kind": EXPORT_KIND, "format": EXPORT_FORMAT, "source": source,
            "exported_at": datetime.now(timezone.utc).isoformat(), "row": row, "row_sha256": row_sha256(row)}


def check_export(document: dict[str, Any]) -> dict[str, Any]:
    """The row of a valid export file (pure). CopyRefused if the file is not one, was altered, or its spec fails."""
    if document.get("kind") != EXPORT_KIND or document.get("format") != EXPORT_FORMAT:
        raise CopyRefused("not_an_export", "the file is not a p11a_game_spec_export (format 1)")
    row = document.get("row")
    if not isinstance(row, dict) or set(row) != set(COLUMNS):
        raise CopyRefused("not_an_export", "the export's row does not have exactly the game_spec_versions columns")
    if row_sha256(row) != document.get("row_sha256"):
        raise CopyRefused("altered_export", "the row does not match the file's row_sha256 (altered after export)")
    if row["status"] != "approved":
        raise CopyRefused("not_approved", f"the exported row is {row['status']}, not approved")
    if spec_sha256_of(row["spec_json"]) != row["spec_sha256"]:
        raise CopyRefused("spec_sha256_mismatch", "the exported spec_json does not hash to its spec_sha256")
    return row


def _connect(url: str, *, read_only: bool, allow_bare_test: bool):
    import psycopg

    from database.target_guard import check_target, verify_server

    target = check_target(url, allow_bare_test=allow_bare_test)  # before connecting
    conn = psycopg.connect(url)
    conn.read_only = read_only
    with conn.cursor() as cursor:
        server = verify_server(cursor, target)
    return conn, target, server


def export_row(url: str, season: int) -> dict[str, Any]:
    conn, target, server = _connect(url, read_only=True, allow_bare_test=True)
    try:
        with conn.cursor() as cursor:
            cursor.execute(f"SELECT {_SELECT} FROM game_spec_versions WHERE season = %s AND status = 'approved'",
                           (season,))
            rows = cursor.fetchall()
    finally:
        conn.rollback()
        conn.close()
    if not rows:
        raise CopyRefused("no_approved_spec", f"{target.dbname} has no approved GameSpec for {season}")
    return build_export(_row_from_db(rows[0]), {"database": target.dbname, "server": server})


def import_row(conn: Any, row: dict[str, Any]) -> dict[str, Any]:
    """Insert `row` (from `check_export`) in the caller's transaction; read it back and verify (raises on mismatch)."""
    with conn.cursor() as cursor:
        cursor.execute(f"SELECT {_SELECT} FROM game_spec_versions WHERE season = %s "
                       "AND (status = 'approved' OR version = %s)", (row["season"], row["version"]))
        existing = [_row_from_db(r) for r in cursor.fetchall()]
        same = [e for e in existing if e["spec_json"] == row["spec_json"] and e["spec_sha256"] == row["spec_sha256"]
                and e["version"] == row["version"] and e["status"] == "approved"]
        if same:
            return {"status": "already_present", "season": row["season"], "version": row["version"]}
        if existing:
            clash = existing[0]
            raise CopyRefused("target_conflict", f"the target already has {row['season']} v{clash['version']} "
                                                 f"({clash['status']}); nothing written")
        values = [None if c in ("manual_id", "based_on_id") else row[c] for c in COLUMNS]
        placeholders = ", ".join("%s::jsonb" if c in TEXT_COLUMNS else "%s" for c in COLUMNS)
        cursor.execute(f"INSERT INTO game_spec_versions ({', '.join(COLUMNS)}) VALUES ({placeholders}) "
                       "RETURNING id, spec_json::text, spec_sha256", values)
        new_id, stored_text, stored_sha = cursor.fetchone()
    if stored_text != row["spec_json"]:
        raise CopyRefused("readback_mismatch", "the stored spec_json text differs from the export; rolled back")
    if stored_sha != row["spec_sha256"] or spec_sha256_of(stored_text) != row["spec_sha256"]:
        raise CopyRefused("readback_mismatch", "the stored spec does not hash to the exported sha256; rolled back")
    return {"status": "imported", "id": new_id, "season": row["season"], "version": row["version"],
            "spec_sha256": stored_sha, "source_manual_id": row["manual_id"], "source_based_on_id": row["based_on_id"],
            "note": "manual_id and based_on_id point at the source database and were imported as NULL"}


def verify_row(url: str, row: dict[str, Any]) -> dict[str, Any]:
    conn, target, _ = _connect(url, read_only=True, allow_bare_test=True)
    try:
        with conn.cursor() as cursor:
            cursor.execute(f"SELECT {_SELECT} FROM game_spec_versions WHERE season = %s AND status = 'approved'",
                           (row["season"],))
            found = [_row_from_db(r) for r in cursor.fetchall()]
    finally:
        conn.rollback()
        conn.close()
    if not found:
        return {"database": target.dbname, "identical": False, "reason": "no approved spec for the season"}
    differing = sorted(c for c in COLUMNS if c not in ("manual_id", "based_on_id") and found[0][c] != row[c])
    return {"database": target.dbname, "identical": not differing, "differing_columns": differing}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    sub = parser.add_subparsers(dest="command", required=True)
    exp = sub.add_parser("export")
    exp.add_argument("--season", type=int, required=True)
    exp.add_argument("--out", type=Path, required=True)
    imp = sub.add_parser("import")
    imp.add_argument("--file", type=Path, required=True)
    imp.add_argument("--confirm-database", required=True)
    ver = sub.add_parser("verify")
    ver.add_argument("--file", type=Path, required=True)
    args = parser.parse_args(argv)

    from data.config import Settings
    from database.target_guard import TargetRefused, check_target

    url = str(Settings().database_url)
    try:
        if args.command == "export":
            if args.out.exists():
                raise CopyRefused("exists", f"{args.out} exists; exports are never overwritten")
            document = export_row(url, args.season)
            args.out.write_text(json.dumps(document, indent=1, sort_keys=True) + "\n", encoding="utf-8")
            result = {"status": "exported", "file": str(args.out), "season": args.season,
                      "version": document["row"]["version"], "spec_sha256": document["row"]["spec_sha256"],
                      "row_sha256": document["row_sha256"], "source": document["source"]["database"]}
        elif args.command == "import":
            row = check_export(json.loads(args.file.read_text(encoding="utf-8")))
            target = check_target(url)  # writers: stratai_test_<suffix> only, never the bare copy
            if args.confirm_database != target.dbname:
                raise CopyRefused("not_confirmed", "--confirm-database must equal the target database's name")
            import psycopg

            from database.target_guard import verify_server

            with psycopg.connect(url) as conn:  # one transaction: committed only if every check passes
                with conn.cursor() as cursor:
                    verify_server(cursor, target)
                result = import_row(conn, row)
        else:
            result = verify_row(url, check_export(json.loads(args.file.read_text(encoding="utf-8"))))
    except (CopyRefused, TargetRefused) as exc:
        print(json.dumps({"status": "refused", "code": exc.code, "message": exc.message}, indent=1))
        return 2
    print(json.dumps(result, indent=1, default=str))
    return 0


if __name__ == "__main__":
    sys.exit(main())
