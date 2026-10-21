"""The data build's checkpoint bookkeeping (preflight-audit fixes 7a-7c) and
state_push's handling of staging/commit failures.

7a  an expired, unfetchable or corrupt previous checkpoint means "start
    fresh" and is forgotten -- it can never wedge later builds;
7b  a checkpoint exists only after its artifact upload succeeded;
7c  DATA_READY requires COMPLETE readiness AND an uploaded checkpoint.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
from pathlib import Path

import pytest

from automation import execution_state as es
from automation import ops
from automation import state_push as sp
from tests.test_automation_state_push import BRANCH, clone, origin, write_json  # noqa: F401
from tests.test_automation_workflows import BUILD, job_blocks, steps_of

MONTH = "2026-10"


def build(status: str = "COMPLETE", *, uploaded: bool = True, previous: str = es.PREVIOUS_DUMP_NONE,
          run_id: str = "b2", valid: int = 19735) -> dict:
    return {
        "run_id": run_id, "finished_at": "t", "billed_minutes": 240, "readiness_status": status,
        "valid_source_rows": valid, "required_source_rows": 19735, "stop_reason": "finished", "fingerprint": "fp",
        "previous_dump": previous,
        "dump": {"artifact_name": f"phase4-db-{run_id}", "run_id": run_id, "sha256": "0" * 64, "size_bytes": 1}
        if uploaded else None,
    }


def state_with_checkpoint(run_id: str = "b1") -> dict:
    return es.record_build(es.initial_state(), build("PARTIAL", run_id=run_id, valid=9000), month=MONTH).state


# --- previous-checkpoint status from the workflow's step facts ------------------------


@pytest.mark.parametrize("run_id, available, download, restore, expected", [
    ("", "", "", "", es.PREVIOUS_DUMP_NONE),                          # first-ever build
    ("b1", "false", "", "", es.PREVIOUS_DUMP_EXPIRED),                # artifact gone: download skipped
    ("b1", "", "", "", es.PREVIOUS_DUMP_EXPIRED),                     # availability unknown: never "usable"
    ("b1", "true", "failure", "", es.PREVIOUS_DUMP_DOWNLOAD_FAILED),
    ("b1", "true", "success", "failure", es.PREVIOUS_DUMP_CORRUPT),   # checksum or pg_restore failed
    ("b1", "true", "success", "success", es.PREVIOUS_DUMP_RESTORED),
])
def test_previous_checkpoint_status(run_id, available, download, restore, expected):
    assert ops.previous_dump_status(run_id, available, download, restore) == expected


# --- 7a --------------------------------------------------------------------------------


def test_restored_checkpoint_resumes_and_is_replaced_by_the_new_one():
    state = es.record_build(state_with_checkpoint(), build("PARTIAL", previous=es.PREVIOUS_DUMP_RESTORED, valid=15000),
                            month=MONTH).state
    assert state["data_build"]["dump"]["artifact_name"] == "phase4-db-b2"


def test_a_restored_checkpoint_is_kept_when_the_new_upload_fails():
    state = es.record_build(state_with_checkpoint(), build("PARTIAL", uploaded=False,
                                                           previous=es.PREVIOUS_DUMP_RESTORED), month=MONTH).state
    assert state["data_build"]["dump"]["artifact_name"] == "phase4-db-b1"  # still valid and resumable


@pytest.mark.parametrize("previous", sorted(es.PREVIOUS_DUMP_UNUSABLE))
def test_an_unusable_previous_checkpoint_is_forgotten_not_kept(previous):
    state = es.record_build(state_with_checkpoint(), build("PARTIAL", uploaded=False, previous=previous),
                            month=MONTH).state
    assert state["data_build"] is None


@pytest.mark.parametrize("previous", sorted(es.PREVIOUS_DUMP_UNUSABLE))
def test_a_fresh_build_after_an_unusable_checkpoint_records_the_new_one(previous):
    state = es.record_build(state_with_checkpoint(), build("PARTIAL", previous=previous), month=MONTH).state
    assert state["data_build"]["dump"]["artifact_name"] == "phase4-db-b2"


def test_a_stale_checkpoint_cannot_wedge_later_builds():
    state = state_with_checkpoint()
    state = es.record_build(state, build("PARTIAL", uploaded=False, previous=es.PREVIOUS_DUMP_EXPIRED,
                                         run_id="b2"), month=MONTH).state
    assert state["data_build"] is None
    # The next build sees no previous checkpoint and starts fresh.
    assert ops.previous_dump_status("", "", "", "") == es.PREVIOUS_DUMP_NONE
    state = es.record_build(state, build("COMPLETE", run_id="b3"), month=MONTH).state
    assert state["data_build"]["dump"]["artifact_name"] == "phase4-db-b3"


def test_locate_reports_an_expired_checkpoint_as_unavailable(tmp_path, monkeypatch):
    state_dir = tmp_path / "state"
    state_dir.mkdir()
    (state_dir / ops.EXECUTION_STATE_FILE).write_text(json.dumps(state_with_checkpoint()), encoding="utf-8")
    outputs = tmp_path / "out"
    monkeypatch.setenv("GITHUB_OUTPUT", str(outputs))
    monkeypatch.setenv("GITHUB_REPOSITORY", "o/r")
    monkeypatch.setattr(ops, "dump_available", lambda repository, dump: False)
    ops.cmd_locate_dump(argparse.Namespace(state_dir=state_dir))
    written = dict(line.split("=", 1) for line in outputs.read_text(encoding="utf-8").splitlines())
    assert written == {"run_id": "b1", "name": "phase4-db-b1", "sha256": "0" * 64, "available": "false"}


def test_locate_with_no_checkpoint_offers_nothing(tmp_path, monkeypatch):
    outputs = tmp_path / "out"
    monkeypatch.setenv("GITHUB_OUTPUT", str(outputs))
    monkeypatch.setenv("GITHUB_REPOSITORY", "o/r")
    ops.cmd_locate_dump(argparse.Namespace(state_dir=tmp_path / "no-state-yet"))
    written = dict(line.split("=", 1) for line in outputs.read_text(encoding="utf-8").splitlines())
    assert written["run_id"] == "" and written["available"] == "false"


# --- 7b / 7c -------------------------------------------------------------------------


def test_uploaded_complete_checkpoint_is_recorded_and_ready():
    transition = es.record_build(es.initial_state(), build("COMPLETE"), month=MONTH)
    assert transition.event == es.EVENT_DATA_READY
    assert transition.state["data_build"]["dump"]["artifact_name"] == "phase4-db-b2"


def test_complete_readiness_without_an_uploaded_checkpoint_is_not_ready():
    for starting in (es.initial_state(), state_with_checkpoint()):
        transition = es.record_build(starting, build("COMPLETE", uploaded=False, previous=es.PREVIOUS_DUMP_RESTORED),
                                     month=MONTH)
        assert transition.event != es.EVENT_DATA_READY
        assert "NOT ready" in transition.message
        # The only checkpoint named is one that was actually uploaded earlier (or none).
        assert (transition.state["data_build"] or {}).get("run_id") in (None, "b1")


def test_first_ever_build_with_a_failed_upload_claims_no_checkpoint():
    transition = es.record_build(es.initial_state(), build("COMPLETE", uploaded=False), month=MONTH)
    assert transition.state["data_build"] is None
    assert transition.event != es.EVENT_DATA_READY


def test_repeated_builds_without_a_usable_checkpoint_trip_the_breaker():
    state = es.initial_state()
    for n in range(3):
        state = es.record_build(state, build("COMPLETE", uploaded=False, run_id=f"b{n}"), month=MONTH).state
    assert state["status"] == es.ESCALATED


def record_build_cli(tmp_path, monkeypatch, *, dump_meta: bool, readiness: str = "COMPLETE", **prev) -> dict:
    state_dir = tmp_path / "state"
    state_dir.mkdir(exist_ok=True)
    report = tmp_path / "report.json"
    report.write_text(json.dumps({"build": {"stop_reason": None}, "readiness": {
        "status": readiness, "reasons": ["r"], "valid_source_rows": 19735, "required_source_rows": 19735,
        "team_event_stats_fingerprint": "fp"}}), encoding="utf-8")
    meta = tmp_path / "dump-meta.json"
    meta.write_text(json.dumps({"artifact_name": "phase4-db-9", "run_id": "9", "sha256": "0" * 64,
                                "size_bytes": 1}), encoding="utf-8")
    notify = tmp_path / "notify.md"
    monkeypatch.setenv("GITHUB_REPOSITORY", "o/r")
    monkeypatch.setattr(ops, "run_billed_minutes", lambda repository, run_id: 240)
    ops.cmd_record_build(argparse.Namespace(
        state_dir=state_dir, run_id="9", report=report, dump_meta=meta if dump_meta else None,
        prev_run_id=prev.get("run_id", ""), prev_available=prev.get("available", ""),
        download_outcome=prev.get("download", ""), restore_outcome=prev.get("restore", ""),
        notify_out=notify, owner="owner", run_url="u"))
    return {"state": ops.load_execution_state(state_dir), "notify": notify.read_text(encoding="utf-8")}


def test_cli_upload_succeeded_records_the_checkpoint_and_says_ready(tmp_path, monkeypatch):
    out = record_build_cli(tmp_path, monkeypatch, dump_meta=True)
    assert out["state"]["data_build"]["dump"]["artifact_name"] == "phase4-db-9"
    assert "authorizes a human to dispatch" in out["notify"]


def test_cli_upload_failed_records_nothing_and_never_says_ready(tmp_path, monkeypatch):
    # The workflow passes --dump-meta only when the Upload step succeeded; here it did not.
    out = record_build_cli(tmp_path, monkeypatch, dump_meta=False)
    assert out["state"]["data_build"] is None
    assert "authorizes" not in out["notify"] and "NOT ready" in out["notify"]


def test_cli_expired_previous_checkpoint_is_forgotten(tmp_path, monkeypatch):
    state_dir = tmp_path / "state"
    state_dir.mkdir()
    (state_dir / ops.EXECUTION_STATE_FILE).write_text(json.dumps(state_with_checkpoint()), encoding="utf-8")
    out = record_build_cli(tmp_path, monkeypatch, dump_meta=False, readiness="PARTIAL", run_id="b1",
                           available="false")
    assert out["state"]["data_build"] is None
    assert out["state"]["builds"][-1]["previous_dump"] == es.PREVIOUS_DUMP_EXPIRED


# --- workflow wiring -----------------------------------------------------------------


def build_steps() -> dict[str, str]:
    return {step.split("\n", 1)[0].removeprefix("name: "): step for step in steps_of(job_blocks(BUILD)["build"])}


def test_workflow_checks_availability_before_downloading():
    steps = build_steps()
    assert "python -m automation.ops locate-dump" in steps["Locate previous dump"]
    download = steps["Download previous dump"]
    assert "if: steps.previous.outputs.available == 'true'" in download
    assert "continue-on-error: true" in download
    assert "if: steps.download.outcome == 'success'" in steps["Restore previous dump"]
    assert "continue-on-error" not in steps["Restore previous dump"]  # a half-restored DB stops the build


def test_workflow_records_a_checkpoint_only_after_the_upload_succeeded():
    steps = build_steps()
    assert "id: upload" in steps["Upload dump"]
    record = steps["Record build"]
    assert "UPLOADED: ${{ steps.upload.outcome }}" in record
    assert re.search(r'if \[ "\$UPLOADED" = "success" \] && \[ -f "\$RUNNER_TEMP/dump-meta.json" \]; then meta=', record)
    assert "steps.dump.outcome" not in record
    for flag in ("--prev-run-id", "--prev-available", "--download-outcome", "--restore-outcome"):
        assert flag in record


def test_the_dump_size_ceiling_prevents_an_upload():
    steps = build_steps()
    assert "exit 1" in steps["Dump database"] and "262144000" in steps["Dump database"]
    assert "if: steps.dump.outcome == 'success'" in steps["Upload dump"]  # oversize dump -> no upload -> no checkpoint


# --- state_push: staging and commit failures fail closed ------------------------------


def test_a_failed_git_add_is_never_nothing_to_publish(origin, tmp_path):
    heavy = clone(origin, tmp_path / "heavy")
    write_json(heavy, "execution_state.json", {"status": "READY", "builds": ["b1"]})

    def add_fails(command):
        if "add" in command:
            return subprocess.CompletedProcess(command, 128, "", "fatal: Unable to create index.lock")
        return sp._run(command)

    status, detail = sp.publish_state(heavy, branch=BRANCH, paths=["execution_state.json"], message="m",
                                      runner=add_fails, pause=lambda s: None)
    assert status == sp.ADD_FAILED and "index.lock" in detail
    assert status not in sp.SUCCESS_STATUSES


def test_a_missing_state_file_fails_the_publication(origin, tmp_path, monkeypatch):
    heavy = clone(origin, tmp_path / "heavy")
    code = sp.main(["--state-dir", str(heavy), "--branch", BRANCH, "--message", "m", "never-written.json"])
    assert code == 1


def test_a_failed_commit_is_reported_as_such(origin, tmp_path):
    heavy = clone(origin, tmp_path / "heavy")
    write_json(heavy, "execution_state.json", {"status": "READY", "builds": ["b1"]})

    def commit_fails(command):
        if "commit" in command:
            return subprocess.CompletedProcess(command, 1, "", "error: gpg failed to sign")
        return sp._run(command)

    status, _ = sp.publish_state(heavy, branch=BRANCH, paths=["execution_state.json"], message="m",
                                 runner=commit_fails, pause=lambda s: None)
    assert status == sp.COMMIT_FAILED


def test_every_failure_status_is_distinct_and_non_zero():
    failures = {sp.ADD_FAILED, sp.COMMIT_FAILED, sp.CONFLICT, sp.EXHAUSTED}
    assert len(failures) == 4 and failures.isdisjoint(sp.SUCCESS_STATUSES)
    assert sp.SUCCESS_STATUSES == {sp.PUBLISHED, sp.NOTHING}


def test_rows_that_were_never_uploaded_are_not_progress():
    state = es.record_build(es.initial_state(), build("PARTIAL", uploaded=False, valid=15000), month=MONTH).state
    assert state["best_valid_source_rows"] == 0 and state["consecutive_no_progress_builds"] == 1
    state = es.record_build(state, build("PARTIAL", valid=12000), month=MONTH).state   # uploaded, so real
    assert state["best_valid_source_rows"] == 12000 and state["consecutive_no_progress_builds"] == 0
