"""Phase 4 real-data execution on STRATAI EPA (decision D15).

Runs the existing Phase 4 milestone machinery unchanged -- M2's dataset
builder, M3's harness and split, the M4 baselines, the M5-M7 models and
calibration -- against the local canonical database, with EPA from STRATAI's
chained replay instead of Statbotics. Nothing here defines a model, feature,
metric, split or threshold; every one is imported from the milestone that
owns it. Database access is through ReadOnlySessionDatabase, so this script
cannot write to the canonical database.

Subcommands (each writes a write-once JSON result next to the frame):

    build-frame --chain CHAIN --out DIR     M2 training frame for 2024-2026, persisted + exact cache
    m04 --frame DIR                         M4 baselines through M3 (D7 split), run twice for reproducibility
    m05 --frame DIR --m04 RESULT            M5 ranking model vs the frozen M4 ranking baseline (D5)
    m06 --frame DIR --m04 RESULT            M6 win-prob model vs the frozen M4 win-prob baseline
    m07 --frame DIR                         M7 calibration of the M6 model (D6), pre-registered isotonic

Every result records the frame's content hash; the frame records the EPA
provider's provenance.
"""

from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import random
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from data.config import Settings
from database.connection import DatabaseConfig
from database.readonly import ReadOnlySessionDatabase

SEASONS = [2024, 2025, 2026]
TRAIN_SEASONS = [2024, 2025]  # D7
HELD_OUT_SEASON = 2026  # D7
FRAME_CACHE = "frame_rows.json.gz"
FRAME_INFO = "frame_info.json"
SHUFFLE_SEED = 20260930


def _database() -> ReadOnlySessionDatabase:
    return ReadOnlySessionDatabase(DatabaseConfig(Settings().database_url))


