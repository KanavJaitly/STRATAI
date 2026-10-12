"""The local test configuration for exercising STRATAI end to end on historical seasons (2026-10-11).

    python -m scripts.local_test_env --print          # show the environment (no secrets)
    python -m scripts.local_test_env --serve           # run the API on http://127.0.0.1:8765 against stratai_test
    python -m scripts.local_test_env --serve --database stratai_test_2023 --port 8766   # 2023, kept in its own copy

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


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--print", action="store_true", dest="show")
    parser.add_argument("--serve", action="store_true")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--database", choices=ALLOWED_DATABASES, default="stratai_test")
    args = parser.parse_args(argv)
    env = environment(args.database)
    if args.show:
        for key, value in env.items():
            print(f"{key}={'***' if key in ('DATABASE_URL', 'HUMAN_INPUTS_WRITE_TOKEN') else value}")
    if args.serve:
        os.environ.update(env)
        for key in ("uploads", "approval_records"):
            (SCRATCH / key).mkdir(parents=True, exist_ok=True)
        import uvicorn

        from api import create_app

        uvicorn.run(create_app(), host="127.0.0.1", port=args.port, log_level="warning")
    return 0


if __name__ == "__main__":
    sys.exit(main())
