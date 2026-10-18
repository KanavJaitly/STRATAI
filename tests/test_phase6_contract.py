"""Phase 6 contract tests (P6-M14): the frozen specification, the records, the served statuses and the docs agree.

Pure: these read files, the git index and the app's OpenAPI only, never a database.
"""

from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
RESULTS = ROOT / ".agent" / "phase6" / "results"
FREEZE = ROOT / ".agent" / "phase6" / "P6_M0_FREEZE.md"
DOCS = ROOT / "docs" / "phase6.md"


def _record(name: str) -> dict:
    return json.loads((RESULTS / name).read_text(encoding="utf-8"))


def _blob(path: str) -> str:
    return subprocess.run(["git", "hash-object", path], capture_output=True, text=True, check=True,
                          cwd=ROOT).stdout.strip()


def test_p6_m0_frozen_files_are_unchanged():
    freeze = FREEZE.read_text(encoding="utf-8")
    for path in ("docs/P6Milestones.md", ".agent/phase6/P6_M0_DECISIONS.md", "docs/ROADMAP.md",
                 "docs/P5Milestones.md"):
        row = next(line for line in freeze.splitlines() if f"`{path}`" in line)
        assert re.search(r"`([0-9a-f]{40})`", row).group(1) == _blob(path), path


def test_p6_m10_served_status_matches_its_recorded_gate():
    from ml.strategy.outcome import BASELINE_GATE_PASSED, SERVED_BASELINE_STATUS

    record = _record("p6_m10_outcome_model.json")
    assert BASELINE_GATE_PASSED is record["gate_passed"] is False
    assert SERVED_BASELINE_STATUS == ("not_validated", "p6_m10_gate_failed")
    assert record["served_baseline_status"].startswith("not_validated")


def test_p6_m10_registered_artifact_matches_its_fit_record():
    from scripts.phase6_common import REGISTRY_DIR, file_sha256

    fit = _record("p6_m10_fit.json")
    path = REGISTRY_DIR / "strategy_outcome_component" / "p6m10-v1" / "model.json"
    if not path.exists():
        pytest.skip("the model registry is not available on this machine")
    assert file_sha256(path) == fit["registry"]["model_sha256"]


def test_p6_m13_rerun_supersedes_run1_and_both_are_kept():
    run1, rerun = _record("p6_m13_parity_audit.json"), _record("p6_m13_parity_audit_rerun1.json")
    assert run1["p6_dm2_met"] is False and rerun["p6_dm2_met"] is True
    assert rerun["supersedes"]["record"] == "p6_m13_parity_audit.json"
    assert rerun["contexts"] == run1["contexts"]  # same plan, contexts and seed


def test_done_means_match_the_records():
    from scripts.phase6_done_means import dm1, dm2

    assert dm2()["met"] is True and dm2()["record"] == "p6_m13_parity_audit_rerun1.json"
    one = dm1()
    assert one["met"] is False and any("P6-M1 season rulesets" in b for b in one["blocked_on"])


def test_every_phase6_record_carries_commit_provenance():
    for path in RESULTS.glob("*.json"):
        provenance = json.loads(path.read_text(encoding="utf-8"))["provenance"]
        assert re.fullmatch(r"[0-9a-f]{40}", provenance["commit"]), path.name


def test_no_phase6_http_routes_exist():
    """P6-A1: Phase 6 delivers engines and service functions; HTTP endpoints are Phase 7."""
    from api import create_app
    from data.config import Settings

    paths = set(create_app(Settings()).openapi()["paths"])
    assert not [p for p in paths if re.search(r"strategy|alliance-selection|pick-list|playoff", p)]


def test_docs_cover_every_milestone_and_record():
    text = DOCS.read_text(encoding="utf-8")
    for milestone in [f"P6-M{i}" for i in range(15)]:
        assert milestone in text, milestone
    for path in RESULTS.glob("*.json"):
        assert path.name in text, path.name
