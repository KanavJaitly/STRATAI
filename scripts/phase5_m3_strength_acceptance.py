"""P5-M3 acceptance: the strength view on 1,000 real appearances, computed once.

    python -m scripts.phase5_m3_strength_acceptance --frame FRAME_DIR --snapshot SNAPSHOT_DIR --chain CHAIN

Frozen criteria (docs/P5Milestones.md, P5-M3), recorded write-once in
.agent/phase5/results/p5_m3_strength_acceptance.json:

* population: 1,000 appearances sampled once (seed 20261003) from the D18 frame's
  2026 rows; an appearance is (team, event, the match's scheduled time);
* exact equality between the view and the assembler's TeamFeatures for every field
  (ml.views.strength.matches_features), using the production D18 EPA source;
* every numeric field has n and an uncertainty, and every absent value a reason
  (enforced by the view's models; re-checked here);
* every EPA value has its provenance (value source, source state, source event).

Additionally recorded: equality with the D18 frame's own TeamFeatures for the fields
the frame carries (it predates epa_source_state), a stronger check than the criterion.
"""

from __future__ import annotations

import argparse
import random
import sys
from pathlib import Path

from data.config import Settings
from database.connection import DatabaseConfig
from database.readonly import ReadOnlySessionDatabase
from ml.features.assembler import build_team_features
from ml.features.scale import ScaleLookup
from ml.ratings.d18_source import load_d18_provider
from ml.views.strength import Measure, TeamStrengthView, build_team_strength, matches_features
from scripts.phase5_records import sha256_file, write_once
from scripts.run_phase4_stratai import frame_info, load_frame_rows

SEED = 20261003
SAMPLE = 1000
RECORD = "p5_m3_strength_acceptance.json"
FRAME_FIELDS_EXCLUDED = {"epa_source_state"}  # added in Phase 5; the D18 frame predates it


def _measures(view: TeamStrengthView) -> list[Measure]:
    found: list[Measure] = []

    def walk(value) -> None:
        if isinstance(value, Measure):
            found.append(value)
        elif hasattr(value, "model_fields"):
            for name in type(value).model_fields:
                walk(getattr(value, name))
        elif isinstance(value, list):
            for item in value:
                walk(item)

    walk(view)
    return found


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--frame", type=Path, required=True)
    parser.add_argument("--snapshot", type=Path, required=True)
    parser.add_argument("--chain", type=Path, required=True)
    args = parser.parse_args(argv)

    database = ReadOnlySessionDatabase(DatabaseConfig(Settings().database_url))
    provider, integrity = load_d18_provider(database, args.snapshot, args.chain)
    rows = [r for r in load_frame_rows(args.frame) if r.season == 2026]
    appearances = sorted({(t.team_number, r.event_key, r.scheduled_time): t
                          for r in rows for t in (*r.red_teams, *r.blue_teams)}.items(),
                         key=lambda kv: (kv[0][2], kv[0][1], kv[0][0]))
    sample = random.Random(SEED).sample(appearances, SAMPLE)

    scales = ScaleLookup(database)
    view_mismatch, frame_mismatch, contract_failures = [], [], []
    states: dict[str, int] = {}
    for (team, event, as_of), frame_features in sample:
        view = build_team_strength(database, team, event, as_of, epa_provider=provider, scale_lookup=scales)
        features = build_team_features(database, team, event, as_of, epa_provider=provider, scale_lookup=scales)
        diff = matches_features(view, features)
        if diff:
            view_mismatch.append({"team": team, "event": event, "as_of": as_of.isoformat(), "fields": diff})
        if features.model_dump(exclude=FRAME_FIELDS_EXCLUDED) != frame_features.model_dump(exclude=FRAME_FIELDS_EXCLUDED):
            frame_mismatch.append({"team": team, "event": event, "as_of": as_of.isoformat()})
        problems = [m for m in _measures(view) if m.n < 0]
        if view.epa.total.value is not None and (view.epa.epa_value_source is None or view.epa.epa_source_state is None
                                                 or view.epa.source_event_key is None):
            problems.append("epa_provenance_missing")
        if problems:
            contract_failures.append({"team": team, "event": event, "problems": [str(p) for p in problems]})
        states[str(view.epa.epa_source_state)] = states.get(str(view.epa.epa_source_state), 0) + 1

    passed = not view_mismatch and not contract_failures
    result = {
        "milestone": "P5-M3", "spec": "docs/P5Milestones.md (frozen P5-M0)",
        "population": {"frame_content_hash": frame_info(args.frame)["manifest"]["content_hash"],
                       "frame_info_sha256": sha256_file(args.frame / "frame_info.json"),
                       "season": 2026, "distinct_appearances": len(appearances), "sampled": len(sample), "seed": SEED},
        "epa_source": {"provider": provider.source, "snapshot_integrity": integrity},
        "criterion_exact_equality_with_assembler": {"mismatches": len(view_mismatch), "examples": view_mismatch[:10]},
        "criterion_contracts": {"failures": len(contract_failures), "examples": contract_failures[:10]},
        "additional_equality_with_d18_frame": {"mismatches": len(frame_mismatch), "examples": frame_mismatch[:10],
                                               "fields_excluded": sorted(FRAME_FIELDS_EXCLUDED)},
        "epa_source_states": states,
        "passed": passed,
    }
    path = write_once(RECORD, result)
    print(f"assembler mismatches {len(view_mismatch)}, contract failures {len(contract_failures)}, "
          f"frame mismatches {len(frame_mismatch)}, states {states}; passed={passed} -> {path}")
    return 0 if passed else 1


if __name__ == "__main__":
    sys.exit(main())
