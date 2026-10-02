"""P5-M0 audit of the curated robot-design dataset (analysis only; builds no Phase 5 component).

    python .agent/phase5/robot_design_audit/audit.py SNAPSHOT_DIR OUT_JSON

Reads data/reference/frc_robot_design_curated.csv (the source of truth for its rows) and
the canonical STRATAI database, read-only. Reports: structure; joinability; the outcome
data that exists for joinable rows and how selected that sample is (EPA percentile within
season); a *draft* two-level taxonomy assigned by transparent keyword rules (for review, not
a classifier of record); the extractable structured attributes; and which rows carry
unsourced numeric performance claims. It computes no archetype performance statistic.
"""

from __future__ import annotations

import csv
import gzip
import hashlib
import json
import re
import sys
from bisect import bisect_left
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from data.alliances import read_event_alliances  # noqa: E402
from data.config import Settings  # noqa: E402
from data.rankings import read_final_ranks_for_season  # noqa: E402
from database.connection import DatabaseConfig  # noqa: E402
from database.readonly import ReadOnlySessionDatabase  # noqa: E402

CSV = Path("data/reference/frc_robot_design_curated.csv")
STRATAI_SEASONS = (2024, 2025, 2026)

# Draft taxonomy: (function, family) assigned by the first matching rule over the micro-archetype
# name, then the specifications. Ordered; deliberately coarse; every assignment is listed for review.
FUNCTION_RULES = [
    ("endgame_climb", r"climb|stilt|sky-hook|winch"),
    ("drivetrain_defense", r"shunt|omnidirectional|wedge|plow|swerve module|drivetrain"),
    ("scoring_launcher", r"shooter|launcher|flywheel|turret|hood|catapult|slingshot|punch|accelerator"),
    ("scoring_placer", r"elevator|lift|mast|arm|boom|linkage|telescop|cascade|dropper|stack|wrist|probe|carrier|rail|slide"),
    ("acquisition", r"intake|sweeper|collector|grabber|harvester|burglar|jaw|claw|suction|vacuum|up-righter|forklift"),
    ("indexing_storage", r"indexer|hopper|auger|spindexer|channel|pocket|basket|funnel|shuttle|diverter|tower"),
]
FAMILY_RULES = [
    ("flywheel_turret", r"turret"),
    ("flywheel_adjustable_hood", r"hood|pitch-adjust|tilting|variable"),
    ("flywheel_fixed", r"flywheel|shooter|launcher|accelerator"),
    ("catapult_pneumatic", r"pneumatic.*catapult|catapult|punch"),
    ("elastic_launcher", r"slingshot|surgical tubing|spring"),
    ("elevator_cascade", r"cascad"),
    ("elevator_continuous", r"continuous"),
    ("elevator_other", r"elevator|lift|mast|carriage"),
    ("arm_four_bar", r"four-bar|parallel linkage"),
    ("arm_multi_joint", r"double-jointed|dual-joint|multi-axis|multi-joint"),
    ("arm_telescoping", r"telescop|boom|slide|rail"),
    ("arm_single_pivot", r"pivot|single-jointed|arm"),
    ("effector_suction", r"suction|vacuum"),
    ("effector_pneumatic_jaw", r"jaw|clamp|beak"),
    ("effector_roller", r"roller|sweeper|wheel|claw|grabber"),
    ("storage_passive", r"hopper|funnel|gravity|passive|basket|dropper|pocket|diverter|channel|auger|indexer|spindexer|shuttle"),
    ("drivetrain", r"shunt|omnidirectional|swerve|wedge|plow|tracks"),
]
ATTRIBUTE_RULES = {
    "actuation_pneumatic": r"pneumatic|piston|cylinder|venturi|vacuum",
    "actuation_elastic_or_spring": r"spring|elastic|surgical tubing|gas-spring|gas strut",
    "actuation_passive_gravity": r"passive|gravity|un-motorized",
    "has_turret": r"turret|slewing",
    "has_vision_or_localization": r"vision|camera|localization|odometry|neural",
    "has_sensors": r"sensor|break-beam|tof|encoder",
    "material_carbon_fiber": r"carbon",
    "material_steel": r"steel",
    "material_polycarbonate": r"polycarbonate",
    "drivetrain_swerve": r"swerve",
    "drivetrain_tank_or_tracks": r"tank|tracks",
}
NUMERIC_CLAIM = re.compile(r"\d+(\.\d+)?\s*(%|ms\b|milliseconds|seconds|sec\b|lbs|lb\b|ft/s|balls/sec|°|-degree|degree|inch|inches|\"|-foot|foot|feet|x\b)",
                           re.IGNORECASE)


def first_match(rules, text):
    return next((label for label, pattern in rules if re.search(pattern, text, re.IGNORECASE)), "unassigned")


