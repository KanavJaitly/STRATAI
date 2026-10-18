"""P6-M6 (a): candidate profiles equal their source functions exactly (`.agent/phase6/decisions/P6_M6A_PLAN.md`).

    python -m scripts.phase6_m6a_profiles      # DATABASE_URL = the isolated stratai_test copy (read-only)

Writes the write-once record `.agent/phase6/results/p6_m6a_profiles.json`. Hard budget: 45 minutes.
"""

from __future__ import annotations

import random
import sys
import time
from pathlib import Path

from scripts.phase6_common import git_blob, isolated_database, write_once

PLAN = ".agent/phase6/decisions/P6_M6A_PLAN.md"
SEED, EVENTS = 20261011, 30
BUDGET_SECONDS = 45 * 60
SNAPSHOT = Path("C:/Dev/StratAI-artifacts/statbotics/statbotics_snapshot_20261001T220423Z")
CHAIN = Path("C:/Dev/StratAI-artifacts/ratings/epa-chain/chain_e77d9444c57a7b50.json")


def main() -> int:
    from ml.features.scale import ScaleLookup
    from ml.playoffs.data import read_event_playoffs, selection_features
    from ml.playoffs.selection import INSUFFICIENT, candidate_profile
    from ml.ratings.d18_source import load_d18_provider
    from ml.synergy.score import alliance_synergy

    started = time.time()
    database = isolated_database()
    provider, integrity = load_d18_provider(database, SNAPSHOT, CHAIN)
    scales = ScaleLookup(database)
    eligible = sorted((e for e in read_event_playoffs(database, 2026)
                       if e.alliances and not e.division_champion and e.latest_qualification is not None),
                      key=lambda e: e.event_key)
    sample = random.Random(SEED).sample(eligible, EVENTS)
    checked, mismatches, over_budget = 0, [], False
    for event in sample:
        if time.time() - started > BUDGET_SECONDS:
            over_budget = True
            break
        teams = {t for a in event.alliances for t in a.picks}
        features = selection_features(database, event, teams, provider=provider, scales=scales)
        for alliance in event.alliances:
            members = [features[t] for t in alliance.picks]
            for team in alliance.picks:
                f = features[team]
                profile = candidate_profile(f, members if len(members) == 3 else None)
                expected = {
                    "scoring_epa": (f.epa_total, None), "average_score": (f.average_score, f.matches_used),
                    "reliability": (f.reliability_score, f.matches_used),
                    "consistency": (f.consistency_rating, f.matches_used),
                    "defense": (f.defense_score, f.defense_observation_count),
                    "feeding": (f.feeding_score, f.feeding_observation_count)}
                for name, (value, n) in expected.items():
                    got = getattr(profile, name)
                    if (got.value, got.n) != (value, n):
                        mismatches.append(f"{event.event_key}/{team}/{name}: {got.value!r},{got.n!r} != {value!r},{n!r}")
                for name, value in (("defense", f.defense_score), ("feeding", f.feeding_score)):
                    if value is None and getattr(profile, name).validation_status != INSUFFICIENT:
                        mismatches.append(f"{event.event_key}/{team}/{name}: absent but not insufficient_data")
                if len(members) == 3:
                    reference = alliance_synergy(*members)
                    if (profile.synergy.value, profile.role_compatibility.value) != (reference.overall_score,
                                                                                      reference.role_fit_term):
                        mismatches.append(f"{event.event_key}/{team}/synergy differs from alliance_synergy")
                checked += 1
    record = {"milestone": "P6-M6", "criterion": "a", "plan": PLAN, "plan_blob": git_blob(PLAN),
              "epa_integrity": integrity, "events": [e.event_key for e in sample], "teams_checked": checked,
              "mismatches": mismatches[:50], "mismatch_count": len(mismatches),
              "passed": not mismatches and not over_budget and checked > 0, "over_budget": over_budget,
              "minutes": round((time.time() - started) / 60, 1)}
    path = write_once("p6_m6a_profiles.json", record)
    print({k: record[k] for k in ("teams_checked", "mismatch_count", "passed", "minutes")}, "->", path)
    return 0 if record["passed"] else 1


if __name__ == "__main__":
    sys.exit(main())
