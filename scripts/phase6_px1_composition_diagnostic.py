"""PX-1 composition diagnostic: what a fourth listed team is, and which PX-1 observations it touches (read-only).

    python -m scripts.phase6_px1_composition_diagnostic     # DATABASE_URL = the isolated stratai_test copy

**Diagnostic only.**
- Nothing is fitted, evaluated, served or changed. PX-1, PX-2, PX-4, M6 (b) and M8 are not run.
- The frozen specification, the PX-1 code, the populations and every gate are untouched.
- **Output:** `.agent/phase6/diagnostics/p6_px1_composition_diagnostic.json` (with commit provenance).

**What it measures** (Kanav, 2026-10-05):
- For every seeded 2024–2026 event, the meaning of each fourth listed `picks` entry: a FIRST Championship round-3
  pick (every alliance at the event lists 4 teams), a standard-event backup consistent with T604/T608, or an
  anomaly.
- **PX-1 candidate observations.** A decided `semifinal` set 1–13 or `final` set 1 match at a seeded event, with
  both sides mapped as the frozen PX-1 spec §1 maps them. EPA completeness is assessed at the selection moment.
- **Each observation's composition under:**
  - the current implementation (every listed team);
  - (A) the captain and the first two listed picks;
  - (B) the selection-time members: the first three at standard events, all four at Championship divisions;
  - the three teams on the field (information only).

**What it does not apply.** The P6-M1 bracket-reproduction exclusion: no approved ruleset exists, so the counts
are the pre-M1 candidate population.

Hard budget: 30 minutes (the 45-minute rule).
"""

from __future__ import annotations

import json
import sys
import time
from collections import Counter, defaultdict
from pathlib import Path

from scripts.phase6_common import isolated_database, provenance

OUT = Path(".agent/phase6/diagnostics/p6_px1_composition_diagnostic.json")
SEASONS, TRAIN, HELD_OUT = (2024, 2025, 2026), (2024, 2025), 2026
BUDGET_SECONDS = 30 * 60
SNAPSHOT = Path("C:/Dev/StratAI-artifacts/statbotics/statbotics_snapshot_20261001T220423Z")
CHAIN = Path("C:/Dev/StratAI-artifacts/ratings/epa-chain/chain_e77d9444c57a7b50.json")


def classify_fourth_teams(event) -> tuple[str, dict[int, str]]:
    """(event kind, {seed: meaning of its 4th listed team}) from the event's own alliances and matches."""
    from ml.playoffs.px1 import map_side

    sizes = [len(a.picks) for a in event.alliances]
    if all(s == 4 for s in sizes):
        return "championship_division_pattern", {a.seed: "round3_pick" for a in event.alliances}
    ordered = sorted(event.matches, key=lambda m: (m.scheduled_time is None, m.scheduled_time, m.match_key))
    meanings = {}
    for alliance in event.alliances:
        if len(alliance.picks) != 4:
            continue
        fourth = alliance.picks[3]
        played = [m for m in ordered if map_side(m.red, event.alliances) is alliance
                  or map_side(m.blue, event.alliances) is alliance]
        on = [fourth in (m.red + m.blue) for m in played]
        if not any(on):
            meanings[alliance.seed] = "anomalous_backup_never_played"
        elif on[0]:
            meanings[alliance.seed] = "anomalous_backup_in_first_match"
        else:
            meanings[alliance.seed] = "backup_consistent"
    kind = "standard_with_anomaly" if any(v.startswith("anomalous") for v in meanings.values()) else (
        "standard_with_backup" if meanings else "standard_no_fourth")
    return kind, meanings


