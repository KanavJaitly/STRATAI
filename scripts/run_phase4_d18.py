"""Phase 4 under decision D18: Statbotics-primary EPA, STRATAI fallback for 2026iscmp only.

Specification: .agent/phase4/D18_SOURCE_SPEC.md, frozen at commit ec1b0af before
any D18 dataset or metric existed. This script defines no model, feature, metric,
split or threshold: every milestone run delegates to the same functions the D15
runner (scripts/run_phase4_stratai.py) uses, and M11 to
scripts/run_m11_generalization.generalization_checks, unchanged. What it adds is
the D18 source (ml.ratings.statbotics_primary), its verification (spec §6), and
guards:

* methodology freeze: the D18 spec, the D16 spec, every model/metric/gate
  module, and the D15 result records must be unchanged since ec1b0af;
* implementation pin: the source/feature code must be committed and unchanged
  since the commit that built the D18 frame;
* single run: every milestone result is write-once under RESULTS_DIR, and a
  milestone whose record exists refuses to run again.

Subcommands, in order:

    verify --snapshot DIR --chain CHAIN      spec §6 S1-S6 over every 2024-2026 appearance (no metric)
    build-frame --snapshot DIR --chain CHAIN --out DIR
    m04 | m05v2 | m06 | m07 | m11 --frame DIR
"""

from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import random
import sys
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ml.ratings.statbotics_primary import (
    D18_FREEZE_COMMIT,
    D18_SPEC,
    FALLBACK_EVENT,
    RULE_A1_SEASON_END,
    VALUE_SOURCE_FALLBACK,
    VALUE_SOURCE_STATBOTICS,
    StatboticsPrimaryEpa,
    StatboticsTeamEvent,
)
from scripts import run_phase4_stratai as d15

RESULTS_DIR = Path(".agent/phase4/results/d18")
VERIFICATION_RECORD = RESULTS_DIR / "source_verification.json"
PARITY_SAMPLE = 6000  # spec §6 S4: at least 5,000
PARITY_SEED = 20261001

# Spec §4: unchanged since the D18 freeze. Methodology, gates, and the D15 evidence.
METHODOLOGY_FILES = [
    D18_SPEC, d15.SPEC_PATH, "docs/P4Milestones.md",
    "ml/models/baselines.py", "ml/models/ranking_xgb.py", "ml/models/ranking_xgb_v2.py", "ml/models/team_vector.py",
    "ml/models/win_prob.py", "ml/backtest/harness.py", "ml/backtest/metrics.py", "ml/backtest/ranking_midpoint.py",
    "ml/calibration/calibrator.py", "ml/calibration/gate.py", "ml/features/scale.py",
    "ml/features/score_breakdown.py", "scripts/run_m4_baseline_backtest.py", "scripts/run_m11_generalization.py",
    ".agent/phase4/M04_ACCEPTANCE.md", ".agent/phase4/M05_ACCEPTANCE.md", ".agent/phase4/M06_ACCEPTANCE.md",
    ".agent/phase4/M07_ESCALATION.md",
    *(f".agent/phase4/results/{name}" for name in (
        "m04_result.json", "m05_result.json", "m05v2_result.json", "m06_result.json", "m07_result.json")),
]
# The D18 source and feature implementation: pinned to the commit that built the frame.
IMPLEMENTATION_FILES = [
    "ml/ratings/statbotics_primary.py", "ml/ratings/provider.py", "ml/features/assembler.py",
    "ml/dataset/builder.py", "scripts/run_phase4_stratai.py", "scripts/sync_statbotics_snapshot.py",
]
# This file is pinned function by function: whatever produced or verified the frame must be
# byte-identical to the pinned commit. Amended 2026-10-02 (before M11 ran): run_m11's readiness
# step needed a non-read-only connection (D8's temp tables, as scripts/run_m11_generalization.py
# uses), which the whole-file pin could not admit; every frame-producing function stays pinned.
THIS_FILE = "scripts/run_phase4_d18.py"
PINNED_FUNCTIONS = ["load_source", "verify", "build_frame", "_frame_provenance_counts", "_qual_count",
                    "_find_key", "_stratai_availability", "_guard", "methodology_check", "_frame_guard",
                    "run_m04", "run_m05v2", "run_m06", "run_m07"]

