"""P6-M12: historical validation of the strategy engine, as `.agent/phase6/decisions/P6_M12_SAMPLING.md` fixes it.

    python -m scripts.phase6_m12_strategy_validation     # DATABASE_URL = the isolated stratai_test copy

- **Setup:** creates the retained isolated clone `stratai_test_p6m12` from `stratai_test` (never from serving), and
  runs everything there.
- **Checks:**
  - (a) the engine replayed at match time reproduces the P6-M10 frame-based odds bit for bit;
  - (b) future sentinel rows change nothing;
  - (c) honest odds;
  - (d) the mentor review, recorded as not performed.
- **Record:** write-once `.agent/phase6/results/p6_m12_strategy_validation.json`.
- **Time budget:** a hard 45 minutes.
"""

from __future__ import annotations

import random
import sys
import time
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path

from scripts.phase6_common import REGISTRY_DIR, git_blob, load_frame, read_record, write_once

PLAN = ".agent/phase6/decisions/P6_M12_SAMPLING.md"
CLONE = "stratai_test_p6m12"
SEED_BASE = 20261008
PER_STRATUM, SENTINELS = 15, 20
BUDGET_SECONDS = 45 * 60
SNAPSHOT = Path("C:/Dev/StratAI-artifacts/statbotics/statbotics_snapshot_20261001T220423Z")
CHAIN = Path("C:/Dev/StratAI-artifacts/ratings/epa-chain/chain_e77d9444c57a7b50.json")
FAR_FUTURE = datetime(2026, 12, 31, tzinfo=timezone.utc)
SENTINEL_PREFIX = "t_p6m12_sentinel"
RECORD = "p6_m12_strategy_validation_rerun1.json"
SUPERSEDES = {"record": "p6_m12_strategy_validation.json", "failure_record": ".agent/phase6/P6_M12_RUN1_FAILURE.md",
              "reason": "harness defect: coach sentinels were timestamped +1h (legitimately past for later sampled matches at the same event); now far-future like the other sentinel rows; per-match sentinel outcomes recorded; same plan, sample and seed"}

WEEK_SQL = """
SELECT DISTINCT ON (r.source_object_id) r.source_object_id, (r.payload_json->>'week')::int
FROM raw_source_payloads r
WHERE r.source = 'tba' AND r.source_object_type = 'event' AND r.is_current AND r.source_object_id = ANY(%s)
ORDER BY r.source_object_id, r.id DESC
"""


def _dump(teams):
    return sorted((t.model_dump(exclude={"epa_source_state"}) for t in teams), key=lambda t: t["team_number"])


def _fingerprint(engine, context):
    from ml.strategy.representation import Strategy

    red = [t.team_number for t in context.red_teams]
    baseline = engine.assess(context, "red", Strategy.baseline(red))
    recommendation = engine.recommend(context, "red")
    rec = recommendation.recommended
    return {"baseline_p_red": baseline.p_ours,
            "recommended": None if rec is None else (rec.strategy.sha256(), rec.p_ours),
            "alternatives": [(a.strategy.sha256(), a.p_ours) for a in recommendation.alternatives],
            "observations": len(context.observations)}