def main() -> int:
    from ml.features.scale import ScaleLookup
    from ml.playoffs.data import read_event_playoffs, selection_features
    from ml.playoffs.px1 import map_side
    from ml.ratings.d18_source import load_d18_provider

    started = time.time()
    database = isolated_database()
    provider, integrity = load_d18_provider(database, SNAPSHOT, CHAIN)
    scales = ScaleLookup(database)
    out: dict = {"what": "read-only PX-1 composition diagnostic; nothing fitted or evaluated", "seasons": {}}
    for season in SEASONS:
        events = read_event_playoffs(database, season)
        event_kinds: Counter[str] = Counter()
        fourth: Counter[str] = Counter()
        sizes: Counter[int] = Counter()
        championship_keys, anomalies = [], []
        rows: Counter[str] = Counter()
        by_meaning: Counter[str] = Counter()
        for event in events:
            if time.time() - started > BUDGET_SECONDS:
                out["stopped_at_budget"] = f"{season} {event.event_key}"
                break
            if not event.alliances or event.division_champion:
                rows["excluded_division_champion_or_no_alliances_events"] += 1
                continue
            sizes.update(len(a.picks) for a in event.alliances)
            kind, meanings = classify_fourth_teams(event)
            event_kinds[kind] += 1
            fourth.update(meanings.values())
            if kind == "championship_division_pattern":
                championship_keys.append(event.event_key)
            anomalies += [{"event": event.event_key, "seed": s, "kind": k}
                          for s, k in meanings.items() if k.startswith("anomalous")]
            if event.latest_qualification is None:
                rows["event_without_selection_moment"] += 1
                continue
            teams = {t for a in event.alliances for t in a.picks}
            features = selection_features(database, event, teams, provider=provider, scales=scales)
            seeds = {a.seed: a for a in event.alliances}
            for m in event.matches:
                if not ((m.competition_level == "semifinal" and 1 <= m.set_number <= 13)
                        or (m.competition_level == "final" and m.set_number == 1)):
                    rows["outside_sf1_13_f1"] += 1
                    continue
                red, blue = map_side(m.red, event.alliances), map_side(m.blue, event.alliances)
                if red is None or blue is None:
                    rows["side_unmappable"] += 1
                    continue
                if m.winner is None:
                    rows["tie_or_unplayed"] += 1
                    continue
                split = "train" if season in TRAIN else "held_out"
                rows[f"{split}:candidate"] += 1
                sides = (seeds[red.seed], seeds[blue.seed])
                championship = kind == "championship_division_pattern"
                listed = [a.picks for a in sides]
                a_three = [a.picks[:3] for a in sides]
                b_members = [a.picks if championship else a.picks[:3] for a in sides]

                def complete(compositions) -> bool:
                    return all(features[t].epa_total_present for comp in compositions for t in comp)

                eligible = {"current_listed": complete(listed), "A_captain_two_picks": complete(a_three),
                            "B_selection_members": complete(b_members)}
                for name, ok in eligible.items():
                    rows[f"{split}:eligible:{name}"] += ok
                differs_a = listed != a_three
                differs_b = listed != b_members
                if differs_a:
                    rows[f"{split}:composition_differs_current_vs_A"] += 1
                    if eligible["current_listed"] and eligible["A_captain_two_picks"]:
                        rows[f"{split}:composition_differs_current_vs_A:eligible_under_both"] += 1
                    if eligible["current_listed"] != eligible["A_captain_two_picks"]:
                        rows[f"{split}:eligibility_differs_current_vs_A"] += 1
                    for a in sides:
                        if len(a.picks) == 4:
                            meaning = meanings.get(a.seed, "round3_pick")
                            by_meaning[f"{split}:{meaning}"] += 1
                if differs_b:
                    rows[f"{split}:composition_differs_current_vs_B"] += 1
                if a_three != b_members:
                    rows[f"{split}:composition_differs_A_vs_B"] += 1
                on_field = [set(m.red), set(m.blue)]  # sides = (red alliance, blue alliance)
                if any(set(comp) != field for comp, field in zip(a_three, on_field)):
                    rows[f"{split}:on_field_trio_differs_from_A"] += 1
        out["seasons"][str(season)] = {
            "events_with_playoffs": len(events), "seeded_event_kinds": dict(event_kinds),
            "championship_division_pattern_events": championship_keys,
            "alliance_listed_sizes": {str(k): v for k, v in sorted(sizes.items())},
            "fourth_listed_team_meanings": dict(fourth), "anomalies": anomalies,
            "px1_candidate_rows": dict(sorted(rows.items())),
            "side_appearances_with_a_fourth_listed_team_by_meaning": dict(sorted(by_meaning.items())),
        }
    out.update({"epa_integrity": integrity, "minutes": round((time.time() - started) / 60, 1),
                "provenance": provenance()})
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(out, indent=1, sort_keys=True, default=str) + "\n", encoding="utf-8")
    print(json.dumps({s: v["px1_candidate_rows"] for s, v in out["seasons"].items()}, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