APPEARANCES_SQL = """
SELECT DISTINCT m.season, mt.team_number, m.event_key, m.scheduled_time
FROM matches m JOIN match_teams mt ON mt.match_key = m.match_key
WHERE m.season = ANY(%(seasons)s) AND m.scheduled_time IS NOT NULL
ORDER BY m.scheduled_time, m.event_key, mt.team_number
"""
# "Completed match" for T_end / T_w1: both official alliance scores recorded (ml.features.scale's timeline).
EVENT_LAST_MATCH_SQL = """
SELECT m.event_key, e.season, MAX(m.scheduled_time)
FROM matches m JOIN events e ON e.event_key = m.event_key
WHERE e.season = ANY(%(seasons)s) AND m.scheduled_time IS NOT NULL
  AND m.score_red IS NOT NULL AND m.score_blue IS NOT NULL
GROUP BY m.event_key, e.season
"""


class D18GuardError(RuntimeError):
    pass


# --- guards ------------------------------------------------------------------------------


def _head() -> str:
    return d15._git("rev-parse", "HEAD").strip()


def methodology_check() -> dict[str, Any]:
    changed = set(d15._git("diff", "--name-only", D18_FREEZE_COMMIT, "HEAD").splitlines())
    changed |= set(d15._git("diff", "--name-only", "HEAD").splitlines())
    spec_frozen = d15._git("rev-parse", f"{D18_FREEZE_COMMIT}:{D18_SPEC}").strip()
    spec_now = d15._git("hash-object", D18_SPEC).strip()
    touched = sorted(f for f in METHODOLOGY_FILES if f in changed)
    return {"freeze_commit": D18_FREEZE_COMMIT, "spec_blob_at_freeze": spec_frozen, "spec_blob_now": spec_now,
            "methodology_files_changed_since_freeze": touched, "ok": spec_frozen == spec_now and not touched}


def _function_sources(text: str) -> dict[str, str]:
    import ast

    tree = ast.parse(text)
    return {node.name: ast.get_source_segment(text, node) for node in tree.body
            if isinstance(node, (ast.FunctionDef, ast.ClassDef))}


def implementation_check(pinned_commit: str | None = None) -> dict[str, Any]:
    dirty = sorted(set(d15._git("diff", "--name-only", "HEAD").splitlines()) & set(IMPLEMENTATION_FILES + [THIS_FILE]))
    drift, functions_changed = [], []
    if pinned_commit is not None:
        drift = sorted(set(d15._git("diff", "--name-only", pinned_commit, "HEAD").splitlines()) & set(IMPLEMENTATION_FILES))
        import subprocess

        then = _function_sources(subprocess.run(["git", "show", f"{pinned_commit}:{THIS_FILE}"], capture_output=True,
                                                check=True).stdout.decode("utf-8"))
        now = _function_sources(Path(THIS_FILE).read_text(encoding="utf-8"))
        functions_changed = [name for name in PINNED_FUNCTIONS if then.get(name) != now.get(name)]
    return {"head": _head(), "pinned_commit": pinned_commit, "uncommitted": dirty,
            "changed_since_pinned_commit": drift, "pinned_functions_changed": functions_changed,
            "ok": not dirty and not drift and not functions_changed}


def _guard(*, pinned_commit: str | None = None) -> dict[str, Any]:
    method, impl = methodology_check(), implementation_check(pinned_commit)
    if not (method["ok"] and impl["ok"]):
        raise D18GuardError(json.dumps({"methodology": method, "implementation": impl}, indent=1))
    return {"methodology": method, "implementation": impl}


def _write_record(name: str, value: dict[str, Any]) -> Path:
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    path = RESULTS_DIR / name
    d15._write_once(path, {**value, "source_version": "D18", "recorded_at": datetime.now(timezone.utc).isoformat()})
    return path


# --- the D18 source (spec §1-3), loaded with S1 integrity checks ---------------------------


def _qual_count(record: dict[str, Any]) -> int | None:
    return ((record.get("record") or {}).get("qual") or {}).get("count")


