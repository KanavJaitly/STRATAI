"""P6-M1 research evidence from existing TBA data (read-only; research input, not a ruleset).

    DATABASE_URL=<isolated stratai_test copy> python -m scripts.phase6_m1_tba_evidence --out <file.json>

Kanav's P6-M1 workflow of 2026-10-05: Claude prepares a cited research draft and a person verifies it. This script
supplies the TBA half of that draft. It reads the already-ingested TBA data and modifies nothing.

**Two questions:**
- **D2: the TBA mapping.** Does TBA's (`semifinal`, set n) correspond to match n of the manual's Table 10-2?
  - The manual's bracket is written below as `MANUAL_TABLE_10_2`, transcribed from Table 10-2 (identical in 2024,
    2025 and 2026).
  - Set n's expected red and blue seeds are derived from the actual winners of earlier sets, then compared with the
    seeds TBA's teams actually map to.
  - The table is evidence for the research draft only. It is never read by a ruleset or a model.
- **D5: the fourth listed team.** What is the fourth team in TBA's `picks` list?
  - Whole-event pattern: does every alliance at the event list 4 teams, or only some?
  - Event type.
  - When the fourth team first plays: never, in its alliance's first playoff match, or later.
  - Whether the fourth team was the highest-ranked available team after selection (backup rule 10.6.3).

**Runtime:** seconds. It carries a 10-minute budget (the 45-minute rule).
"""

from __future__ import annotations

import argparse
import json
import time
from collections import Counter, defaultdict
from pathlib import Path

from data.alliances import read_event_alliances
from data.rankings import read_final_ranks_for_season
from ml.playoffs.data import read_event_playoffs
from ml.playoffs.px1 import map_side
from scripts.phase6_common import isolated_database

BUDGET_SECONDS = 600
SEASONS = (2024, 2025, 2026)

# Manual Table 10-2 (2024 p.123, 2025 p.127, 2026 p.127): match -> (red source, blue source).
# ("seed", n) | ("W", match) | ("L", match).
MANUAL_TABLE_10_2 = {
    1: (("seed", 1), ("seed", 8)), 2: (("seed", 4), ("seed", 5)), 3: (("seed", 2), ("seed", 7)),
    4: (("seed", 3), ("seed", 6)), 5: (("L", 1), ("L", 2)), 6: (("L", 3), ("L", 4)), 7: (("W", 1), ("W", 2)),
    8: (("W", 3), ("W", 4)), 9: (("L", 7), ("W", 6)), 10: (("L", 8), ("W", 5)), 11: (("W", 7), ("W", 8)),
    12: (("W", 10), ("W", 9)), 13: (("L", 11), ("W", 12)),
}
FINALS = (("W", 11), ("W", 13))


def _event_types(database) -> dict[str, str]:
    with database.cursor() as cursor:
        cursor.execute("SELECT event_key, event_type FROM events")
        return {k: t for k, t in cursor.fetchall()}


def _set_result(matches, alliances):
    """{(level, set): (red_seed, blue_seed, winner_seed, loser_seed, match_numbers)} from the decided matches."""
    out = {}
    by_set = defaultdict(list)
    for m in matches:
        by_set[(m.competition_level, m.set_number)].append(m)
    for key, ms in by_set.items():
        ms.sort(key=lambda m: (m.match_number, m.match_key))
        sides = set()
        winner = None
        wins = Counter()
        for m in ms:
            red, blue = map_side(m.red, alliances), map_side(m.blue, alliances)
            if red is None or blue is None:
                sides.add(None)
                continue
            sides.add((red.seed, blue.seed))
            if m.winner == "red":
                winner = red.seed
                wins[red.seed] += 1
            elif m.winner == "blue":
                winner = blue.seed
                wins[blue.seed] += 1
        if len(sides) != 1 or None in sides:
            out[key] = None
            continue
        red_seed, blue_seed = next(iter(sides))
        if key[0] == "final":
            winner = max(wins, key=wins.get) if wins else None
        loser = None if winner is None else (blue_seed if winner == red_seed else red_seed)
        out[key] = (red_seed, blue_seed, winner, loser, [m.match_number for m in ms])
    return out


def _resolve(source, results):
    kind, value = source
    if kind == "seed":
        return value
    result = results.get(("semifinal", value))
    if result is None:
        return None
    return result[2] if kind == "W" else result[3]


