"""Write-once result records for Phase 5 evaluations (docs/P5Milestones.md, standing rules).

Every Phase 5 metric is computed once, on a pre-stated population, and recorded
write-once with its input hashes and the commit that produced it. This module is the
one place that does that recording:

* write_once refuses to overwrite an existing record;
* it refuses to record anything while tracked files differ from HEAD (other than the
  user's own .gitignore edit), so the recorded commit really is the code that ran;
* every record carries its provenance: commit, python version, recorded-at time, and
  whatever input hashes the caller supplies.
"""

from __future__ import annotations

import hashlib
import json
import platform
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

RESULTS_DIR = Path(".agent/phase5/results")
# The user's own long-standing local edit; never part of any Phase 5 change.
IGNORED_DIRTY = {".gitignore"}


class RecordError(RuntimeError):
    pass


def _git(*args: str) -> str:
    return subprocess.run(["git", *args], capture_output=True, text=True, check=True).stdout


def sha256_file(path: Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def provenance() -> dict[str, Any]:
    dirty = sorted(set(_git("diff", "--name-only", "HEAD").splitlines()) - IGNORED_DIRTY)
    if dirty:
        raise RecordError(f"refusing to record a result with uncommitted tracked changes: {dirty}")
    return {"commit": _git("rev-parse", "HEAD").strip(), "python": platform.python_version(),
            "recorded_at": datetime.now(timezone.utc).isoformat()}


def write_once(name: str, value: dict[str, Any], *, results_dir: Path = RESULTS_DIR) -> Path:
    """Record ``value`` as ``results_dir/name``; never overwrite an existing record."""
    path = results_dir / name
    if path.exists():
        raise RecordError(f"{path} exists: Phase 5 results are write-once")
    record = {**value, "provenance": provenance()}
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(record, indent=1, sort_keys=True, default=str) + "\n", encoding="utf-8")
    return path