def main() -> int:
    from data.config import Settings
    from database.connection import Database, DatabaseConfig
    from ml.features.assembler import build_match_feature_row
    from ml.features.scale import ScaleLookup
    from ml.ratings.d18_source import load_d18_provider
    from ml.strategy.coach_inputs import COACH_SOURCE, load_coach_observations, submit_coach_observation
    from ml.strategy.display import ABOVE_HIGH, BELOW_LOW, display_odds
    from ml.strategy.engine import StrategyEngine
    from ml.strategy.outcome import MatchContext, load_registered_strategy_model, missing_inputs
    from ml.strategy.representation import Strategy
    from scripts.phase5_isolated_db import clone, isolated_url, serving_name

    started = time.time()
    url = str(Settings().database_url)
    if serving_name(url) != "stratai_test":
        raise SystemExit("run with DATABASE_URL = the isolated stratai_test copy")
    clone(CLONE, replace=True)
    database = Database(DatabaseConfig(isolated_url(url, CLONE)))

    fit = read_record("p6_m10_fit.json")
    model = load_registered_strategy_model(REGISTRY_DIR, expected_sha256=fit["registry"]["model_sha256"])
    engine = StrategyEngine(model)
    rows, frame_hash = load_frame()

    def frame_context(row):
        return MatchContext(tuple(row.red_teams), tuple(row.blue_teams))

    population = sorted((r for r in rows if r.season == 2026 and r.comp_level == "qualification" and r.label != "tie"
                         and len(r.red_teams) == 3 and len(r.blue_teams) == 3
                         and all(t.epa_total_present for t in (*r.red_teams, *r.blue_teams))
                         and not missing_inputs(frame_context(r))), key=lambda r: r.match_key)
    with database.cursor() as cursor:
        cursor.execute(WEEK_SQL, (sorted({r.event_key for r in population}),))
        weeks = dict(cursor.fetchall())
    strata: dict[int, list] = defaultdict(list)
    for row in population:
        week = weeks.get(row.event_key)
        strata[-1 if week is None else week].append(row)
    sample = []
    for week in sorted(strata):
        members = strata[week]
        sample.extend(members if len(members) <= PER_STRATUM
                      else random.Random(SEED_BASE + week).sample(members, PER_STRATUM))

    provider, integrity = load_d18_provider(database, SNAPSHOT, CHAIN)
    scales = ScaleLookup(database)

    def replay(row):
        features = build_match_feature_row(database, row.match_key, row.scheduled_time, epa_provider=provider,
                                           scale_lookup=scales)
        observations, invalid = load_coach_observations(database, row.event_key, row.scheduled_time)
        return features, MatchContext(tuple(features.red_teams), tuple(features.blue_teams),
                                      observations=observations), invalid

    results, fingerprints, over_budget = [], {}, False
    honest = {"sum_to_one_violations": 0, "engine_differs_from_model": 0, "raw_below_0_05": 0,
              "raw_above_0_95": 0, "display_rule_violations": 0}
    for index, row in enumerate(sample):
        if time.time() - started > BUDGET_SECONDS:
            over_budget = True
            break
        features, context, _ = replay(row)
        features_equal = (_dump(features.red_teams) == _dump(row.red_teams)
                          and _dump(features.blue_teams) == _dump(row.blue_teams))
        red = [t.team_number for t in context.red_teams]
        blue = [t.team_number for t in context.blue_teams]
        expected = model.evaluate(frame_context(row), Strategy.baseline(red), Strategy.baseline(blue))
        engine_baseline = engine.assess(context, "red", Strategy.baseline(red))
        direct = model.evaluate(context, Strategy.baseline(red), Strategy.baseline(blue))
        p, q = engine_baseline.evaluation.p_red, engine_baseline.evaluation.p_blue
        honest["sum_to_one_violations"] += abs(p + q - 1.0) > 1e-12
        honest["engine_differs_from_model"] += (p != direct.p_red)
        honest["raw_below_0_05"] += min(p, q) < 0.05
        honest["raw_above_0_95"] += max(p, q) > 0.95
        honest["display_rule_violations"] += engine_baseline.display_ours != display_odds(p) or (
            p < 0.05 and engine_baseline.display_ours != BELOW_LOW) or (p > 0.95 and engine_baseline.display_ours != ABOVE_HIGH)
        results.append({"match_key": row.match_key, "week": weeks.get(row.event_key), "features_equal": features_equal,
                        "reproduced": p == expected.p_red, "p_red": p})
        if index < SENTINELS:
            fingerprints[row.match_key] = (row, _fingerprint(engine, context))

    sentinel_results = {}
    if not over_budget:
        inserted = []
        with database.cursor() as cursor:
            for n, (match_key, (row, _)) in enumerate(fingerprints.items()):
                sentinel = f"{row.event_key}_{SENTINEL_PREFIX}{n}"
                cursor.execute("INSERT INTO matches (match_key, event_key, season, competition_level, set_number, "
                               "match_number, scheduled_time, score_red, score_blue, winning_alliance, last_updated) "
                               "VALUES (%s, %s, %s, 'qualification', 1, %s, %s, 999, 0, 'red', NOW())",
                               (sentinel, row.event_key, row.season, 900 + n, FAR_FUTURE))
                for colour, teams in (("red", row.red_teams), ("blue", row.blue_teams)):
                    for t in teams:
                        cursor.execute("INSERT INTO match_teams (match_key, team_number, alliance_color, last_updated) "
                                       "VALUES (%s, %s, %s, NOW())", (sentinel, t.team_number, colour))
                        cursor.execute("INSERT INTO scouting_observations (match_key, event_key, team_number, "
                                       "scout_identifier, defense_rating, feeding_rating, source, submitted_at) "
                                       "VALUES (%s, %s, %s, 'p6m12-sentinel', 5, 5, 'p6m12_sentinel', %s)",
                                       (sentinel, row.event_key, t.team_number, FAR_FUTURE))
                inserted.append(sentinel)
        for match_key, (row, _) in fingerprints.items():
            submit_coach_observation(database, {"event_key": row.event_key, "team_number": row.red_teams[0].team_number,
                                                "kind": "robot_unavailable", "observer": "p6m12-sentinel",
                                                "observed_at": FAR_FUTURE.isoformat()})
        for match_key, (row, before) in fingerprints.items():
            _, context, _ = replay(row)
            sentinel_results[match_key] = _fingerprint(engine, context) == before
        with database.cursor() as cursor:
            cursor.execute("DELETE FROM scouting_observations WHERE source = 'p6m12_sentinel'")
            cursor.execute("DELETE FROM match_teams WHERE match_key = ANY(%s)", (inserted,))
            cursor.execute("DELETE FROM matches WHERE match_key = ANY(%s)", (inserted,))
            cursor.execute("DELETE FROM raw_source_payloads WHERE source = %s AND payload_json->>'observer' = %s",
                           (COACH_SOURCE, "p6m12-sentinel"))

    reproduced = sum(r["reproduced"] for r in results)
    features_equal = sum(r["features_equal"] for r in results)
    honest_ok = all(honest[k] == 0 for k in ("sum_to_one_violations", "engine_differs_from_model",
                                             "display_rule_violations"))
    criteria = {
        "a_reproduction": {"matches": len(results), "reproduced": reproduced, "features_equal": features_equal,
                           "passed": len(results) == len(sample) and reproduced == len(results)},
        "b_sentinels": {"matches": len(sentinel_results), "unchanged": sum(sentinel_results.values()),
                        "per_match": sentinel_results,
                        "passed": len(sentinel_results) == min(SENTINELS, len(sample)) and all(sentinel_results.values())},
        "c_honest_odds": {**honest, "passed": honest_ok and len(results) == len(sample)},
        "d_mentor_review": {"performed": False, "note": "optional, not gating; no genuine named review was supplied"},
    }
    record = {
        "milestone": "P6-M12", "supersedes": SUPERSEDES, "plan": PLAN, "plan_blob": git_blob(PLAN), "frame_content_hash": frame_hash,
        "clone": CLONE, "epa_source": {"provider": "d18", "integrity": integrity},
        "model": {"version_tag": model.version_tag, "model_sha256": model.artifact_sha256,
                  "served_baseline_status": list(model.baseline_status)},
        "population": len(population), "strata": {str(w): len(m) for w, m in sorted(strata.items())},
        "sample": [r["match_key"] for r in results], "criteria": criteria,
        "passed": all(c.get("passed", True) for c in criteria.values()) and not over_budget,
        "validated_here": ["engine replay reproduces the P6-M10 odds at match time (point-in-time correctness)",
                           "no future row, scouting observation or coach observation leaks into any output",
                           "odds are reported unclamped and displayed by the one rule"],
        "not_validated_here": ["strategy effects (no historical strategy records; 0 scouting rows)",
                               "defense and feeding effects", "baseline calibration (P6-M10 gate FAILED)",
                               "playoff context (P6-M3 not run)"],
        "over_budget": over_budget, "minutes": round((time.time() - started) / 60, 1),
    }
    path = write_once(RECORD, record)
    print({k: v["passed"] for k, v in criteria.items() if "passed" in v}, "passed:", record["passed"],
          "minutes:", record["minutes"], "->", path)
    return 0 if record["passed"] else 1


if __name__ == "__main__":
    sys.exit(main())
