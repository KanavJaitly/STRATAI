"""P5-M2 historical validation L1 and L2 (LIVE_EPA_REFRESH_DESIGN.md §10), under decision P5-D11. Recorded once.

    python -m scripts.phase5_m2_l1_l2 l1 --snapshot DIR --chain CHAIN
    python -m scripts.phase5_m2_l1_l2 l2 --snapshot DIR --chain CHAIN --frame FRAME --registry DIR \\
        --ranking-sha256 SHA --win-prob-sha256 SHA

**Population:** all 2024–2026 appearances (D18's own `APPEARANCES_SQL`: 319,301), read-only on the serving
database. **Provider:** the live provider in simulated-retrieval mode with `a1a2_policy="d18_skip"` (P5-D11) and
concluded seasons 2024–2026 (historical). It is compared with the frozen D18 provider (`load_d18_provider`).

**L1, equivalence.**
- **Setup:** frozen mode, i.e. the root snapshot with `retrieved_at` set to the D18 availability, and STRATAI
  from the D15 chain.
- **Pass:** every appearance's result is identical to D18's, including the 450 `stratai_fallback` appearances,
  with no tolerance.
- **What is compared:** the served (event, total, auto, teleop, endgame, value source), or the withheld reason.

**L2, simulated cadence.** Each record is retrieved at `event_end` + lag, for lag ∈ {6, 24, 72} h.
- **Pass, for each lag:**
  - 0 served values with `available_at` ≥ as_of;
  - every appearance whose result differs from D18 is explained by the lag (its D18-served record's simulated
    retrieval is not before as_of);
  - per-state counts are reported.
- **Diagnostic only, at lag 24 h with the frozen models:**
  - the M5 v2 midpoint Spearman (D18 frame, held-out 2026);
  - the qualification ECE on EPA-complete matches.
  Features are the frame's own, with the provider-dependent fields (the EPA fields and `epa_scale`) recomputed
  exactly as `build_team_features` composes them. That is checked against the assembler on a seeded sample of
  200 appearances first.
"""

from __future__ import annotations

import argparse
import json
import random
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

LAGS = (6, 24, 72)
DIAGNOSTIC_LAG = 24
SEASONS = (2024, 2025, 2026)
POLICY = "d18_skip"  # P5-D11
CHECK_SAMPLE, CHECK_SEED = 200, 20261007


def _outcome(provider, team: int, target: str, as_of: datetime) -> tuple:
    from ml.ratings.provider import TeamEventEpa

    try:
        found = provider.point_in_time_epa(team, target, as_of)
    except Exception as exc:  # a refusal (pending / unavailable / D18 hard error)
        return ("refused", type(exc).__name__)
    if isinstance(found, TeamEventEpa):
        return ("served", found.event_key, found.total, found.auto, found.teleop, found.endgame, found.source)
    return ("withheld", found.reason)


def _state(provider, team: int, target: str, as_of: datetime) -> tuple[str, Any]:
    from ml.ratings.provider import TeamEventEpa

    try:
        found = provider.point_in_time_epa(team, target, as_of)
    except Exception as exc:
        return f"refused:{type(exc).__name__}", None
    if isinstance(found, TeamEventEpa):
        return found.provenance.get("epa_source_state"), found
    return "withheld_no_prior_event", None


def _sources(args):
    from data.config import Settings
    from database.connection import DatabaseConfig
    from database.readonly import ReadOnlySessionDatabase
    from ml.ratings.d18_source import load_d18_provider
    from ml.ratings.live_source import stratai_source
    from scripts.run_phase4_d18 import APPEARANCES_SQL

    database = ReadOnlySessionDatabase(DatabaseConfig(Settings().database_url))
    d18, integrity = load_d18_provider(database, args.snapshot, args.chain)
    stratai = stratai_source(database, args.chain)
    with database.cursor() as cursor:
        cursor.execute(APPEARANCES_SQL, {"seasons": list(SEASONS)})
        appearances = cursor.fetchall()
    return database, d18, integrity, stratai, appearances


def _live(database, args, schedule, stratai):
    from ml.ratings.live_source import load_live_provider

    return load_live_provider(database, root_dir=args.snapshot, chain=args.chain, a1a2_policy=POLICY,
                              concluded_seasons=set(SEASONS), schedule=schedule, stratai=stratai)


