"""Register the D18 models of record as the production artifacts, traceably.

    python -m scripts.register_d18_production_models --frame FRAME_DIR --registry DIR [--version-tag d18]

The D18 milestone runs evaluated models fit deterministically on frame ab1adbf3 but
persisted no model files. This script produces the production artifacts by the
same fits and refuses to register unless each reproduces its recorded D18 result
exactly -- it re-judges nothing and changes no model:

* M5 v2 (RankingXGBModelV2) on the D7 training rows: the midpoint Spearman and
  top-8 recall must equal results/d18/m05v2_result.json bit for bit.
* M6 + symmetric isotonic calibrator (CalibratedWinProbModel = the D18 M7 pair) on
  the EPA-complete training rows: the fit diagnostics, ECE and every G2 bin's count,
  wins and p-value must equal results/d18/m07_result.json. (The pair is served
  because the qualification calibration evidence belongs to it; M7 itself FAILED,
  which the API reports.)

Each artifact is registered write-once with provenance -- source version, spec and
freeze commit, frame hash, evaluation record and its sha256, the reproduction
check, the producing commit -- then loaded back through the sha256 pin and checked
prediction-for-prediction. It prints the Settings pins to configure, and writes
.agent/production/d18_model_registration.json.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ml.backtest.harness import _match_features
from ml.backtest.ranking_midpoint import MIDPOINT, decision_snapshots, evaluate_ranking
from ml.calibration.gate import evaluate_calibration_gate
from ml.dataset.builder import LABEL_RED_WIN, LABEL_TIE
from ml.models.calibrated_win_prob import (
    CALIBRATED_WIN_PROB_MODEL_TYPE,
    CALIBRATED_WIN_PROB_MODEL_VERSION,
    CalibratedWinProbModel,
)
from ml.models.ranking_xgb_v2 import FEATURE_NAMES_V2, RANKING_MODEL_V2_VERSION, RankingXGBModelV2
from ml.models.win_prob import FEATURE_NAMES as WIN_PROB_FEATURE_NAMES
from ml.ratings.statbotics_primary import D18_FREEZE_COMMIT, D18_SPEC
from ml.registry import load_registered_model, model_file_sha256, register_model
from scripts.run_phase4_stratai import _final_ranks, _folds, frame_info, load_frame_rows

RESULTS = Path(".agent/phase4/results/d18")
RECORD = Path(".agent/production/d18_model_registration.json")
RANKING_MODEL_TYPE = "ranking_xgb_v2"


class ReproductionError(RuntimeError):
    pass


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _head() -> str:
    return subprocess.run(["git", "rev-parse", "HEAD"], capture_output=True, text=True, check=True).stdout.strip()


def _calibrated_gate(model: CalibratedWinProbModel, rows: list) -> tuple[list, list, dict[str, Any]]:
    evaluated = [r for r in rows if r.label != LABEL_TIE]
    q = [model.predict_win_prob(_match_features(r)) for r in evaluated]
    labels = [r.label == LABEL_RED_WIN for r in evaluated]
    gate = evaluate_calibration_gate(q, labels, symmetry_errors=[0.0] * len(q), order_independent=True,
                                     fit_isolated=True).to_dict()
    return evaluated, q, gate


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--frame", type=Path, required=True)
    parser.add_argument("--registry", type=Path, required=True)
    parser.add_argument("--version-tag", default="d18")
    args = parser.parse_args(argv)
    if RECORD.exists():
        raise SystemExit(f"{RECORD} exists: the D18 production artifacts are registered once")

    frame_hash = frame_info(args.frame)["manifest"]["content_hash"]
    recorded_frame = json.loads((RESULTS / "frame_info.json").read_text(encoding="utf-8"))["manifest"]["content_hash"]
    if frame_hash != recorded_frame:
        raise ReproductionError(f"{args.frame} is not the D18 frame {recorded_frame}")
    m05 = json.loads((RESULTS / "m05v2_result.json").read_text(encoding="utf-8"))
    m07 = json.loads((RESULTS / "m07_result.json").read_text(encoding="utf-8"))
    rows = load_frame_rows(args.frame)
    fold, epa_fold, _, _ = _folds(rows)

    ranking = RankingXGBModelV2()
    ranking.fit(fold.train_rows)
    snapshots = decision_snapshots(fold.test_rows, MIDPOINT)
    evaluation = evaluate_ranking(ranking.predict_rating, snapshots, _final_ranks(2026))
    ranking_check = {"midpoint_spearman": evaluation.spearman, "recorded": m05["primary"]["model"]["spearman"],
                     "top8_recall": evaluation.top_k_recall, "recorded_top8": m05["primary"]["model"]["top_k_recall"]}
    if evaluation.spearman != ranking_check["recorded"] or evaluation.top_k_recall != ranking_check["recorded_top8"]:
        raise ReproductionError(f"M5 v2 refit does not reproduce the D18 record: {ranking_check}")

    win_prob = CalibratedWinProbModel()
    win_prob.fit(epa_fold.train_rows)
    evaluated, q, gate = _calibrated_gate(win_prob, epa_fold.test_rows)
    bins_now = [(b["count"], b.get("observed_wins"), b["p_value"]) for b in gate["g2"]["bins"]]
    bins_then = [(b["count"], b.get("observed_wins"), b["p_value"]) for b in m07["gate"]["g2"]["bins"]]
    win_check = {"ece": gate["ece"], "recorded_ece": m07["gate"]["ece"], "g2_bins_identical": bins_now == bins_then,
                 "fit_diagnostics_identical": win_prob.fit_diagnostics == m07["fit_diagnostics"],
                 "g2_status": gate["g2"]["status"], "recorded_g2_status": m07["gate"]["g2"]["status"]}
    if not (gate["ece"] == m07["gate"]["ece"] and win_check["g2_bins_identical"] and win_check["fit_diagnostics_identical"]):
        raise ReproductionError(f"calibrated win-prob refit does not reproduce the D18 M7 record: {win_check}")

    commit, created = _head(), datetime.now(timezone.utc)
    common = {"source_version": "D18", "spec": D18_SPEC, "spec_freeze_commit": D18_FREEZE_COMMIT,
              "frame_content_hash": frame_hash, "epa_source": "d18_statbotics_primary", "producing_commit": commit}
    register_model(ranking, registry_dir=args.registry, model_type=RANKING_MODEL_TYPE,
                   model_version=RANKING_MODEL_V2_VERSION, version_tag=args.version_tag,
                   training_dataset_hash=frame_hash, feature_list=FEATURE_NAMES_V2, created_at=created,
                   random_seed=42, metrics={"held_out_2026_midpoint_spearman": evaluation.spearman,
                                            "held_out_2026_top8_recall": evaluation.top_k_recall},
                   provenance={**common, "milestone": "M05 v2 (gate passed; acceptance pending review)",
                               "evaluation_record": str(RESULTS / "m05v2_result.json"),
                               "evaluation_record_sha256": _sha256(RESULTS / "m05v2_result.json"),
                               "reproduction": ranking_check})
    register_model(win_prob, registry_dir=args.registry, model_type=CALIBRATED_WIN_PROB_MODEL_TYPE,
                   model_version=CALIBRATED_WIN_PROB_MODEL_VERSION, version_tag=args.version_tag,
                   training_dataset_hash=frame_hash, feature_list=WIN_PROB_FEATURE_NAMES, created_at=created,
                   random_seed=42, metrics={"held_out_2026_ece": gate["ece"]},
                   provenance={**common, "milestone": "M06 model + M07 symmetric isotonic calibrator "
                                                       "(M07 gate FAILED: G2 2/9 bins; playoffs not calibrated)",
                               "evaluation_record": str(RESULTS / "m07_result.json"),
                               "evaluation_record_sha256": _sha256(RESULTS / "m07_result.json"),
                               "reproduction": win_check})

    pins = {}
    for model_type, model_class, features, model in ((RANKING_MODEL_TYPE, RankingXGBModelV2, FEATURE_NAMES_V2, ranking),
                                                     (CALIBRATED_WIN_PROB_MODEL_TYPE, CalibratedWinProbModel,
                                                      WIN_PROB_FEATURE_NAMES, win_prob)):
        sha = model_file_sha256(args.registry, model_type, args.version_tag)
        loaded, _ = load_registered_model(model_class, registry_dir=args.registry, model_type=model_type,
                                          version_tag=args.version_tag, current_feature_list=list(features),
                                          expected_sha256=sha)
        if model_type == RANKING_MODEL_TYPE:
            teams = [t for r in fold.test_rows for t in (*r.red_teams, *r.blue_teams)]
            mismatches = sum(model.predict_rating(t) != loaded.predict_rating(t) for t in teams)
            compared = len(teams)
        else:
            mismatches = sum(model.predict_win_prob(_match_features(r)) != loaded.predict_win_prob(_match_features(r))
                             for r in evaluated)
            compared = len(evaluated)
        if mismatches:
            raise ReproductionError(f"{model_type}: {mismatches} of {compared} predictions differ after reload")
        pins[model_type] = {"sha256": sha, "round_trip_predictions_compared": compared, "round_trip_mismatches": 0}

    record = {"registered_at": created.isoformat(), "registry": str(args.registry), "version_tag": args.version_tag,
              "producing_commit": commit, "frame_content_hash": frame_hash,
              "ranking": {"model_type": RANKING_MODEL_TYPE, **pins[RANKING_MODEL_TYPE], "reproduction": ranking_check},
              "win_prob": {"model_type": CALIBRATED_WIN_PROB_MODEL_TYPE, **pins[CALIBRATED_WIN_PROB_MODEL_TYPE],
                           "reproduction": win_check},
              "settings": {"ML_REGISTRY_DIR": str(args.registry),
                           "ML_RANKING_MODEL_VERSION_TAG": args.version_tag,
                           "ML_RANKING_MODEL_SHA256": pins[RANKING_MODEL_TYPE]["sha256"],
                           "ML_WIN_PROB_MODEL_VERSION_TAG": args.version_tag,
                           "ML_WIN_PROB_MODEL_SHA256": pins[CALIBRATED_WIN_PROB_MODEL_TYPE]["sha256"]}}
    RECORD.parent.mkdir(parents=True, exist_ok=True)
    RECORD.write_text(json.dumps(record, indent=1, default=str) + "\n", encoding="utf-8")
    print(json.dumps(record, indent=1, default=str))
    print("\nSettings pins (.env):")
    for key, value in record["settings"].items():
        print(f"{key}={value}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
