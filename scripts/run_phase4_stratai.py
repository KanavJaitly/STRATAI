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
    m07 --frame DIR                         M7 under D16 (symmetric isotonic; G1-G4)
    m05v2-preflight --frame DIR             M5 v2 input checks only: no metric, no ranks
    m05v2 --frame DIR --m04 RESULT          the single, pre-registered M5 v2 evaluation (D16 §1.5)

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


def statbotics_provider(database, snapshot: Path):
    """The Statbotics reference source (D13 SQL over team_event_stats), refused unless the
    table is exactly the cached snapshot (scripts/sync_statbotics_snapshot.py)."""
    from ml.ratings.provider import StatboticsPointInTimeEpa
    from scripts.sync_statbotics_snapshot import table_fingerprint

    manifest = _load_json(snapshot / "manifest.json")
    _, fingerprint = table_fingerprint(database, manifest["seasons"])
    if fingerprint != manifest["team_event_stats"]["sha256"] or manifest["failures"]:
        raise RuntimeError(f"team_event_stats does not match snapshot {snapshot.name} (or it recorded failures)")

    class _SnapshotStatbotics(StatboticsPointInTimeEpa):
        def provenance(self):
            return {**super().provenance(), "snapshot": snapshot.name, "team_event_stats_sha256": fingerprint,
                    "producing_commit": manifest["producing_commit"], "retrieved": [manifest["started_at"],
                                                                                   manifest["finished_at"]]}

    return _SnapshotStatbotics(database)


def build_frame(chain: Path | None, out: Path, statbotics_snapshot: Path | None = None) -> Path:
    from ml.dataset.builder import _compute_content_hash, build_training_frame, persist_training_frame
    from ml.ratings.provider import StrataiPointInTimeEpa

    database = _database()
    if (chain is None) == (statbotics_snapshot is None):
        raise ValueError("give exactly one EPA source: --chain (STRATAI) or --statbotics-snapshot")
    provider = (StrataiPointInTimeEpa.from_chain_manifest(database, chain) if chain is not None
                else statbotics_provider(database, statbotics_snapshot))
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
        "provider_diagnostics": dict(getattr(provider, "diagnostics", {})),
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
    """M7 under decision D16 (M05_M07_REDESIGN_SPEC.md §2): the M6 model with the
    symmetric isotonic calibrator, judged by G1 (ECE < 0.05), G2 (exact per-bin
    Poisson-binomial test, Holm), G3 (exact symmetry) and G4 (fit isolation)."""
    from ml.backtest.harness import _match_features
    from ml.backtest.metrics import brier_score, expected_calibration_error, log_loss
    from ml.calibration.calibrator import SymmetricIsotonicCalibrator, fit_calibrated_win_prob_model
    from ml.calibration.gate import evaluate_calibration_gate
    from ml.dataset.builder import LABEL_RED_WIN, LABEL_TIE
    from ml.models.win_prob import WinProbXGBModel

    rows = load_frame_rows(frame_dir)
    _, epa_fold, _, _ = _folds(rows)
    model, calibrator, diagnostics = fit_calibrated_win_prob_model(
        WinProbXGBModel, epa_fold.train_rows, calibrator_factory=SymmetricIsotonicCalibrator)
    # G4: the model and calibrator only ever received epa_fold.train_rows (2024+2025, strictly before 2026)
    fit_isolated = (all(r.season in TRAIN_SEASONS for r in epa_fold.train_rows)
                    and max(r.scheduled_time for r in epa_fold.train_rows)
                    < min(r.scheduled_time for r in epa_fold.test_rows))
    raw, q, labels, symmetry, forward = [], [], [], [], []
    evaluated = [r for r in epa_fold.test_rows if r.label != LABEL_TIE]
    for row in evaluated:
        features = _match_features(row)
        swapped = features.model_copy(update={"red_teams": features.blue_teams, "blue_teams": features.red_teams})
        p = model.predict_win_prob(features)
        q_rb = calibrator.calibrate(p)
        q_br = calibrator.calibrate(model.predict_win_prob(swapped))
        raw.append(p)
        q.append(q_rb)
        labels.append(row.label == LABEL_RED_WIN)
        symmetry.append(abs(q_rb + q_br - 1.0))
        forward.append(q_rb)
    backward = [calibrator.calibrate(model.predict_win_prob(_match_features(r))) for r in reversed(evaluated)]
    gate = evaluate_calibration_gate(q, labels, symmetry_errors=symmetry,
                                     order_independent=forward == list(reversed(backward)),
                                     fit_isolated=fit_isolated)
    return {
        "milestone": "M07", "decision": "D16", "spec": ".agent/phase4/M05_M07_REDESIGN_SPEC.md §2",
        "frame_content_hash": frame_info(frame_dir)["manifest"]["content_hash"],
        "calibrator": "SymmetricIsotonicCalibrator", "fit_diagnostics": diagnostics,
        "held_out_rows": len(labels), "ties_excluded": len(epa_fold.test_rows) - len(evaluated),
        "raw_m6": {"ece": expected_calibration_error(raw, labels), "log_loss": log_loss(raw, labels),
                   "brier": brier_score(raw, labels)},
        "calibrated": {"ece": gate.ece, "log_loss": log_loss(q, labels), "brier": brier_score(q, labels)},
        "gate": gate.to_dict(),
        "gate_passed": gate.passed,
    }