def tba_mapping(events) -> dict:
    per_set = defaultdict(Counter)
    mismatch_examples = []
    events_checked = 0
    for event in events:
        if len(event.alliances) != 8 or event.division_champion:
            continue
        events_checked += 1
        results = _set_result(event.matches, event.alliances)
        for n, (red_src, blue_src) in list(MANUAL_TABLE_10_2.items()) + [("final", FINALS)]:
            key = ("final", 1) if n == "final" else ("semifinal", n)
            actual = results.get(key, "absent")
            if actual == "absent":
                per_set[str(n)]["absent"] += 1
                continue
            if actual is None:
                per_set[str(n)]["unmappable_side"] += 1
                continue
            expected = (_resolve(red_src, results), _resolve(blue_src, results))
            if None in expected:
                per_set[str(n)]["expected_unresolvable"] += 1
                continue
            if expected == actual[:2]:
                per_set[str(n)]["match"] += 1
            elif expected == actual[1::-1]:
                per_set[str(n)]["colors_swapped"] += 1
            else:
                per_set[str(n)]["mismatch"] += 1
                if len(mismatch_examples) < 10:
                    mismatch_examples.append({"event": event.event_key, "set": n, "expected_red_blue": expected,
                                              "actual_red_blue": actual[:2]})
            per_set[str(n)]["max_match_number_" + str(max(actual[4]))] += 1
    other = Counter()
    for event in events:
        for m in event.matches:
            if m.competition_level not in ("semifinal", "final") or (m.competition_level == "final" and
                                                                      m.set_number != 1) or (
                    m.competition_level == "semifinal" and not 1 <= m.set_number <= 13):
                other[(m.competition_level, m.set_number)] += 1
    return {"seeded_8_alliance_events": events_checked, "per_set": {k: dict(v) for k, v in per_set.items()},
            "matches_outside_sf1_13_f1": {f"{k[0]}:{k[1]}": v for k, v in other.items()},
            "mismatch_examples": mismatch_examples}


def fourth_teams(season: int, events, types: dict[str, str], ranks: dict[str, dict[int, int]]) -> dict:
    pattern = Counter()
    type_by_pattern = defaultdict(Counter)
    first_play = Counter()
    highest_available = Counter()
    examples = defaultdict(list)
    for event in events:
        if event.division_champion or not event.alliances:
            continue
        sizes = [len(a.picks) for a in event.alliances]
        n4 = sum(s == 4 for s in sizes)
        if n4 == 0:
            label = "no_alliance_lists_4"
        elif n4 == len(sizes):
            label = "every_alliance_lists_4"
        else:
            label = "some_alliances_list_4"
        if any(s > 4 for s in sizes):
            label += "+some_list_more_than_4"
        pattern[label] += 1
        type_by_pattern[label][str(types.get(event.event_key))] += 1
        if len(examples[label]) < 12:
            examples[label].append(event.event_key)
        if label != "some_alliances_list_4":
            continue
        selected = {t for a in event.alliances for t in a.picks[:3]}
        declined = {t for a in event.alliances for t in a.declines}
        event_ranks = ranks.get(event.event_key, {})
        ordered_matches = sorted(event.matches, key=lambda m: (m.scheduled_time is None, m.scheduled_time,
                                                                 m.match_key))
        used_backups: set[int] = set()
        for a in sorted((a for a in event.alliances if len(a.picks) == 4),
                        key=lambda a: next((i for i, m in enumerate(ordered_matches)
                                            if a.picks[3] in m.red + m.blue), 10**6)):
            fourth = a.picks[3]
            played = [i for i, m in enumerate(ordered_matches) if len(set(a.picks[:3]) & set(m.red + m.blue)) >= 2]
            with_fourth = [i for i in played if fourth in ordered_matches[i].red + ordered_matches[i].blue]
            if not with_fourth:
                first_play["never_plays"] += 1
            elif with_fourth[0] == played[0]:
                first_play["plays_in_alliances_first_playoff_match"] += 1
            else:
                first_play["first_plays_after_alliances_first_match"] += 1
            if event_ranks and fourth in event_ranks:
                pool = sorted((r, t) for t, r in event_ranks.items()
                              if t not in selected and t not in declined and t not in used_backups)
                highest_available["is_highest_ranked_unselected_team" if pool and pool[0][1] == fourth
                                  else "is_not"] += 1
            else:
                highest_available["no_rank_data"] += 1
            used_backups.add(fourth)
    return {"events_by_pattern": dict(pattern),
            "event_type_by_pattern": {k: dict(v) for k, v in type_by_pattern.items()},
            "examples": dict(examples),
            "partial_events_fourth_team_first_play": dict(first_play),
            "partial_events_fourth_team_vs_highest_ranked_unselected": dict(highest_available),
            "note": ("highest-ranked check ignores BACKUP POOL declines/absences (not in TBA), so 'is_not' is "
                     "an upper bound on non-conformance")}


