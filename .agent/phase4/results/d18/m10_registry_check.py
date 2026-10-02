"""M10 registry round trip on the real D18 models of record (verification, no metric gate).

    python .agent/phase4/results/d18/m10_registry_check.py FRAME_DIR REGISTRY_PARENT OUT_JSON

M10 was accepted on synthetic models (v1). This checks the same guarantees on
the models Phase 5 would serve: M5 v2 (RankingXGBModelV2) and M6
(WinProbXGBModel), each fit exactly as its D18 run fits it, registered into a
fresh write-once registry outside the repository, loaded back, and compared
prediction-for-prediction on every held-out 2026 row. It also checks the
feature-list refusal, and whether the M12 API loader (api.ml_loading) can
load the M5 model of record at all.
"""

from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[4]))

from ml.backtest.harness import _match_features  # noqa: E402
from ml.models.ranking_xgb import FEATURE_NAMES as V1_FEATURE_NAMES  # noqa: E402
from ml.models.ranking_xgb import RankingXGBModel  # noqa: E402
from ml.models.ranking_xgb_v2 import FEATURE_NAMES_V2, RANKING_MODEL_V2_VERSION, RankingXGBModelV2  # noqa: E402
from ml.models.win_prob import FEATURE_NAMES as WIN_PROB_FEATURE_NAMES  # noqa: E402
from ml.models.win_prob import WIN_PROB_MODEL_VERSION, WinProbXGBModel  # noqa: E402
from ml.registry import load_registered_model, register_model  # noqa: E402
from scripts.run_phase4_stratai import _folds, frame_info, load_frame_rows  # noqa: E402

RESULTS = Path(".agent/phase4/results/d18")


def main(frame_dir: Path, registry_parent: Path, out: Path) -> None:
    rows = load_frame_rows(frame_dir)
    fold, epa_fold, _, _ = _folds(rows)
    frame_hash = frame_info(frame_dir)["manifest"]["content_hash"]
    created = datetime.now(timezone.utc)
    registry = registry_parent / f"registry_d18_check_{created.strftime('%Y%m%dT%H%M%SZ')}"
    m05 = json.loads((RESULTS / "m05v2_result.json").read_text(encoding="utf-8"))
    m06 = json.loads((RESULTS / "m06_result.json").read_text(encoding="utf-8"))

    ranking = RankingXGBModelV2()
    ranking.fit(fold.train_rows)
    win_prob = WinProbXGBModel()
    win_prob.fit(epa_fold.train_rows)
    register_model(ranking, registry_dir=registry, model_type="ranking_xgb_v2", model_version=RANKING_MODEL_V2_VERSION,
                   version_tag="d18-2026-10-02", training_dataset_hash=frame_hash, feature_list=FEATURE_NAMES_V2,
                   created_at=created, metrics={"held_out_2026_midpoint_spearman": m05["primary"]["model"]["spearman"]})
    register_model(win_prob, registry_dir=registry, model_type="win_prob_xgb", model_version=WIN_PROB_MODEL_VERSION,
                   version_tag="d18-2026-10-02", training_dataset_hash=frame_hash, feature_list=WIN_PROB_FEATURE_NAMES,
                   created_at=created, metrics={"held_out_2026_log_loss": m06["model"]["aggregate"]["log_loss"],
                                                "held_out_2026_brier": m06["model"]["aggregate"]["brier_score"]})

    loaded_ranking, ranking_manifest = load_registered_model(
        RankingXGBModelV2, registry_dir=registry, model_type="ranking_xgb_v2", version_tag="d18-2026-10-02",
        current_feature_list=list(FEATURE_NAMES_V2))
    loaded_win_prob, win_prob_manifest = load_registered_model(
        WinProbXGBModel, registry_dir=registry, model_type="win_prob_xgb", version_tag="d18-2026-10-02",
        current_feature_list=list(WIN_PROB_FEATURE_NAMES))

    teams = [t for r in fold.test_rows for t in (*r.red_teams, *r.blue_teams)]
    rating_mismatch = sum(ranking.predict_rating(t) != loaded_ranking.predict_rating(t) for t in teams)
    win_mismatch = sum(win_prob.predict_win_prob(_match_features(r)) != loaded_win_prob.predict_win_prob(_match_features(r))
                       for r in epa_fold.test_rows)

    def refused(model_class, model_type, feature_list) -> str | None:
        try:
            load_registered_model(model_class, registry_dir=registry, model_type=model_type,
                                  version_tag="d18-2026-10-02", current_feature_list=feature_list)
        except Exception as exc:  # the refusal is the expected outcome
            return f"{type(exc).__name__}: {str(exc)[:160]}"
        return None

    result = {
        "registry": str(registry), "frame_content_hash": frame_hash,
        "ranking_v2": {"manifest": ranking_manifest.model_dump(mode="json"), "team_appearances_compared": len(teams),
                       "round_trip_mismatches": int(rating_mismatch)},
        "win_prob": {"manifest": win_prob_manifest.model_dump(mode="json"), "rows_compared": len(epa_fold.test_rows),
                     "round_trip_mismatches": int(win_mismatch)},
        "drifted_feature_list_refused": refused(RankingXGBModelV2, "ranking_xgb_v2", list(FEATURE_NAMES_V2)[:-1]),
        "api_loader_can_load_m5_model_of_record": refused(RankingXGBModel, "ranking_xgb_v2", list(V1_FEATURE_NAMES)) is None,
        "api_loader_refusal": refused(RankingXGBModel, "ranking_xgb_v2", list(V1_FEATURE_NAMES)),
    }
    result["passed"] = (rating_mismatch == 0 and win_mismatch == 0 and result["drifted_feature_list_refused"] is not None)
    out.write_text(json.dumps(result, indent=1, default=str) + "\n", encoding="utf-8")
    print(json.dumps({k: v for k, v in result.items() if k not in ("ranking_v2", "win_prob")}, indent=1))
    print("ranking mismatches", rating_mismatch, "of", len(teams), "| win-prob mismatches", win_mismatch)


if __name__ == "__main__":
    main(Path(sys.argv[1]), Path(sys.argv[2]), Path(sys.argv[3]))
