"""Verify the production API serves the D18 system Phase 4 evaluated.

    python -m scripts.verify_d18_production --frame FRAME_DIR [--sample 300]

Uses the real application (api.create_app with Settings from the environment) and
the real database, read-only. Checks, and records in
.agent/production/d18_integration_check.json:

1. the served ranking model is RankingXGBModelV2 (ranking_xgb_v2) and the served
   win-probability model is the D18 M7 pair, with artifact sha256s equal to the
   registration record (.agent/production/d18_model_registration.json);
2. the EPA source is d18_statbotics_primary over the verified snapshot recorded in
   results/d18/source_verification.json;
3. served features equal the evaluated ones: for sampled held-out 2026 matches
   (every 2026iscmp qualification match included), the features the API builds
   at the match's scheduled time equal the D18 frame's TeamFeatures field for
   field, and the served value equals the rounded model output on the frame row;
4. per-team provenance is returned (statbotics / stratai_fallback);
5. playoff matches and unstated ad-hoc contexts get no validated probability.

It re-evaluates no milestone: it compares the serving path with the recorded frame.
"""

from __future__ import annotations

import argparse
import json
import random
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

RESULTS = Path(".agent/phase4/results/d18")
REGISTRATION = Path(".agent/production/d18_model_registration.json")
RECORD = Path(".agent/production/d18_integration_check.json")