def load_source(database, snapshot: Path, chain: Path, *, strict: bool) -> tuple[StatboticsPrimaryEpa, dict[str, Any]]:
    """The D18 provider over the cached snapshot. Raises unless S1 holds exactly."""
    from ml.ratings.provider import StrataiPointInTimeEpa, read_team_event_facts
    from scripts.sync_statbotics_snapshot import table_fingerprint

    manifest = d15._load_json(snapshot / "manifest.json")
    if manifest["failures"] or manifest["events_fetched"] != manifest["events_requested"]:
        raise D18GuardError(f"snapshot {snapshot.name} recorded failures")
    raw: dict[tuple[int, str], dict[str, Any]] = {}
    event_meta: dict[str, set[tuple[str, int]]] = defaultdict(set)
    for entry in manifest["events"]:
        data = gzip.decompress((snapshot / entry["raw_file"]).read_bytes())
        if hashlib.sha256(data).hexdigest() != entry["raw_sha256"]:
            raise D18GuardError(f"{entry['raw_file']} does not match its manifest sha256")
        for record in json.loads(data):
            raw[(record["team"], record["event"])] = record
            event_meta[record["event"]].add((record["status"], record["week"]))
    rows, fingerprint = table_fingerprint(database, manifest["seasons"])
    if fingerprint != manifest["team_event_stats"]["sha256"]:
        raise D18GuardError(f"team_event_stats does not match snapshot {snapshot.name}")
    mismatched, statbotics = [], {}
    for team, event_key, season, total, auto, teleop, endgame, played in rows:
        record = raw.get((team, event_key))
        published = None if record is None else (record.get("epa") or {}).get("total_points")
        if record is None or (published is None) != (total is None) or (
                total is not None and abs(float(published) - total) > 1e-9):
            mismatched.append([team, event_key, total, published])
            continue
        statbotics[(team, event_key)] = StatboticsTeamEvent(season, total, auto, teleop, endgame, played,
                                                            _qual_count(record))
    raw_only = sorted(set(raw) - set(statbotics) - {(m[0], m[1]) for m in mismatched})
    mixed = sorted(e for e, meta in event_meta.items() if len(meta) != 1)
    if mismatched or raw_only or mixed:
        raise D18GuardError(f"S1 failed: {len(mismatched)} raw/table mismatches {mismatched[:5]}, "
                            f"{len(raw_only)} raw records with no table row, events with mixed status/week {mixed}")

    with database.cursor() as cursor:
        cursor.execute(EVENT_LAST_MATCH_SQL, {"seasons": manifest["seasons"]})
        last_match = cursor.fetchall()
    season_end: dict[int, datetime] = {}
    week_one: dict[int, datetime] = {}
    for event_key, season, last in last_match:
        season_end[season] = max(season_end.get(season, last), last)
        if event_meta.get(event_key) == {("Completed", 1)}:
            week_one[season] = max(week_one.get(season, last), last)
    if set(week_one) != set(manifest["seasons"]) or set(season_end) != set(manifest["seasons"]):
        raise D18GuardError(f"T_w1/T_end undefined for some season: {sorted(week_one)} / {sorted(season_end)}")

    fallback = StrataiPointInTimeEpa.from_chain_manifest(database, chain)
    s1 = {"raw_files_verified": len(manifest["events"]), "raw_records": len(raw), "table_rows": len(rows),
          "team_event_stats_sha256": fingerprint, "raw_equals_table_epa_total": len(statbotics),
          "a1_team_events": sum(v.rule == RULE_A1_SEASON_END for v in statbotics.values()),
          "a1_team_events_valid": sum(v.rule == RULE_A1_SEASON_END and v.valid for v in statbotics.values()),
          "invalid_team_events": sum(not v.valid for v in statbotics.values()), "ok": True}
    info = {"snapshot": snapshot.name, "endpoint": manifest["base_url"] + manifest["endpoint"],
            "params_template": manifest["params_template"], "schema_version": manifest["schema_version"],
            "retrieved": [manifest["started_at"], manifest["finished_at"]],
            "snapshot_producing_commit": manifest["producing_commit"], "team_event_stats_sha256": fingerprint}
    provider = StatboticsPrimaryEpa(statbotics, read_team_event_facts(database), season_end, week_one, fallback,
                                    provenance_info=info, strict=strict)
    return provider, s1


# --- spec §6 verification -----------------------------------------------------------------


def _find_key(value: Any, key: str) -> Any:
    if isinstance(value, dict):
        if key in value:
            return value[key]
        value = list(value.values())
    if isinstance(value, list):
        for item in value:
            found = _find_key(item, key)
            if found is not None:
                return found
    return None


