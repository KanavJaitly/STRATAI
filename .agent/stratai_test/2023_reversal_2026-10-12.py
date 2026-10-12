"""Reverse this session's 2023 TBA sync (pipeline runs 7663-7847) in stratai_test, after preserving it in
stratai_test_2023. Dry run by default: everything happens in one transaction that is rolled back unless --apply
and every check passes.

Why: ml.ratings.provider.read_team_event_facts reads every event in the database, so 2023 team-events became D13
candidates for 2024-2026 targets and changed D18 lookups on the evaluation copy (3,076 2024 team-events).
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import psycopg

sys.path.insert(0, os.getcwd())
from scripts.local_test_env import environment  # noqa: E402
from scripts.phase5_isolated_db import isolated_url, serving_name  # noqa: E402
from data.staging.normalizer import normalize_tba_team  # noqa: E402

SP = Path(__file__).parent
BASE = json.loads((SP / "baseline_before.json").read_text())
RUNS = (7663, 7847)
COPY = "stratai_test_2023"
APPLY = "--apply" in sys.argv

url = environment()["DATABASE_URL"]
assert serving_name(url) == "stratai_test", serving_name(url)
report: dict = {"apply": APPLY}


def check(name: str, ok: bool, detail=None) -> None:
    report.setdefault("checks", {})[name] = {"ok": bool(ok), **({"detail": detail} if detail is not None else {})}
    if not ok:
        raise SystemExit(f"CHECK FAILED {name}: {detail}")


if APPLY:
    with psycopg.connect(isolated_url(url, "postgres"), autocommit=True) as admin:
        if admin.execute("SELECT 1 FROM pg_database WHERE datname = %s", (COPY,)).fetchone():
            report["copy"] = f"{COPY} already exists (kept)"
        else:
            admin.execute(f'CREATE DATABASE "{COPY}" TEMPLATE "stratai_test"')
            report["copy"] = f"created {COPY} from stratai_test (with 2023)"

with psycopg.connect(url) as conn, conn.cursor() as c:
    c.execute("SELECT current_database()")
    check("database", c.fetchone()[0] == "stratai_test")

    # 1. the runs: 185 contiguous event_sync runs of 2023 events, and nothing after them
    c.execute("SELECT count(*), count(*) FILTER (WHERE pipeline_name = 'event_sync' AND scope_key LIKE '2023%%'), "
              "min(started_at), max(finished_at) FROM pipeline_runs WHERE id BETWEEN %s AND %s", RUNS)
    n, n2023, start, end = c.fetchone()
    check("runs_are_2023_event_syncs", n == 185 and n2023 == 185, [n, n2023])
    c.execute("SELECT max(id) FROM pipeline_runs")
    check("no_later_runs", c.fetchone()[0] == RUNS[1])
    c.execute("SELECT count(*) FROM pipeline_runs WHERE started_at BETWEEN %s - interval '1 hour' AND %s + interval '1 hour' "
              "AND id NOT BETWEEN %s AND %s", (start, end, *RUNS))
    check("no_other_runs_nearby", c.fetchone()[0] == 0)
    report["window"] = [str(start), str(end)]

    # 2. raw payloads landed by the sync (window from 10 s before the first run, as the season driver lands first)
    c.execute("CREATE TEMP TABLE new_raw AS SELECT id, source, source_object_type, source_object_id FROM raw_source_payloads "
              "WHERE ingested_at BETWEEN %s - interval '10 seconds' AND %s + interval '10 seconds'", (start, end))
    c.execute("SELECT source || '.' || source_object_type, count(*) FROM new_raw GROUP BY 1 ORDER BY 1")
    landed = dict(c.fetchall())
    report["landed"] = landed
    check("landed_matches_sync_log", landed == {"tba.event": 185, "tba.match": 16342, "tba.team": 1373}, landed)
    c.execute("SELECT count(*) FROM raw_source_payloads WHERE ingested_at BETWEEN %s - interval '1 hour' AND %s + interval '1 hour'",
              (start, end))
    check("no_other_raw_nearby", c.fetchone()[0] == sum(landed.values()))
    c.execute("SELECT count(*) FROM new_raw WHERE source_object_type IN ('event', 'match') AND source_object_id NOT LIKE '2023%%'")
    check("event_match_payloads_all_2023", c.fetchone()[0] == 0)

    # 3. team objects: superseded (an older version exists) vs new
    c.execute("CREATE TEMP TABLE team_objs AS SELECT DISTINCT n.source_object_id AS oid, EXISTS (SELECT 1 FROM raw_source_payloads r "
              "WHERE r.source = 'tba' AND r.source_object_type = 'team' AND r.source_object_id = n.source_object_id "
              "AND r.id NOT IN (SELECT id FROM new_raw)) AS superseded FROM new_raw n WHERE n.source_object_type = 'team'")
    c.execute("SELECT count(*) FILTER (WHERE superseded), count(*) FILTER (WHERE NOT superseded) FROM team_objs")
    superseded, new = c.fetchone()
    report["team_objects"] = {"superseded": superseded, "new": new}
    check("team_objects", superseded == 1198 and new == 175, [superseded, new])

    # invariant baseline: objects not touched by the sync with != 1 current version
    invariant_sql = ("SELECT count(*) FROM (SELECT source, source_object_type, source_object_id, sum(is_current::int) s "
                     "FROM raw_source_payloads GROUP BY 1, 2, 3) x WHERE s != 1")
    c.execute(invariant_sql)
    report["is_current_anomalies_before"] = c.fetchone()[0]

    # watermarks touched in the window must all be 2023 scopes
    c.execute("SELECT id, source, object_type, scope_key FROM source_watermarks WHERE last_updated BETWEEN %s - interval '10 seconds' "
              "AND %s + interval '10 seconds'", (start, end))
    marks = c.fetchall()
    report["watermarks"] = len(marks)
    check("watermarks_all_2023", all(str(m[3]).startswith("2023") for m in marks), [m for m in marks if not str(m[3]).startswith("2023")][:5])

    # 4. nothing outside the sync references 2023 events
    for table in ("team_event_stats", "team_metrics", "scouting_observations", "scouting_access_codes"):
        c.execute(f"SELECT count(*) FROM {table} t JOIN events e USING (event_key) WHERE e.season = 2023")
        check(f"no_2023_{table}", c.fetchone()[0] == 0)

    # 5. delete
    deleted = {}
    for name, sql, args in (
        ("canonical_lineage", "DELETE FROM canonical_lineage WHERE pipeline_run_id BETWEEN %s AND %s", RUNS),
        ("data_quality_issues", "DELETE FROM data_quality_issues WHERE pipeline_run_id BETWEEN %s AND %s", RUNS),
        ("match_teams", "DELETE FROM match_teams WHERE match_key IN (SELECT match_key FROM matches WHERE season = 2023)", None),
        ("matches", "DELETE FROM matches WHERE season = 2023", None),
        ("events", "DELETE FROM events WHERE season = 2023", None),
        ("raw_source_payloads", "DELETE FROM raw_source_payloads WHERE id IN (SELECT id FROM new_raw)", None),
        ("source_watermarks", "DELETE FROM source_watermarks WHERE id = ANY(%s)", ([m[0] for m in marks],)),
        ("pipeline_runs", "DELETE FROM pipeline_runs WHERE id BETWEEN %s AND %s", RUNS),
    ):
        c.execute(sql, args)
        deleted[name] = c.rowcount
    report["deleted"] = deleted

    # restore the superseded team payload versions as current (the raw writer's invariant: newest = current)
    c.execute("SELECT count(*) FROM raw_source_payloads r JOIN team_objs t ON t.oid = r.source_object_id "
              "WHERE r.source = 'tba' AND r.source_object_type = 'team' AND r.is_current")
    check("superseded_all_not_current", c.fetchone()[0] == 0)
    c.execute("UPDATE raw_source_payloads r SET is_current = TRUE FROM (SELECT max(id) AS id FROM raw_source_payloads x "
              "JOIN team_objs t ON t.oid = x.source_object_id AND t.superseded WHERE x.source = 'tba' "
              "AND x.source_object_type = 'team' GROUP BY x.source_object_id) m WHERE r.id = m.id")
    report["restored_current"] = c.rowcount
    check("restored_current", c.rowcount == 1198, c.rowcount)

    # new teams: unreferenced now, then deleted
    c.execute("SELECT count(*) FROM teams WHERE ('frc' || team_number) IN (SELECT oid FROM team_objs WHERE NOT superseded) AND ("
              "EXISTS (SELECT 1 FROM match_teams m WHERE m.team_number = teams.team_number) OR "
              "EXISTS (SELECT 1 FROM team_event_stats s WHERE s.team_number = teams.team_number) OR "
              "EXISTS (SELECT 1 FROM team_metrics s WHERE s.team_number = teams.team_number) OR "
              "EXISTS (SELECT 1 FROM scouting_observations s WHERE s.team_number = teams.team_number))")
    check("new_teams_unreferenced", c.fetchone()[0] == 0)
    c.execute("DELETE FROM teams WHERE ('frc' || team_number) IN (SELECT oid FROM team_objs WHERE NOT superseded)")
    deleted["teams"] = c.rowcount
    check("new_teams_deleted", c.rowcount == 175, c.rowcount)

    # canonical rows of superseded teams, rebuilt from the restored current payload (the normal TBA normalizer)
    c.execute("SELECT r.payload_json FROM raw_source_payloads r JOIN team_objs t ON t.oid = r.source_object_id AND t.superseded "
              "WHERE r.source = 'tba' AND r.source_object_type = 'team' AND r.is_current")
    changed = 0
    for (payload,) in c.fetchall():
        team = normalize_tba_team(payload)
        c.execute("UPDATE teams SET name = %s, city = %s, state_province = %s, country = %s, rookie_year = %s "
                  "WHERE team_number = %s AND (name, city, state_province, country, rookie_year) IS DISTINCT FROM (%s, %s, %s, %s, %s)",
                  (team.name, team.city, team.state_province, team.country, team.rookie_year, team.team_number,
                   team.name, team.city, team.state_province, team.country, team.rookie_year))
        changed += c.rowcount
    report["teams_canonical_restored"] = changed

    # 6. verify against the pre-sync baseline
    c.execute(invariant_sql)
    after_anomalies = c.fetchone()[0]
    check("is_current_invariant", after_anomalies == report["is_current_anomalies_before"] - 0 or after_anomalies == 0,
          [report["is_current_anomalies_before"], after_anomalies])
    for season in ("2023", "2024", "2025", "2026"):
        row = {}
        for name, sql in {
            "events": "SELECT count(*) FROM events WHERE season = %s",
            "matches": "SELECT count(*) FROM matches WHERE season = %s",
            "match_teams": "SELECT count(*) FROM match_teams mt JOIN matches m USING (match_key) WHERE m.season = %s",
            "team_event_stats": "SELECT count(*) FROM team_event_stats WHERE season = %s",
            "team_metrics": "SELECT count(*) FROM team_metrics WHERE season = %s",
            "raw_payloads": "SELECT count(*) FROM raw_source_payloads WHERE source_object_id LIKE %s",
        }.items():
            c.execute(sql, (f"{season}%",) if name == "raw_payloads" else (int(season),))
            row[name] = c.fetchone()[0]
        check(f"counts_{season}", row == BASE[season], [row, BASE[season]])
    c.execute("SELECT md5(string_agg(m.match_key || ':' || coalesce(m.score_red::text,'') || ':' || "
              "coalesce(m.score_blue::text,'') || ':' || coalesce(m.winning_alliance,''), ',' ORDER BY m.match_key)) "
              "FROM matches m WHERE m.season BETWEEN 2024 AND 2026")
    check("matches_fp", c.fetchone()[0] == BASE["matches_fp_2024_2026"])
    c.execute("SELECT md5(string_agg(team_number || ':' || coalesce(name,'') || ':' || coalesce(rookie_year::text,''), "
              "',' ORDER BY team_number)), count(*) FROM teams")
    fp, count = c.fetchone()
    check("teams_fp", fp == BASE["teams_fp"] and count == BASE["teams"], [fp, count])
    c.execute("SELECT count(*) FROM raw_source_payloads WHERE ingested_at > %s - interval '10 seconds'", (start,))
    check("no_raw_after_window_start", c.fetchone()[0] == 0)

    if APPLY:
        conn.commit()
        report["result"] = "committed"
    else:
        conn.rollback()
        report["result"] = "dry run: rolled back"

print(json.dumps(report, indent=1, default=str))
