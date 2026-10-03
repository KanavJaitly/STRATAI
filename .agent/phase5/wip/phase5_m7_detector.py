"""P5-M7 criteria (b) and (c), under decision P5-D12 (event-level Welch). Recorded once.

    python -m scripts.phase5_m7_detector

Frozen criteria (docs/P5Milestones.md, P5-M7). The record is
.agent/phase5/results/p5_m7_detector.json, recorded only after P5-D12.

**Detector (P5-D12):**
- the unit is the event, valued as its mean component share of the official `totalPoints` (zero-total rows
  excluded);
- Welch's two-sample t-test of week w's events against earlier weeks' events (week w uses only weeks ≤ w);
- Holm correction across the four components within each (season, week) family, at α = 0.05;
- the effect size is the difference in mean share, in percentage points.

**Population:** all 2024–2026 completed matches with valid breakdowns (criterion (a)'s rows), with weeks from TBA's
event `week`. Events without one are outside the series.

**(b) False alarms:**
- 1,000 within-season permutations of the events' week labels (seed 20261008, pre-declared);
- the family-wise flag rate is the share of (season, week) families with at least one flag, over all
  permutations;
- **pass:** rate ≤ 0.05, and its 95% Clopper–Pearson upper bound ≤ 0.07.

**(c) Real flags:** the detector on the real labels, recorded descriptively with no accuracy claim.
"""

from __future__ import annotations

import json
import sys
from datetime import datetime, timezone

import numpy as np

PERMUTATIONS = 1000
PERMUTATION_SEED = 20261008
FAR_MAX, CP_UPPER_MAX = 0.05, 0.07
TEST = "event_welch"  # P5-D12
RECORD = "p5_m7_detector.json"


def main() -> int:
    from data.config import Settings
    from database.connection import DatabaseConfig
    from database.readonly import ReadOnlySessionDatabase
    from ml.meta.weekly import (
        DESCRIPTIVE,
        clopper_pearson_upper,
        detect,
        event_week_permutation,
        share_tables,
    )
    from scripts.phase5_m7_meta import load_rows
    from scripts.phase5_records import provenance, write_once

    provenance()  # refuse up front if the tree is dirty
    started = datetime.now(timezone.utc)
    database = ReadOnlySessionDatabase(DatabaseConfig(Settings().database_url))
    try:
        rows, counts, failures = load_rows(database)
    finally:
        database.close()
    if failures:
        raise SystemExit(f"{len(failures)} rows fail the P5-M7 adapters; criterion (a) no longer holds")
    tables = share_tables(rows, TEST)

    real = [family for table in tables for family in detect(table)]
    for family in real:
        for test in family["tests"]:
            test["share_difference_pp"] = round(100 * test["share_difference"], 3)

    rng = np.random.default_rng(PERMUTATION_SEED)
    flagged = families = 0
    for _ in range(PERMUTATIONS):
        for table in tables:
            for family in detect(table, event_week_permutation(table, rng)):
                families += 1
                flagged += family["flagged"]
    rate = flagged / families
    upper = clopper_pearson_upper(flagged, families)
    result = {
        "milestone": "P5-M7", "decision": "P5-D12", "test": TEST,
        "population": {"rows": len(rows), "counts": dict(sorted(counts.items())),
                       "units_per_season": {str(t.season): int(len(t.events)) for t in tables}},
        "b_false_alarms": {"permutations": PERMUTATIONS, "seed": PERMUTATION_SEED, "families": families,
                           "flagged_families": flagged, "family_wise_flag_rate": rate, "cp95_upper": upper,
                           "passed": rate <= FAR_MAX and upper <= CP_UPPER_MAX},
        "c_real_flags": {"label": DESCRIPTIVE, "families": len(real), "flagged_families": sum(f["flagged"] for f in real),
                         "by_family": real, "claim": "none (descriptive; no accuracy claim)"},
        "minutes": round((datetime.now(timezone.utc) - started).total_seconds() / 60, 1),
    }
    path = write_once(RECORD, result)
    print(json.dumps({"b": result["b_false_alarms"], "c_flagged": result["c_real_flags"]["flagged_families"],
                      "c_families": result["c_real_flags"]["families"], "minutes": result["minutes"]}, indent=1))
    print(f"-> {path}")
    return 0 if result["b_false_alarms"]["passed"] else 1


if __name__ == "__main__":
    sys.exit(main())
