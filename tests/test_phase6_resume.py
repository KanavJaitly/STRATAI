"""scripts/phase6_resume.py: it runs only the allow-listed automatic preparation, and only when it is ready (2026-10-12).

SYNTHETIC task lists; nothing here runs a harness or writes a record.
"""

from __future__ import annotations

from data.readiness import TASKS
from scripts.phase6_resume import AUTOMATIC, resume


def _task(task_id: str, status: str) -> dict:
    row = next(t for t in TASKS if t[0] == task_id)
    return {"id": task_id, "title": row[1], "actor": row[2], "status": status, "waiting_on": [],
            "authorizes": row[7]}


def test_the_allow_list_is_exactly_the_readiness_reports_automatic_tasks():
    assert set(AUTOMATIC) == {t[0] for t in TASKS if t[6]} == {"R3"}


def test_before_2027_data_nothing_runs_and_every_human_task_is_listed():
    calls = []
    tasks = [_task("R1", "ready_for_human"), _task("R3", "waiting_for_2027_data"), _task("R8", "done"),
             _task("R4", "blocked")]
    summary = resume(tasks, execute=True, runner=lambda args: calls.append(args) or 0)
    assert calls == [] and summary["ran"] == []
    assert [t["id"] for t in summary["for_a_person"]] == ["R1"]
    assert {t["id"] for t in summary["waiting"]} == {"R3", "R4"} and summary["done"] == ["R8"]


def test_when_ready_only_the_c0_check_runs_never_an_authorization_or_acceptance_run():
    calls = []
    every = [_task(t[0], "ready_to_run" if t[0] == "R3" else "ready_for_human") for t in TASKS]
    summary = resume(every, execute=True, runner=lambda args: calls.append(args) or 0)
    assert calls == [("m1-2027",)]
    assert [r["id"] for r in summary["ran"]] == ["R3"]
    assert {t["id"] for t in summary["for_a_person"]} == {t[0] for t in TASKS} - {"R3"}


def test_a_non_automatic_task_marked_ready_to_run_is_still_left_to_a_person():
    calls = []
    summary = resume([_task("R5", "ready_to_run"), _task("R9", "ready_to_run")], execute=True,
                     runner=lambda args: calls.append(args) or 0)
    assert calls == [] and {t["id"] for t in summary["for_a_person"]} == {"R5", "R9"}


def test_without_run_nothing_executes():
    calls = []
    summary = resume([_task("R3", "ready_to_run")], execute=False, runner=lambda args: calls.append(args) or 0)
    assert calls == [] and summary["would_run"] == ["R3"]
