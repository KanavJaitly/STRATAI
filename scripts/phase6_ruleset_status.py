"""READ-ONLY status of the P6-M1 2024-2026 rulesets, for the reviewer's verification steps.

    .\\.venv\\Scripts\\python.exe -m scripts.phase6_ruleset_status

Prints the target database (host, port, name), every 2024-2026 `season_rulesets` row with its full sha256 and status,
whether each v2 row matches the expected v2 hash, and whether each approval-record file exists. Opens a read-only
session: it can never write.
"""

from __future__ import annotations

import sys
from pathlib import Path
from urllib.parse import urlparse

EXPECTED_V2 = {
    2024: "6b3d221227090d4378ef6a6778de70ced410822412a35daa72bcf0c590902971",
    2025: "0ad72856f82dd1abe9d149d27a76124cbec7916d4e97a30645a772b5020f8d7e",
    2026: "7695b4a9f0058a0aff3007ac35939bbb075f5afa2757b4635ce3284a6d66a930",
}
RECORD_DIR = Path(".agent/phase6/decisions")


def main() -> int:
    import psycopg

    from data.config import Settings

    url = str(Settings().database_url)
    target = urlparse(url)
    print(f"target database: {target.hostname}:{target.port}{target.path}")
    with psycopg.connect(url) as connection:
        connection.execute("SET default_transaction_read_only = on")
        rows = connection.execute(
            "SELECT id, season, version, status, created_by, reviewed_by, ruleset_sha256 FROM season_rulesets "
            "WHERE season IN (2024, 2025, 2026) ORDER BY season, version").fetchall()
    for rid, season, version, status, author, reviewer, sha in rows:
        check = ""
        if version >= 2:
            check = "  MATCH" if sha == EXPECTED_V2.get(season) else "  MISMATCH (expected " + EXPECTED_V2[season] + ")"
        print(f"id {rid}  {season} v{version}  {status:<16} reviewed_by={reviewer or '-'}\n    sha256 {sha}{check}")
    for season in EXPECTED_V2:
        approved = [r for r in rows if r[1] == season and r[3] == "approved"]
        record = RECORD_DIR / f"P6_M1_APPROVAL_{season}_v{approved[0][2]}.json" if approved else None
        state = ("approved v%d, record %s" % (approved[0][2], "present" if record.exists() else "MISSING")
                 if approved else "not approved")
        print(f"{season}: {state}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
