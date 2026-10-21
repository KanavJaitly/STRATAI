"""P10-M2: the stress harness's own logic (scripts/phase10_live_sync_stress.py), so its verdict is not taken on trust.
Pure: no database, no run."""

from __future__ import annotations

import time
from types import SimpleNamespace

import pytest

from scripts import phase10_live_sync_stress as harness


def _report(**overrides):
    report = {"polls": [{"completed": 93, "error": None, "problem_count": 0}],
              "load": {"calls": 10, "by_view": {view: {} for view in harness.VIEWS}, "server_errors": 0,
                       "crashes": [], "reader_threads_still_alive": 0},
              "idle_repoll_records_loaded": 0, "pauses": []}
    report.update(overrides)
    return report


def test_a_clean_run_passes():
    assert harness.verdict(_report(), 93) == {"outcome": "pass", "failures": [], "ok": True}


@pytest.mark.parametrize("overrides, reason", [
    ({"polls": [{"completed": 60, "error": None, "problem_count": 0}]}, "not every match completed"),
    ({"stopped_by_time_budget": True}, "time budget"),
    ({"stall": {"call": "analysis", "seconds": 99.5}}, "stall: analysis 99.5 s"),
    ({"polls": [{"completed": 93, "error": "Boom", "problem_count": 0}]}, "poll error"),
    ({"polls": [{"completed": 93, "error": None, "problem_count": 1}]}, "stale, look-ahead or 5xx in the post-poll check"),
    ({"idle_repoll_records_loaded": 3}, "idle re-poll loaded records"),
])
def test_every_failure_is_named(overrides, reason):
    result = harness.verdict(_report(**overrides), 93)
    assert (result["outcome"], result["ok"]) == ("fail", False) and reason in result["failures"]


@pytest.mark.parametrize("load_change, reason", [
    ({"server_errors": 2}, "2 server errors under load"),
    ({"crashes": ["analysis: RuntimeError"]}, "reader crashes"),
    ({"calls": 0}, "no reader call completed"),
    ({"reader_threads_still_alive": 1}, "reader threads did not stop"),
])
def test_load_failures_are_named(load_change, reason):
    report = _report()
    report["load"].update(load_change)
    assert reason in harness.verdict(report, 93)["failures"]


def test_a_view_never_exercised_fails_the_run():
    report = _report()
    del report["load"]["by_view"]["briefing"]
    assert "views never exercised: ['briefing']" in harness.verdict(report, 93)["failures"]


def test_any_pause_makes_the_run_environment_invalid_never_a_pass_or_an_application_failure():
    paused_clean = harness.verdict(_report(pauses=[{"wall_gap_s": 84}]), 93)
    paused_stalled = harness.verdict(_report(pauses=[{"wall_gap_s": 84}], stall={"call": "analysis", "seconds": 99}), 93)
    assert paused_clean["outcome"] == paused_stalled["outcome"] == "environment_invalid"
    assert not paused_clean["ok"] and paused_stalled["failures"]  # the failures are still recorded


def test_the_heartbeat_records_a_gap_when_the_clock_jumps(monkeypatch):
    """A VM suspend shows as the wall clock jumping on resume; the heartbeat must record it."""
    clock = {"wall": 1000.0, "mono": 50.0}
    monkeypatch.setattr(harness.time, "time", lambda: clock["wall"])
    monkeypatch.setattr(harness.time, "monotonic", lambda: clock["mono"])
    beat = harness.Heartbeat()
    waits = iter([False, False, True])

    def wait(_seconds):
        result = next(waits)
        clock["wall"] += 1.0 if not beat.pauses and clock["wall"] < 1001 else 84.0  # one normal tick, then a jump
        clock["mono"] += 1.0
        return result

    beat.done = SimpleNamespace(wait=wait, set=lambda: None)
    beat.run()
    assert len(beat.pauses) == 1 and beat.pauses[0]["wall_gap_s"] == 84.0


def test_the_expected_scores_come_from_the_payloads_of_completed_matches_only():
    recorded = SimpleNamespace(matches={
        "e_qm1": {"alliances": {"red": {"score": 50, "team_keys": ["frc1", "frc2", "frc3"]},
                                "blue": {"score": 40, "team_keys": ["frc4", "frc5", "frc6"]}}},
        "e_qm2": {"alliances": {"red": {"score": 70, "team_keys": ["frc1", "frc4", "frc5"]},
                                "blue": {"score": 20, "team_keys": ["frc2", "frc3", "frc6"]}}}})
    assert harness.expected_scoring(recorded, {"e_qm1"}) == {1: [50], 2: [50], 3: [50], 4: [40], 5: [40], 6: [40]}
    both = harness.expected_scoring(recorded, {"e_qm1", "e_qm2"})
    assert sorted(both[1]) == [50, 70] and sorted(both[6]) == [20, 40]


def test_the_report_names_its_harness_version_and_code():
    assert harness.HARNESS_VERSION.startswith("H4") and len(harness.code_fingerprint()) == 64


def test_the_reader_join_check_is_not_vacuous():
    """H4 bug: the summary was taken before the readers were joined, so `reader_threads_still_alive` was None and the
    check could never fail. A missing value now fails the run too."""
    report = _report()
    report["load"]["reader_threads_still_alive"] = None
    assert "reader threads not joined before the summary" in harness.verdict(report, 93)["failures"]
