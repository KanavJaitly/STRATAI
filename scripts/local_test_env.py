"""The local test configuration for exercising STRATAI end to end on historical seasons (2026-10-11).

    python -m scripts.local_test_env --print          # show the environment (no secrets)
    python -m scripts.local_test_env --serve           # run the API on http://127.0.0.1:8765 against stratai_test
    python -m scripts.local_test_env --serve --database stratai_test_2023 --port 8766   # 2023, kept in its own copy
    python -m scripts.local_test_env --checklist-files DIR   # the SYNTHETIC PDFs docs/browser_acceptance_checklist.md uses
    python -m scripts.local_test_env --cleanup-checklist     # remove what that checklist created in stratai_test
    python -m scripts.local_test_env --cleanup-checklist --actor "Checklist Automation"   # the Playwright run's rows

**What it is:**
- an API instance pointed at the isolated `stratai_test` copy (the test-database guard's rule), with the evaluated
  D18 models pinned by sha256 and the frozen D18 EPA snapshot, so the analysis endpoints answer;
- uploads and P6-M1 approval records go to a scratch directory, never into the repository or the real upload store.

**Why 2023 has its own copy (2026-10-12):** ml.ratings.provider.read_team_event_facts reads every event in the
database, so 2023 team-events in stratai_test would become D13 prior-event candidates for 2024-2026 targets and change
the frozen D18 lookups (3,076 2024 team-events). stratai_test keeps 2024-2026 only; stratai_test_2023 adds 2023.

**What it is not:** the serving configuration.
- It never reads or writes the serving database.
- It changes no `.env`, no deployment and no pin of record.
- The pins are the existing registry artifacts' own sha256s, verified at load as usual.
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

ARTIFACTS = Path("C:/Dev/StratAI-artifacts")
SCRATCH = ARTIFACTS / "local_test"
PINS = {
    "ML_REGISTRY_DIR": str(ARTIFACTS / "ml_registry"),
    "ML_RANKING_MODEL_VERSION_TAG": "d18",
    "ML_RANKING_MODEL_SHA256": "1f0fe5aae90244e2736950928a88e733c85214b8def547b399b87c0cdd136312",
    "ML_WIN_PROB_MODEL_VERSION_TAG": "d18",
    "ML_WIN_PROB_MODEL_SHA256": "c76d329918e1667ae6f641ae6023e0649f34feb7c35064dea8b3db5cd1a8b0a2",
    "EPA_SOURCE": "d18_statbotics_primary",
    "STATBOTICS_SNAPSHOT_DIR": str(ARTIFACTS / "statbotics" / "statbotics_snapshot_20261001T220423Z"),
    "STRATAI_EPA_CHAIN": str(ARTIFACTS / "ratings" / "epa-chain" / "chain_e77d9444c57a7b50.json"),
    "ARTIFACT_STORE_DIR": str(SCRATCH / "uploads"),
    "RULESET_APPROVAL_RECORD_DIR": str(SCRATCH / "approval_records"),
    "HUMAN_INPUTS_WRITE_TOKEN": "local-test-token",
    "CORS_ORIGINS": "http://localhost:5173,http://127.0.0.1:5173,http://localhost:4173",
}


ALLOWED_DATABASES = ("stratai_test", "stratai_test_2023")


def environment(database: str = "stratai_test") -> dict[str, str]:
    """The test environment, with DATABASE_URL pointed at an isolated copy (refuses anything else)."""
    from data.config import Settings
    from scripts.phase5_isolated_db import isolated_url, serving_name

    if database not in ALLOWED_DATABASES:
        raise SystemExit(f"refusing: the local test API runs only against {', '.join(ALLOWED_DATABASES)}")
    url = isolated_url(str(Settings().database_url), database)
    if serving_name(url) != database:
        raise SystemExit(f"refusing: the local test API runs only against {database}")
    return {**PINS, "DATABASE_URL": url}


CHECKLIST_ACTOR = "Checklist Tester"


def write_checklist_files(directory: Path) -> list[Path]:
    """The SYNTHETIC PDFs the browser checklist uploads (2026-10-12). They are not game manuals and never evidence."""
    from tests.pdf_fixtures import make_pdf, manual_pages

    files = {
        "valid_2027.pdf": make_pdf(manual_pages(2027)),
        "partial_2027.pdf": make_pdf([*manual_pages(2027)[:4], ""]),  # 3 topics missing, page 5 blank: 4 warnings
        "wrong_season_2026.pdf": make_pdf(manual_pages(2026)),
        "no_year_2027.pdf": make_pdf(["FIRST Robotics Competition SYNTHETICA\nGame Manual (no year printed)",
                                      *manual_pages(2027)[1:]]),
        "scanned.pdf": make_pdf(["", "", ""]),
        "not_a_pdf.pdf": b"This is a text file with a .pdf name.\n",
    }
    directory.mkdir(parents=True, exist_ok=True)
    written = []
    for name, content in files.items():
        (directory / name).write_bytes(content)
        written.append(directory / name)
    return written


def cleanup_checklist(actor: str = CHECKLIST_ACTOR) -> dict[str, int]:
    """Delete, in stratai_test only, the rows the checklist created under `actor` (any status), and the scratch
    approval records that name `actor`. Nothing else is touched."""
    import psycopg

    url = environment("stratai_test")["DATABASE_URL"]
    deleted: dict[str, int] = {}
    with psycopg.connect(url) as conn, conn.cursor() as cursor:
        cursor.execute("SELECT current_database()")
        if cursor.fetchone()[0] != "stratai_test":
            raise SystemExit("refusing: cleanup runs only on stratai_test")
        for table, column in (("season_rulesets", "created_by"), ("game_spec_versions", "created_by"),
                              ("game_manuals", "uploaded_by")):
            cursor.execute(f"DELETE FROM {table} WHERE {column} = %s", (actor,))
            deleted[table] = cursor.rowcount
    records = SCRATCH / "approval_records"
    deleted["scratch_approval_records"] = 0
    for path in records.glob("*.json") if records.exists() else ():
        if actor in path.read_text(encoding="utf-8"):
            path.unlink()
            deleted["scratch_approval_records"] += 1
    return deleted


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--print", action="store_true", dest="show")
    parser.add_argument("--serve", action="store_true")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--database", choices=ALLOWED_DATABASES, default="stratai_test")
    parser.add_argument("--checklist-files", type=Path, metavar="DIR")
    parser.add_argument("--cleanup-checklist", action="store_true")
    parser.add_argument("--actor", default=CHECKLIST_ACTOR, choices=(CHECKLIST_ACTOR, "Checklist Automation"),
                        help="whose checklist rows --cleanup-checklist removes")
    args = parser.parse_args(argv)
    if args.checklist_files:
        for path in write_checklist_files(args.checklist_files):
            print(path)
    if args.cleanup_checklist:
        print(cleanup_checklist(args.actor))
    env = environment(args.database)
    if args.show:
        print(f"DATABASE_NAME={args.database}")
        for key, value in env.items():
            print(f"{key}={'***' if key in ('DATABASE_URL', 'HUMAN_INPUTS_WRITE_TOKEN') else value}")
    if args.serve:
        os.environ.update(env)
        for key in ("uploads", "approval_records"):
            (SCRATCH / key).mkdir(parents=True, exist_ok=True)
        import uvicorn

        from api import create_app

        print(f"STRATAI local test API: database {args.database} (isolated copy), http://127.0.0.1:{args.port}",
              flush=True)
        uvicorn.run(create_app(), host="127.0.0.1", port=args.port, log_level="warning")
    return 0


if __name__ == "__main__":
    sys.exit(main())