def main(snapshot: Path, out: Path) -> None:
    raw = CSV.read_bytes()
    rows = list(csv.DictReader(CSV.open(encoding="utf-8", newline="")))
    database = ReadOnlySessionDatabase(DatabaseConfig(Settings().database_url))
    with database.cursor() as cursor:
        cursor.execute("SELECT team_number FROM teams")
        known_teams = {t for (t,) in cursor.fetchall()}
        cursor.execute("""SELECT mt.team_number, m.season, m.event_key FROM match_teams mt JOIN matches m
                          ON m.match_key = mt.match_key WHERE m.season = ANY(%s) AND m.score_red IS NOT NULL
                          GROUP BY 1, 2, 3""", (list(STRATAI_SEASONS),))
        events_by_team = defaultdict(set)
        for team, season, event in cursor.fetchall():
            events_by_team[(team, season)].add(event)
    stats = json.loads(gzip.decompress((snapshot / "team_event_stats.json.gz").read_bytes()))
    season_max: dict[tuple[int, int], float] = {}
    for team, event, season, epa, *_ in stats:
        if epa is not None:
            season_max[(team, season)] = max(season_max.get((team, season), epa), epa)
    by_season = defaultdict(list)
    for (team, season), value in season_max.items():
        by_season[season].append(value)
    for season in by_season:
        by_season[season].sort()
    ranks = {s: read_final_ranks_for_season(database, s) for s in STRATAI_SEASONS}
    alliances = {s: read_event_alliances(database, s) for s in STRATAI_SEASONS}

    observations = []
    for index, row in enumerate(rows, start=1):
        year, team = int(row["Year"]), int(row["Team"])
        name, spec, advantage = row["Robot Micro-Archetype"], row["Technical Specifications"], row["Key Characteristic & Competitive Advantage"]
        text = f"{name} {spec}"
        record = {
            "row": index, "year": year, "team": team, "game": row["Game Name"], "micro_archetype": name,
            "draft_function": first_match(FUNCTION_RULES, text), "draft_family": first_match(FAMILY_RULES, text),
            "attributes": sorted(k for k, p in ATTRIBUTE_RULES.items() if re.search(p, f"{spec} {advantage}", re.IGNORECASE)),
            "unsourced_numeric_claims": [m.group(0) for m in NUMERIC_CLAIM.finditer(f"{spec} {advantage}")],
            "in_stratai_seasons": year in STRATAI_SEASONS,
        }
        if year in STRATAI_SEASONS:
            events = sorted(events_by_team.get((team, year), ()))
            best = season_max.get((team, year))
            pool = by_season[year]
            captain_events = sum(1 for e in events for a in alliances[year].get(e, []) if a.captain == team)
            pick_events = sum(1 for e in events for a in alliances[year].get(e, []) if team in a.picks and a.captain != team)
            record.update({
                "joined": team in known_teams and bool(events), "events": len(events),
                "season_max_epa": best,
                "season_max_epa_percentile": None if best is None else round(100 * bisect_left(pool, best) / len(pool), 1),
                "best_qual_rank": min((ranks[year].get(e, {}).get(team) for e in events if ranks[year].get(e, {}).get(team)), default=None),
                "captain_events": captain_events, "picked_events": pick_events,
            })
        observations.append(record)

    recent = [o for o in observations if o["in_stratai_seasons"]]
    percentiles = sorted(o["season_max_epa_percentile"] for o in recent if o["season_max_epa_percentile"] is not None)
    result = {
        "csv": {"path": str(CSV), "sha256": hashlib.sha256(raw).hexdigest(), "rows": len(rows),
                "columns": list(rows[0].keys()), "stated_rows_in_request": 78},
        "structure": {
            "rows_by_year": dict(sorted(Counter(o["year"] for o in observations).items())),
            "distinct_teams": len({o["team"] for o in observations}),
            "team_repeats": {t: n for t, n in Counter(o["team"] for o in observations).most_common() if n > 1},
            "distinct_micro_archetypes": len({o["micro_archetype"] for o in observations}),
            "seasons_absent": [y for y in range(1992, 2027) if y not in {o["year"] for o in observations}],
        },
        "joinability": {
            "rows_in_stratai_seasons": len(recent), "rows_joined": sum(o.get("joined", False) for o in recent),
            "rows_outside_stratai_seasons": len(observations) - len(recent),
        },
        "selection": {
            "season_max_epa_percentile": {"min": percentiles[0], "median": percentiles[len(percentiles) // 2],
                                          "max": percentiles[-1], "n": len(percentiles)},
            "rows_with_best_qual_rank_1": sum(1 for o in recent if o.get("best_qual_rank") == 1),
            "rows_captain_at_least_once": sum(1 for o in recent if o.get("captain_events")),
        },
        "draft_taxonomy": {
            "function_counts": dict(Counter(o["draft_function"] for o in observations).most_common()),
            "family_counts": dict(Counter(o["draft_family"] for o in observations).most_common()),
            "largest_function_x_game_cell": max(Counter((o["draft_function"], o["game"]) for o in observations).values()),
        },
        "attributes": {"coverage": dict(Counter(a for o in observations for a in o["attributes"]).most_common()),
                       "rows_with_no_attribute": sum(1 for o in observations if not o["attributes"])},
        "claims": {"rows_with_unsourced_numeric_claims": sum(1 for o in observations if o["unsourced_numeric_claims"])},
        "observations": observations,
    }
    out.write_text(json.dumps(result, indent=1, default=str) + "\n", encoding="utf-8")
    print(json.dumps({k: v for k, v in result.items() if k != "observations"}, indent=1, default=str))


if __name__ == "__main__":
    main(Path(sys.argv[1]), Path(sys.argv[2]))