def _stratai_availability(chain: Path) -> dict[str, dict[str, int]]:
    """Each chained STRATAI season's recorded availability times (its execution report)."""
    out = {}
    for entry in d15._load_json(chain)["chain"]:
        report = d15._load_json(chain.parent / entry["directory"] / "execution_report.json")
        out[str(entry["season"])] = {k: _find_key(report, k) for k in ("week_one_complete_time", "season_final_time")}
    return out


def verify(snapshot: Path, chain: Path) -> dict[str, Any]:
    from ml.ratings.provider import EPA_SOURCE_SQL, TeamEventEpa

    guard = _guard()
    database = d15._database()
    provider, s1 = load_source(database, snapshot, chain, strict=False)
    with database.cursor() as cursor:
        cursor.execute(APPEARANCES_SQL, {"seasons": d15.SEASONS})
        appearances = cursor.fetchall()

    outcomes: Counter = Counter()
    fallback_outside, leakage, a1_early = [], [], []
    target_fallback = Counter()
    parity_pool = []
    for season, team, target, as_of in appearances:
        before = provider.diagnostics["withheld:availability"]
        found = provider.point_in_time_epa(team, target, as_of)
        if isinstance(found, TeamEventEpa):
            if found.source == VALUE_SOURCE_FALLBACK:
                key = "stratai_fallback"
                available = datetime.fromtimestamp(found.provenance["available_at"], timezone.utc)
                if target != FALLBACK_EVENT:
                    fallback_outside.append([team, target, as_of.isoformat()])
            else:
                key = f"statbotics:{found.provenance['rule']}"
                available = datetime.fromisoformat(found.provenance["available_at"])
                if found.provenance["rule"] == RULE_A1_SEASON_END and as_of <= provider.season_end[
                        provider.statbotics[(team, found.event_key)].season]:
                    a1_early.append([team, target, as_of.isoformat(), found.event_key])
                if not found.provenance["skipped"] and target != FALLBACK_EVENT:
                    parity_pool.append((team, target, as_of, found.event_key))
            if not available < as_of:
                leakage.append([team, target, as_of.isoformat(), found.event_key, available.isoformat()])
        else:
            key = f"withheld:{found.reason}"
            if found.reason == "d18_hard_error":
                key = "hard_error"
            elif target != FALLBACK_EVENT and provider.diagnostics["withheld:availability"] != before:
                key = "withheld:availability"  # every D13 candidate unavailable (§3)
            elif target != FALLBACK_EVENT:
                key = "withheld:no_prior_event"
                parity_pool.append((team, target, as_of, None))
        outcomes[(season, key)] += 1
        if target == FALLBACK_EVENT:
            target_fallback[key] += 1

    rng = random.Random(PARITY_SEED)
    sample = rng.sample(parity_pool, min(PARITY_SAMPLE, len(parity_pool)))
    parity_mismatch = []
    with database.cursor() as cursor:
        for team, target, as_of, served in sample:
            cursor.execute(EPA_SOURCE_SQL, {"team": team, "target": target, "as_of": as_of})
            row = cursor.fetchone()
            if (row[0] if row else None) != served:
                parity_mismatch.append([team, target, as_of.isoformat(), served, row[0] if row else None])

    stratai = _stratai_availability(chain)
    s6 = {str(y): {"statbotics_T_w1": provider.week_one_complete[y].isoformat(),
                   "stratai_week_one_complete": datetime.fromtimestamp(
                       stratai[str(y)]["week_one_complete_time"], timezone.utc).isoformat(),
                   "statbotics_T_end": provider.season_end[y].isoformat(),
                   "stratai_season_final": datetime.fromtimestamp(
                       stratai[str(y)]["season_final_time"], timezone.utc).isoformat()}
          for y in d15.SEASONS}
    iscmp_total = sum(target_fallback.values())
    checks = {
        "S1_snapshot_integrity": s1,
        "S2_fallback_scope": {"appearances_targeting_fallback_event": iscmp_total,
                              "fallback_event_outcomes": dict(target_fallback),
                              "fallback_outside_scope": len(fallback_outside),
                              "ok": not fallback_outside and iscmp_total > 0 and all(
                                  k in ("stratai_fallback", "withheld:no_prior_concluded_event_epa")
                                  for k in target_fallback)},
        "S3_no_silent_fallback": {"hard_errors": len(provider.hard_errors), "examples": provider.hard_errors[:20],
                                  "ok": not provider.hard_errors},
        "S4_selection_parity": {"pool": len(parity_pool), "sampled": len(sample), "seed": PARITY_SEED,
                                "mismatches": len(parity_mismatch), "examples": parity_mismatch[:20],
                                "ok": len(sample) >= 5000 and not parity_mismatch},
        "S5_leakage": {"served_with_available_at_not_before_as_of": len(leakage), "examples": leakage[:20],
                       "a1_served_before_season_end": len(a1_early), "ok": not leakage and not a1_early},
        "S6_week_one_cross_check": s6,
    }
    by_season: dict[str, dict[str, int]] = defaultdict(dict)
    for (season, key), n in sorted(outcomes.items()):
        by_season[str(season)][key] = n
    totals = Counter()
    for (_, key), n in outcomes.items():
        totals[key] += n
    return {
        "milestone": "D18 source verification (spec §6)", "guard": guard,
        "appearances": len(appearances), "outcomes_total": dict(sorted(totals.items())),
        "outcomes_by_season": by_season, "lookup_diagnostics": dict(sorted(provider.diagnostics.items())),
        "provenance": provider.provenance(), "checks": checks,
        "passed": all(c["ok"] for name, c in checks.items() if name != "S6_week_one_cross_check"),
    }


