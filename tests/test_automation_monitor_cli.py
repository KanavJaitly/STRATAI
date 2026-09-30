"""Tests for automation.monitor (state/log persistence, notifications) and
static cost/safety guards on the workflow that runs it."""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path

import pytest

from automation import monitor
from automation import monitor_state as ms
from automation import statbotics_health as health

WORKFLOW = Path(__file__).resolve().parents[1] / ".github" / "workflows" / "statbotics-monitor.yml"


def readiness(day: str, ready: bool) -> health.ReadinessResult:
    return health.ReadinessResult(
        checked_at=f"{day}T15:37:00+00:00", url=health.probe_url(), ready=ready,
        stage_a_passed=ready, stage_b_passed=ready, failed_stage=None if ready else "A",
        failure_code=None if ready else health.FAIL_HTTP_STATUS, detail="HTTP 503" if not ready else "ok",
        http_status=200 if ready else 503, elapsed_ms=5,
        epa_total=41.5 if ready else None, matches_played=12 if ready else None,
    )


def check(tmp_path: Path, day: str, ready: bool):
    notify = tmp_path / f"notify-{day}-{ready}.md"
    transition = monitor.run(
        tmp_path / "state", monitor.MODE_CHECK, checker=lambda: readiness(day, ready),
        notify_out=notify, owner="owner-handle", run_url="https://example.invalid/run/1",
        now=lambda: datetime(2026, 10, 1, tzinfo=timezone.utc),
    )
    return transition, notify


def log_lines(tmp_path: Path) -> list[dict]:
    text = (tmp_path / "state" / monitor.LOG_FILE).read_text(encoding="utf-8")
    return [json.loads(line) for line in text.splitlines()]


def test_first_run_initializes_state_log_and_announces_itself(tmp_path):
    transition, notify = check(tmp_path, "2026-10-01", ready=False)
    assert transition.event == ms.EVENT_MONITOR_INITIALIZED
    assert (tmp_path / "state" / monitor.STATE_FILE).exists()
    assert len(log_lines(tmp_path)) == 1
    body = notify.read_text(encoding="utf-8")
    assert "Statbotics monitor started" in body
    assert "@owner-handle" not in body  # routine, not an escalation


def test_continued_outage_logs_every_check_but_notifies_nobody(tmp_path):
    check(tmp_path, "2026-10-01", ready=False)
    for day in ("2026-10-02", "2026-10-03"):
        transition, notify = check(tmp_path, day, ready=False)
        assert transition.event is None
        assert not notify.exists()
    assert len(log_lines(tmp_path)) == 3


def test_recovery_confirmation_escalates_and_says_phase4_is_not_started(tmp_path):
    check(tmp_path, "2026-10-01", ready=False)
    check(tmp_path, "2026-10-02", ready=True)
    transition, notify = check(tmp_path, "2026-10-03", ready=True)
    assert transition.event == ms.EVENT_RECOVERY_CONFIRMED
    body = notify.read_text(encoding="utf-8")
    assert "@owner-handle" in body
    assert "does not start Phase 4" in body
    assert "team_event_stats" in body  # historical readiness is explicitly not claimed


def test_state_round_trips_through_disk(tmp_path):
    check(tmp_path, "2026-10-01", ready=True)
    saved = json.loads((tmp_path / "state" / monitor.STATE_FILE).read_text(encoding="utf-8"))
    assert saved["status"] == ms.RECOVERY_PENDING
    assert saved["pass_dates"] == ["2026-10-01"]


def test_status_mode_writes_nothing(tmp_path):
    transition = monitor.run(tmp_path / "state", monitor.MODE_STATUS, checker=pytest.fail)
    assert transition.event is None
    assert not (tmp_path / "state").exists()


def test_clear_escalation_mode_never_runs_a_check(tmp_path):
    transition = monitor.run(tmp_path / "state", monitor.MODE_CLEAR_ESCALATION, checker=pytest.fail)
    assert transition.state["status"] == ms.WAITING


def test_corrupt_state_file_fails_loudly(tmp_path):
    state_dir = tmp_path / "state"
    state_dir.mkdir()
    (state_dir / monitor.STATE_FILE).write_text('{"schema_version": 99}', encoding="utf-8")
    with pytest.raises(ValueError):
        monitor.run(state_dir, monitor.MODE_CHECK, checker=lambda: readiness("2026-10-01", True))


def test_logged_check_contains_no_credentials(tmp_path):
    check(tmp_path, "2026-10-01", ready=True)
    raw = (tmp_path / "state" / monitor.LOG_FILE).read_text(encoding="utf-8").lower()
    for marker in ("authorization", "bearer", "password", "api_key", "token"):
        assert marker not in raw


# --- workflow guards: cost and blast radius --------------------------------


@pytest.fixture(scope="module")
def workflow_text() -> str:
    return WORKFLOW.read_text(encoding="utf-8")


def test_workflow_runs_at_most_once_a_day(workflow_text):
    crons = re.findall(r'cron:\s*"([^"]+)"', workflow_text)
    assert len(crons) == 1
    minute, hour, *_ = crons[0].split()
    assert minute.isdigit() and hour.isdigit(), "minute and hour must be fixed values: one run per day"


def test_workflow_has_a_hard_timeout_and_uses_the_1x_linux_runner(workflow_text):
    timeouts = [int(m) for m in re.findall(r"timeout-minutes:\s*(\d+)", workflow_text)]
    assert timeouts and max(timeouts) <= 10
    assert re.findall(r"runs-on:\s*(\S+)", workflow_text) == ["ubuntu-latest"]


def test_workflow_has_no_untrusted_triggers(workflow_text):
    triggers = workflow_text.split("\non:", 1)[1].split("\npermissions:", 1)[0]
    for forbidden in ("pull_request", "push:", "issue_comment", "workflow_run", "repository_dispatch"):
        assert forbidden not in triggers


def test_workflow_permissions_are_minimal(workflow_text):
    block = workflow_text.split("\npermissions:", 1)[1].split("\n\n", 1)[0]
    granted = dict(re.findall(r"^\s+([a-z-]+):\s*(\w+)", block, flags=re.MULTILINE))
    # actions: write exists only for the completion-gated shutdown step, which
    # disables (never deletes) the Phase 4 workflows.
    assert granted == {"contents": "write", "issues": "write", "pull-requests": "read", "actions": "write"}


def test_workflow_uses_no_secrets_and_pins_actions(workflow_text):
    assert "secrets." not in workflow_text
    for ref in re.findall(r"uses:\s*(\S+)", workflow_text):
        assert re.fullmatch(r"[\w.-]+/[\w.-]+@[0-9a-f]{40}", ref), f"{ref} is not pinned to a commit SHA"


def test_workflow_cannot_launch_phase4(workflow_text):
    for forbidden in ("claude", "anthropic", "data.orchestrator", "run_m4_baseline_backtest", "gh workflow run"):
        assert forbidden not in workflow_text.lower()
