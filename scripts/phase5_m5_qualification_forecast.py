"""P5-M5 acceptance: criteria (a) and (b), each computed once and recorded write-once.

    python -m scripts.phase5_m5_qualification_forecast --frame FRAME --registry DIR --win-prob-tag d18 \\
        --win-prob-sha256 SHA

Frozen criteria (docs/P5Milestones.md, P5-M5). The record is
.agent/phase5/results/p5_m5_qualification_forecast.json.

**Population:** the D18 diagnostic population, i.e. held-out 2026 EPA-complete, non-tied qualification matches
(12,245 matches, 7,845 team-events). q comes from the frozen D18 M7 pair, loaded from the registry with its sha256
checked and never refit.

**(a) Reproduction.** Mean actual − expected = 0.0000 and mean |actual − expected| = 1.1207, to 4 dp, as in
`results/d18/m07_diagnostics.json`.

**(b) 80% range coverage, measured once.**
- The range is the central 80% of each team-event's Poisson-binomial, as in ml.views.qualification_forecast.
- `validated` if coverage is within [0.75, 0.85].
- Otherwise it is recorded as a failure, and the range is served `not_validated`.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

RECORD = "p5_m5_qualification_forecast.json"
D18_DIAGNOSTICS = Path(".agent/phase4/results/d18/m07_diagnostics.json")
POPULATION = {"matches": 12245, "team_events": 7845}


def main(argv: list[str] | None = None) -> int:
    from ml.backtest.harness import _match_features
    from ml.dataset.builder import LABEL_RED_WIN, LABEL_TIE
    from ml.models.calibrated_win_prob import CALIBRATED_WIN_PROB_MODEL_TYPE, CalibratedWinProbModel
    from ml.models.win_prob import FEATURE_NAMES
    from ml.registry import load_registered_model
    from ml.views.qualification_forecast import actual_minus_expected, by_team_event, coverage
    from scripts.phase5_records import sha256_file, write_once
    from scripts.run_phase4_stratai import _folds, frame_info, load_frame_rows

    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--frame", type=Path, required=True)
    parser.add_argument("--registry", type=Path, required=True)
    parser.add_argument("--win-prob-tag", required=True)
    parser.add_argument("--win-prob-sha256", required=True)
    args = parser.parse_args(argv)

    model, _ = load_registered_model(CalibratedWinProbModel, registry_dir=args.registry,
                                     model_type=CALIBRATED_WIN_PROB_MODEL_TYPE, version_tag=args.win_prob_tag,
                                     current_feature_list=list(FEATURE_NAMES), expected_sha256=args.win_prob_sha256)
    _, epa_fold, _, _ = _folds(load_frame_rows(args.frame))
    evaluated = [r for r in epa_fold.test_rows if r.label != LABEL_TIE and r.comp_level == "qualification"]
    rows = [(r.event_key, [t.team_number for t in r.red_teams], [t.team_number for t in r.blue_teams],
             float(model.predict_win_prob(_match_features(r))), r.label == LABEL_RED_WIN) for r in evaluated]
    team_events = by_team_event(rows)
    records = [team_events[key] for key in sorted(team_events)]
    population = {"matches": len(rows), "team_events": len(records)}

    recorded = json.loads(D18_DIAGNOSTICS.read_text(encoding="utf-8"))
    recorded = recorded["use_case_impact"]["qualification_expected_wins_per_team_event"]
    a_values = actual_minus_expected(records)
    a = {**a_values, "rounded": {k: round(v, 4) for k, v in a_values.items()},
         "recorded": {"mean_actual_minus_expected": recorded["mean_actual_minus_expected"],
                      "mean_abs_actual_minus_expected": recorded["mean_abs_actual_minus_expected"]}}
    a["exact"] = (a["rounded"]["mean_actual_minus_expected"] == 0.0 == round(recorded["mean_actual_minus_expected"], 4)
                  and a["rounded"]["mean_abs_actual_minus_expected"] == 1.1207
                  == recorded["mean_abs_actual_minus_expected"]) and population == POPULATION
    b = coverage(records)
    b["label"] = "validated" if b["within_band"] else "not_validated"

    info = frame_info(args.frame)
    result = {"milestone": "P5-M5", "spec": "docs/P5Milestones.md (frozen P5-M0)",
              "population": {**population, "expected": POPULATION, "frame_content_hash": info["manifest"]["content_hash"],
                             "frame_info_sha256": sha256_file(args.frame / "frame_info.json")},
              "model": {"type": CALIBRATED_WIN_PROB_MODEL_TYPE, "sha256": args.win_prob_sha256},
              "a_reproduction": a, "b_range_coverage": b, "passed_a": a["exact"]}
    path = write_once(RECORD, result)
    print(json.dumps({"population": population, "a": a, "b": b}, indent=1))
    print(f"-> {path}")
    return 0 if a["exact"] else 1


if __name__ == "__main__":
    sys.exit(main())