# --- frame ---------------------------------------------------------------------------------


def _frame_provenance_counts(rows: list) -> dict[str, Any]:
    counts: dict[str, Counter] = defaultdict(Counter)
    outside = 0
    for row in rows:
        for team in (*row.red_teams, *row.blue_teams):
            label = team.epa_value_source or "withheld"
            counts[str(row.season)][label] += 1
            if row.event_key == FALLBACK_EVENT:
                counts["target_" + FALLBACK_EVENT][label] += 1
            elif team.epa_value_source == VALUE_SOURCE_FALLBACK:
                outside += 1
    return {"d18_appearance_value_sources": {k: dict(v) for k, v in sorted(counts.items())},
            "d18_fallback_outside_scope": outside}


def build_frame(snapshot: Path, chain: Path, out: Path) -> Path:
    guard = _guard()
    verification = d15._load_json(VERIFICATION_RECORD)
    if not verification["passed"] or verification["guard"]["implementation"]["head"] != guard["implementation"]["head"]:
        raise D18GuardError("source verification has not passed at this commit; run `verify` first")
    database = d15._database()
    provider, _ = load_source(database, snapshot, chain, strict=True)
    commit = guard["implementation"]["head"]

    def extra(rows: list) -> dict[str, Any]:
        counts = _frame_provenance_counts(rows)
        if counts["d18_fallback_outside_scope"]:
            raise D18GuardError(f"{counts['d18_fallback_outside_scope']} fallback values outside {FALLBACK_EVENT}")
        return {**counts, "d18_producing_commit": commit, "d18_guard": guard,
                "d18_verification_sha256": hashlib.sha256(VERIFICATION_RECORD.read_bytes()).hexdigest()}

    directory = d15.persist_frame(database, provider, out, extra_info=extra)
    info = d15.frame_info(directory)
    _write_record("frame_info.json", {k: v for k, v in info.items() if k != "excluded"}
                  | {"frame_directory": str(directory), "excluded_count": len(info["excluded"])})
    return directory


# --- milestones ----------------------------------------------------------------------------


def _frame_guard(frame_dir: Path) -> dict[str, Any]:
    info = d15.frame_info(frame_dir)
    record = d15._load_json(RESULTS_DIR / "frame_info.json")
    if record["manifest"]["content_hash"] != info["manifest"]["content_hash"]:
        raise D18GuardError(f"{frame_dir} is not the recorded D18 frame")
    return {**_guard(pinned_commit=info["d18_producing_commit"]), "frame_content_hash": info["manifest"]["content_hash"]}


def _once(name: str) -> None:
    if (RESULTS_DIR / name).exists():
        raise D18GuardError(f"{RESULTS_DIR / name} exists: D18 runs each milestone exactly once")


