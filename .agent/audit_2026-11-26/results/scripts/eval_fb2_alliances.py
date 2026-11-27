"""Does P11-FB2's projected alliance score predict how formed alliances actually score? (2026-11-26 audit)

For every 2024-2026 event with alliances and playoff results (read-only, stratai_test): at the selection moment, project
each formed alliance's no-foul score three ways, all from data strictly before the moment:
  fb2   - the sum of the three robots' P11A A3 component estimates (FB2's V, components mode)
  avg   - the sum over the three robots of (the robot's mean no-foul alliance score at the event) / 3
  epa   - the sum of the three robots' prior-event EPA (Statbotics D13 selection; absent -> alliance skipped for epa)
and compare with the alliance's ACTUAL mean no-foul score over its playoff matches where exactly those three robots
played. This is not a counterfactual: only alliances that were formed are scored. Metrics: MAE, bias, and the
within-event Spearman correlation between projected and actual alliance strength (what pick ranking relies on).
"""
import json
import os
import statistics
import sys
from collections import defaultdict
from urllib.parse import urlparse

sys.path.insert(0, "C:/Dev/StratAI")
os.chdir("C:/Dev/StratAI")
from data.config import Settings  # noqa: E402

u = urlparse(str(Settings().database_url))
os.environ["DATABASE_URL"] = u._replace(path="/stratai_test").geturl()

from scipy.stats import spearmanr  # noqa: E402

from data.alliances import read_event_alliances  # noqa: E402
from database.connection import Database, DatabaseConfig  # noqa: E402
from ml.features.score_components import score_components  # noqa: E402
from ml.playoffs.service import SelectionTimeUnavailable, event_selection_moment  # noqa: E402
from ml.ratings.provider import StatboticsPointInTimeEpa  # noqa: E402
from workspaces import draft_fb2 as fb2  # noqa: E402

db = Database(DatabaseConfig(os.environ["DATABASE_URL"]))
with db.cursor() as cur:
    cur.execute("SELECT current_database()")
    assert cur.fetchone()[0] == "stratai_test"
epa = StatboticsPointInTimeEpa(db)

PLAYOFF_SQL = """
SELECT m.match_key, m.season, mt.alliance_color, array_agg(mt.team_number ORDER BY mt.team_number),
       p.payload_json -> 'score_breakdown' -> mt.alliance_color
FROM matches m JOIN match_teams mt ON mt.match_key = m.match_key
LEFT JOIN raw_source_payloads p ON p.source = 'tba' AND p.source_object_type = 'match'
     AND p.source_object_id = m.match_key AND p.is_current
WHERE m.event_key = %s AND m.competition_level <> 'qualification' AND m.score_red IS NOT NULL
GROUP BY m.match_key, m.season, mt.alliance_color, p.payload_json
"""

