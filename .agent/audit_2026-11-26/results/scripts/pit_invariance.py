"""Point-in-time invariance audit (2026-11-26).

    python pit_invariance.py capture <out.json> [--epa d18|statbotics]
    python pit_invariance.py perturb
    python pit_invariance.py compare <before.json> <after.json>

Runs ONLY against stratai_test_pit (a disposable clone). For a fixed sample of (event, cutoff) points it captures every
served output that takes an as-of moment (or predicts "as of the match's scheduled time"), then `perturb` corrupts every
fact dated at or after each point's cutoff (match results, score breakdowns, rankings, alliances, team_metrics, future
scouting observations, a new future match), and a fresh process captures again. Any difference is a leak: the output
read information from after its cutoff.
"""

from __future__ import annotations

import json
import os
import random
import sys
from datetime import datetime, timedelta, timezone
from urllib.parse import urlparse

sys.path.insert(0, "C:/Dev/StratAI")
os.chdir("C:/Dev/StratAI")

TARGET_DB = "stratai_test_pit"
VOLATILE = {"computed_at", "request_id", "timing_ms", "generated_at", "served_at", "elapsed_ms", "latency_ms",
            "built_at", "log_stamp", "as_of_note"}


def _url() -> str:
    from data.config import Settings
    u = urlparse(str(Settings().database_url))
    return u._replace(path=f"/{TARGET_DB}").geturl()


def _env(epa: str) -> None:
    from scripts.local_test_env import PINS
    os.environ.update({k: v for k, v in PINS.items() if k != "DATABASE_URL"})
    os.environ["DATABASE_URL"] = _url()
    os.environ["EPA_SOURCE"] = "d18_statbotics_primary" if epa == "d18" else "statbotics"
    os.environ["ACCESS_POLICY"] = "open"
    os.environ["ML_STRATEGY_MODEL_VERSION_TAG"] = "p6m10-v1"
    os.environ["ML_STRATEGY_MODEL_SHA256"] = "aded2c829a1f2edbd1ddb50e099b0e88df8a5cc4033efe0fa7270dae235fbf5f"


def _check_db(cur) -> None:
    cur.execute("SELECT current_database()")
    name = cur.fetchone()[0]
    if name != TARGET_DB:
        raise SystemExit(f"STOP: connected to {name}, not {TARGET_DB}")


# --- the sample ---------------------------------------------------------------------------------------------------

