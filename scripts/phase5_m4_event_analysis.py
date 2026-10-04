"""P5-M4 acceptance: criteria (a)–(c), each computed once and recorded write-once.

    python -m scripts.phase5_m4_event_analysis --frame FRAME --snapshot SNAPSHOT --chain CHAIN \\
        --registry DIR --ranking-tag d18 --ranking-sha256 SHA

Frozen criteria (docs/P5Milestones.md, P5-M4). The record is .agent/phase5/results/p5_m4_event_analysis.json.

**Population.** Held-out 2026: the D18 frame's test rows, under D7's split, at the 208 events with final ranks.
The frozen D18 M5 v2 artifact is loaded from the registry with its sha256 checked, never refit. EPA is the D18
provider.

**(a) Reproduction (exact).** D18's per-team midpoint protocol must give raw EPA = 0.5955 and M5 v2 = 0.6112,
equal to `results/d18/m05v2_result.json`.

**(b) The served policy at the event switch point.**
- **The switch time S** is the time of the last team's ⌈n_i/2⌉-th retained qualification row, with n_i from the
  same rows D18 used.
- **The snapshot** is at the event's next canonical qualification match after S: the first decision the switched
  ordering serves. If no later qualification match exists, it is at S + 1 µs.
- **Features** are built by the assembler at that one as_of for every team.
- **Measured:** Spearman against final rank, per event, for M5 v2 and for raw EPA, with the paired event-bootstrap
  CI.
- **Decision:** M5 v2 is served after the switch only if the paired mean difference is > 0.

**(c) Captain hit rate.**
- **Population:** the 208 events with seeded alliances. Actual captains are the seeded alliances' captains.
- **Snapshots:**
  - pre-event, at the first qualification match (nothing from the event);
  - the switch point.
- **Measured:** the policy's ordering against the raw-EPA baseline at each snapshot, with the CI of the paired
  difference.
- **Labelled** `validated_as_measured`. Improvement is claimed only if the CI excludes 0.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import timedelta
from pathlib import Path
from typing import Any

RECORD = "p5_m4_event_analysis.json"
D18_M05V2 = Path(".agent/phase4/results/d18/m05v2_result.json")


def main(argv: list[str] | None = None) -> int:
    from data.alliances import read_event_alliances
    from data.config import Settings
    from database.connection import DatabaseConfig
    from database.readonly import ReadOnlySessionDatabase
    from ml.backtest.ranking_midpoint import MIDPOINT, decision_snapshots, evaluate_ranking
    from ml.features.assembler import build_team_features
    from ml.features.scale import ScaleLookup
    from ml.models.baselines import RawEpaRankingBaseline
    from ml.models.ranking_xgb_v2 import FEATURE_NAMES_V2, RankingXGBModelV2
    from ml.ratings.d18_source import load_d18_provider
    from ml.registry import load_registered_model
    from ml.views.event_analysis import (
        CAPTAINS,
        POLICY_M5V2,
        event_spearman,
        order_teams,
        paired_bootstrap,
        policy_model,
        switch_time,
    )
    from scripts.phase5_records import sha256_file, write_once
    from scripts.run_phase4_stratai import HELD_OUT_SEASON, _final_ranks, _folds, frame_info, load_frame_rows

    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    for name in ("--frame", "--snapshot", "--chain", "--registry"):
        parser.add_argument(name, type=Path, required=True)
    parser.add_argument("--ranking-tag", required=True)
    parser.add_argument("--ranking-sha256", required=True)
    args = parser.parse_args(argv)

    database = ReadOnlySessionDatabase(DatabaseConfig(Settings().database_url))
    m5v2, _ = load_registered_model(RankingXGBModelV2, registry_dir=args.registry, model_type="ranking_xgb_v2",
                                    version_tag=args.ranking_tag, current_feature_list=list(FEATURE_NAMES_V2),
                                    expected_sha256=args.ranking_sha256)
    raw = RawEpaRankingBaseline()
    rows = load_frame_rows(args.frame)
    fold, _, _, _ = _folds(rows)
    final_ranks = _final_ranks(HELD_OUT_SEASON)
    snaps = decision_snapshots(fold.test_rows, MIDPOINT)

    # --- (a) reproduction -----------------------------------------------------------------------
    recorded = json.loads(D18_M05V2.read_text(encoding="utf-8"))
    recorded = recorded.get("result", recorded)["primary"]
    a_raw = evaluate_ranking(raw.predict_rating, snaps, final_ranks)
    a_m5 = evaluate_ranking(m5v2.predict_rating, snaps, final_ranks)
    a = {"raw_epa_spearman": a_raw.spearman, "m5v2_midpoint_spearman": a_m5.spearman,
         "recorded_raw_epa": recorded["baseline_same_protocol"]["spearman"],
         "recorded_m5v2": recorded["model"]["spearman"], "events": a_m5.events_scored, "teams": a_m5.teams_scored}
    a["exact"] = (a["raw_epa_spearman"] == a["recorded_raw_epa"] and a["m5v2_midpoint_spearman"] == a["recorded_m5v2"]
                  and round(a["raw_epa_spearman"], 4) == 0.5955 and round(a["m5v2_midpoint_spearman"], 4) == 0.6112)

    # --- snapshots: pre-event and switch point, one as_of per event --------------------------------
    times = {r.match_key: r.scheduled_time for r in fold.test_rows}
    provider, integrity = load_d18_provider(database, args.snapshot, args.chain)
    scales = ScaleLookup(database)
    alliances = read_event_alliances(database, HELD_OUT_SEASON)
    events = sorted(e for e in snaps if final_ranks.get(e))
    per_event: dict[str, dict[str, Any]] = {}
    for number, event_key in enumerate(events, start=1):
        team_rows: dict[int, list] = {}
        for row in fold.test_rows:
            if row.event_key == event_key and row.comp_level == "qualification":
                for tf in (*row.red_teams, *row.blue_teams):
                    team_rows.setdefault(tf.team_number, []).append(row.scheduled_time)
        switch = switch_time(team_rows)
        with database.cursor() as cursor:
            cursor.execute("SELECT MIN(scheduled_time) FROM matches WHERE event_key = %s AND "
                           "competition_level = 'qualification' AND scheduled_time > %s", (event_key, switch))
            following = cursor.fetchone()[0]
            cursor.execute("SELECT MIN(scheduled_time) FROM matches WHERE event_key = %s AND "
                           "competition_level = 'qualification' AND scheduled_time IS NOT NULL", (event_key,))
            first = cursor.fetchone()[0]
        switch_as_of = following if following is not None else switch + timedelta(microseconds=1)
        teams = sorted(snaps[event_key])
        snapshot_features = {
            name: [build_team_features(database, t, event_key, as_of, epa_provider=provider, scale_lookup=scales)
                   for t in teams]
            for name, as_of in (("pre_event", first), ("switch", switch_as_of))}
        ranks = final_ranks[event_key]
        entry: dict[str, Any] = {"switch_time": switch.isoformat(), "switch_as_of": switch_as_of.isoformat(),
                                 "switch_as_of_is_next_match": following is not None,
                                 "pre_event_as_of": first.isoformat(), "teams": len(teams)}
        for name, features in snapshot_features.items():
            m5_scores = {f.team_number: m5v2.predict_rating(f) for f in features}
            raw_scores = {f.team_number: raw.predict_rating(f) for f in features}
            entry[name] = {"m5v2_spearman": event_spearman(m5_scores, ranks),
                           "raw_epa_spearman": event_spearman(raw_scores, ranks),
                           "m5v2_top8": [o.team_number for o in order_teams(features, m5v2.predict_rating)[:8]],
                           "raw_top8": [o.team_number for o in order_teams(features, raw.predict_rating)[:8]]}
        seeded = [al for al in alliances.get(event_key, []) if al.seed is not None and al.captain is not None]
        entry["captains"] = sorted(al.captain for al in seeded) if seeded else None
        per_event[event_key] = entry
        if number % 25 == 0:
            print(f"[{number}/{len(events)}] {event_key}", flush=True)

    # --- (b) the served policy at the switch point ------------------------------------------------
    pairs = [(e["switch"]["m5v2_spearman"], e["switch"]["raw_epa_spearman"]) for e in per_event.values()
             if e["switch"]["m5v2_spearman"] is not None and e["switch"]["raw_epa_spearman"] is not None]
    b_boot = paired_bootstrap([m - r for m, r in pairs])
    serve_m5v2 = b_boot["mean_difference"] > 0
    b = {"events": len(pairs), "m5v2_mean_spearman": sum(m for m, _ in pairs) / len(pairs),
         "raw_epa_mean_spearman": sum(r for _, r in pairs) / len(pairs), "paired": b_boot,
         "serve_m5v2_after_switch": serve_m5v2,
         "next_match_snapshots": sum(e["switch_as_of_is_next_match"] for e in per_event.values())}

    # --- (c) captain hit rate -------------------------------------------------------------------
    c: dict[str, Any] = {"label": "validated_as_measured"}
    captain_events = {k: e for k, e in per_event.items() if e["captains"]}
    c["events"] = len(captain_events)
    c["events_with_fewer_than_8_seeded_captains"] = sum(len(e["captains"]) < 8 for e in captain_events.values())
    for name, switched in (("pre_event", False), ("switch", True)):
        model = policy_model(switched, serve_m5v2)
        policy_rates, raw_rates = [], []
        for e in captain_events.values():
            actual = set(e["captains"])
            top = e[name]["m5v2_top8" if model == POLICY_M5V2 else "raw_top8"]
            policy_rates.append(len(set(top) & actual) / CAPTAINS)  # ml.views.event_analysis.captain_hit_rate
            raw_rates.append(len(set(e[name]["raw_top8"]) & actual) / CAPTAINS)
        boot = paired_bootstrap([p - r for p, r in zip(policy_rates, raw_rates)])
        c[name] = {"policy_model": model, "policy_hit_rate": sum(policy_rates) / len(policy_rates),
                   "raw_epa_hit_rate": sum(raw_rates) / len(raw_rates),
                   "policy_hit_rate_ci95": paired_bootstrap(policy_rates)["ci95"],
                   "paired": boot, "improvement_claimed": boot["ci95"][0] > 0}

    info = frame_info(args.frame)
    result = {"milestone": "P5-M4", "spec": "docs/P5Milestones.md (frozen P5-M0)",
              "population": {"frame_content_hash": info["manifest"]["content_hash"],
                             "frame_info_sha256": sha256_file(args.frame / "frame_info.json"),
                             "season": HELD_OUT_SEASON, "events": len(per_event)},
              "models": {"ranking_xgb_v2_sha256": args.ranking_sha256, "raw_epa": "RawEpaRankingBaseline"},
              "epa_source": {"provider": provider.source, "snapshot_integrity": integrity},
              "a_reproduction": a, "b_served_policy": b, "c_captain_hit_rate": c, "per_event": per_event,
              "passed_a": a["exact"]}
    path = write_once(RECORD, result)
    print(json.dumps({"a": a, "b": b, "c": {k: v for k, v in c.items()}}, indent=1, default=str))
    print(f"-> {path}")
    return 0 if a["exact"] else 1


if __name__ == "__main__":
    sys.exit(main())