def run_m04(frame_dir: Path) -> dict[str, Any]:
    _once("m04_result.json")
    guard = _frame_guard(frame_dir)
    result = d15.run_m04(frame_dir)
    return {**result, "guard": guard, "passed": result["reproducible"]}


def run_m05v2(frame_dir: Path) -> dict[str, Any]:
    _once("m05v2_result.json")
    guard = _frame_guard(frame_dir)
    reference = d15._load_json(RESULTS_DIR / "m04_result.json")["result"]["ranking"]["aggregate"]["spearman"]
    result = d15.evaluate_m05v2(frame_dir, reference, reference_key="d18_m04_ranking_spearman")
    return {**result, "spec": f"{d15.SPEC_PATH} §1 + {D18_SPEC} §4", "guard": guard,
            "passed": result["gate_passed"] and result["reproducible"]}


def run_m06(frame_dir: Path) -> dict[str, Any]:
    _once("m06_result.json")
    guard = _frame_guard(frame_dir)
    result = d15.run_m06(frame_dir, d15._load_json(RESULTS_DIR / "m04_result.json"))
    passed = (result["gate_log_loss_beats_or_matches"] and result["gate_brier_beats_or_matches"]
              and result["reproducible"] and result["held_out_symmetry_max_abs_error"] <= 1e-12
              and result["held_out_order_independent"])
    return {**result, "guard": guard, "passed": passed}


def run_m07(frame_dir: Path) -> dict[str, Any]:
    _once("m07_result.json")
    guard = _frame_guard(frame_dir)
    result = d15.run_m07(frame_dir)
    return {**result, "guard": guard, "passed": result["gate_passed"]}


def _non_epa_readiness_problems(readiness) -> list[str]:
    """D8's breakdown and final-ranking requirements (as scripts/run_m11_generalization.py applies them)."""
    from automation.data_readiness import BREAKDOWN_INVALID, BREAKDOWN_RAW_MISSING, UNKNOWN

    problems = list(readiness.reasons) if readiness.status == UNKNOWN else []
    for season, counts in readiness.score_breakdown_counts.items():
        for status in (BREAKDOWN_INVALID, BREAKDOWN_RAW_MISSING):
            if counts.get(status):
                problems.append(f"{season}: {counts[status]} completed match(es) {status}")
    if readiness.rankings_missing or not readiness.rankings_events_required:
        problems.append(f"held-out final rankings missing for {len(readiness.rankings_missing)} of "
                        f"{readiness.rankings_events_required} events")
    return problems


