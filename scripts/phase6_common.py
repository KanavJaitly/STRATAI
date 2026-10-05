"""Shared Phase 6 constants and helpers for the evaluation scripts (not used by the served engines).

- **Records** are write-once in `.agent/phase6/results/`, with the commit, through Phase 5's
  `scripts.phase5_records`. A record is refused while tracked files are uncommitted.
- **Data:**
  - the D18 frame is the evaluated Phase 4 population;
  - the model registry is the production registry (write-once entries);
  - the database is always the isolated copy: scripts read `Settings().database_url` and refuse anything that is
    not a `stratai_test*` copy.
"""

from __future__ import annotations

import hashlib
import json
import subprocess
from pathlib import Path
from typing import Any

from scripts.phase5_records import provenance, write_once as _write_once

RESULTS_DIR = Path(".agent/phase6/results")
FRAME_DIR = Path("C:/Dev/StratAI-artifacts/phase4/frame_ab1adbf38b43c2f3")
REGISTRY_DIR = Path("C:/Dev/StratAI-artifacts/ml_registry")
M6M7_VERSION_TAG = "d18"
M6M7_SHA256 = "c76d329918e1667ae6f641ae6023e0649f34feb7c35064dea8b3db5cd1a8b0a2"
P6_M10_VERSION_TAG = "p6m10-v1"
TRAIN_SEASONS, HELD_OUT_SEASON = (2024, 2025), 2026


def write_once(name: str, value: dict[str, Any]) -> Path:
    return _write_once(name, value, results_dir=RESULTS_DIR)


def read_record(name: str) -> dict[str, Any] | None:
    path = RESULTS_DIR / name
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else None


def git_blob(path: str) -> str:
    return subprocess.run(["git", "hash-object", path], capture_output=True, text=True, check=True).stdout.strip()


def file_sha256(path: str | Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def isolated_database():
    """A read-only session on the isolated copy; refuses the serving database."""
    from data.config import Settings
    from database.connection import DatabaseConfig
    from database.readonly import ReadOnlySessionDatabase
    from scripts.phase5_isolated_db import serving_name

    url = str(Settings().database_url)
    name = serving_name(url)
    if not name.startswith("stratai_test"):
        raise SystemExit(f"refusing database {name!r}: Phase 6 evaluations run only on an isolated stratai_test copy")
    return ReadOnlySessionDatabase(DatabaseConfig(Settings().database_url))


def load_frame():
    from scripts.run_phase4_stratai import frame_info, load_frame_rows

    return load_frame_rows(FRAME_DIR), frame_info(FRAME_DIR)["manifest"]["content_hash"]


def load_m6m7():
    from ml.models.calibrated_win_prob import CALIBRATED_WIN_PROB_MODEL_TYPE, CalibratedWinProbModel
    from ml.models.win_prob import FEATURE_NAMES
    from ml.registry import load_registered_model

    model, _ = load_registered_model(CalibratedWinProbModel, registry_dir=REGISTRY_DIR,
                                     model_type=CALIBRATED_WIN_PROB_MODEL_TYPE, version_tag=M6M7_VERSION_TAG,
                                     current_feature_list=FEATURE_NAMES, expected_sha256=M6M7_SHA256)
    return model


__all__ = ["RESULTS_DIR", "FRAME_DIR", "REGISTRY_DIR", "write_once", "read_record", "provenance", "git_blob",
           "file_sha256", "isolated_database", "load_frame", "load_m6m7"]
