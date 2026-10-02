"""Phase 4's done-means gate (docs/P4Milestones.md, Milestone 13).

    python -m scripts.phase4_done_means [--results DIR]

The phase is done only when both conditions hold on the held-out season, as
recorded by the single, write-once D18 milestone runs (.agent/phase4/results/d18):

1. the ranking model beats the naive baseline: the M5 model of record (v2)
   passed its frozen gate (D16 §1.5 under D18 §4);
2. the win probability is calibrated: M7 passed its frozen gate (D16 §2.3,
   which replaced the plan's [0.60, 0.70) -> 58-62% band with G1-G4).

It reads the records only -- it computes, refits and re-judges nothing -- and
exits 0 only when both conditions are recorded as passed, so the M13 box
cannot be checked while either is unmet. The literal 58-62% band is reported
for transparency, not used as the gate (D16 replaced it).
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

RESULTS_DIR = Path(".agent/phase4/results/d18")


@dataclass(frozen=True)
class DoneMeans:
    ranking_beats_baseline: bool
    ranking_detail: dict[str, Any]
    win_prob_calibrated: bool
    calibration_detail: dict[str, Any]

    @property
    def met(self) -> bool:
        return self.ranking_beats_baseline and self.win_prob_calibrated

    def to_dict(self) -> dict[str, Any]:
        return {**asdict(self), "met": self.met}


def _load(results_dir: Path, name: str) -> dict[str, Any]:
    path = results_dir / name
    if not path.exists():
        raise FileNotFoundError(f"{path} does not exist: the milestone has not been run")
    return json.loads(path.read_text(encoding="utf-8"))


def evaluate_done_means(results_dir: Path = RESULTS_DIR) -> DoneMeans:
    m05 = _load(results_dir, "m05v2_result.json")
    m07 = _load(results_dir, "m07_result.json")
    band = next((b for b in m07["gate"]["g2"]["bins"] if b["lower"] == 0.6), None)
    return DoneMeans(
        ranking_beats_baseline=m05["passed"] is True,
        ranking_detail={"model_spearman": m05["primary"]["model"]["spearman"],
                        "baseline_same_protocol_spearman": m05["primary"]["baseline_same_protocol"]["spearman"]},
        win_prob_calibrated=m07["passed"] is True,
        calibration_detail={"ece": m07["gate"]["ece"], "g2_status": m07["gate"]["g2"]["status"],
                            "g2_rejected_bins": m07["gate"]["g2"]["rejected_bins"],
                            "g2_eligible_bins": m07["gate"]["g2"]["eligible_bins"],
                            "band_0.60_0.70_for_information": None if band is None else
                            {"n": band["count"], "mean_predicted": band["mean_predicted"],
                             "observed": band["observed_rate"]}},
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--results", type=Path, default=RESULTS_DIR)
    result = evaluate_done_means(parser.parse_args(argv).results)
    print(json.dumps(result.to_dict(), indent=1))
    print("Phase 4 done-means: " + ("MET" if result.met else "NOT MET -- the M13 sign-off box stays unchecked"))
    return 0 if result.met else 1


if __name__ == "__main__":
    sys.exit(main())