out = {"alliances": [], "events": 0, "skipped": defaultdict(int)}
per_event = []
for season in (2024, 2025, 2026):
    alliances = read_event_alliances(db, season)
    for event_key, rows in sorted(alliances.items()):
        try:
            moment = event_selection_moment(db, event_key)
            est = fb2.estimate_event(fb2.load_rows(db, event_key, moment), switch_passed=True)
        except (SelectionTimeUnavailable, fb2.Fb2Unavailable) as exc:
            out["skipped"][type(exc).__name__] += 1
            continue
        if est.mode != fb2.MODE_COMPONENTS:
            out["skipped"]["not_components_mode"] += 1
            continue
        # Robot mean no-foul alliance score at the event before the moment (the "avg" baseline).
        team_rows = defaultdict(list)
        for r in fb2.load_rows(db, event_key, moment).rows:
            if r.components is not None:
                for t in r.teams:
                    team_rows[t].append(sum(r.components.values()))
        with db.cursor() as cur:
            cur.execute(PLAYOFF_SQL, (event_key,))
            played = defaultdict(list)
            for match_key, s, colour, teams, breakdown in cur.fetchall():
                if breakdown is None or len(teams) != 3:
                    continue
                try:
                    c = score_components(s, breakdown)
                except Exception:
                    continue
                played[tuple(teams)].append(c.auto + c.teleop + c.endgame)
        event_rows = []
        for a in rows:
            if a.seed is None or len(a.picks) < 3:
                continue
            trio = tuple(sorted(a.picks[:3]))
            if trio not in played or any(t not in est.values for t in trio):
                out["skipped"]["no_playoff_match_with_exactly_the_three_picks_or_no_estimate"] += 1
                continue
            actual = statistics.fmean(played[trio])
            pred_fb2 = sum(est.total(t) for t in trio)
            pred_avg = sum(statistics.fmean(team_rows[t]) / 3 for t in trio) if all(team_rows[t] for t in trio) else None
            epas = [epa.point_in_time_epa(t, event_key, moment) for t in trio]
            pred_epa = sum(e.epa_total for e in epas) if all(hasattr(e, "epa_total") and e.epa_total is not None
                                                             for e in epas) else None
            row = {"event": event_key, "season": season, "seed": a.seed, "teams": trio, "matches": len(played[trio]),
                   "actual": actual, "fb2": pred_fb2, "avg": pred_avg, "epa": pred_epa}
            out["alliances"].append(row)
            event_rows.append(row)
        out["events"] += 1
        if len(event_rows) >= 4:
            per_event.append(event_rows)


json.dump({"alliances": out["alliances"], "skipped": dict(out["skipped"])}, open(sys.argv[1] + ".raw.json", "w"),
          default=str)


def summarize(rows, key):
    rs = [r for r in rows if r[key] is not None]
    if not rs:
        return {"n": 0}
    err = [r[key] - r["actual"] for r in rs]
    return {"n": len(rs), "mae": round(statistics.fmean(abs(e) for e in err), 2), "bias": round(statistics.fmean(err), 2)}


result = {"events_scored": out["events"], "alliances": len(out["alliances"]), "skipped": dict(out["skipped"])}
for season in (2024, 2025, 2026, "all"):
    rs = [r for r in out["alliances"] if season == "all" or r["season"] == season]
    both = [r for r in rs if r["avg"] is not None]
    with_epa = [r for r in both if r["epa"] is not None]
    res = {"fb2_vs_avg": {k: summarize(both, k) for k in ("fb2", "avg")},
           "epa_subset": {k: summarize(with_epa, k) for k in ("fb2", "avg", "epa")}}
    for name, keys, need_epa in (("within_event_spearman_fb2_vs_avg", ("fb2", "avg"), False),
                                 ("within_event_spearman_epa_subset", ("fb2", "avg", "epa"), True)):
        rhos = {k: [] for k in keys}
        for ev in per_event:
            ev = [r for r in ev if (season == "all" or r["season"] == season) and r["avg"] is not None
                  and (not need_epa or r["epa"] is not None)]
            if len(ev) < 4:
                continue
            vals = {k: spearmanr([r[k] for r in ev], [r["actual"] for r in ev]).statistic for k in keys}
            if all(v == v for v in vals.values()):
                for k in keys:
                    rhos[k].append(vals[k])
        res[name] = {k: round(statistics.fmean(v), 4) if v else None for k, v in rhos.items()}
        res[name]["events"] = len(rhos[keys[0]])
        if rhos["fb2"]:
            res[name]["fb2_beats_avg"] = sum(a > b for a, b in zip(rhos["fb2"], rhos["avg"]))
            res[name]["avg_beats_fb2"] = sum(a < b for a, b in zip(rhos["fb2"], rhos["avg"]))
    result[str(season)] = res
json.dump({"result": result, "alliances": out["alliances"]}, open(sys.argv[1], "w"), indent=1, default=str)
print(json.dumps(result, indent=1))
