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


# Superseded 2026-10-17 by P7-A5 / R8 (.agent/phase7/P7_M0_DECISIONS.md; docs/phase7.md, "Contract-test changes").
# This test enforced P6-A1 ("HTTP endpoints and locked response shapes are Phase 7"): no route path could name
# strategy, alliance selection, pick lists or playoffs. Phase 7 now adds those routes, so the test becomes an
# allow-list: such a path may exist only in the Phase 7 modules the frozen spec names, and anywhere else it still
# fails. The P6-A1 boundary between engines (Phase 6) and HTTP (Phase 7) is what it keeps enforcing.
PHASE6_CAPABILITY_PATH = re.compile(r"strategy|alliance-selection|pick-list|playoff")
# Each Phase 7 module may serve only its own path family (R8).
PHASE7_CAPABILITY_ROUTES = {
    "api.routes.strategy": re.compile(r"^/strategy/"),
    "api.routes.alliance_selection": re.compile(r"^/events/\{event_key\}/alliance-selection(/|$)"),
    "api.routes.pre_match_report": re.compile(r"^/matches/\{match_key\}/pre-match-report$"),
}


def _stray_capability_routes(app) -> list[tuple[str, str]]:
    from starlette.routing import Mount

    from tests.phase7_support import api_routes_checked

    assert not [route for route in app.routes if isinstance(route, Mount)], "a mounted sub-application is unchecked"
    stray = []
    for path, route in api_routes_checked(app):  # proven complete: the walk covers every OpenAPI operation
        family = PHASE7_CAPABILITY_ROUTES.get(route.endpoint.__module__)
        if PHASE6_CAPABILITY_PATH.search(path) and (family is None or not family.search(path)):
            stray.append((path, route.endpoint.__module__))
        if family is not None and not family.search(path):
            stray.append((path, route.endpoint.__module__))
    return stray


def test_phase6_capability_routes_live_only_in_the_phase7_modules():
    """P6-A1, as superseded by P7-A5: Phase 6 capabilities reach HTTP only through the named Phase 7 route
    modules, each within its own path family -- and no other route anywhere may name them."""
    from api import create_app
    from data.config import Settings

    assert not _stray_capability_routes(create_app(Settings()))


def test_the_capability_route_check_catches_a_planted_stray_route():
    """Not vacuous (2026-10-18): a strategy path served from any other module is caught, through an included
    router exactly as the real routes are mounted."""
    from fastapi import APIRouter

    from api import create_app
    from data.config import Settings

    app = create_app(Settings())
    router = APIRouter()

    @router.get("/strategy/planted")
    def planted() -> dict:
        return {}

    app.include_router(router)
    app.openapi_schema = None
    assert ("/strategy/planted", __name__) in _stray_capability_routes(app)


def test_docs_cover_every_milestone_and_record():
    text = DOCS.read_text(encoding="utf-8")
    for milestone in [f"P6-M{i}" for i in range(15)]:
        assert milestone in text, milestone
    for path in RESULTS.glob("*.json"):
        assert path.name in text, path.name