def run_l1(args) -> dict[str, Any]:
    from ml.ratings.live_epa import frozen_d18_schedule

    database, d18, integrity, stratai, appearances = _sources(args)
    live = _live(database, args, frozen_d18_schedule, stratai)
    mismatches, outcomes = [], Counter()
    for season, team, target, as_of in appearances:
        expected, actual = _outcome(d18, team, target, as_of), _outcome(live, team, target, as_of)
        outcomes[actual[0] if actual[0] != "served" else f"served:{actual[-1]}"] += 1
        if expected != actual:
            mismatches.append({"team": team, "target": target, "as_of": as_of.isoformat(),
                               "d18": list(expected), "live": list(actual)})
    database.close()
    return {"check": "L1 equivalence (frozen mode)", "policy": POLICY, "appearances": len(appearances),
            "outcomes": dict(sorted(outcomes.items())), "mismatches": len(mismatches),
            "examples": mismatches[:20], "d18_snapshot_integrity": integrity,
            "snapshot_id": live.retrieval.snapshot_id, "passed": len(appearances) == 319301 and not mismatches
            and outcomes.get("served:stratai_fallback", 0) == 450}


def _available_before(found, as_of: datetime) -> bool:
    available = found.provenance.get("available_at")
    when = (datetime.fromtimestamp(available, timezone.utc) if isinstance(available, (int, float))
            else datetime.fromisoformat(available))
    return when < as_of


def run_l2(args) -> dict[str, Any]:
    from ml.ratings.live_epa import lag_schedule

    database, d18, integrity, stratai, appearances = _sources(args)
    per_lag: dict[str, Any] = {}
    providers = {}
    for lag in LAGS:
        live = _live(database, args, lag_schedule(lag), stratai)
        providers[lag] = live
        leaked, unexplained, differing = [], [], 0
        states: Counter = Counter()
        retrieved = live.retrieval.retrieved_at  # type: ignore[attr-defined]
        for season, team, target, as_of in appearances:
            expected = _outcome(d18, team, target, as_of)
            state, found = _state(live, team, target, as_of)
            states[state] += 1
            if found is not None and not _available_before(found, as_of):
                leaked.append([team, target, as_of.isoformat()])
            actual = _outcome(live, team, target, as_of)
            if actual == expected:
                continue
            differing += 1
            served_event = expected[1] if expected[0] == "served" and expected[-1] == "statbotics" else None
            when = retrieved.get((team, served_event)) if served_event else None
            if not (when is not None and not when < as_of):
                unexplained.append({"team": team, "target": target, "as_of": as_of.isoformat(),
                                    "d18": list(expected), "live": list(actual)})
        per_lag[f"{lag}h"] = {"states": dict(sorted(states.items())), "differing_from_d18": differing,
                              "served_with_available_at_not_before_as_of": len(leaked), "leak_examples": leaked[:10],
                              "unexplained_differences": len(unexplained), "unexplained_examples": unexplained[:10],
                              "passed": not leaked and not unexplained}
    diagnostic = l2_diagnostic(args, database, providers[DIAGNOSTIC_LAG])
    database.close()
    return {"check": "L2 simulated cadence", "policy": POLICY, "appearances": len(appearances), "lags": per_lag,
            "diagnostic_lag_24h": diagnostic, "d18_snapshot_integrity": integrity,
            "passed": all(v["passed"] for v in per_lag.values()) and diagnostic["substitution_check"]["mismatches"] == 0}


