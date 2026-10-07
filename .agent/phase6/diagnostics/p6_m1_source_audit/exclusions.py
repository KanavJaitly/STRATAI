"""Audit of every stored event exclusion (read-only, isolated copy): the evidence, and what excluding it removes.

The counts use a copy of the stored ruleset WITHOUT its exclusions (and, for small events, a hypothetical 8-alliance
reading), purely to measure what the exclusion removes. Nothing is stored or changed."""

import json
import pathlib
import sys

sys.path.insert(0, r"C:\Dev\StratAI")
from data.rulesets import RulesetError, SeasonRuleset  # noqa: E402
from data.rankings import read_final_ranks_for_season  # noqa: E402
from ml.features.scale import ScaleLookup  # noqa: E402
from ml.playoffs.data import event_members, playoff_rows, read_event_playoffs, selection_features  # noqa: E402
from ml.playoffs.px1 import map_side  # noqa: E402
from ml.ratings.d18_source import load_d18_provider  # noqa: E402
from scripts.phase6_common import isolated_database  # noqa: E402

A = pathlib.Path(r"C:\Users\Kanav\AppData\Local\Temp\claude\c--Dev-StratAI\7c888c37-aa1f-476d-a442-bd691493b99d\scratchpad\audit")
SNAPSHOT = pathlib.Path("C:/Dev/StratAI-artifacts/statbotics/statbotics_snapshot_20261001T220423Z")
CHAIN = pathlib.Path("C:/Dev/StratAI-artifacts/ratings/epa-chain/chain_e77d9444c57a7b50.json")
db = isolated_database()
provider, _ = load_d18_provider(db, SNAPSHOT, CHAIN)
scales = ScaleLookup(db)
out = {}
for y in (2024, 2025, 2026):
    stored = json.loads((A / f"stored_{y}.json").read_text(encoding="utf-8"))
    excluded = {e["event_key"]: e for e in stored["event_exclusions"]}
    unexcluded = dict(stored, event_exclusions=[])
    rules = SeasonRuleset.model_validate(unexcluded)
    ranks = read_final_ranks_for_season(db, y)
    events = {e.event_key: e for e in read_event_playoffs(db, y)}
    for key, ex in excluded.items():
        e = events[key]
        er = rules.for_event(key)
        info = {"reason": ex["reason"], "qualification_teams": e.team_count, "ranked_teams": len(ranks.get(key, {})),
                "alliances_listed": len(e.alliances), "alliance_sizes": [len(a.picks) for a in e.alliances],
                "placeholder_teams": sorted(t for a in e.alliances for t in a.picks if t not in ranks.get(key, {})),
                "roster_rule_covers": None, "playoff_matches": len(e.matches), "split": "held_out" if y == 2026 else "train"}
        try:
            info["roster_rule_covers"] = rules.alliances_for(e.team_count)
        except RulesetError as exc:
            info["roster_rule_covers"] = f"not covered ({exc.code})"
        try:
            members = event_members(e, er)
            feats = selection_features(db, e, {t for m in members.values() for t in m}, provider=provider, scales=scales)
            rows, why = playoff_rows(e, rules.bracket(8), feats, er)
            info["px1_rows_if_not_excluded"] = len(rows)
            info["px1_other_exclusions"] = dict(why)
        except Exception as exc:  # noqa: BLE001 -- report, never interpret
            info["px1_rows_if_not_excluded"] = f"not computable ({type(exc).__name__}: {exc})"
        if ex["reason"].startswith("backup"):
            seed_lines = []
            for a in e.alliances:
                if len(a.picks) == 4:
                    ms = sorted((m for m in e.matches if map_side(m.red, e.alliances) is a or map_side(m.blue, e.alliances) is a),
                                key=lambda m: (m.scheduled_time, m.match_key))
                    seed_lines.append({"seed": a.seed, "listed": list(a.picks),
                                       "on_field": [[m.match_key, [t for t in a.picks if t in m.red + m.blue]] for m in ms]})
            info["four_listed_alliances"] = seed_lines
        out[key] = info
        print(key, json.dumps({k: v for k, v in info.items() if k != "four_listed_alliances"}, default=str))
(A / "exclusions.json").write_text(json.dumps(out, indent=1, default=str), encoding="utf-8")
