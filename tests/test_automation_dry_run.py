"""Phase D dry run: the fourteen required scenarios, end to end through the real
decision modules (monitor state -> preflight -> lock -> attempt recording ->
completion). Only GitHub, Statbotics and Claude are simulated; every verdict
comes from production code.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import pytest

from automation import execution_state as es
from automation import monitor_state as ms
from automation import ops
from automation import statbotics_health as health
from automation.completion import PHASE_ACCEPTANCE_FILE, REQUIRED_ACCEPTANCE_FILES, CompletionFacts, evaluate
from automation.execution_lock import LockOwner, acquire
from tests.test_automation_execution_lock import FakeGitHub

MONTH = "2026-10"


def check(day: str, ready: bool, code: str = health.FAIL_HTTP_STATUS) -> health.ReadinessResult:
    return health.ReadinessResult(
        checked_at=f"{day}T15:37:00+00:00", url=health.probe_url(), ready=ready, stage_a_passed=ready,
        stage_b_passed=ready, failed_stage=None if ready else "A", failure_code=None if ready else code,
        detail="sim", http_status=200 if ready else 503, elapsed_ms=1,
        epa_total=40.0 if ready else None, matches_played=12 if ready else None,
    )


def monitor_after(*checks: health.ReadinessResult) -> str:
    state = ms.initial_state()
    for result in checks:
        state = ms.apply_check(state, result).state
    return state["status"]


def build_record(status: str, valid: int) -> dict:
    return {"run_id": "b1", "finished_at": "t", "billed_minutes": 240, "readiness_status": status,
            "valid_source_rows": valid, "required_source_rows": 19761, "stop_reason": "finished",
            "fingerprint": "fp", "dump": {"artifact_name": "phase4-db-b1", "run_id": "b1", "sha256": "0" * 64,
                                          "size_bytes": 1}}


def preflight(kind: str, *, monitor: str, state: dict, **overrides) -> es.PreflightDecision:
    values = dict(kind=kind, month=MONTH, monitor_status=monitor, probe_ready=True, probe_detail="ok",
                  execution_state=state, dump_available=True, main_sha="main",
                  secrets_present={"CLAUDE_CODE_OAUTH_TOKEN" if kind == "attempt" else "TBA_API_KEY": True})
    values.update(overrides)
    return es.preflight(es.PreflightFacts(**values))


@pytest.fixture
def data_ready() -> dict:
    return es.record_build(es.initial_state(), build_record("COMPLETE", 19761), month=MONTH).state


def record_attempt(tmp_path: Path, monkeypatch, state: dict, *, outcome: dict | None, publish: dict | None) -> es.Transition:
    """Drive the real `ops record-attempt` path with files on disk."""
    state_dir = tmp_path / "state"
    state_dir.mkdir(exist_ok=True)
    (state_dir / ops.EXECUTION_STATE_FILE).write_text(json.dumps(state), encoding="utf-8")
    outcome_path, publish_path = tmp_path / "outcome.json", tmp_path / "publish.json"
    for path, payload in ((outcome_path, outcome), (publish_path, publish)):
        path.unlink(missing_ok=True)
        if payload is not None:
            path.write_text(json.dumps(payload), encoding="utf-8")
    monkeypatch.setenv("GITHUB_REPOSITORY", "o/r")
    monkeypatch.setattr(ops, "run_billed_minutes", lambda repository, run_id: 290)
    ops.cmd_record_attempt(argparse.Namespace(
        state_dir=state_dir, run_id="777", base_sha="main", outcome=outcome_path, publish=publish_path,
        notify_out=tmp_path / "notify.md", owner="owner", run_url="u"))
    return es.Transition(ops.load_execution_state(state_dir), None, "")


def published(branch: str, files: list[str]) -> dict:
    return {"ok": True, "violations": [], "published": {branch: f"sha-{branch[-3:]}"}, "new_acceptance_files": files,
            "pull_requests": {branch: "https://github.com/o/r/pull/1"}, "compare_links": {}, "push_failures": {}}


# 1-4: the monitor ----------------------------------------------------------------


def test_1_statbotics_down_authorizes_nothing():
    status = monitor_after(check("2026-10-01", False), check("2026-10-02", False))
    assert status == ms.WAITING
    assert not preflight("build", monitor=status, state=es.initial_state()).allowed


def test_2_recovered_once_is_not_trusted():
    status = monitor_after(check("2026-10-01", True))
    assert status == ms.RECOVERY_PENDING
    assert not preflight("build", monitor=status, state=es.initial_state()).allowed


def test_3_recovered_twice_permits_a_data_build_but_not_an_attempt():
    status = monitor_after(check("2026-10-01", True), check("2026-10-02", True))
    assert status == ms.RECOVERY_CONFIRMED
    assert preflight("build", monitor=status, state=es.initial_state()).allowed
    attempt = preflight("attempt", monitor=status, state=es.initial_state())
    assert not attempt.allowed and any("run the data build first" in r for r in attempt.reasons)


def test_4_flap_does_not_confirm_and_a_fresh_probe_failure_blocks_even_when_confirmed(data_ready):
    assert monitor_after(check("2026-10-01", True), check("2026-10-02", False), check("2026-10-03", True)) \
        == ms.RECOVERY_PENDING
    decision = preflight("attempt", monitor=ms.RECOVERY_CONFIRMED, state=data_ready,
                         probe_ready=False, probe_detail="http_status: HTTP 503")
    assert not decision.allowed


# 5-6: historical data ------------------------------------------------------------


def test_5_partial_historical_data_blocks_execution():
    state = es.record_build(es.initial_state(), build_record("PARTIAL", 15000), month=MONTH).state
    assert not preflight("attempt", monitor=ms.RECOVERY_CONFIRMED, state=state).allowed


def test_6_complete_historical_data_permits_execution(data_ready):
    decision = preflight("attempt", monitor=ms.RECOVERY_CONFIRMED, state=data_ready)
    assert decision.allowed and decision.base_sha == "main"


# 7-9: locking and crashes -----------------------------------------------------


def test_7_duplicate_trigger_gets_no_lock():
    github = FakeGitHub()
    assert acquire(github, LockOwner("500", "attempt", "t"), "base").acquired
    github.runs["500"] = "queued"
    assert not acquire(github, LockOwner("501", "attempt", "t"), "base").acquired


def test_8_existing_execution_is_left_alone():
    github = FakeGitHub()
    acquire(github, LockOwner("500", "build", "t"), "base")
    github.runs["500"] = "in_progress"
    result = acquire(github, LockOwner("501", "attempt", "t"), "base")
    assert not result.acquired and "active run 500" in result.reason


def test_9_runner_crash_is_recorded_reclaimed_and_resumed(tmp_path, monkeypatch, data_ready):
    state = record_attempt(tmp_path, monkeypatch, data_ready, outcome=None, publish=None).state
    assert state["attempts"][-1]["outcome"] == es.OUTCOME_INFRASTRUCTURE_FAILED
    assert state["status"] == es.READY  # one crash is not an escalation

    github = FakeGitHub()
    acquire(github, LockOwner("777", "attempt", "t"), "base")
    github.runs["777"] = "completed"
    assert acquire(github, LockOwner("778", "attempt", "t"), "base").reclaimed_from.run_id == "777"


# 10-12: stops -------------------------------------------------------------------


def test_10_timeout_keeps_committed_work_and_resumes_from_it(tmp_path, monkeypatch, data_ready):
    state = record_attempt(
        tmp_path, monkeypatch, data_ready,
        outcome={"outcome": es.OUTCOME_BUDGET_EXHAUSTED, "stop_reason": "attempt time budget reached"},
        publish=published("automation/phase4-m04", [".agent/phase4/M04_ACCEPTANCE.md"]),
    ).state
    assert state["status"] == es.READY
    assert state["last_published"]["branch"] == "automation/phase4-m04"
    decision = preflight("attempt", monitor=ms.RECOVERY_CONFIRMED, state=state,
                         main_contains_published=False, published_contains_main=True)
    assert decision.allowed and decision.base_sha == "sha-m04"


def test_11_m11_ambiguity_stops_for_a_human(tmp_path, monkeypatch, data_ready):
    state = record_attempt(
        tmp_path, monkeypatch, data_ready,
        outcome={"outcome": es.OUTCOME_ESCALATED, "stop_reason": "M11 logical-feature set not decided"},
        publish=published("automation/phase4-m07", [".agent/phase4/M07_ACCEPTANCE.md"]),
    ).state
    assert state["status"] == es.ESCALATED and "M11" in state["escalation_reason"]
    assert "@owner" in (tmp_path / "notify.md").read_text(encoding="utf-8")
    assert not preflight("attempt", monitor=ms.RECOVERY_CONFIRMED, state=state).allowed


def test_12_paid_paths_are_refused(tmp_path, monkeypatch, data_ready):
    refused = preflight("attempt", monitor=ms.RECOVERY_CONFIRMED, state=data_ready,
                        forbidden_secrets_present=["ANTHROPIC_API_KEY"])
    assert not refused.allowed and any("paid billing" in r for r in refused.reasons)

    nothing_committed = {"ok": True, "bundle_present": False, "violations": [], "published": {},
                         "new_acceptance_files": [], "push_failures": {}, "error": None}
    state = record_attempt(tmp_path, monkeypatch, data_ready,
                           outcome={"outcome": es.OUTCOME_USAGE_EXHAUSTED, "stop_reason": "usage limit"},
                           publish=nothing_committed).state
    assert state["status"] == es.ESCALATED


def test_12b_a_harness_violation_overrides_whatever_claude_claimed(tmp_path, monkeypatch, data_ready):
    violation = {**published("automation/phase4-m04", []), "ok": False, "published": {},
                 "violations": ["automation/phase4-m04 modifies protected harness paths: ['docs/P4Milestones.md']"]}
    state = record_attempt(tmp_path, monkeypatch, data_ready,
                           outcome={"outcome": es.OUTCOME_PROGRESS, "stop_reason": "all good"},
                           publish=violation).state
    assert state["attempts"][-1]["outcome"] == es.OUTCOME_HARNESS_VIOLATION
    assert state["status"] == es.ESCALATED


# 13-14: completion and shutdown ------------------------------------------------


def test_13_completion_requires_everything_and_then_stops_further_attempts(data_ready):
    files = frozenset({*REQUIRED_ACCEPTANCE_FILES, PHASE_ACCEPTANCE_FILE})
    assert not evaluate(CompletionFacts(files - {"M13_ACCEPTANCE.md"}, "CLOSED", frozenset())).complete
    assert not evaluate(CompletionFacts(files, "OPEN", frozenset())).complete
    assert evaluate(CompletionFacts(files, "CLOSED", frozenset())).complete
    assert not preflight("attempt", monitor=ms.RECOVERY_CONFIRMED, state=data_ready, phase4_complete=True).allowed


def test_14_shutdown_disables_every_workflow_only_when_complete():
    workflow = (Path(__file__).resolve().parents[1] / ".github" / "workflows" / "statbotics-monitor.yml").read_text(
        encoding="utf-8")
    step = workflow.split("- name: Disable automation (Phase 4 complete)", 1)[1].split("- name:", 1)[0]
    assert "if: steps.completion.outputs.complete == 'true'" in step
    for name in ("phase4-execute.yml", "phase4-data-build.yml", "statbotics-monitor.yml"):
        assert f"gh workflow disable {name}" in step
    assert "gh workflow delete" not in workflow and "gh run delete" not in workflow