def l2_diagnostic(args, database, provider) -> dict[str, Any]:
    """Diagnostic only: the frozen models on the frame's held-out 2026 rows with lag-24 EPA."""
    from ml.backtest.harness import _match_features
    from ml.backtest.metrics import expected_calibration_error
    from ml.backtest.ranking_midpoint import MIDPOINT, decision_snapshots, evaluate_ranking
    from ml.dataset.builder import LABEL_RED_WIN, LABEL_TIE
    from ml.features.assembler import _point_in_time_epa, build_team_features
    from ml.features.scale import ScaleLookup
    from ml.models.calibrated_win_prob import CALIBRATED_WIN_PROB_MODEL_TYPE, CalibratedWinProbModel
    from ml.models.ranking_xgb_v2 import FEATURE_NAMES_V2, RankingXGBModelV2
    from ml.models.win_prob import FEATURE_NAMES
    from ml.registry import load_registered_model
    from scripts.run_phase4_stratai import HELD_OUT_SEASON, _final_ranks, _folds, load_frame_rows

    scales = ScaleLookup(database)

    def substituted(tf, event_key: str, as_of: datetime):
        try:
            epa = _point_in_time_epa(database, tf.team_number, event_key, as_of, provider)
        except Exception:  # refused under the lag: the team cannot be served at this as_of
            return None
        season = scales.event_season(event_key)
        _, epa_scale = (None, None) if season is None else scales.feature_scales(season, as_of, epa.source_event_key)
        return tf.model_copy(update={
            "epa_total": epa.epa_total, "epa_total_present": epa.epa_total is not None, "epa_auto": epa.epa_auto,
            "epa_auto_present": epa.epa_auto is not None, "epa_teleop": epa.epa_teleop,
            "epa_teleop_present": epa.epa_teleop is not None, "epa_endgame": epa.epa_endgame,
            "epa_endgame_present": epa.epa_endgame is not None, "epa_source_event_key": epa.source_event_key,
            "epa_withheld_reason": epa.withheld_reason, "epa_value_source": epa.value_source,
            "epa_source_state": epa.source_state, "epa_scale": epa_scale, "epa_scale_present": epa_scale is not None})

    rows = load_frame_rows(args.frame)
    fold, epa_fold, _, _ = _folds(rows)
    test = [r for r in fold.test_rows]
    rng = random.Random(CHECK_SEED)
    sample = rng.sample([(r, tf) for r in test for tf in (*r.red_teams, *r.blue_teams)], CHECK_SAMPLE)
    check_mismatch, check_refused = 0, 0
    for row, tf in sample:  # substitution == the assembler under the same provider
        sub = substituted(tf, row.event_key, row.scheduled_time)
        if sub is None:
            check_refused += 1
            continue
        full = build_team_features(database, tf.team_number, row.event_key, row.scheduled_time, epa_provider=provider,
                                   scale_lookup=scales)
        check_mismatch += sub != full

    ranking, _ = load_registered_model(RankingXGBModelV2, registry_dir=args.registry, model_type="ranking_xgb_v2",
                                       version_tag="d18", current_feature_list=list(FEATURE_NAMES_V2),
                                       expected_sha256=args.ranking_sha256)
    win, _ = load_registered_model(CalibratedWinProbModel, registry_dir=args.registry,
                                   model_type=CALIBRATED_WIN_PROB_MODEL_TYPE, version_tag="d18",
                                   current_feature_list=list(FEATURE_NAMES), expected_sha256=args.win_prob_sha256)
    snaps = decision_snapshots(test, MIDPOINT)
    refused_snapshots = 0
    lagged: dict[str, dict] = {}
    for event_key, teams in snaps.items():
        lagged[event_key] = {}
        times = {r.match_key: r.scheduled_time for r in test if r.event_key == event_key}
        for team, snap in teams.items():
            sub = substituted(snap.features, event_key, times[snap.match_key])
            if sub is None:
                refused_snapshots += 1
                continue
            lagged[event_key][team] = type(snap)(snap.team, snap.event_key, snap.k, snap.n, snap.match_key, sub)
    spearman = evaluate_ranking(ranking.predict_rating, lagged, _final_ranks(HELD_OUT_SEASON))
    q, y, refused_matches, incomplete = [], [], 0, 0
    for row in test:
        if row.comp_level != "qualification" or row.label == LABEL_TIE:
            continue
        red = [substituted(t, row.event_key, row.scheduled_time) for t in row.red_teams]
        blue = [substituted(t, row.event_key, row.scheduled_time) for t in row.blue_teams]
        if any(t is None for t in red + blue):
            refused_matches += 1
            continue
        if not all(t.epa_total_present for t in red + blue):
            incomplete += 1
            continue
        lagged_row = row.model_copy(update={"red_teams": red, "blue_teams": blue})
        q.append(float(win.predict_win_prob(_match_features(lagged_row))))
        y.append(row.label == LABEL_RED_WIN)
    return {"label": "diagnostic only (not a pass criterion)", "lag_hours": DIAGNOSTIC_LAG,
            "substitution_check": {"sample": CHECK_SAMPLE, "seed": CHECK_SEED, "mismatches": check_mismatch,
                                   "refused": check_refused},
            "m5v2_midpoint_spearman": spearman.spearman, "m5v2_events": spearman.events_scored,
            "refused_snapshots": refused_snapshots, "qualification_ece_epa_complete": expected_calibration_error(q, y),
            "ece_matches": len(q), "refused_matches": refused_matches, "epa_incomplete_matches": incomplete,
            "reference_d18": {"m5v2_midpoint_spearman": 0.6112, "qualification_ece_epa_complete": 0.015}}


def main(argv: list[str] | None = None) -> int:
    from scripts.phase5_records import provenance, write_once

    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("check", choices=("l1", "l2"))
    for name in ("--snapshot", "--chain"):
        parser.add_argument(name, type=Path, required=True)
    parser.add_argument("--frame", type=Path)
    parser.add_argument("--registry", type=Path)
    parser.add_argument("--ranking-sha256")
    parser.add_argument("--win-prob-sha256")
    args = parser.parse_args(argv)
    provenance()  # refuse up front if the tree is dirty
    started = datetime.now(timezone.utc)
    result = run_l1(args) if args.check == "l1" else run_l2(args)
    result["minutes"] = round((datetime.now(timezone.utc) - started).total_seconds() / 60, 1)
    path = write_once(f"p5_m2_{args.check}.json", {"milestone": "P5-M2", "decision": "P5-D11", **result})
    print(json.dumps({k: v for k, v in result.items() if k not in ("examples", "d18_snapshot_integrity")}, indent=1,
                     default=str)[:4000])
    print(f"-> {path}")
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    sys.exit(main())
