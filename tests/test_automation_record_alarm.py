"""The data build never looks recorded when its state was not published.

The Notify step's real shell script is extracted from the workflow and run
under bash for each combination of Record/Persist outcomes, with `gh`
replaced by a function that records every call instead of commenting.
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import textwrap
from pathlib import Path

import pytest

from automation import ops
from tests.test_automation_workflows import BUILD, job_blocks, steps_of

FAKE_GH = '''gh() {
  printf '%s\\n' "$*" >> "$GH_CALLS"
  while [ $# -gt 0 ]; do
    if [ "$1" = "--body-file" ]; then cat "$2" >> "$GH_BODIES"; fi
    shift
  done
}
'''


def build_step(name: str) -> str:
    return next(s for s in steps_of(job_blocks(BUILD)["build"]) if s.startswith(f"name: {name}\n"))


def notify_script() -> str:
    step = build_step("Notify tracking issue")
    run = step.split("        run: |\n", 1)[1]
    return textwrap.dedent(run)


def run_notify(tmp_path: Path, *, recorded: str, persisted: str, notify_md: bool = True) -> dict:
    bash = shutil.which("bash")
    assert bash, "bash is required to execute the workflow step"
    temp = tmp_path / "runner-temp"
    temp.mkdir()
    if notify_md:
        (temp / "notify.md").write_text("### Phase 4 data build: COMPLETE\n\nhistorical data ready\n", encoding="utf-8")
    calls, bodies = tmp_path / "gh-calls.txt", tmp_path / "gh-bodies.txt"
    script = tmp_path / "notify.sh"
    script.write_text(FAKE_GH + notify_script(), encoding="utf-8", newline="\n")
    env = {"PATH": subprocess.os.environ.get("PATH", ""), "RUNNER_TEMP": temp.as_posix(),
           "TRACKING_ISSUE": "27", "OWNER": "owner-handle", "STATE_BRANCH": "automation/phase4-state",
           "RUN_URL": "https://example.invalid/run/9", "RECORDED": recorded, "PERSISTED": persisted,
           "GH_CALLS": calls.as_posix(), "GH_BODIES": bodies.as_posix()}
    completed = subprocess.run([bash, script.as_posix()], env=env, capture_output=True, text=True)
    return {
        "code": completed.returncode,
        "calls": calls.read_text(encoding="utf-8").splitlines() if calls.exists() else [],
        "bodies": bodies.read_text(encoding="utf-8") if bodies.exists() else "",
    }


# 1. record succeeds -> normal publication and notification ---------------------------


def test_recorded_and_published_posts_the_normal_notification(tmp_path):
    out = run_notify(tmp_path, recorded="success", persisted="success")
    assert out["code"] == 0
    assert len(out["calls"]) == 1 and out["calls"][0].startswith("issue comment 27")
    assert "historical data ready" in out["bodies"] and "NOT published" not in out["bodies"]


def test_recorded_and_published_with_nothing_to_say_posts_nothing(tmp_path):
    out = run_notify(tmp_path, recorded="success", persisted="success", notify_md=False)
    assert out["code"] == 0 and out["calls"] == []


# 2. record-build crashes -> one explicit alarm, failed step, no false result ----------


@pytest.mark.parametrize("recorded", ["failure", "cancelled"])
def test_a_crashed_record_posts_one_not_published_alarm_and_fails(tmp_path, recorded):
    # Persist is skipped when Record failed (its condition requires record success).
    out = run_notify(tmp_path, recorded=recorded, persisted="skipped")
    assert out["code"] == 1
    assert len(out["calls"]) == 1                                  # exactly one comment: no duplicate
    assert "state NOT published" in out["bodies"] and "@owner-handle" in out["bodies"]
    assert f"record-build {recorded}" in out["bodies"]
    assert "historical data ready" not in out["bodies"]           # the stale result is never announced


def test_persist_never_runs_after_a_crashed_record():
    persist = build_step("Persist state")
    assert "if: always() && steps.lock.outputs.acquired == 'true' && steps.record.outcome == 'success'" in persist
    assert "id: record" in build_step("Record build")


def test_a_record_crash_before_writing_leaves_state_untouched(tmp_path, monkeypatch):
    state_dir = tmp_path / "state"
    state_dir.mkdir()
    before = {"schema_version": 1, "status": "READY", "escalation_reason": None, "data_build": None, "builds": [],
              "attempts": [], "consecutive_no_progress_builds": 0, "consecutive_no_progress_attempts": 0,
              "best_valid_source_rows": 0, "last_published": None, "ledger": {}}
    (state_dir / ops.EXECUTION_STATE_FILE).write_text(json.dumps(before), encoding="utf-8")
    report = tmp_path / "report.json"
    report.write_text("{ truncated", encoding="utf-8")                # the build left a corrupt report
    monkeypatch.setenv("GITHUB_REPOSITORY", "o/r")
    monkeypatch.setattr(ops, "run_billed_minutes", lambda repository, run_id: 240)
    with pytest.raises(json.JSONDecodeError):
        ops.cmd_record_build(argparse.Namespace(
            state_dir=state_dir, run_id="9", report=report, dump_meta=None, prev_run_id="", prev_available="",
            download_outcome="", restore_outcome="", notify_out=tmp_path / "notify.md", owner="o", run_url="u"))
    assert json.loads((state_dir / ops.EXECUTION_STATE_FILE).read_text(encoding="utf-8")) == before
    assert not (state_dir / ops.EXECUTION_LOG_FILE).exists()           # no progress, no data_build, no build
    assert not (tmp_path / "notify.md").exists()                       # nothing that could be announced


# 3. state-push failures keep their existing behaviour -------------------------------


@pytest.mark.parametrize("persisted", ["failure", "cancelled"])
def test_a_failed_state_push_still_posts_one_alarm_and_fails(tmp_path, persisted):
    out = run_notify(tmp_path, recorded="success", persisted=persisted)
    assert out["code"] == 1 and len(out["calls"]) == 1
    assert "state NOT published" in out["bodies"] and f"state push {persisted}" in out["bodies"]
    assert "historical data ready" not in out["bodies"]