def main(argv: list[str] | None = None) -> int:
    from fastapi.testclient import TestClient

    from api import create_app
    from api.routes.predictions import display_probability
    from data.config import Settings
    from ml.backtest.harness import _match_features
    from ml.features.assembler import build_match_feature_row
    from ml.features.scale import ScaleLookup
    from ml.models.calibrated_win_prob import CalibratedWinProbModel
    from ml.models.ranking_xgb_v2 import RankingXGBModelV2
    from scripts.run_phase4_stratai import load_frame_rows

    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--frame", type=Path, required=True)
    parser.add_argument("--sample", type=int, default=300)
    parser.add_argument("--record", type=Path, default=RECORD, help="write-once output path")
    args = parser.parse_args(argv)
    record_path = args.record
    if record_path.exists():
        raise SystemExit(f"{record_path} exists: verification records are write-once")

    settings = Settings()
    registration = json.loads(REGISTRATION.read_text(encoding="utf-8"))
    verification = json.loads((RESULTS / "source_verification.json").read_text(encoding="utf-8"))
    app = create_app(settings)
    checks: dict[str, Any] = {}

    ranking, win = app.state.ranking_model, app.state.win_prob_model
    checks["1_models"] = {
        "ranking_class": type(ranking.model).__name__ if ranking else None,
        "ranking_model_type": ranking.manifest.model_type if ranking else None,
        "ranking_sha256_matches_registration": bool(ranking) and ranking.sha256 == registration["ranking"]["sha256"],
        "win_prob_class": type(win.model).__name__ if win else None,
        "win_prob_model_type": win.manifest.model_type if win else None,
        "win_prob_sha256_matches_registration": bool(win) and win.sha256 == registration["win_prob"]["sha256"],
        "ranking_provenance_source_version": ranking.manifest.provenance.get("source_version") if ranking else None,
    }
    checks["1_models"]["ok"] = (isinstance(getattr(ranking, "model", None), RankingXGBModelV2)
                                and isinstance(getattr(win, "model", None), CalibratedWinProbModel)
                                and checks["1_models"]["ranking_sha256_matches_registration"]
                                and checks["1_models"]["win_prob_sha256_matches_registration"])

    rows = [r for r in load_frame_rows(args.frame) if r.season == 2026]
    by_key = {r.match_key: r for r in rows}
    quals = [r for r in rows if r.comp_level == "qualification"]
    playoffs = [r for r in rows if r.comp_level != "qualification"]
    rng = random.Random(20261002)
    sample = rng.sample([r for r in quals if r.event_key != "2026iscmp"], args.sample)
    sample += [r for r in quals if r.event_key == "2026iscmp"]

    with TestClient(app) as client:
        first = client.get(f"/predictions/matches/{sample[0].match_key}/win-probability").json()
        epa = first["epa"]
        recorded = verification["provenance"]
        checks["2_epa_source"] = {
            "epa_source": epa["epa_source"], "evaluated_configuration": epa["evaluated_configuration"],
            "snapshot": epa["provenance"].get("snapshot"), "recorded_snapshot": recorded.get("snapshot"),
            "team_event_stats_sha256": epa["provenance"].get("team_event_stats_sha256"),
            "recorded_team_event_stats_sha256": recorded.get("team_event_stats_sha256"),
        }
        checks["2_epa_source"]["ok"] = (epa["epa_source"] == "d18_statbotics_primary" and epa["evaluated_configuration"]
                                        and epa["provenance"].get("snapshot") == recorded.get("snapshot")
                                        and epa["provenance"].get("team_event_stats_sha256")
                                        == recorded.get("team_event_stats_sha256"))

        provider = app.state.epa_source.provider
        database = app.state.database
        feature_mismatches, value_mismatches, provenance_mismatches, labels = [], [], [], {}
        for row in sample:
            served = build_match_feature_row(database, row.match_key, row.scheduled_time, epa_provider=provider,
                                             scale_lookup=ScaleLookup(database))
            expected = sorted((t.model_dump() for t in (*row.red_teams, *row.blue_teams)), key=lambda t: t["team_number"])
            actual = sorted((t.model_dump() for t in (*served.red_teams, *served.blue_teams)), key=lambda t: t["team_number"])
            if expected != actual:
                feature_mismatches.append(row.match_key)
            body = client.get(f"/predictions/matches/{row.match_key}/win-probability").json()
            shown = body.get("red_win_probability")
            if shown is None:
                shown = body.get("unvalidated_red_win_probability")
            # validated exactly when the match is in M7's evaluated population (every team EPA-present)
            epa_complete = all(t.epa_total_present for t in (*row.red_teams, *row.blue_teams))
            gated_right = (body.get("validation_status") == "approximately_calibrated_qualification") == epa_complete
            if shown != display_probability(win.model.predict_win_prob(_match_features(row))) or not gated_right:
                value_mismatches.append(row.match_key)
            api_teams = {t["team_number"]: (t["epa_value_source"], t["epa_source_event_key"]) for t in body["teams"]}
            frame_teams = {t.team_number: (t.epa_value_source, t.epa_source_event_key)
                           for t in (*row.red_teams, *row.blue_teams)}
            if api_teams != frame_teams:
                provenance_mismatches.append(row.match_key)
            for source, _ in api_teams.values():
                labels[str(source)] = labels.get(str(source), 0) + 1
        iscmp = [r for r in sample if r.event_key == "2026iscmp"]
        checks["3_served_features_equal_evaluated"] = {
            "matches_compared": len(sample), "of_which_2026iscmp": len(iscmp),
            "feature_mismatches": feature_mismatches[:10], "feature_mismatch_count": len(feature_mismatches),
            "served_value_mismatch_count": len(value_mismatches),
            "ok": not feature_mismatches and not value_mismatches}
        checks["4_provenance"] = {"labels_seen": labels, "mismatch_count": len(provenance_mismatches),
                                  "ok": not provenance_mismatches and labels.get("stratai_fallback", 0) > 0
                                  and labels.get("statbotics", 0) > 0}

        playoff_bodies = [client.get(f"/predictions/matches/{r.match_key}/win-probability").json()
                          for r in rng.sample(playoffs, 25)]

        # Ad-hoc and ranking requests are evaluated "as of now". D18 refuses (epa_source_incomplete)
        # when a team's latest prior event has no valid Statbotics row outside the 2026iscmp fallback
        # scope -- e.g. teams whose latest event is an unprocessed 2026 Israeli event. Record every
        # attempt; require refusals to be that documented code (never a 500), and the normal path to
        # work on the first event that answers.
        attempts, ranking_body, adhoc = [], None, None
        for row in sample:
            response = client.get(f"/predictions/events/{row.event_key}/ranking")
            code = None if response.status_code == 200 else response.json()["error"]["code"]
            attempts.append({"event_key": row.event_key, "status": response.status_code, "code": code})
            if response.status_code == 200:
                ranking_body = response.json()
                teams = [t.team_number for t in (*row.red_teams, *row.blue_teams)]
                adhoc = client.post("/predictions/win-probability", json={
                    "event_key": row.event_key, "red_team_numbers": teams[:3], "blue_team_numbers": teams[3:]}).json()
                break
            if len(attempts) >= 20:
                break
        refusals = [a for a in attempts if a["status"] != 200]
        checks["5_gating"] = {
            "playoff_matches": len(playoff_bodies),
            "playoff_validated_values_served": sum(b.get("red_win_probability") is not None for b in playoff_bodies),
            "playoff_all_not_validated": all(b.get("validation_status") == "not_validated" for b in playoff_bodies),
            "ranking_attempts": attempts,
            "refusals_all_epa_source_incomplete": all(a["status"] == 422 and a["code"] == "epa_source_incomplete"
                                                      for a in refusals),
            "adhoc_unstated_context": None if adhoc is None else {
                "red_win_probability": adhoc.get("red_win_probability"),
                "unvalidated_red_win_probability": adhoc.get("unvalidated_red_win_probability"),
                "validation_status": adhoc.get("validation_status")},
            "ranking": None if ranking_body is None else {
                "event_key": ranking_body["event_key"], "model_type": ranking_body.get("model_type"),
                "teams": len(ranking_body.get("rankings", [])), "validation_status": ranking_body.get("validation_status"),
                "epa_value_sources": sorted({str(e["epa_value_source"]) for e in ranking_body.get("rankings", [])})},
        }
        checks["5_gating"]["ok"] = (checks["5_gating"]["playoff_validated_values_served"] == 0
                                    and checks["5_gating"]["playoff_all_not_validated"]
                                    and checks["5_gating"]["refusals_all_epa_source_incomplete"]
                                    and adhoc is not None and adhoc.get("red_win_probability") is None
                                    and adhoc.get("validation_status") == "not_validated"
                                    and ranking_body is not None and ranking_body.get("model_type") == "ranking_xgb_v2")

    if record_path.exists():
        raise SystemExit(f"{record_path} exists: verification records are write-once")
    result = {"checked_at": datetime.now(timezone.utc).isoformat(), "frame": str(args.frame),
              "checks": checks, "passed": all(c["ok"] for c in checks.values())}
    record_path.parent.mkdir(parents=True, exist_ok=True)
    record_path.write_text(json.dumps(result, indent=1, default=str) + "\n", encoding="utf-8")
    print(json.dumps({name: check["ok"] for name, check in checks.items()}, indent=1))
    print("D18 production alignment:", "VERIFIED" if result["passed"] else "FAILED", f"-> {record_path}")
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    sys.exit(main())
