"""P11A E2 research: build one season's evaluation population from the raw Statbotics pages (PROTOCOL.json).

    python -I research/p11_e2/build_population.py --season 2024 --raw research/p11_e2/cache/raw \
        --out research/p11_e2/cache/population

Writes <out>/population_<season>.json:
- the included events, with their qualification alliance rows (the information set) and playoff alliance targets;
- an exclusion log, with every excluded event, match or alliance and its reason.

Only recorded results and the event metadata named in PROTOCOL.json are read. No Statbotics model output is read.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path

INCLUDED_TYPES = {"regional", "district", "district_cmp", "champs_div"}
COMPONENTS = ("auto", "teleop", "endgame", "no_foul")
MIN_QUAL_MATCHES = 12


def load_pages(folder: Path, kind: str) -> list[dict]:
    manifest = json.loads((folder / "manifest.json").read_text())
    rows: list[dict] = []
    for page in manifest["pages"]:
        if page["kind"] == kind:
            rows.extend(json.loads((folder / page["file"]).read_bytes()))
    return rows


def alliance_row(match: dict, color: str) -> tuple[dict | None, str | None]:
    result = match.get("result") or {}
    teams = (match.get("alliances") or {}).get(color, {}).get("team_keys") or []
    dq = (match.get("alliances") or {}).get(color, {}).get("dq_team_keys") or []
    surrogate = (match.get("alliances") or {}).get(color, {}).get("surrogate_team_keys") or []
    values = {c: result.get(f"{color}_{c}_points") for c in ("auto", "teleop", "endgame")}
    values["no_foul"] = result.get(f"{color}_no_foul")
    score = result.get(f"{color}_score")
    row = {"match": match["key"], "color": color, "teams": [int(t) for t in teams], "time": match.get("time"),
           "comp_level": match.get("comp_level"), "elim": bool(match.get("elim")), "score": score,
           "dq": [int(t) for t in dq], "surrogate": [int(t) for t in surrogate], **values}
    if score is None or any(values[c] is None for c in COMPONENTS):
        return row, "missing_result"
    if len(teams) != 3:
        return row, "not_three_robots"
    if abs(values["auto"] + values["teleop"] + values["endgame"] - values["no_foul"]) > 1e-6 or values["no_foul"] > score + 1e-6:
        return row, "parity_failure"
    row["fouls"] = score - values["no_foul"]
    if dq:
        return row, "dq_alliance"
    return row, None


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--season", type=int, required=True, choices=(2024, 2025, 2026))
    parser.add_argument("--raw", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args(argv)
    folder = args.raw / str(args.season)
    events = {e["key"]: e for e in load_pages(folder, "events")}
    matches = load_pages(folder, "matches")
    by_event: dict[str, list[dict]] = {}
    for m in matches:
        by_event.setdefault(m["event"], []).append(m)

    exclusions: list[dict] = []
    reasons: Counter = Counter()
    included = []
    for key, event in sorted(events.items()):
        if event.get("type") not in INCLUDED_TYPES:
            reasons[f"event:{event.get('type')}"] += 1
            exclusions.append({"level": "event", "key": key, "reason": f"event_type_{event.get('type')}"})
            continue
        quals, elims, dq_anomalies = [], [], []
        for m in sorted(by_event.get(key, []), key=lambda m: (m.get("time") or 0, m["key"])):
            for color in ("red", "blue"):
                row, why = alliance_row(m, color)
                if why is None and row["time"] is None:
                    why = "no_time"
                target = elims if m.get("elim") else quals
                if why is None:
                    target.append(row)
                else:
                    reasons[f"{'elim' if m.get('elim') else 'qual'}_alliance:{why}"] += 1
                    exclusions.append({"level": "alliance", "key": f"{m['key']}:{color}", "reason": why})
                    if why == "dq_alliance" and m.get("elim"):
                        dq_anomalies.append(row)
        qual_matches = {r["match"] for r in quals}
        if len(qual_matches) < MIN_QUAL_MATCHES or not elims:
            why = "event_too_small" if len(qual_matches) < MIN_QUAL_MATCHES else "no_playoff_rows"
            reasons[f"event:{why}"] += 1
            exclusions.append({"level": "event", "key": key, "reason": why})
            continue
        selection_moment = max(r["time"] for r in quals)
        qual_teams = {t for r in quals for t in r["teams"]}
        kept = []
        for row in elims:
            if row["time"] <= selection_moment:
                why = "playoff_before_selection"
            elif set(row["teams"]) - qual_teams:
                why = "robot_without_quals"
            else:
                kept.append(row)
                continue
            reasons[f"elim_alliance:{why}"] += 1
            exclusions.append({"level": "alliance", "key": f"{row['match']}:{row['color']}", "reason": why})
        if not kept:
            reasons["event:no_valid_playoff_rows"] += 1
            exclusions.append({"level": "event", "key": key, "reason": "no_valid_playoff_rows"})
            continue
        included.append({"key": key, "type": event["type"], "week": event.get("week"),
                         "start_date": event.get("start_date"), "end_date": event.get("end_date"),
                         "selection_moment": selection_moment, "teams": sorted(qual_teams),
                         "quals": quals, "elims": kept, "dq_elim_rows": dq_anomalies})
    args.out.mkdir(parents=True, exist_ok=True)
    summary = {"season": args.season, "events_total": len(events), "events_included": len(included),
               "qual_rows": sum(len(e["quals"]) for e in included),
               "elim_rows": sum(len(e["elims"]) for e in included),
               "elim_matches": len({r["match"] for e in included for r in e["elims"]}),
               "exclusion_counts": dict(sorted(reasons.items()))}
    (args.out / f"population_{args.season}.json").write_text(json.dumps(
        {"summary": summary, "events": included, "exclusions": exclusions}))
    print(json.dumps(summary))
    return 0


if __name__ == "__main__":
    sys.exit(main())
