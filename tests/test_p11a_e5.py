"""P11A E5 harness (research/p11a_e5/run_e5.py): its refusals and its pure core, on SYNTHETIC data only.

These check that the harness computes what the protocol says. They are not E5 results: no real event is read, and the
synthetic playoff labels are invented.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from research.p11a_e5 import run_e5
from tests.p11a_support import snapshot, synthetic_registry, truths  # noqa: F401 (autouse fixture)
from tests.test_phase11_draft_log import setup

PROTOCOL = Path(__file__).resolve().parents[1] / "research" / "p11a_e5" / "PROTOCOL.json"


def test_the_draft_protocol_is_refused():
    with pytest.raises(run_e5.E5Refused) as refused:
        run_e5.load_registered_protocol(PROTOCOL)
    assert refused.value.code == "protocol_not_registered"
    assert json.loads(PROTOCOL.read_text())["status"] == "draft_not_registered"
    assert run_e5.main(["--protocol", str(PROTOCOL), "--run", "R1"]) == 3


def _registered(tmp_path, *, decided=True, record=True, events=("2025abc",), budget=40):
    tmp_path.mkdir(parents=True, exist_ok=True)
    data = json.loads(PROTOCOL.read_text())
    data["status"] = "registered"
    for d in data["decisions_required"]:
        d["decided"] = decided
    data["runs"] = [{"id": "R1", "seasons": [int(events[0][:4])], "budget_minutes": budget, "events": list(events)}]
    path = tmp_path / "PROTOCOL.json"
    path.write_text(json.dumps(data))
    decisions = tmp_path / "decisions"
    decisions.mkdir()
    if record:
        sha = hashlib.sha256(path.read_bytes()).hexdigest()
        (decisions / "P11A_E5_REGISTRATION_2099-01-01.md").write_text(f"registered protocol sha256 {sha}\n")
    return path, decisions


def test_registration_needs_the_record_the_decisions_and_an_unaltered_file(tmp_path):
    path, decisions = _registered(tmp_path / "a", record=False)
    with pytest.raises(run_e5.E5Refused):
        run_e5.load_registered_protocol(path, decisions)
    path, decisions = _registered(tmp_path / "b", decided=False)
    with pytest.raises(run_e5.E5Refused):
        run_e5.load_registered_protocol(path, decisions)
    path, decisions = _registered(tmp_path / "c")
    assert run_e5.load_registered_protocol(path, decisions)["status"] == "registered"
    path.write_text(path.read_text().replace("2000", "2001"))  # altered after registration
    with pytest.raises(run_e5.E5Refused):
        run_e5.load_registered_protocol(path, decisions)


def test_runs_never_touch_2027_or_exceed_45_minutes(tmp_path):
    for sub, kwargs in (("a", {"events": ("2027abc",)}), ("b", {"budget": 46})):
        path, decisions = _registered(tmp_path / sub, **kwargs)
        protocol = run_e5.load_registered_protocol(path, decisions)
        with pytest.raises(run_e5.E5Refused) as refused:
            run_e5.check_run(protocol, "R1")
        assert refused.value.code in ("holdout", "budget")


def _event():
    """A synthetic event (teams 1-24, ranked by number) and its synthetic actual selection."""
    truth = {i: v for i, v in enumerate(truths(24, 7).values(), start=1)}
    snap = snapshot(truth=truth)
    picks = [(1, 9, 17), (2, 10, 18), (3, 11, 19), (4, 12, 20), (5, 13, 21), (6, 14, 22), (7, 15, 23), (8, 16, 24)]
    alliances = [SimpleNamespace(seed=s, picks=p, declines=()) for s, p in enumerate(picks, start=1)]
    outcomes = {s: SimpleNamespace(level="sf", wins=s % 3, losses=2, ties=0) for s in range(1, 9)}
    return snap, alliances, outcomes


def test_the_core_measures_regret_under_as1_and_the_baselines():
    snap, alliances, outcomes = _event()
    result = run_e5.evaluate_event(snap, setup(), alliances, outcomes,
                                   {"individual_epa": list(range(24, 0, -1)), "p11_fb1": list(range(24, 0, -1))})
    assert result["evaluable"] and len(result["picks"]) == 16
    for p in result["picks"]:
        assert p["evaluable"], p
        assert p["regret"] >= -1e-9  # the plan's top has the largest AS-1 value among the selectable teams
        if p["agree_top1"]:
            assert abs(p["regret"]) < 1e-9 and p["actual_rank"] == 1
        for b in p["baselines"].values():
            assert b["v_plan_minus_baseline"] >= -1e-9
    assert {a["seed"] for a in result["alliances"]} == set(range(1, 9))
    summary = run_e5.summarise([result, {**result, "event_key": "9911syn2"}], n_boot=200)
    assert summary["statement"].startswith("E5 is descriptive and observational")
    assert summary["first_pick"]["picks"] == 16 and summary["first_pick"]["mean_regret"] >= 0
    assert summary["association_regret_vs_playoff_win_share"]["kind"] == "observational"


def test_an_event_without_an_approved_registered_configuration_is_not_evaluable():
    snap, alliances, outcomes = _event()
    snap.scoring_config = None
    result = run_e5.evaluate_event(snap, setup(), alliances, outcomes, {})
    assert result == {"event_key": snap.event_key, "evaluable": False,
                      "reason": f"scoring_config_not_approved: no scoring configuration exists for {snap.season}"}
    assert run_e5.summarise([result])["evaluable_events"] == 0


def test_strata_separate_championship_divisions_and_split_others_at_the_median():
    assert run_e5.stratum("Championship Division", 75, 40) == "championship_division"
    assert run_e5.stratum("Regional", 41, 40) == "large" and run_e5.stratum("District", 40, 40) == "small"
