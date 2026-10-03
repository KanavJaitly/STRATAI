"""P5-M7 acceptance: criterion (a), adapter parity, plus the weekly distributions. Recorded write-once.

    python -m scripts.phase5_m7_meta parity

Population: every completed 2024–2026 match's alliance rows that have a breakdown (docs/P5Milestones.md, P5-M7).

**(a) Adapter parity.** auto + teleop + endgame + fouls + adjust = totalPoints = the official score, on 100% of
valid rows. An adapter error or a mismatch counts as a failure, and every failure is listed. The weekly
distributions (descriptive) are recorded alongside.

**(b) and (c) are not run.** The detector's test is open decision Q2 (.agent/phase5/M07_DECISION_REQUIRED.md),
which must be decided before their results exist.
"""

from __future__ import annotations

import argparse
import sys
from collections import Counter


def load_rows(database) -> tuple[list, Counter, list]:
    from ml.features.score_breakdown import ScoreBreakdownSchemaError, UnsupportedSeasonError
    from ml.features.score_components import score_components
    from ml.meta.weekly import ROWS_SQL, ComponentRow

    counts: Counter = Counter()
    failures, rows = [], []
    with database.cursor() as cursor:
        cursor.execute(ROWS_SQL, {"seasons": [2024, 2025, 2026]})
        fetched = cursor.fetchall()
    for season, event_key, week, match_key, score_red, score_blue, breakdown in fetched:
        counts[f"{season}:completed_matches"] += 1
        for alliance, official in (("red", score_red), ("blue", score_blue)):
            alliance_breakdown = breakdown.get(alliance) if isinstance(breakdown, dict) else None
            if not isinstance(alliance_breakdown, dict):
                counts[f"{season}:no_breakdown"] += 1
                continue
            counts[f"{season}:valid_rows"] += 1
            try:
                parts = score_components(season, alliance_breakdown)
            except (ScoreBreakdownSchemaError, UnsupportedSeasonError) as exc:
                failures.append({"match_key": match_key, "alliance": alliance, "error": str(exc)})
                continue
            if parts.total != official:
                failures.append({"match_key": match_key, "alliance": alliance, "total": parts.total,
                                 "official": official})
                continue
            counts[f"{season}:parity"] += 1
            counts[f"{season}:no_tba_week" if week is None else f"{season}:with_week"] += 1
            rows.append(ComponentRow(season, event_key, week, match_key, alliance, parts, official))
    return rows, counts, failures


def main(argv: list[str] | None = None) -> int:
    from data.config import Settings
    from database.connection import DatabaseConfig
    from database.readonly import ReadOnlySessionDatabase
    from ml.meta.weekly import DESCRIPTIVE, weekly_distributions
    from scripts.phase5_records import write_once

    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("check", choices=("parity",))
    parser.parse_args(argv)
    database = ReadOnlySessionDatabase(DatabaseConfig(Settings().database_url))
    rows, counts, failures = load_rows(database)
    valid = sum(v for k, v in counts.items() if k.endswith(":valid_rows"))
    parity = sum(v for k, v in counts.items() if k.endswith(":parity"))
    result = {"milestone": "P5-M7", "spec": "docs/P5Milestones.md (frozen P5-M0)",
              "a_adapter_parity": {"valid_rows": valid, "parity_rows": parity, "share": parity / valid,
                                   "failures": failures[:50], "failure_count": len(failures),
                                   "passed": parity == valid and not failures},
              "counts": dict(sorted(counts.items())),
              "weekly_distributions": {"label": DESCRIPTIVE, "by_season_week_component": weekly_distributions(rows)},
              "b_c_status": "not run: detector test is open decision Q2 (.agent/phase5/M07_DECISION_REQUIRED.md)"}
    path = write_once("p5_m7_adapter_parity.json", result)
    print(result["a_adapter_parity"] | {"failures": len(failures)}, dict(sorted(counts.items())), f"-> {path}")
    return 0 if result["a_adapter_parity"]["passed"] else 1


if __name__ == "__main__":
    sys.exit(main())