FREEZE_COMMIT = "d77ffe4"  # the commit that froze M05_M07_REDESIGN_SPEC.md as D16
SPEC_PATH = ".agent/phase4/M05_M07_REDESIGN_SPEC.md"
M05V2_RESULT_RECORD = Path(".agent/phase4/results/m05v2_result.json")
# Methodology and acceptance files the single M5 v2 run must leave exactly as frozen.
M05V2_FROZEN_FILES = [
    SPEC_PATH, "docs/P4Milestones.md", ".agent/phase4/M04_ACCEPTANCE.md", ".agent/phase4/results/m04_result.json",
    "ml/models/baselines.py", "ml/backtest/harness.py", "ml/backtest/metrics.py", "ml/models/ranking_xgb.py",
    "scripts/run_m4_baseline_backtest.py",
]


def _git(*args: str) -> str:
    import subprocess

    return subprocess.run(["git", *args], capture_output=True, text=True, check=True).stdout


def _frozen_file_check() -> dict[str, Any]:
    changed = set(_git("diff", "--name-only", FREEZE_COMMIT, "HEAD").splitlines())
    changed |= set(_git("diff", "--name-only").splitlines())  # uncommitted changes count too
    files = list(M05V2_FROZEN_FILES)
    # the dataset builder changed only to carry D16's scale fields: every changed line must say so
    builder_diff = [line for line in _git("diff", "-U0", FREEZE_COMMIT, "HEAD", "--", "ml/dataset/builder.py").splitlines()
                    if line[:1] in "+-" and not line.startswith(("+++", "---"))]
    removed = [line[1:] for line in builder_diff if line.startswith("-")]
    added = [line[1:] for line in builder_diff if line.startswith("+")]
    # a removed line may only come back with " scale_lookup=scales," added; every other added line is scale-only
    restored = [line.replace(" scale_lookup=scales,", "") for line in added]
    builder_additive_only = (all(r in restored for r in removed)
                             and all(("scale" in a.lower()) for a in added))
    spec_at_freeze = _git("rev-parse", f"{FREEZE_COMMIT}:{SPEC_PATH}").strip()
    spec_now = _git("hash-object", SPEC_PATH).strip()
    return {"freeze_commit": FREEZE_COMMIT, "spec_blob_at_freeze": spec_at_freeze, "spec_blob_now": spec_now,
            "spec_unchanged": spec_at_freeze == spec_now,
            "frozen_files_changed_since_freeze": sorted(f for f in files if f in changed),
            "dataset_builder_changes": builder_diff, "dataset_builder_additive_scale_only": builder_additive_only,
            "ok": spec_at_freeze == spec_now and not any(f in changed for f in files) and builder_additive_only}


