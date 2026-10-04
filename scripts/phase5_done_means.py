"""Report Phase 5's immutable done-means, DM1 and DM2, from the write-once records (P5-M10).

    python -m scripts.phase5_done_means [--json]

Reads .agent/phase5/results/ only and computes nothing new. A done-means is MET only when every record its
definition requires exists and says so. It is never inferred from code existing.

**DM1** (docs/P5Milestones.md) requires all three P5-M9 records:
- `dm1_dry_run.json`, within 5 days;
- `dm1_score.json`;
- `dm1_mentor_review.json`.

**DM2** requires the P5-M6 verification to pass criteria (a)–(e). The record read is
`p5_m6_replay_rerun1.json` when it declares that it supersedes `p5_m6_replay.json` (the failed first run, kept),
otherwise `p5_m6_replay.json`. DM2 also requires P5-M6's declared dependency, *P5-M2 adopted*. Adoption is a
recorded human decision (P5-D3), taken after L1–L4 pass, and is read from `p5_m2_adoption.json`, which only a
human decision creates.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

RESULTS = Path(".agent/phase5/results")


def _load(name: str, results: Path) -> dict[str, Any] | None:
    path = results / name
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else None


def dm1(results: Path = RESULTS) -> dict[str, Any]:
    run, score, review = (_load(n, results) for n in ("dm1_dry_run.json", "dm1_score.json", "dm1_mentor_review.json"))
    missing = [n for n, r in (("dm1_dry_run.json", run), ("dm1_score.json", score),
                              ("dm1_mentor_review.json", review)) if r is None]
    within = bool(run and run["clock"]["within_5_days"])
    met = not missing and within
    return {"done_means": "DM1", "met": met, "missing_records": missing,
            "within_5_days": within if run else None,
            "elapsed_hours": run["clock"]["elapsed_hours"] if run else None,
            "blocked_on": [] if met else [
                "required human input (.agent/phase5/M09_ACCEPTANCE.md): the 2026 spec entered from the manual, "
                "catalog specs, codebook, two codings and a consensus coding, the action->function map, the rubric, "
                ">= 10 team profiles, the mentor review"]}


def dm2(results: Path = RESULTS) -> dict[str, Any]:
    rerun, adoption = _load("p5_m6_replay_rerun1.json", results), _load("p5_m2_adoption.json", results)
    supersedes = (rerun or {}).get("supersedes", {}).get("record") == "p5_m6_replay.json"
    replay = rerun if supersedes else _load("p5_m6_replay.json", results)
    replay_passed = bool(replay and replay["passed"])
    adopted = bool(adoption and adoption.get("adopted"))
    blocked = []
    if not replay_passed:
        blocked.append("the P5-M6 verification record is missing or did not pass")
    if not adopted:
        blocked.append("P5-M6's dependency 'P5-M2 adopted' is unmet: L1-L4 have passed; the P5-D3 adoption "
                       "decision (human) is pending")
    return {"done_means": "DM2", "met": replay_passed and adopted, "replay_passed": replay_passed,
            "replay_record": None if replay is None else ("p5_m6_replay_rerun1.json" if supersedes else "p5_m6_replay.json"),
            "replay_problems": None if replay is None else replay.get("problem_count", len(replay.get("problems", []))),
            "p5_m2_adopted": adopted, "blocked_on": blocked}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    report = {"DM1": dm1(), "DM2": dm2()}
    report["phase5_complete"] = report["DM1"]["met"] and report["DM2"]["met"]
    if args.json:
        print(json.dumps(report, indent=1))
    else:
        for name in ("DM1", "DM2"):
            item = report[name]
            print(f"{name}: {'MET' if item['met'] else 'NOT MET'}")
            for reason in item["blocked_on"]:
                print(f"  - {reason}")
        print(f"Phase 5 complete: {report['phase5_complete']}")
    return 0 if report["phase5_complete"] else 1


if __name__ == "__main__":
    sys.exit(main())
