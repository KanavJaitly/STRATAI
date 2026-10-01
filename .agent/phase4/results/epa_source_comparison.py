"""Read-only: STRATAI EPA (D15 chain artifacts) vs Statbotics EPA (D17 snapshot), per team-event.

    python .agent/phase4/results/epa_source_comparison.py CHAIN_JSON SNAPSHOT_DIR OUT_JSON

Compares the end-of-event values both sources publish for the same (team, event),
and how often each would be eligible under D13 + availability. Analysis only;
it changes no data, model or methodology.
"""

from __future__ import annotations

import gzip
import json
import sys
from pathlib import Path

import numpy as np
from scipy.stats import pearsonr, spearmanr


def main(chain_path: Path, snapshot: Path, out: Path) -> None:
    chain = json.loads(chain_path.read_text())
    stratai = {}
    for entry in chain["chain"]:
        for e in json.loads((chain_path.parent / entry["directory"] / "team_events.json").read_text()):
            stratai[(e["team"], e["event_key"])] = e
    rows = json.loads(gzip.decompress((snapshot / "team_event_stats.json.gz").read_bytes()))
    statbotics = {(r[0], r[1]): {"season": r[2], "epa_total": r[3], "epa_auto": r[4], "epa_teleop": r[5],
                                 "epa_endgame": r[6], "matches_played": r[7]} for r in rows}
    shared = sorted(set(stratai) & set(statbotics))
    result = {"stratai_team_events": len(stratai), "statbotics_team_events": len(statbotics), "shared": len(shared),
              "only_stratai": len(set(stratai) - set(statbotics)), "only_statbotics": len(set(statbotics) - set(stratai)),
              "by_season": {}}
    for season in (2024, 2025, 2026):
        keys = [k for k in shared if statbotics[k]["season"] == season and statbotics[k]["epa_total"] is not None]
        a = np.asarray([stratai[k]["epa"] for k in keys])
        b = np.asarray([statbotics[k]["epa_total"] for k in keys])
        diff = a - b
        exact = int((np.abs(diff) < 0.005).sum())
        season_end = [k for k in keys if stratai[k]["epa_is_season_end"]]
        result["by_season"][str(season)] = {
            "team_events": len(keys), "pearson": round(float(pearsonr(a, b)[0]), 4),
            "spearman": round(float(spearmanr(a, b)[0]), 4), "mean_diff_stratai_minus_statbotics": round(float(diff.mean()), 3),
            "mean_abs_diff": round(float(np.abs(diff).mean()), 3), "median_abs_diff": round(float(np.median(np.abs(diff))), 3),
            "exact_to_0.01": exact, "exact_share": round(exact / len(keys), 4),
            "stratai_season_end_flagged": len(season_end),
        }
    out.write_text(json.dumps(result, indent=2))
    print(json.dumps(result, indent=1))


if __name__ == "__main__":
    main(Path(sys.argv[1]), Path(sys.argv[2]), Path(sys.argv[3]))