def selection_evidence(events, ranks: dict[str, dict[int, int]]) -> dict:
    """Captains, leads joining higher alliances, and declines, against the qualification ranking.

    Evidence for the selection booleans. TBA records no timing of declines, so this is suggestive, not decisive."""
    counts = Counter()
    declined_captains = []
    for event in events:
        if event.division_champion or not event.alliances:
            continue
        event_ranks = ranks.get(event.event_key)
        if not event_ranks:
            counts["events_without_ranks"] += 1
            continue
        counts["events"] += 1
        n = len(event.alliances)
        declined = {t for a in event.alliances for t in a.declines}
        counts["declines_recorded"] += len(declined)
        taken: set[int] = set()
        for alliance in sorted(event.alliances, key=lambda a: a.seed):
            eligible = [t for t in event_ranks if t not in taken]
            best = min(eligible, key=lambda t: event_ranks[t]) if eligible else None
            counts["captain_is_best_ranked_not_yet_on_an_alliance" if alliance.captain == best
                   else "captain_is_not"] += 1
            taken.update(alliance.picks[:2])
            if alliance.captain in declined:
                declined_captains.append({"event": event.event_key, "seed": alliance.seed,
                                          "team": alliance.captain, "rank": event_ranks.get(alliance.captain)})
            for pick in alliance.picks[1:3]:
                if event_ranks.get(pick, 10**6) <= n:
                    counts["round_1_or_2_pick_ranked_in_top_n_alliances"] += 1
    return {"counts": dict(counts), "declined_teams_who_captain_an_alliance": len(declined_captains),
            "declined_captain_ranks": dict(Counter("top_8" if (d["rank"] or 99) <= 8 else "below_8"
                                                   for d in declined_captains)),
            "declined_captain_examples": declined_captains[:10],
            "note": ("'captain_is_not' uses the final qualification ranking and the captain plus round-1 pick of "
                     "earlier alliances; declines (whose timing TBA does not record) are not excluded")}


def placeholder_alliances(events, ranks: dict[str, dict[int, int]]) -> dict:
    """Small events (10.6.6): alliances whose teams never appear in the qualification ranking.

    TBA records a small event's bye format as 8 alliances. The non-existent alliances are filled with placeholder team
    numbers, and their "bye" matches carry results."""
    out = []
    for event in events:
        if event.division_champion or not event.alliances:
            continue
        event_ranks = ranks.get(event.event_key, {})
        phantom = [a for a in event.alliances if a.picks and not any(t in event_ranks for t in a.picks)]
        unranked = sorted({t for a in event.alliances for t in a.picks if t not in event_ranks})
        if phantom or unranked:
            out.append({"event": event.event_key, "ranked_teams": len(event_ranks),
                        "qualification_team_count": event.team_count,
                        "alliances": len(event.alliances),
                        "placeholder_alliance_seeds": [a.seed for a in phantom],
                        "real_alliances": len(event.alliances) - len(phantom),
                        "manual_10_6_6_alliances": min(8, (len(event_ranks) - 1) // 3) if event_ranks else None,
                        "unranked_alliance_teams": unranked})
    return {"events": out, "count": len(out)}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args(argv)
    start = time.monotonic()
    database = isolated_database()
    types = _event_types(database)
    out = {"generated_by": "scripts.phase6_m1_tba_evidence", "read_only": True, "seasons": {}}
    for season in SEASONS:
        if time.monotonic() - start > BUDGET_SECONDS:
            out["stopped_at_budget"] = season
            break
        events = read_event_playoffs(database, season)
        ranks = read_final_ranks_for_season(database, season)
        alliance_events = read_event_alliances(database, season)
        out["seasons"][str(season)] = {
            "events_with_playoff_matches": len(events),
            "events_with_alliances": len(alliance_events),
            "alliance_counts": dict(Counter(len(v) for v in alliance_events.values())),
            "tba_mapping": tba_mapping(events),
            "fourth_team": fourth_teams(season, events, types, ranks),
            "selection": selection_evidence(events, ranks),
            "small_event_placeholders": placeholder_alliances(events, ranks),
        }
    out["elapsed_seconds"] = round(time.monotonic() - start, 1)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(out, indent=1, default=str), encoding="utf-8")
    print(json.dumps(out, indent=1, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