def run_m05v2_preflight(frame_dir: Path) -> dict[str, Any]:
    """Inputs only. Computes no metric and reads no final rank."""
    import statistics as st

    from ml.backtest.ranking_midpoint import MIDPOINT, decision_snapshots
    from ml.models.ranking_xgb_v2 import event_contribution_targets

    rows = load_frame_rows(frame_dir)
    fold, _, _, _ = _folds(rows)
    presence = {}
    for season in SEASONS:
        teams = [t for r in rows if r.season == season for t in (*r.red_teams, *r.blue_teams)]
        with_epa = [t for t in teams if t.epa_total_present]
        presence[season] = {"appearances": len(teams),
                            "score_scale_present": round(sum(t.score_scale_present for t in teams) / len(teams), 4),
                            "epa_scale_present_given_epa": round(sum(t.epa_scale_present for t in with_epa) / len(with_epa), 4)
                            if with_epa else None}
    # independent check of S(Y, t) against SQL stddev_pop for random snapshots
    database = _database()
    rng = random.Random(20260930)
    sample = rng.sample([r for r in rows], 40)
    worst = 0.0
    checked = 0
    with database.cursor() as cursor:
        for r in sample:
            t = r.red_teams[0] if r.red_teams else None
            if t is None or not t.score_scale_present:
                continue
            cursor.execute(
                "SELECT stddev_pop(s) FROM (SELECT score_red AS s FROM matches WHERE season = %(y)s AND scheduled_time < %(t)s "
                "AND score_red IS NOT NULL AND score_blue IS NOT NULL UNION ALL SELECT score_blue FROM matches "
                "WHERE season = %(y)s AND scheduled_time < %(t)s AND score_red IS NOT NULL AND score_blue IS NOT NULL) x",
                {"y": r.season, "t": r.scheduled_time})
            worst = max(worst, abs(float(cursor.fetchone()[0]) - t.score_scale))
            checked += 1
    targets, exclusions = event_contribution_targets(fold.train_rows)
    snaps = decision_snapshots(fold.test_rows, MIDPOINT)
    last_qual = {}
    for r in fold.test_rows:
        if r.comp_level == "qualification":
            last_qual[r.event_key] = max(last_qual.get(r.event_key, r.scheduled_time), r.scheduled_time)
    by_key = {r.match_key: r for r in fold.test_rows}
    after_quals = sum(1 for ev in snaps.values() for sn in ev.values() if by_key[sn.match_key].scheduled_time > last_qual[sn.event_key])
    n_values = [sn.n for ev in snaps.values() for sn in ev.values()]
    used = [sn.features.matches_used for ev in snaps.values() for sn in ev.values()]
    return {
        "milestone": "M05v2 preflight", "frozen_files": _frozen_file_check(),
        "frame_content_hash": frame_info(frame_dir)["manifest"]["content_hash"],
        "scale_presence": presence,
        "scale_sql_check": {"snapshots_checked": checked, "max_abs_difference": worst, "ok": checked > 0 and worst < 1e-9},
        "training_targets": {"labelled_team_events": len(targets), "exclusions": exclusions,
                             "training_rows": len(fold.train_rows)},
        "decision_snapshots_2026": {"events": len(snaps), "team_events": len(n_values),
                                    "snapshots_after_qualification": after_quals,
                                    "n_i": {"min": min(n_values), "median": st.median(n_values), "max": max(n_values)},
                                    "matches_known_at_snapshot": {"min": min(used), "median": st.median(used), "max": max(used)}},
    }


