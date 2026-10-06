"""Exact PX-1 population counts under Kanav's 2026-10-06 composition decisions (read-only; nothing fitted).

    python -m scripts.phase6_px1_exclusion_counts     # DATABASE_URL = the isolated stratai_test copy

**Diagnostic for the change plan only.**
- Nothing is fitted, evaluated or changed, and PX-1/PX-2/PX-4/M8 are not run.
- **Output:** `.agent/phase6/diagnostics/p6_px1_exclusion_counts.json`.

**The decisions it counts** (`.agent/phase6/decisions/P6_PX1_COMPOSITION_DECISIONS.md`, documented, not implemented):
- **D-PX1-1:** composition = the alliance at the selection moment, i.e. the captain and the two original picks. A
  standard-event backup (TBA's 4th `picks` entry) is never part of it.
- **D-PX1-2:** FIRST Championship division rows, whose selection-time alliances have four members, are excluded
  from PX-1 and counted by season and event.

**Classification.** A Championship division is recognised here by the data pattern (every alliance lists 4
teams). That is fine for a count, but an implementation must take membership from the approved ruleset's cited
variant.

**Not applied:** the P6-M1 reproduction exclusion (no approved ruleset). The counts are the pre-M1 candidate
population, in the frozen exclusion order: unmappable side, tie or unplayed, then (new) four-member alliance,
then EPA-incomplete.
"""

from __future__ import annotations

import json
import sys
import time
from collections import Counter
from pathlib import Path

from scripts.phase6_common import isolated_database, provenance

OUT = Path(".agent/phase6/diagnostics/p6_px1_exclusion_counts.json")
SEASONS, TRAIN = (2024, 2025, 2026), (2024, 2025)
SNAPSHOT = Path("C:/Dev/StratAI-artifacts/statbotics/statbotics_snapshot_20261001T220423Z")
CHAIN = Path("C:/Dev/StratAI-artifacts/ratings/epa-chain/chain_e77d9444c57a7b50.json")
BUDGET_SECONDS = 30 * 60


def main() -> int:
    from ml.features.scale import ScaleLookup
    from ml.playoffs.data import read_event_playoffs, selection_features
    from ml.playoffs.px1 import map_side
    from ml.ratings.d18_source import load_d18_provider

    started = time.time()
    database = isolated_database()
    provider, integrity = load_d18_provider(database, SNAPSHOT, CHAIN)
    scales = ScaleLookup(database)
    out: dict = {"seasons": {}}
    for season in SEASONS:
        split = "train" if season in TRAIN else "held_out"
        counts: Counter[str] = Counter()
        per_event: dict[str, dict[str, int]] = {}
        for event in read_event_playoffs(database, season):
            if time.time() - started > BUDGET_SECONDS:
                raise SystemExit("over budget: nothing recorded")
            if not event.alliances or event.division_champion:
                continue
            championship = all(len(a.picks) == 4 for a in event.alliances)
            members = {a.seed: (a.picks if championship else a.picks[:3]) for a in event.alliances}
            features = selection_features(database, event, {t for m in members.values() for t in m},
                                          provider=provider, scales=scales)
            event_counts: Counter[str] = Counter()
            for m in event.matches:
                if not ((m.competition_level == "semifinal" and 1 <= m.set_number <= 13)
                        or (m.competition_level == "final" and m.set_number == 1)):
                    event_counts["outside_sf1_13_f1"] += 1
                    continue
                red, blue = map_side(m.red, event.alliances), map_side(m.blue, event.alliances)
                if red is None or blue is None:
                    event_counts["side_unmappable"] += 1
                elif m.winner is None:
                    event_counts["tie_or_unplayed"] += 1
                elif championship:
                    event_counts["excluded_four_member_alliance"] += 1
                    # what EPA-completeness would have said, for the record only
                    if all(features[t].epa_total_present for s in (red.seed, blue.seed) for t in members[s]):
                        event_counts["excluded_four_member_alliance:epa_complete"] += 1
                elif all(features[t].epa_total_present for s in (red.seed, blue.seed) for t in members[s]):
                    event_counts["eligible"] += 1
                else:
                    event_counts["epa_incomplete"] += 1
            counts.update(event_counts)
            if championship:
                per_event[event.event_key] = dict(event_counts)
        out["seasons"][str(season)] = {"split": split, "counts": dict(sorted(counts.items())),
                                       "championship_division_events": per_event}
    out.update({"epa_integrity": integrity, "minutes": round((time.time() - started) / 60, 1),
                "provenance": provenance()})
    OUT.write_text(json.dumps(out, indent=1, sort_keys=True, default=str) + "\n", encoding="utf-8")
    print(json.dumps({s: v["counts"] for s, v in out["seasons"].items()}, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