def sample_points(cur, seed: int = 20261126) -> list[dict]:
    """Two events per season (2024-2026), not week 1 (the documented week-1 statistics caveat), each with two cutoffs:
    the scheduled time of the event's middle qualification match, and the selection moment."""
    rng = random.Random(seed)
    points = []
    for season in (2024, 2025, 2026):
        cur.execute("""
            SELECT m.event_key, COUNT(*) FROM matches m JOIN events e ON e.event_key = m.event_key
            WHERE m.season = %s AND m.competition_level = 'qualification' AND m.score_red IS NOT NULL
              AND e.start_date > (SELECT MIN(start_date) + 7 FROM events WHERE season = %s)
            GROUP BY m.event_key HAVING COUNT(*) BETWEEN 50 AND 90 ORDER BY m.event_key""", (season, season))
        events = [r[0] for r in cur.fetchall()]
        for event in sorted(rng.sample(events, 2)):
            cur.execute("""SELECT match_key, scheduled_time FROM matches WHERE event_key = %s
                           AND competition_level = 'qualification' AND scheduled_time IS NOT NULL
                           ORDER BY scheduled_time, match_key""", (event,))
            quals = cur.fetchall()
            mid_key, mid_time = quals[len(quals) // 2]
            points.append({"event_key": event, "season": season, "target_match": mid_key,
                           "cutoff": mid_time.isoformat(),
                           "selection_moment": (quals[-1][1] + timedelta(minutes=1)).isoformat()})
    return points


# --- capture -------------------------------------------------------------------------------------------------------

def _clean(value):
    if isinstance(value, dict):
        return {k: _clean(v) for k, v in value.items() if k not in VOLATILE}
    if isinstance(value, list):
        return [_clean(v) for v in value]
    return value


def capture(out: str, epa: str) -> None:
    _env(epa)
    import psycopg
    from fastapi.testclient import TestClient
    from api import create_app
    from data.config import Settings

    with psycopg.connect(_url()) as conn, conn.cursor() as cur:
        _check_db(cur)
        points = sample_points(cur)
        rosters = {}
        for p in points:
            cur.execute("""SELECT DISTINCT mt.team_number FROM match_teams mt JOIN matches m ON m.match_key = mt.match_key
                           WHERE m.event_key = %s AND m.competition_level = 'qualification' ORDER BY 1""",
                        (p["event_key"],))
            rosters[p["event_key"]] = [r[0] for r in cur.fetchall()]
            cur.execute("SELECT alliance_color, team_number FROM match_teams WHERE match_key = %s ORDER BY 1, 2",
                        (p["target_match"],))
            rows = cur.fetchall()
            p["red"] = [t for c, t in rows if c == "red"]
            p["blue"] = [t for c, t in rows if c == "blue"]
    client = TestClient(create_app(Settings()))
    results: dict = {"epa": epa, "points": points, "outputs": {}}

    def get(name, path, **params):
        r = client.get(path, params=params)
        results["outputs"][name] = {"status": r.status_code, "body": _clean(r.json())}

    def post(name, path, body, **params):
        r = client.post(path, json=body, params=params)
        results["outputs"][name] = {"status": r.status_code, "body": _clean(r.json())}

    for p in points:
        e, m = p["event_key"], p["target_match"]
        for label, cutoff in (("mid", p["cutoff"]), ("sel", p["selection_moment"])):
            k = f"{e}:{label}"
            get(f"{k}:matches", f"/events/{e}/matches", as_of=cutoff)
            get(f"{k}:analysis", f"/events/{e}/analysis", as_of=cutoff)
            get(f"{k}:forecast", f"/events/{e}/qualification-forecast", as_of=cutoff)
            get(f"{k}:candidates", f"/events/{e}/alliance-selection/candidates", as_of=cutoff)
            for team in rosters[e][:12]:
                get(f"{k}:strength:{team}", f"/teams/{team}/events/{e}/strength", as_of=cutoff)
            post(f"{k}:winprob_adhoc", "/predictions/win-probability",
                 {"event_key": e, "red_team_numbers": p["red"], "blue_team_numbers": p["blue"],
                  "match_context": "qualification"}, as_of=cutoff)
            post(f"{k}:synergy", "/predictions/alliance-synergy", {"event_key": e, "team_numbers": p["red"]},
                 as_of=cutoff)
            post(f"{k}:hyp_recommend", "/strategy/hypothetical/recommend",
                 {"event_key": e, "red_team_numbers": p["red"], "blue_team_numbers": p["blue"],
                  "match_context": "qualification", "side": "red"}, as_of=cutoff)
        # "as of the match's scheduled time" routes, for the target (middle) match: its own result is perturbed too.
        get(f"{e}:match_winprob", f"/predictions/matches/{m}/win-probability")
        get(f"{e}:prematch", f"/matches/{m}/pre-match-report", as_of=p["cutoff"])
        post(f"{e}:match_recommend", f"/strategy/matches/{m}/recommend", {"side": "red"})
        # The live draft's fallback inputs at the selection moment (P11-FB2 estimates, P5-M4 ordering).
        results["outputs"][f"{e}:fb2"] = _fb2(e, p)
    with open(out, "w", encoding="utf-8") as f:
        json.dump(results, f, indent=0, sort_keys=True, default=str)
    statuses: dict = {}
    for v in results["outputs"].values():
        if isinstance(v, dict) and "status" in v:
            statuses[v["status"]] = statuses.get(v["status"], 0) + 1
    print("captured", len(results["outputs"]), "outputs; statuses", statuses)


def _fb2(event_key: str, p: dict) -> dict:
    from api.ml_loading import load_epa_source, load_pinned_ranking_model
    from data.config import Settings
    from database.connection import Database, DatabaseConfig
    from workspaces import draft_recommendations as rec

    settings = Settings()
    db = Database(DatabaseConfig(settings.database_url))
    epa, ranking = load_epa_source(settings, db), load_pinned_ranking_model(settings)
    now = datetime.now(timezone.utc)
    try:
        ordering = rec.event_ordering(db, event_key, now, epa_source=epa, ranking=ranking)
        ctx = rec.fb2_context(db, event_key, ordering)
        est = ctx.estimates
        return {"ordering": list(ordering.teams), "as_of": ordering.as_of.isoformat(),
                "mode": None if est is None else est.mode,
                "values": None if est is None else {str(t): {c: round(v, 9) for c, v in comps.items()}
                                                    for t, comps in sorted(est.values.items())},
                "unavailable": ctx.unavailable}
    except Exception as exc:  # a refusal is an output too
        return {"error": f"{type(exc).__name__}: {exc}"}


# --- perturbation --------------------------------------------------------------------------------------------------

def perturb(points_file: str) -> None:
    import psycopg
    points = json.load(open(points_file, encoding="utf-8"))["points"]
    with psycopg.connect(_url()) as conn, conn.cursor() as cur:
        _check_db(cur)
        counts = {}
        # 1. Every match result at or after any point's cutoff at its event, and every match at the season's later
        #    events: the union, swapped red <-> blue exactly once (raw payload breakdowns swapped too, parity kept).
        keys: set = set()
        for p in points:
            e, cutoff = p["event_key"], datetime.fromisoformat(p["cutoff"])
            cur.execute("""SELECT match_key FROM matches
                           WHERE (event_key = %s AND scheduled_time >= %s)
                              OR (season = %s AND event_key IN (SELECT event_key FROM events
                                   WHERE season = %s AND start_date > (SELECT end_date FROM events WHERE event_key = %s)))""",
                        (e, cutoff, p["season"], p["season"], e))
            keys |= {r[0] for r in cur.fetchall()}
        keys = sorted(keys)
        cur.execute("UPDATE matches SET score_red = score_blue, score_blue = score_red WHERE match_key = ANY(%s)", (keys,))
        counts["matches_swapped"] = cur.rowcount
        cur.execute("""UPDATE raw_source_payloads SET payload_json = jsonb_set(jsonb_set(payload_json,
                           '{score_breakdown,red}', COALESCE(payload_json->'score_breakdown'->'blue', 'null')),
                           '{score_breakdown,blue}', COALESCE(payload_json->'score_breakdown'->'red', 'null'))
                       WHERE source = 'tba' AND source_object_type = 'match' AND source_object_id = ANY(%s)
                         AND jsonb_typeof(payload_json->'score_breakdown') = 'object'""", (keys,))
        counts["breakdowns_swapped"] = cur.rowcount
        for p in points:
            e, cutoff = p["event_key"], datetime.fromisoformat(p["cutoff"])
            # 2. Rankings and alliances (TBA event payloads) reversed / shuffled.
            cur.execute("""UPDATE raw_source_payloads SET payload_json = jsonb_set(payload_json, '{rankings}',
                             COALESCE((SELECT jsonb_agg(r ORDER BY ord DESC) FROM jsonb_array_elements(payload_json->'rankings')
                                       WITH ORDINALITY AS x(r, ord)), '[]'::jsonb))
                           WHERE source = 'tba' AND source_object_type = 'event_ranking' AND source_object_id = %s
                             AND jsonb_typeof(payload_json->'rankings') = 'array'""", (e,))
            counts[f"{e}:rankings_payload"] = cur.rowcount
            # 3. team_metrics (current-state snapshot) for the event: corrupted.
            cur.execute("SELECT column_name FROM information_schema.columns WHERE table_name = 'team_metrics' "
                        "AND data_type = 'double precision' AND column_name LIKE '%%average%%'")
            avg_cols = [r[0] for r in cur.fetchall()]
            cur.execute("UPDATE team_metrics SET " + ", ".join(f"{c} = COALESCE({c}, 0) * 3 + 50" for c in avg_cols)
                        + " WHERE event_key = %s", (e,))
            counts[f"{e}:team_metrics"] = cur.rowcount
            # 4. Future scouting observations: extreme defense scores, after the cutoff, for every rostered team.
            cur.execute("""SELECT DISTINCT mt.team_number, m.match_key, m.scheduled_time FROM match_teams mt
                           JOIN matches m ON m.match_key = mt.match_key
                           WHERE m.event_key = %s AND m.scheduled_time >= %s AND m.competition_level = 'qualification'""",
                        (e, cutoff))
            rows = cur.fetchall()
            cur.execute("SELECT column_name FROM information_schema.columns WHERE table_name = 'scouting_observations'")
            cols = {r[0] for r in cur.fetchall()}
            inserted = 0
            for team, mk, when in rows:
                data = {"event_key": e, "match_key": mk, "team_number": team, "source": "human_scout",
                        "submitted_at": when + timedelta(minutes=5)}
                data["scout_identifier"] = "pit-audit"
                data["defense_rating"] = 5
                data["feeding_rating"] = 5
                try:
                    cur.execute("SAVEPOINT s")
                    cur.execute(f"INSERT INTO scouting_observations ({', '.join(data)}) VALUES "
                                f"({', '.join(['%s'] * len(data))})", list(data.values()))
                    cur.execute("RELEASE SAVEPOINT s")
                    inserted += 1
                except Exception as exc:
                    cur.execute("ROLLBACK TO SAVEPOINT s")
                    counts[f"{e}:scouting_error"] = f"{type(exc).__name__}: {str(exc)[:160]}"
                    break
            counts[f"{e}:scouting_inserted"] = inserted
        conn.commit()
    print(json.dumps(counts, indent=1, default=str))


# --- compare --------------------------------------------------------------------------------------------------------

def _diff(a, b, path="", out=None, limit=8):
    out = [] if out is None else out
    if len(out) >= limit:
        return out
    if type(a) is not type(b):
        out.append(f"{path}: {str(a)[:80]} != {str(b)[:80]}")
    elif isinstance(a, dict):
        for k in sorted(set(a) | set(b)):
            if k not in a or k not in b:
                out.append(f"{path}.{k}: present only on one side")
            else:
                _diff(a[k], b[k], f"{path}.{k}", out, limit)
    elif isinstance(a, list):
        if len(a) != len(b):
            out.append(f"{path}: length {len(a)} != {len(b)}")
        for i, (x, y) in enumerate(zip(a, b)):
            _diff(x, y, f"{path}[{i}]", out, limit)
    elif a != b:
        out.append(f"{path}: {str(a)[:80]} != {str(b)[:80]}")
    return out


def compare(before: str, after: str) -> None:
    a = json.load(open(before, encoding="utf-8"))["outputs"]
    b = json.load(open(after, encoding="utf-8"))["outputs"]
    changed = {k: _diff(a[k], b.get(k)) for k in a if a[k] != b.get(k)}
    print(f"{len(a)} outputs compared; {len(changed)} changed")
    for k, d in sorted(changed.items()):
        print(" ", k)
        for line in d:
            print("     ", line)


if __name__ == "__main__":
    cmd = sys.argv[1]
    if cmd == "capture":
        capture(sys.argv[2], sys.argv[3] if len(sys.argv) > 3 else "d18")
    elif cmd == "perturb":
        _env("d18")
        perturb(sys.argv[2])
    elif cmd == "compare":
        compare(sys.argv[2], sys.argv[3])