def _write_once(path: Path, value: Any) -> None:
    if path.exists():
        raise FileExistsError(f"{path} exists; results are write-once")
    path.write_text(json.dumps(value, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8")


def _load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


# --- M2 frame ------------------------------------------------------------------------


def build_frame(chain: Path, out: Path) -> Path:
    from ml.dataset.builder import _compute_content_hash, build_training_frame, persist_training_frame
    from ml.ratings.provider import StrataiPointInTimeEpa

    database = _database()
    provider = StrataiPointInTimeEpa.from_chain_manifest(database, chain)
    started = time.time()
    result = build_training_frame(database, SEASONS, epa_provider=provider)
    elapsed = time.time() - started
    directory = out / f"frame_{result.manifest.content_hash[:16]}"
    if directory.exists():
        raise FileExistsError(f"{directory} exists; frames are write-once")
    directory.mkdir(parents=True)
    persisted = persist_training_frame(result, directory)
    cache = [row.model_dump(mode="json") for row in result.rows]
    (directory / FRAME_CACHE).write_bytes(gzip.compress(json.dumps(cache).encode("utf-8"), mtime=0))
    reloaded = load_frame_rows(directory)
    exact = _compute_content_hash(SEASONS, False, reloaded) == result.manifest.content_hash
    _write_once(directory / FRAME_INFO, {
        "built_at": datetime.now(timezone.utc).isoformat(),
        "build_seconds": round(elapsed, 1),
        "manifest": result.manifest.model_dump(mode="json"),
        "parquet": persisted.parquet_path.name,
        "cache": FRAME_CACHE,
        "cache_reload_reproduces_content_hash": exact,
        "provider_diagnostics": dict(provider.diagnostics),
        "excluded": [e.model_dump(mode="json") for e in result.excluded],
    })
    if not exact:
        raise RuntimeError("the JSON cache does not reproduce the frame's content hash")
    print(f"frame: {result.manifest.row_count} rows, {result.manifest.excluded_count} excluded "
          f"({result.manifest.excluded_by_reason}) in {elapsed:.0f}s -> {directory}")
    return directory


def load_frame_rows(directory: Path) -> list:
    from ml.dataset.builder import TrainingRow

    data = json.loads(gzip.decompress((directory / FRAME_CACHE).read_bytes()))
    return [TrainingRow.model_validate(row) for row in data]


def frame_info(directory: Path) -> dict[str, Any]:
    return _load_json(directory / FRAME_INFO)


def _final_ranks(season: int) -> dict[str, dict[int, int]]:
    from data.rankings import read_final_ranks_for_season

    return read_final_ranks_for_season(_database(), season)


def _folds(rows: list) -> tuple[Any, Any, int, int]:
    """D7's hold-out fold, and the EPA-complete fold M4's runner derives from it."""
    from ml.backtest.harness import hold_out_season_split
    from scripts.run_m4_baseline_backtest import _split_epa_complete

    fold = hold_out_season_split(rows, held_out_season=HELD_OUT_SEASON)
    epa_fold, train_excluded, test_excluded = _split_epa_complete(fold)
    return fold, epa_fold, train_excluded, test_excluded


# --- milestones ------------------------------------------------------------------------


def run_m04(frame_dir: Path) -> dict[str, Any]:
    """M4 exactly as scripts/run_m4_baseline_backtest.py runs it, on the cached frame."""
    from ml.backtest.harness import run_ranking_backtest, run_win_prob_backtest
    from ml.models.baselines import EpaWinProbBaseline, RawEpaRankingBaseline

    rows = load_frame_rows(frame_dir)
    final_ranks = _final_ranks(HELD_OUT_SEASON)
    runs = []
    for _ in range(2):  # the milestone's reproducibility test: same data -> identical metrics
        fold, epa_fold, train_excluded, test_excluded = _folds(rows)
        win_prob = run_win_prob_backtest(EpaWinProbBaseline, [epa_fold])
        ranking = run_ranking_backtest(RawEpaRankingBaseline, [fold], final_ranks)
        runs.append({
            "train_rows": len(fold.train_rows), "test_rows": len(fold.test_rows),
            "epa_complete_train_rows": len(epa_fold.train_rows), "epa_complete_test_rows": len(epa_fold.test_rows),
            "epa_incomplete_excluded": {"train": train_excluded, "test": test_excluded},
            "win_prob": win_prob.model_dump(mode="json"), "win_prob_summary": win_prob.summary(),
            "ranking": ranking.model_dump(mode="json"), "ranking_summary": ranking.summary(),
        })
    info = frame_info(frame_dir)
    return {
        "milestone": "M04",
        "split": {"train_seasons": TRAIN_SEASONS, "held_out_season": HELD_OUT_SEASON},
        "frame_content_hash": info["manifest"]["content_hash"],
        "epa_source": info["manifest"]["epa_source"], "epa_provenance": info["manifest"]["epa_provenance"],
        "final_rank_events": len(final_ranks),
        "reproducible": runs[0] == runs[1],
        "result": runs[0],
    }


def _labels_shuffled(rows: list, seed: int) -> list:
    """The same rows with (label, margin, scores) permuted across rows: any real
    signal left afterwards would have to come from leakage."""
    targets = [(r.label, r.score_margin, r.score_red, r.score_blue) for r in rows]
    random.Random(seed).shuffle(targets)
    return [r.model_copy(update={"label": t[0], "score_margin": t[1], "score_red": t[2], "score_blue": t[3]})
            for r, t in zip(rows, targets)]


def run_m05(frame_dir: Path, m04: dict[str, Any]) -> dict[str, Any]:
    from ml.backtest.harness import Fold, run_ranking_backtest
    from ml.models.ranking_xgb import RankingXGBModel

    rows = load_frame_rows(frame_dir)
    final_ranks = _final_ranks(HELD_OUT_SEASON)
    fold, _, _, _ = _folds(rows)
    first = run_ranking_backtest(RankingXGBModel, [fold], final_ranks)
    second = run_ranking_backtest(RankingXGBModel, [fold], final_ranks)
    shuffled = Fold(label=fold.label + " (labels shuffled)", train_rows=_labels_shuffled(fold.train_rows, SHUFFLE_SEED),
                    test_rows=fold.test_rows, split_strategy=fold.split_strategy)
    shuffle_result = run_ranking_backtest(RankingXGBModel, [shuffled], final_ranks)
    model = RankingXGBModel()
    model.fit(fold.train_rows)
    gain = model._booster.get_score(importance_type="gain")  # noqa: SLF001 - read-only diagnostic
    total_gain = sum(gain.values())
    baseline = m04["result"]["ranking"]["aggregate"]
    spearman = first.aggregate.spearman
    return {
        "milestone": "M05",
        "frame_content_hash": frame_info(frame_dir)["manifest"]["content_hash"],
        "baseline_spearman": baseline["spearman"], "baseline_top8_recall": baseline["top_k_recall"],
        "model": first.model_dump(mode="json"), "model_summary": first.summary(),
        "gate_d5_strictly_beats_baseline_spearman": spearman is not None and baseline["spearman"] is not None
        and spearman > baseline["spearman"],
        "reproducible": first == second,
        "label_shuffle": shuffle_result.model_dump(mode="json"),
        "best_iteration": model.best_iteration,
        "feature_gain_share": {k: v / total_gain for k, v in sorted(gain.items(), key=lambda kv: -kv[1])},
    }


def run_m06(frame_dir: Path, m04: dict[str, Any]) -> dict[str, Any]:
    from ml.backtest.harness import _match_features, run_win_prob_backtest
    from ml.models.win_prob import WinProbXGBModel

    rows = load_frame_rows(frame_dir)
    fold, epa_fold, _, _ = _folds(rows)
    # the population the frozen baseline was scored on (scripts/run_m11_generalization.py's precedent)
    first = run_win_prob_backtest(WinProbXGBModel, [epa_fold])
    second = run_win_prob_backtest(WinProbXGBModel, [epa_fold])
    full = run_win_prob_backtest(WinProbXGBModel, [fold])
    model = WinProbXGBModel()
    model.fit(epa_fold.train_rows)
    worst_symmetry = 0.0
    forward = []
    for row in epa_fold.test_rows:
        features = _match_features(row)
        swapped = features.model_copy(update={"red_teams": features.blue_teams, "blue_teams": features.red_teams})
        p, q = model.predict_win_prob(features), model.predict_win_prob(swapped)
        worst_symmetry = max(worst_symmetry, abs(p + q - 1.0))
        forward.append(p)
    backward = [model.predict_win_prob(_match_features(row)) for row in reversed(epa_fold.test_rows)]
    baseline = m04["result"]["win_prob"]["aggregate"]
    agg = first.aggregate
    return {
        "milestone": "M06",
        "frame_content_hash": frame_info(frame_dir)["manifest"]["content_hash"],
        "baseline": {k: baseline[k] for k in ("row_count", "log_loss", "brier_score", "accuracy", "roc_auc",
                                              "calibration_error")},
        "model": first.model_dump(mode="json"), "model_summary": first.summary(),
        "gate_log_loss_beats_or_matches": agg.log_loss is not None and agg.log_loss <= baseline["log_loss"],
        "gate_brier_beats_or_matches": agg.brier_score is not None and agg.brier_score <= baseline["brier_score"],
        "reproducible": first == second,
        "held_out_symmetry_max_abs_error": worst_symmetry,
        "held_out_order_independent": forward == list(reversed(backward)),
        "diagnostic_full_held_out_fold": full.model_dump(mode="json"),
    }


def run_m07(frame_dir: Path) -> dict[str, Any]:
    from ml.backtest.metrics import brier_score, expected_calibration_error, log_loss
    from ml.calibration.calibrator import (
        IsotonicCalibrator,
        apply_calibrated_model,
        check_calibration_band,
        compute_reliability_bins,
        fit_calibrated_win_prob_model,
    )
    from ml.models.win_prob import WinProbXGBModel

    rows = load_frame_rows(frame_dir)
    _, epa_fold, _, _ = _folds(rows)
    model, calibrator, diagnostics = fit_calibrated_win_prob_model(
        WinProbXGBModel, epa_fold.train_rows, calibrator_factory=IsotonicCalibrator)
    raw, calibrated, labels = apply_calibrated_model(model, calibrator, epa_fold.test_rows)
    bins = compute_reliability_bins(calibrated, labels)
    band = check_calibration_band(bins, target=0.60)
    near = [(p, y) for p, y in zip(calibrated, labels) if 0.58 <= p <= 0.62]
    symmetry = max(abs(calibrator.calibrate(p) + calibrator.calibrate(1.0 - p) - 1.0) for p in raw)
    ece = expected_calibration_error(calibrated, labels)
    return {
        "milestone": "M07",
        "frame_content_hash": frame_info(frame_dir)["manifest"]["content_hash"],
        "calibrator": "isotonic (pre-registered)", "fit_diagnostics": diagnostics,
        "held_out_rows": len(labels),
        "raw": {"ece": expected_calibration_error(raw, labels), "log_loss": log_loss(raw, labels),
                "brier": brier_score(raw, labels)},
        "calibrated": {"ece": ece, "log_loss": log_loss(calibrated, labels), "brier": brier_score(calibrated, labels)},
        "gate_d6_ece_below_0_05": ece is not None and ece < 0.05,
        "reliability_bins": [b.__dict__ for b in bins],
        "band_check_as_implemented": {"bin": [band.bin.lower, band.bin.upper] if band.bin else None,
                                      "empirical_rate": band.bin.empirical_rate if band.bin else None,
                                      "within_band": band.within_band},
        "diagnostic_predictions_in_0_58_0_62": {
            "count": len(near), "empirical_rate": (sum(y for _, y in near) / len(near)) if near else None},
        "calibrated_symmetry_max_abs_error": symmetry,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    sub = parser.add_subparsers(dest="command", required=True)
    b = sub.add_parser("build-frame")
    b.add_argument("--chain", type=Path, required=True)
    b.add_argument("--out", type=Path, required=True)
    for name in ("m04", "m05", "m06", "m07"):
        command = sub.add_parser(name)
        command.add_argument("--frame", type=Path, required=True)
        if name in ("m05", "m06"):
            command.add_argument("--m04", type=Path, required=True, help="the frozen M4 result JSON")
    args = parser.parse_args(argv)

    if args.command == "build-frame":
        build_frame(args.chain, args.out)
        return 0
    if args.command == "m04":
        result = run_m04(args.frame)
    elif args.command == "m05":
        result = run_m05(args.frame, _load_json(args.m04))
    elif args.command == "m06":
        result = run_m06(args.frame, _load_json(args.m04))
    else:
        result = run_m07(args.frame)
    digest = hashlib.sha256(json.dumps(result, sort_keys=True, default=str).encode()).hexdigest()[:12]
    path = args.frame / f"{args.command}_result_{digest}.json"
    _write_once(path, {**result, "ran_at": datetime.now(timezone.utc).isoformat()})
    shown = {k: v for k, v in result.items() if not isinstance(v, (dict, list))}
    print(json.dumps(shown, indent=2, default=str))
    print(f"-> {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