def run_m05v2(frame_dir: Path, m04: dict[str, Any]) -> dict[str, Any]:
    """The single pre-registered M5 v2 evaluation (D16 §1.5). Refuses to run twice."""
    from ml.backtest.ranking_midpoint import FIRST, LAST, MIDPOINT, decision_snapshots, evaluate_ranking
    from ml.models.baselines import RawEpaRankingBaseline
    from ml.models.ranking_xgb_v2 import FEATURE_NAMES_V2, RankingXGBModelV2

    existing = list(frame_dir.glob("m05v2_result_*.json")) + ([M05V2_RESULT_RECORD] if M05V2_RESULT_RECORD.exists() else [])
    if existing:
        raise RuntimeError(f"M5 v2 has already been run ({existing[0]}); D16 allows exactly one run")
    frozen = _frozen_file_check()
    if not frozen["ok"]:
        raise RuntimeError(f"frozen methodology changed since {FREEZE_COMMIT}: {frozen}")

    rows = load_frame_rows(frame_dir)
    fold, _, _, _ = _folds(rows)
    final_ranks = _final_ranks(HELD_OUT_SEASON)
    model, twin = RankingXGBModelV2(), RankingXGBModelV2()
    model.fit(fold.train_rows)
    twin.fit(fold.train_rows)
    baseline = RawEpaRankingBaseline()
    snaps = {"midpoint": decision_snapshots(fold.test_rows, MIDPOINT),
             "first": decision_snapshots(fold.test_rows, FIRST),
             "last": decision_snapshots(fold.test_rows, LAST)}
    primary = evaluate_ranking(model.predict_rating, snaps["midpoint"], final_ranks)
    primary_twin = evaluate_ranking(twin.predict_rating, snaps["midpoint"], final_ranks)
    base_primary = evaluate_ranking(baseline.predict_rating, snaps["midpoint"], final_ranks)
    frozen_baseline = m04["result"]["ranking"]["aggregate"]["spearman"]
    gate = (primary.spearman is not None and base_primary.spearman is not None
            and primary.spearman > base_primary.spearman and primary.spearman > frozen_baseline)

    secondary = {}
    for name in ("first", "last"):
        m = evaluate_ranking(model.predict_rating, snaps[name], final_ranks)
        b = evaluate_ranking(baseline.predict_rating, snaps[name], final_ranks)
        secondary[name] = {"model_spearman": m.spearman, "model_top8": m.top_k_recall,
                           "baseline_spearman": b.spearman, "baseline_top8": b.top_k_recall,
                           "events": m.events_scored, "teams": m.teams_scored}
    shuffle = []
    for seed in range(1, 9):
        shuffled = RankingXGBModelV2()
        shuffled.fit(_labels_shuffled(fold.train_rows, seed))
        shuffle.append(evaluate_ranking(shuffled.predict_rating, snaps["midpoint"], final_ranks).spearman)
    gain = model.feature_gain()
    total_gain = sum(gain.values())
    population = snaps["midpoint"]
    return {
        "milestone": "M05v2", "decision": "D16", "spec": f"{SPEC_PATH} §1 (frozen at {FREEZE_COMMIT})",
        "frozen_files": frozen,
        "frame_content_hash": frame_info(frame_dir)["manifest"]["content_hash"],
        "split": {"train_seasons": TRAIN_SEASONS, "held_out_season": HELD_OUT_SEASON,
                  "train_rows": len(fold.train_rows), "test_rows": len(fold.test_rows)},
        "fit": {"labelled_team_events": model.labelled_team_events, "target_exclusions": model.target_exclusions,
                "train_samples": model.fit_train_sample_count, "validation_samples": model.fit_validation_sample_count,
                "best_iteration": model.best_iteration},
        "primary": {"model": primary.to_dict(), "baseline_same_protocol": base_primary.to_dict(),
                    "frozen_baseline_0.5951": frozen_baseline},
        "gate_beats_same_protocol_baseline": primary.spearman is not None and base_primary.spearman is not None
        and primary.spearman > base_primary.spearman,
        "gate_beats_frozen_baseline": primary.spearman is not None and primary.spearman > frozen_baseline,
        "gate_passed": gate,
        "reproducible": primary.to_dict() == primary_twin.to_dict(),
        "secondary": {**secondary, "label_shuffle_midpoint_spearman": shuffle,
                      "label_shuffle_mean": sum(x for x in shuffle if x is not None) / len(shuffle),
                      "feature_gain_share": {k: v / total_gain for k, v in sorted(gain.items(), key=lambda kv: -kv[1])},
                      "features": list(FEATURE_NAMES_V2)},
        "population": {"events_with_snapshots": len(population), "team_events": sum(len(v) for v in population.values()),
                       "events_scored": primary.events_scored, "events_skipped": primary.events_skipped,
                       "teams_scored": primary.teams_scored},
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    sub = parser.add_subparsers(dest="command", required=True)
    b = sub.add_parser("build-frame")
    b.add_argument("--chain", type=Path, help="STRATAI EPA chain manifest")
    b.add_argument("--statbotics-snapshot", type=Path, help="Statbotics snapshot directory (D17)")
    b.add_argument("--out", type=Path, required=True)
    for name in ("m04", "m05", "m06", "m07", "m05v2-preflight", "m05v2"):
        command = sub.add_parser(name)
        command.add_argument("--frame", type=Path, required=True)
        if name in ("m05", "m06", "m05v2"):
            command.add_argument("--m04", type=Path, required=True, help="the frozen M4 result JSON")
    args = parser.parse_args(argv)

    if args.command == "build-frame":
        build_frame(args.chain, args.out, args.statbotics_snapshot)
        return 0
    if args.command == "m04":
        result = run_m04(args.frame)
    elif args.command == "m05":
        result = run_m05(args.frame, _load_json(args.m04))
    elif args.command == "m06":
        result = run_m06(args.frame, _load_json(args.m04))
    elif args.command == "m05v2-preflight":
        result = run_m05v2_preflight(args.frame)
    elif args.command == "m05v2":
        result = run_m05v2(args.frame, _load_json(args.m04))
    else:
        result = run_m07(args.frame)
    digest = hashlib.sha256(json.dumps(result, sort_keys=True, default=str).encode()).hexdigest()[:12]
    path = args.frame / f"{args.command.replace('-', '_')}_result_{digest}.json"
    _write_once(path, {**result, "ran_at": datetime.now(timezone.utc).isoformat()})
    if args.command == "m05v2":
        _write_once(M05V2_RESULT_RECORD, {**result, "artifact": str(path)})  # the in-repo record; blocks a second run
    shown = {k: v for k, v in result.items() if not isinstance(v, (dict, list))}
    print(json.dumps(shown, indent=2, default=str))
    print(f"-> {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
