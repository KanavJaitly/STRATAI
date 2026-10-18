"""Phase 6 done-means, from the write-once records alone (P6-M14).

    python -m scripts.phase6_done_means

- **P6-DM1:** alliance selection on real past events (`p6_m8_dm1.json`, under the frozen P6-Q1 definition).
- **P6-DM2:** verifiably zero AI-odds inflation. This is the latest P6-M13 parity-audit record; a labelled rerun
  supersedes the run it names.

Phase 6 is complete only when both are met. Nothing here computes or re-decides anything.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

RESULTS = Path(".agent/phase6/results")


def _load(name: str, results: Path = RESULTS) -> dict[str, Any] | None:
    path = results / name
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else None


def dm2(results: Path = RESULTS) -> dict[str, Any]:
    rerun = _load("p6_m13_parity_audit_rerun1.json", results)
    supersedes = (rerun or {}).get("supersedes", {}).get("record") == "p6_m13_parity_audit.json"
    record = rerun if supersedes else _load("p6_m13_parity_audit.json", results)
    met = bool(record and record.get("p6_dm2_met"))
    return {"done_means": "P6-DM2", "met": met,
            "record": None if record is None else ("p6_m13_parity_audit_rerun1.json" if supersedes
                                                   else "p6_m13_parity_audit.json"),
            "blocked_on": [] if met else ["the P6-M13 parity audit is missing or did not pass"]}


def dm1(results: Path = RESULTS) -> dict[str, Any]:
    record = _load("p6_m8_dm1.json", results)
    met = bool(record and record.get("met"))
    blocked = []
    if not met:
        if _load("p6_m1_ruleset_check.json", results) is None:
            blocked.append("required human input: approved P6-M1 season rulesets for 2024, 2025 and 2026, entered "
                           "from the game manuals and approved by a named reviewer (scripts.phase6_rulesets); "
                           "PX-1 through PX-4 and P6-M8 cannot run without them")
        for name, label in (("p6_m2_px1.json", "PX-1"), ("p6_m3_px2.json", "PX-2"), ("p6_m5_px4.json", "PX-4")):
            r = _load(name, results)
            if r is not None and not r.get("passed"):
                blocked.append(f"{label} failed its gate: D9 stop until Kanav decides")
        if record is None:
            blocked.append("P6-M8 has not run (it also needs its dated pre-run record and a named mentor's review)")
    return {"done_means": "P6-DM1", "met": met, "record": None if record is None else "p6_m8_dm1.json",
            "blocked_on": blocked}


def main() -> int:
    one, two = dm1(), dm2()
    for result in (one, two):
        print(f"{result['done_means']}: {'MET' if result['met'] else 'NOT MET'}")
        for reason in result["blocked_on"]:
            print(f"  - {reason}")
    complete = one["met"] and two["met"]
    print(f"Phase 6 complete: {complete}")
    return 0 if complete else 1


if __name__ == "__main__":
    sys.exit(main())