def run_m11(frame_dir: Path) -> dict[str, Any]:
    """D18 §5: M11's generalization test with the M5 model of record (v2) under its own protocol."""
    from automation.data_readiness import assess_readiness
    from ml.backtest.harness import run_win_prob_backtest
    from ml.backtest.ranking_midpoint import MIDPOINT, decision_snapshots, evaluate_ranking
    from ml.models.baselines import EpaWinProbBaseline, RawEpaRankingBaseline
    from ml.models.ranking_xgb_v2 import RankingXGBModelV2
    from ml.models.win_prob import WinProbXGBModel
    from scripts.run_m11_generalization import generalization_checks

    _once("m11_result.json")
    guard = _frame_guard(frame_dir)
    for dependency in ("m05v2_result.json", "m06_result.json"):
        if not d15._load_json(RESULTS_DIR / dependency)["passed"]:
            raise D18GuardError(f"M11 depends on {dependency}, which did not pass")
    from data.config import Settings
    from database.connection import Database, DatabaseConfig

    # D8's readiness builds session temp tables, refused in a read-only session; it writes no
    # canonical table (scripts/run_m11_generalization.py calls it the same way).
    readiness = assess_readiness(Database(DatabaseConfig(Settings().database_url)))
    database = d15._database()
    problems = _non_epa_readiness_problems(readiness)
    if problems or not d15._load_json(VERIFICATION_RECORD)["passed"]:
        raise D18GuardError(f"M11 readiness refused: {problems}")

    rows = d15.load_frame_rows(frame_dir)
    fold, epa_fold, train_excluded, test_excluded = d15._folds(rows)
    final_ranks = d15._final_ranks(d15.HELD_OUT_SEASON)
    model_win_prob = run_win_prob_backtest(WinProbXGBModel, [epa_fold]).aggregate
    baseline_win_prob = run_win_prob_backtest(EpaWinProbBaseline, [epa_fold]).aggregate
    ranking_model = RankingXGBModelV2()
    ranking_model.fit(fold.train_rows)
    snapshots = decision_snapshots(fold.test_rows, MIDPOINT)
    model_ranking = evaluate_ranking(ranking_model.predict_rating, snapshots, final_ranks)
    baseline_ranking = evaluate_ranking(RawEpaRankingBaseline().predict_rating, snapshots, final_ranks)
    present = sum(t.average_auto_points_present for r in fold.test_rows for t in (*r.red_teams, *r.blue_teams))
    checks = generalization_checks(model_win_prob=model_win_prob, baseline_win_prob=baseline_win_prob,
                                   model_ranking=model_ranking, baseline_ranking=baseline_ranking,
                                   held_out_auto_points_present=present)
    m05v2 = d15._load_json(RESULTS_DIR / "m05v2_result.json")
    m06 = d15._load_json(RESULTS_DIR / "m06_result.json")
    m04 = d15._load_json(RESULTS_DIR / "m04_result.json")
    consistent = {
        "m6_log_loss": model_win_prob.log_loss == m06["model"]["aggregate"]["log_loss"],
        "m4_win_prob_log_loss": baseline_win_prob.log_loss == m04["result"]["win_prob"]["aggregate"]["log_loss"],
        "m5v2_midpoint_spearman": model_ranking.spearman == m05v2["primary"]["model"]["spearman"],
        "baseline_midpoint_spearman": baseline_ranking.spearman == m05v2["primary"]["baseline_same_protocol"]["spearman"],
    }
    return {
        "milestone": "M11", "spec": f"{D18_SPEC} §5", "guard": guard,
        "readiness": {"status": readiness.status, "non_epa_problems": problems},
        "split": {"train_rows": len(fold.train_rows), "test_rows": len(fold.test_rows),
                  "epa_complete": [len(epa_fold.train_rows), len(epa_fold.test_rows)],
                  "epa_incomplete_excluded": [train_excluded, test_excluded]},
        "ranking_model": "RankingXGBModelV2 (M5 model of record), midpoint snapshot",
        "checks": [{"name": c.name, "value": c.value, "bars": c.bars, "lower_is_better": c.lower_is_better,
                    "passed": c.passed, "line": c.line()} for c in checks],
        "consistent_with_d18_records": consistent,
        "passed": all(c.passed for c in checks),
    }


MILESTONES = {"m04": run_m04, "m05v2": run_m05v2, "m06": run_m06, "m07": run_m07, "m11": run_m11}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    sub = parser.add_subparsers(dest="command", required=True)
    for name in ("verify", "build-frame"):
        command = sub.add_parser(name)
        command.add_argument("--snapshot", type=Path, required=True)
        command.add_argument("--chain", type=Path, required=True)
        if name == "build-frame":
            command.add_argument("--out", type=Path, required=True)
    for name in MILESTONES:
        sub.add_parser(name).add_argument("--frame", type=Path, required=True)
    args = parser.parse_args(argv)

    if args.command == "verify":
        result = verify(args.snapshot, args.chain)
        path = _write_record(VERIFICATION_RECORD.name, result)
        print(json.dumps({"passed": result["passed"], "outcomes_total": result["outcomes_total"],
                          "checks_ok": {k: v.get("ok") for k, v in result["checks"].items()}}, indent=1, default=str))
        print(f"-> {path}")
        return 0 if result["passed"] else 1
    if args.command == "build-frame":
        print(f"-> {build_frame(args.snapshot, args.chain, args.out)}")
        return 0
    result = MILESTONES[args.command](args.frame)
    digest = hashlib.sha256(json.dumps(result, sort_keys=True, default=str).encode()).hexdigest()[:12]
    artifact = args.frame / f"d18_{args.command}_result_{digest}.json"
    d15._write_once(artifact, {**result, "ran_at": datetime.now(timezone.utc).isoformat()})
    path = _write_record(f"{args.command}_result.json", {**result, "artifact": str(artifact)})
    print(json.dumps({k: v for k, v in result.items() if not isinstance(v, (dict, list))}, indent=2, default=str))
    print(f"-> {path}")
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    sys.exit(main())
