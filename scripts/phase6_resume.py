"""Resume the 2027 Phase 6 preparation from its blockers (2026-10-12).

    python -m scripts.phase6_resume            # show every 2027 task, its status and who acts next (reads only)
    python -m scripts.phase6_resume --run      # also run the automatic preparation whose prerequisites are met

DATABASE_URL must be an isolated stratai_test copy, as for every Phase 6 run.

**What it may run:** only the tasks in AUTOMATIC, which is the readiness report's automatic tasks (data/readiness.py
TASKS) and nothing else: R3, the C0 ruleset reproduction check (`phase6_playoff_track m1-2027`). A task runs only
when its status is `ready_to_run`, meaning:
- the 2027 ruleset is approved by a named, qualified reviewer;
- 2027 matches exist;
- its write-once record does not exist yet.

Its own harness keeps the 45-minute budget, and the record it writes is still committed by a person.

**What it never does:**
- authorize, run, confirm or review anything else. Every R and M task other than R3 is a human decision, or a run
  that needs one first (FINAL-1, PX-2b, PX-4b, M8b and its miss review, the M10b runs, the parity rerun);
- touch the serving database, a model registration or a serving pin.

Those are printed as tasks for the person named, with what they wait on.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Callable

# The only tasks this command may run, each with the harness command that runs it. Kept equal to the readiness
# report's automatic tasks by tests/test_phase6_resume.py.
AUTOMATIC: dict[str, tuple[str, ...]] = {"R3": ("m1-2027",)}


def _run_playoff_track(args: tuple[str, ...]) -> int:
    from scripts.phase6_playoff_track import main

    return main(list(args))


def plan(tasks: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    """Split the tasks into what runs now, what waits for a person, and what waits for data or another task."""
    out: dict[str, list[dict[str, Any]]] = {"run_now": [], "human": [], "waiting": [], "done": [], "failed": []}
    for task in tasks:
        status = task["status"]
        if status == "done":
            out["done"].append(task)
        elif status == "failed":
            out["failed"].append(task)
        elif status == "ready_to_run" and task["id"] in AUTOMATIC:
            out["run_now"].append(task)
        elif status in ("ready_for_human", "ready_to_run"):
            out["human"].append(task)
        else:
            out["waiting"].append(task)
    return out


def resume(tasks: list[dict[str, Any]], *, execute: bool,
           runner: Callable[[tuple[str, ...]], int] = _run_playoff_track) -> dict[str, Any]:
    """Run (when execute) only the allow-listed automatic tasks that are ready; report everything."""
    steps = plan(tasks)
    ran = []
    for task in steps["run_now"]:
        if not execute:
            break
        ran.append({"id": task["id"], "command": list(AUTOMATIC[task["id"]]), "exit": runner(AUTOMATIC[task["id"]])})
    summary = {
        "ran": ran,
        "would_run": [t["id"] for t in steps["run_now"]] if not execute else [],
        "for_a_person": [{"id": t["id"], "title": t["title"], "actor": t["actor"], "authorizes": t["authorizes"]}
                         for t in steps["human"]],
        "waiting": [{"id": t["id"], "status": t["status"], "waiting_on": t["waiting_on"]} for t in steps["waiting"]],
        "done": [t["id"] for t in steps["done"]],
        "failed": [t["id"] for t in steps["failed"]],
    }
    return summary


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--run", action="store_true", help="run the automatic preparation whose prerequisites are met")
    args = parser.parse_args(argv)

    from data.config import Settings
    from data.readiness import phase6_tasks
    from scripts.phase6_common import isolated_database

    tasks = phase6_tasks(isolated_database(), Path(Settings().phase6_dir))
    print(json.dumps(resume(tasks, execute=args.run), indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
