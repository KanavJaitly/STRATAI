"""P5-M10 contract tests: docs/phase5.md is pinned to the live API, the code's labels and the write-once records.

Pure: reads the docs, the OpenAPI schema, constants and .agent/phase5/results/. A drift in either direction fails.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from api import create_app
from data.config import Settings
from scripts.phase5_done_means import dm1, dm2

DOCS = Path("docs/phase5.md")
RESULTS = Path(".agent/phase5/results")
PHASE5_PATHS = {
    "/teams/{team_number}/events/{event_key}/strength",
    "/events/{event_key}/analysis",
    "/events/{event_key}/qualification-forecast",
}


@pytest.fixture(scope="module")
def docs() -> str:
    return DOCS.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def openapi() -> dict:
    return create_app(Settings()).openapi()


def _record(name: str) -> dict:
    return json.loads((RESULTS / name).read_text(encoding="utf-8"))


def test_every_phase5_endpoint_is_live_and_documented(docs, openapi):
    live = set(openapi["paths"])
    assert PHASE5_PATHS <= live
    human = {p for p in live if p.startswith("/human-inputs")}
    documented = set(re.findall(r"`(?:GET|POST|PUT) (/[^`?]+)", docs))
    assert documented == PHASE5_PATHS | human, documented ^ (PHASE5_PATHS | human)
    for path in human:  # every method of every human-input route is documented
        for method in openapi["paths"][path]:
            assert f"`{method.upper()} {path}`" in docs or f"`{method.upper()} {path}?" in docs, (method, path)


def test_reliability_caveat_travels_on_endpoints_serving_it(openapi):
    for path in ("/teams/{team_number}/events/{event_key}/strength", "/events/{event_key}/analysis"):
        assert "INTERIM" in openapi["paths"][path]["get"]["description"]


@pytest.mark.parametrize("label", [
    "validated", "validated_as_measured", "descriptive", "not_validated", "approximately_calibrated_qualification",
    "heuristic_not_validated_against_outcomes", "curated_reference_unverified", "live_refresh_not_yet_validated",
    "descriptive_definition_pending", "provisional", "low_confidence", "fallback_stratai", "withheld_no_prior_event", "stale",
    "pending", "unavailable", "current"])
def test_every_served_label_is_documented(docs, label):
    assert f"`{label}`" in docs


@pytest.mark.parametrize("code", ["invalid_as_of", "epa_source_pending", "epa_source_incomplete",
                                  "epa_source_not_loaded", "model_not_loaded", "event_not_found", "team_not_found"])
def test_error_codes_are_documented(docs, code):
    assert f"`{code}`" in docs


def test_label_constants_used_by_code_are_the_documented_ones():
    from ml.gameanalysis.capability import HEURISTIC
    from ml.ratings.epa_states import ALL_STATES
    from ml.ratings.live_epa import LIVE_REFRESH_NOT_YET_VALIDATED
    from ml.views import event_analysis as ea
    from ml.views import qualification_forecast as qf
    from ml.views import strength

    docs = DOCS.read_text(encoding="utf-8")
    for label in (*ALL_STATES, LIVE_REFRESH_NOT_YET_VALIDATED, ea.VALIDATED_AS_MEASURED, ea.VALIDATED_RAW_EPA,
                  ea.DESCRIPTIVE, qf.NOT_VALIDATED, HEURISTIC, strength.DEFINITION_PENDING, strength.NOT_VALIDATED):
        assert f"`{label}`" in docs, label


def test_every_record_carries_provenance():
    records = sorted(RESULTS.glob("*.json"))
    assert records
    for path in records:
        provenance = json.loads(path.read_text(encoding="utf-8"))["provenance"]
        assert re.fullmatch(r"[0-9a-f]{40}", provenance["commit"]), path


def test_documented_numbers_equal_the_records(docs):
    m3 = _record("p5_m3_strength_acceptance.json")
    assert m3["criterion_exact_equality_with_assembler"]["mismatches"] == 0
    m4 = _record("p5_m4_event_analysis.json")
    b = m4["b_served_policy"]
    for value in (b["m5v2_mean_spearman"], b["paired"]["mean_difference"], *b["paired"]["ci95"]):
        assert f"{abs(value):.4f}" in docs
    m5 = _record("p5_m5_qualification_forecast.json")
    assert f"{m5['b_range_coverage']['coverage']:.4f}" in docs
    m7 = _record("p5_m7_adapter_parity.json")
    assert f"{m7['a_adapter_parity']['valid_rows']:,}" in docs


def test_pinned_serving_decisions_match_their_records():
    from ml.views import event_analysis as ea
    from ml.views import qualification_forecast as qf

    assert ea.SERVE_M5V2_AFTER_SWITCH is _record("p5_m4_event_analysis.json")["b_served_policy"]["serve_m5v2_after_switch"]
    assert qf.RANGE_COVERAGE_VALIDATED is _record("p5_m5_qualification_forecast.json")["b_range_coverage"]["within_band"]


def test_open_decisions_are_recorded_and_referenced(docs):
    for name in ("M02_DECISION_REQUIRED.md", "M07_DECISION_REQUIRED.md", "M08_DECISION_REQUIRED.md"):
        assert (Path(".agent/phase5") / name).exists()
        assert name in docs


def test_done_means_never_inferred_from_code(tmp_path):
    assert dm1(tmp_path)["met"] is False and dm2(tmp_path)["met"] is False
    (tmp_path / "p5_m6_replay.json").write_text(json.dumps({"passed": False, "problem_count": 14}))
    assert dm2(tmp_path)["replay_passed"] is False
    (tmp_path / "p5_m6_replay_rerun1.json").write_text(json.dumps(
        {"passed": True, "problem_count": 0, "supersedes": {"record": "p5_m6_replay.json"}}))
    report = dm2(tmp_path)
    assert report["replay_passed"] and report["replay_record"] == "p5_m6_replay_rerun1.json"
    assert not report["met"]  # P5-M2 adoption (a human decision) is still required
    (tmp_path / "p5_m2_adoption.json").write_text(json.dumps({"adopted": True}))
    assert dm2(tmp_path)["met"]


def test_real_done_means_status_matches_the_records():
    """As recorded: DM1 is blocked by human input; DM2's replay passed but P5-M2 is not adopted."""
    one, two = dm1(), dm2()
    assert one["met"] is False and "dm1_dry_run.json" in one["missing_records"]
    assert two["replay_passed"] is True and two["p5_m2_adopted"] is False and two["met"] is False
