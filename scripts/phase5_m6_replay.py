"""P5-M6 / DM2: replay real events through the production ingestion path and check the serving path.

    python -m scripts.phase5_m6_replay ARGS --debug-event 2026arli    # debug: one full event, records nothing
    python -m scripts.phase5_m6_replay ARGS --recorded                 # the P5-D14 verification (disabled)

ARGS = --snapshot DIR --chain CHAIN --registry DIR --ranking-tag d18 --ranking-sha256 SHA --win-prob-tag d18
--win-prob-sha256 SHA.

**Frozen criteria:** P5-M6 (a)–(e) in docs/P5Milestones.md, unchanged.

**Population:** amended by P5-D14 (`.agent/phase5/M06_Q4_PROPOSAL.md`):
- the seeded, stratified selection recorded in `.agent/phase5/results/p5_m6_selection.json`
  (scripts/phase5_m6_selection.py);
- drawn before any recorded check;
- real historical data only; no synthetic score correction.

**Recorded run:**
- Disabled (`RECORDED_RUN_ENABLED = False`) until Kanav approves executing it.
- When enabled, it runs once, write-once, under a hard 45-minute budget (CLAUDE.md).
- Exceeding the budget stops it and records it as incomplete: a failure, never a partial pass.

**Setup.**
- **Database:** an isolated template copy of the serving database (scripts/phase5_isolated_db). It never touches
  the serving one, which is read only. Before the run, the planned events' canonical matches, team_metrics, raw
  match, ranking and alliance payloads, and watermarks are removed.
- **Payloads:** recorded payloads enter through `data.orchestrator.sync_event`, with only HTTP replaced
  (data.replay.ReplayTBAClient). The watch follow-on (`after_watch_sync`) recomputes `team_metrics`.
- **Order (corrected for the labelled rerun, `p5_m6_replay_rerun1.json`):**
  - every event's qualification schedule is landed first;
  - every planned checked step of every event then runs in **global chronological order**;
  - before each step, every selected event's other matches whose time has passed land as a bulk catch-up sync,
    one per event, through the same production path.
  So each as_of sees exactly the selected events' earlier rows.
- **Steps:** a step is the event's matches sharing a scheduled time. Serving is read at as_of = the step's time
  + 1 µs.
- **Baselines:** a bulk sync is a new input, so it resets the control baseline of every team in it.
- **Re-requests:** each one uses the EPA settings its response was served under.
- **Log:** the complete response log is recorded write-once (`p5_m6_replay_rerun1_log.json`). The original failed
  record (`p5_m6_replay.json`, commit eafba43) is kept unchanged.
- **EPA:** P5-M2's simulated retrieval at a 24 h lag, with concluded seasons before the event's own season. The
  production rule is `d18_skip` (P5-D11). `literal_state` is still computed, and the two are compared at the EPA
  lookup as a diagnostic.

**Checks per step:**
- **(a)** Every affected team's served strength view equals the assembler's TeamFeatures. Its match count rises
  by exactly 1, traced to the new raw payload. 2 seeded control teams are checked too.
- **(b)** The no-op re-poll lands nothing and re-serves identically. Control teams show no in-event change since
  their latest served state.
- **(d)** `team_metrics` equals a fresh recompute, excluding `computed_at`: for the step's served teams, and for
  every rostered team at each window's last step.

**Per event:**
- **(e)** On 2026iscmp, EPA-present teams are served `fallback_stratai` with provenance, at least once.
- **Leakage sentinels:** at the qualification window's middle step, on an affected team.
  - a scored match row 1 h after as_of;
  - a scouting observation on its just-played match, submitted 1 h after as_of.
  Neither may change a served output.
- **Endpoints** (analysis and qualification forecast), each must return 200:
  - at the end of E1's and E2's windows;
  - at E4's window, before the switch (expecting `raw_epa`, not passed) and after it (expecting
    `ranking_xgb_v2`, passed).

**End of run:**
- **(c)** A seeded sample of 150 logged strength responses, plus every sentinel step's, is re-served at its as_of
  on the final database. All must be identical.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import random
import sys
import time
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

LAG_HOURS = 24
POLICIES = ("d18_skip", "literal_state")
PRODUCTION_POLICY = "d18_skip"  # P5-D11
SEASONS = (2024, 2025, 2026)
CONTROL_TEAMS = 2
RESERVE_SAMPLE = 150
SAMPLE_SEED = 20261005  # the harness's own draws (controls, (c) sample); the population seed is the selection's
BUDGET_MINUTES = 45.0
FINAL_RESERVE_MINUTES = 6.0  # kept back for the end-of-run checks
DEBUG_DIR = Path(".agent/phase5/debug")
RESULTS_DIR = Path(".agent/phase5/results")
SELECTION_RECORD = "p5_m6_selection.json"
RECORD = "p5_m6_replay_rerun1.json"  # the labelled rerun (harness corrections approved 2026-10-03)
LOG_RECORD = "p5_m6_replay_rerun1_log.json"  # the complete response log, write-once
SUPERSEDES = {
    "record": "p5_m6_replay.json", "commit": "eafba43",
    "reason": "harness defects, approved for correction by Kanav 2026-10-03 (.agent/phase5/M06_RECORDED_RUN_FAILURE.md): "
              "(1) control baselines now reset after a bulk sync that lands the team's matches; (2) each re-request "
              "uses the EPA settings it was served under; (3) planned actions run in global chronological order, so "
              "every as_of sees the selected events' earlier rows. Population, selection, criteria unchanged",
}
RECORDED_RUN_ENABLED = True  # Kanav approved executing the P5-D14 verification (2026-10-03)
FALLBACK_EVENT = "2026iscmp"
ENDPOINT_AT_END = ("E1", "E2")
METRICS_TIMESTAMP_FIELDS = {"computed_at"}
SENTINEL_KEY = "zzzsentinel_qm999"
IN_EVENT = ("scoring", "auto_points", "defense", "feeding")


def _canonical(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")


def prepare_isolated(name: str, events: list[str]) -> Any:
    """Clone the serving database, then remove the planned events' replayed rows."""
    from data.config import Settings
    from database.connection import Database, DatabaseConfig
    from scripts.phase5_isolated_db import clone, isolated_url

    clone(name, replace=True)
    database = Database(DatabaseConfig(isolated_url(str(Settings().database_url), name)))
    with database.cursor() as c:
        c.execute("SELECT count(*) FROM scouting_observations WHERE event_key = ANY(%s)", (events,))
        if c.fetchone()[0]:
            raise SystemExit("a planned event has scouting observations; its matches cannot be removed for replay")
        c.execute("DELETE FROM team_metrics WHERE event_key = ANY(%s)", (events,))
        c.execute("DELETE FROM match_teams WHERE match_key IN (SELECT match_key FROM matches WHERE event_key = ANY(%s))",
                  (events,))
        c.execute("DELETE FROM matches WHERE event_key = ANY(%s)", (events,))
        c.execute("DELETE FROM raw_source_payloads WHERE source = 'tba' AND ("
                  "(source_object_type = 'match' AND payload_json->>'event_key' = ANY(%s)) OR "
                  "(source_object_type IN ('event_ranking', 'event_alliances') AND source_object_id = ANY(%s)))",
                  (events, events))
        c.execute("DELETE FROM source_watermarks WHERE scope_key = ANY(%s)", (events,))
    return database


def load_sources(args, events: list[str]) -> tuple[dict, tuple]:
    """Recorded payloads and STRATAI values, read from the serving database (read-only), then closed: a
    template copy needs the serving database free of connections."""
    from data.config import Settings
    from data.replay import load_recorded_event
    from database.connection import DatabaseConfig
    from database.readonly import ReadOnlySessionDatabase
    from ml.ratings.live_source import stratai_source

    serving = ReadOnlySessionDatabase(DatabaseConfig(Settings().database_url))
    try:
        return {e: load_recorded_event(serving, e) for e in events}, stratai_source(serving, args.chain)
    finally:
        serving.close()


def full_event_plan(recorded, stratum: str = "debug") -> dict[str, Any]:
    """Debug: every match of one event, each step checked (no bulk syncs)."""
    from scripts.phase5_m6_selection import group_steps

    quals = [(k, m["time"]) for k, m in recorded.matches.items() if m.get("comp_level") == "qm"]
    playoffs = [(k, m["time"]) for k, m in recorded.matches.items() if m.get("comp_level") != "qm"]
    q_steps, p_steps = group_steps(quals), group_steps(playoffs)
    return {"stratum": stratum, "event_key": recorded.event_key, "season": int(recorded.event_key[:4]),
            "roster_size": len(recorded.teams), "pre_window_bulk": [],
            "qual_window": [list(s.match_keys) for s in q_steps], "post_window_bulk": [],
            "playoff_window": [list(s.match_keys) for s in p_steps], "switch_step_in_window": None,
            "sentinel_steps": [len(q_steps) // 2]}


def schedule(plans: list[dict[str, Any]], recorded: dict) -> tuple[list[tuple], dict[str, list[str]]]:
    """Correction (3): every planned checked step in global chronological order (ties: plan order, then position),
    and, per event, the matches outside its windows, which land as bulk catch-up once their time has passed."""
    steps, bulk_pending = [], {}
    for p_index, plan in enumerate(plans):
        rec = recorded[plan["event_key"]]
        windows = [("qual", i, keys) for i, keys in enumerate(plan["qual_window"])]
        windows += [("playoff", i, keys) for i, keys in enumerate(plan["playoff_window"])]
        for position, (kind, index, keys) in enumerate(windows):
            steps.append((max(rec.matches[k]["time"] for k in keys), p_index, position, kind, index, keys, len(windows)))
        windowed = {k for _, _, keys in windows for k in keys}
        bulk_pending[plan["event_key"]] = sorted(k for k in rec.matches if k not in windowed)
    return sorted(steps, key=lambda step: (step[0], step[1], step[2])), bulk_pending


def run_plans(args, plans: list[dict[str, Any]], recorded: dict, stratai: tuple, run_name: str,
              budget_minutes: float = BUDGET_MINUTES) -> dict[str, Any]:
    from fastapi.testclient import TestClient

    from api import create_app
    from api.dependencies import get_database, get_epa_source, get_ranking_model, get_win_prob_model
    from api.ml_loading import ServedEpaSource, ServedModel
    from data.config import Settings
    from data.metrics.compute import compute_team_metrics
    from data.metrics.read import look_up_team_metrics
    from data.orchestrator import after_watch_sync, sync_event
    from data.replay import ReplayTBAClient
    from ml.features.assembler import build_team_features
    from ml.features.scale import ScaleLookup
    from ml.models.calibrated_win_prob import CALIBRATED_WIN_PROB_MODEL_TYPE, CalibratedWinProbModel
    from ml.models.ranking_xgb_v2 import FEATURE_NAMES_V2, RankingXGBModelV2
    from ml.models.win_prob import FEATURE_NAMES
    from ml.ratings.live_epa import lag_schedule
    from ml.ratings.live_source import load_live_provider
    from ml.ratings.provider import TeamEventEpa
    from ml.registry import load_registered_model
    from ml.views.strength import TeamStrengthView, matches_features
    from scripts.phase5_isolated_db import isolated_url

    started = time.monotonic()
    rng = random.Random(SAMPLE_SEED)
    database = prepare_isolated(run_name, [p["event_key"] for p in plans])
    tba = ReplayTBAClient(recorded)
    win_model, win_manifest = load_registered_model(
        CalibratedWinProbModel, registry_dir=args.registry, model_type=CALIBRATED_WIN_PROB_MODEL_TYPE,
        version_tag=args.win_prob_tag, current_feature_list=list(FEATURE_NAMES), expected_sha256=args.win_prob_sha256)
    rank_model, rank_manifest = load_registered_model(
        RankingXGBModelV2, registry_dir=args.registry, model_type="ranking_xgb_v2", version_tag=args.ranking_tag,
        current_feature_list=list(FEATURE_NAMES_V2), expected_sha256=args.ranking_sha256)
    served_win = ServedModel(win_model, win_manifest, args.win_prob_tag, args.win_prob_sha256)
    served_rank = ServedModel(rank_model, rank_manifest, args.ranking_tag, args.ranking_sha256)

    def providers(season: int) -> dict[str, Any]:
        concluded = {s for s in SEASONS if s < season}
        return {p: load_live_provider(database, root_dir=args.snapshot, chain=args.chain, a1a2_policy=p,  # type: ignore[arg-type]
                                      concluded_seasons=concluded, schedule=lag_schedule(LAG_HOURS), stratai=stratai)
                for p in POLICIES}

    holder: dict[str, Any] = {"providers": providers(plans[0]["season"])}
    app = create_app(Settings(epa_source="statbotics", database_url=isolated_url(str(Settings().database_url), run_name)))
    app.dependency_overrides[get_database] = lambda: database
    app.dependency_overrides[get_epa_source] = lambda: ServedEpaSource(
        holder["providers"][PRODUCTION_POLICY], "p5_live_statbotics", False,
        {k: v for k, v in holder["providers"][PRODUCTION_POLICY].provenance().items() if k != "lookup_diagnostics"})
    app.dependency_overrides[get_win_prob_model] = lambda: served_win
    app.dependency_overrides[get_ranking_model] = lambda: served_rank

    log: list[dict[str, Any]] = []
    problems: list[str] = []
    counts: dict[str, int] = defaultdict(int)
    last_state: dict[tuple[str, int], dict] = {}
    sentinel_steps: list[int] = []
    incomplete: str | None = None
    global_step = -1
    client = TestClient(app)

    def serve_strength(team: int, event_key: str, as_of: datetime) -> dict:
        response = client.get(f"/teams/{team}/events/{event_key}/strength", params={"as_of": as_of.isoformat()})
        return response.json() if response.status_code == 200 else {"status": response.status_code, **response.json()}

    def epa_outcome(provider, team: int, event_key: str, as_of: datetime) -> Any:
        try:
            found = provider.point_in_time_epa(team, event_key, as_of)
        except Exception as exc:  # a refusal is an outcome too
            return (type(exc).__name__, getattr(exc, "record", str(exc)))
        if isinstance(found, TeamEventEpa):
            return (found.event_key, found.total, found.auto, found.teleop, found.endgame, found.source,
                    found.provenance.get("epa_source_state"))
        return ("unavailable", found.reason)

    def land(event_key: str, keys: list[str], kind: str) -> None:
        tba.complete(keys)
        result = sync_event(event_key, database=database, tba=tba, pipeline_name="p5_m6_replay")
        after_watch_sync(database, event_key, result)
        counts[kind] += 1

    def roster(event_key: str) -> list[int]:
        with database.cursor() as c:
            c.execute("SELECT DISTINCT mt.team_number FROM match_teams mt JOIN matches m ON m.match_key = "
                      "mt.match_key WHERE m.event_key = %s ORDER BY 1", (event_key,))
            return [r[0] for r in c.fetchall()]

    def endpoints(plan: dict, as_of: datetime, label: str, expect: tuple[str, bool] | None = None) -> None:
        for path in (f"/events/{plan['event_key']}/analysis", f"/events/{plan['event_key']}/qualification-forecast"):
            response = client.get(path, params={"as_of": as_of.isoformat()})
            body = response.json()
            log.append({"event": plan["event_key"], "as_of": as_of.isoformat(), "path": path, "label": label,
                        "status": response.status_code, "response": body})
            counts["endpoint_calls"] += 1
            if response.status_code != 200:
                problems.append(f"endpoint {label} {path}: {response.status_code}")
            elif expect is not None and path.endswith("/analysis"):
                ordering = body["ordering"]
                if (ordering["model"], ordering["switch_point_passed"]) != expect:
                    problems.append(f"endpoint {label}: ordering {ordering['model']}/{ordering['switch_point_passed']}, "
                                    f"expected {expect}")
                counts["switch_checks"] += 1

    def sentinels(event_key: str, team: int, played: list[str], as_of: datetime, step: int) -> None:
        baseline = serve_strength(team, event_key, as_of)
        match_key = f"{event_key}_{SENTINEL_KEY}"
        with database.cursor() as c:  # (1) a scored match one hour after as_of
            c.execute("INSERT INTO matches (match_key, event_key, season, competition_level, match_number, "
                      "scheduled_time, score_red, score_blue) VALUES (%s, %s, %s, 'qualification', 999, %s, 999, 0)",
                      (match_key, event_key, int(event_key[:4]), as_of + timedelta(hours=1)))
            c.execute("INSERT INTO match_teams (match_key, team_number, alliance_color) VALUES (%s, %s, 'red')",
                      (match_key, team))
        leaked_match = serve_strength(team, event_key, as_of) != baseline
        with database.cursor() as c:
            c.execute("DELETE FROM match_teams WHERE match_key = %s", (match_key,))
            c.execute("DELETE FROM matches WHERE match_key = %s", (match_key,))
            # (2) a scouting observation on the just-played match, submitted one hour after as_of
            c.execute("INSERT INTO scouting_observations (match_key, event_key, team_number, scout_identifier, "
                      "defense_rating, feeding_rating, source, submitted_at) VALUES (%s, %s, %s, 'p5-m6-sentinel', "
                      "5, NULL, 'human_scout', %s)", (played[0], event_key, team, as_of + timedelta(hours=1)))
        leaked_observation = serve_strength(team, event_key, as_of) != baseline
        with database.cursor() as c:
            c.execute("DELETE FROM scouting_observations WHERE scout_identifier = 'p5-m6-sentinel'")
        counts["sentinel_checks"] += 2
        sentinel_steps.append(step)
        if leaked_match:
            problems.append(f"sentinel step {step} {event_key}: a future match row changed a served output")
        if leaked_observation:
            problems.append(f"sentinel step {step} {event_key}: a future scouting observation changed a served output")

    with client:
        for plan in plans:  # the qualification schedule is published before each event
            sync_event(plan["event_key"], database=database, tba=tba, pipeline_name="p5_m6_replay")
        # (3) every planned checked step, in global chronological order; every other match of a selected event is
        # landed through the same production path once its scheduled time has passed (bulk catch-up per event)
        steps, bulk_pending = schedule(plans, recorded)
        fallback_served: dict[str, int] = defaultdict(int)

        def catch_up(as_of: datetime) -> bool:
            landed_any = False
            for other in plans:
                key_event, rec_other = other["event_key"], recorded[other["event_key"]]
                due = [k for k in bulk_pending[key_event]
                       if datetime.fromtimestamp(rec_other.matches[k]["time"], timezone.utc) < as_of]
                if not due:
                    continue
                bulk_pending[key_event] = [k for k in bulk_pending[key_event] if k not in set(due)]
                land(key_event, due, "bulk_syncs")
                landed_any = True
                counts["bulk_matches"] += len(due)
                for key in due:  # (1) a bulk sync is a new input for every team in it: reset its baseline
                    for alliance in rec_other.matches[key]["alliances"].values():
                        for team_key in alliance["team_keys"]:
                            last_state.pop((key_event, int(team_key[3:])), None)
            return landed_any

        for _, p_index, position, kind, index, keys, n_windows in steps:
            plan = plans[p_index]
            event_key, rec = plan["event_key"], recorded[plan["event_key"]]
            elapsed = (time.monotonic() - started) / 60
            if elapsed > budget_minutes - FINAL_RESERVE_MINUTES:
                incomplete = f"time budget reached at {elapsed:.1f} min before {event_key} {kind} step {index}"
                break
            global_step += 1
            as_of = datetime.fromtimestamp(max(rec.matches[k]["time"] for k in keys), timezone.utc) \
                + timedelta(microseconds=1)
            if catch_up(as_of) or holder.get("season") != plan["season"]:
                holder["providers"], holder["season"] = providers(plan["season"]), plan["season"]
            affected = [int(k[3:]) for key in keys for a in rec.matches[key]["alliances"].values()
                        for k in a["team_keys"]]
            before = {t: build_team_features(database, t, event_key, as_of - timedelta(microseconds=2),
                                             epa_provider=holder["providers"][PRODUCTION_POLICY]).matches_used
                      for t in affected}
            land(event_key, keys, "step_syncs")
            holder["providers"], holder["season"] = providers(plan["season"]), plan["season"]  # the atomic swap
            scales = ScaleLookup(database)
            teams = roster(event_key)
            others = [t for t in teams if t not in affected]
            control = sorted(rng.sample(others, min(CONTROL_TEAMS, len(others))))
            for team in affected + control:
                role = "affected" if team in affected else "control"
                view = serve_strength(team, event_key, as_of)
                entry = {"step": global_step, "stratum": plan["stratum"], "season": plan["season"],
                         "as_of": as_of.isoformat(), "event": event_key, "team": team, "role": role,
                         "response": view}
                log.append(entry)
                if "strength" not in view:
                    problems.append(f"step {global_step} {event_key} {team}: refused {view}")
                    continue
                features = build_team_features(database, team, event_key, as_of,
                                               epa_provider=holder["providers"][PRODUCTION_POLICY],
                                               scale_lookup=scales)
                outcomes = {p: epa_outcome(prov, team, event_key, as_of) for p, prov in holder["providers"].items()}
                counts["policy_checks"] += 1
                if outcomes["d18_skip"] != outcomes["literal_state"]:
                    counts["policy_differences"] += 1  # diagnostic: production is d18_skip (P5-D11)
                counts["equality_checks"] += 1
                mismatch = matches_features(TeamStrengthView.model_validate(view["strength"]), features)
                if mismatch:
                    problems.append(f"(a) step {global_step} {event_key} {team}: served != assembler {mismatch}")
                if role == "affected":
                    counts["affected_checks"] += 1
                    if features.matches_used != before[team] + 1:
                        problems.append(f"(a) step {global_step} {event_key} {team}: matches_used "
                                        f"{before[team]} -> {features.matches_used}")
                    with database.cursor() as c:
                        c.execute("SELECT max(id) FROM raw_source_payloads WHERE source = 'tba' AND "
                                  "source_object_type = 'match' AND source_object_id = ANY(%s)", (keys,))
                        entry["trace"] = {"match_keys": keys, "raw_payload_id": c.fetchone()[0]}
                        if entry["trace"]["raw_payload_id"] is None:
                            problems.append(f"(a) step {global_step} {event_key}: no raw payload for {keys}")
                current = view["strength"]
                in_event = {k: current[k] for k in IN_EVENT}
                previous = last_state.get((event_key, team))
                if role == "control" and previous is not None:
                    counts["control_checks"] += 1
                    if in_event != previous["in_event"]:
                        problems.append(f"(b) step {global_step} {event_key} control {team}: in-event change "
                                        f"since step {previous['step']}")
                    if current["epa"] != previous["epa"]:
                        counts["control_epa_changes"] += 1
                last_state[(event_key, team)] = {"step": global_step, "in_event": in_event, "epa": current["epa"]}
                if event_key == FALLBACK_EVENT and current["epa"]["total"]["value"] is not None:
                    epa = current["epa"]
                    counts["fallback_views"] += 1
                    if (epa["epa_source_state"] == "fallback_stratai" and epa["epa_value_source"] == "stratai_fallback"
                            and epa["source_event_key"] in ("2026isde1", "2026isde2")):
                        fallback_served[event_key] += 1
                    else:
                        problems.append(f"(e) step {global_step} {team}: {epa['epa_source_state']}")
            last_of_window = (kind == "qual" and index == len(plan["qual_window"]) - 1) or (
                kind == "playoff" and index == len(plan["playoff_window"]) - 1)
            for team in teams if last_of_window else affected + control:  # (d)
                stored = look_up_team_metrics(database, team, event_key).metrics
                fresh = compute_team_metrics(database, team, event_key)
                counts["metrics_checks"] += 1
                if stored is None or stored.model_dump(exclude=METRICS_TIMESTAMP_FIELDS) != fresh.model_dump(
                        exclude=METRICS_TIMESTAMP_FIELDS):
                    problems.append(f"(d) step {global_step} {event_key} {team}: team_metrics != recompute")
            again = sync_event(event_key, database=database, tba=tba, pipeline_name="p5_m6_replay")  # (b)
            counts["noop_polls"] += 1
            if sum(again.loaded.values()) or sum(again.landed.values()):
                problems.append(f"(b) step {global_step} {event_key}: re-poll landed {again.landed}")
            if serve_strength(affected[0], event_key, as_of) != next(
                    e["response"] for e in reversed(log) if e.get("team") == affected[0] and e["event"] == event_key):
                problems.append(f"(b) step {global_step} {event_key}: re-serve after a no-op poll changed")
            if kind == "qual" and index in plan["sentinel_steps"]:
                sentinels(event_key, affected[0], keys, as_of, global_step)
            switch = plan.get("switch_step_in_window")
            if kind == "qual" and switch is not None and index == switch - 1:
                endpoints(plan, as_of, "before_switch", ("raw_epa", False))
            if kind == "qual" and switch is not None and index == switch:
                endpoints(plan, as_of, "after_switch", ("ranking_xgb_v2", True))
            if position == n_windows - 1 and plan["stratum"] in ENDPOINT_AT_END:
                endpoints(plan, as_of, "end_of_window")
            if position == n_windows - 1:
                print(f"[{run_name}] {plan['stratum']} {event_key} done at "
                      f"{(time.monotonic() - started) / 60:.1f} min, problems={len(problems)}", flush=True)
        if FALLBACK_EVENT in {p["event_key"] for p in plans} and not fallback_served[FALLBACK_EVENT] and not incomplete:
            problems.append("(e) no fallback_stratai value was served at 2026iscmp")
        counts["fallback_served"] = sum(fallback_served.values())

        logged = [e for e in log if "team" in e and "response" in e]
        sample = rng.sample(logged, min(RESERVE_SAMPLE, len(logged)))
        sample += [e for e in logged if e["step"] in sentinel_steps and e not in sample]
        reserve_mismatch = 0
        for season in sorted({e["season"] for e in sample}):  # (c) (2) with the EPA settings each was served under
            holder["providers"], holder["season"] = providers(season), season
            for entry in (e for e in sample if e["season"] == season):
                again = serve_strength(entry["team"], entry["event"], datetime.fromisoformat(entry["as_of"]))
                entry["reserve_identical"] = again == entry["response"]
                reserve_mismatch += again != entry["response"]
                counts["reserved"] += 1
        counts["logged_strength_responses"] = len(logged)
        if reserve_mismatch:
            problems.append(f"(c) {reserve_mismatch} sampled responses re-served differently on the final database")

    minutes = round((time.monotonic() - started) / 60, 1)
    if minutes > budget_minutes and not incomplete:
        incomplete = f"finished at {minutes} min, over the {budget_minutes:.0f}-minute budget"
    return {"run": run_name, "plans": [{k: p[k] for k in ("stratum", "event_key")} for p in plans],
            "checked_steps": global_step + 1, "planned_steps": sum(len(p["qual_window"]) + len(p["playoff_window"])
                                                                   for p in plans),
            "minutes": minutes, "incomplete": incomplete,
            "harness": {"control_teams_per_step": CONTROL_TEAMS, "reserve_sample": RESERVE_SAMPLE,
                        "seed": SAMPLE_SEED, "budget_minutes": budget_minutes, "production_policy": PRODUCTION_POLICY},
            "counts": dict(counts), "problems": problems, "log_sha256": hashlib.sha256(_canonical(log)).hexdigest(),
            "replay_log_context": {"retrieval": f"simulated lag {LAG_HOURS} h",
                                   "snapshot_id": holder["providers"][PRODUCTION_POLICY].retrieval.snapshot_id,
                                   "stratai_fingerprint": json.dumps(stratai[1].get("seasons"), sort_keys=True),
                                   "model_sha256": {"ranking_xgb_v2": args.ranking_sha256,
                                                    "win_prob_xgb_calibrated": args.win_prob_sha256}},
            "passed": not problems and not incomplete, "log": log}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    for name in ("--snapshot", "--chain", "--registry"):
        parser.add_argument(name, type=Path, required=True)
    for name in ("--ranking-tag", "--ranking-sha256", "--win-prob-tag", "--win-prob-sha256"):
        parser.add_argument(name, required=True)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--debug-event", help="debug only: replay one full event (time-budgeted), record nothing")
    mode.add_argument("--recorded", action="store_true", help="the P5-D14 recorded verification (disabled)")
    args = parser.parse_args(argv)
    if args.recorded:
        if not RECORDED_RUN_ENABLED:
            raise SystemExit("the recorded P5-M6 verification is disabled until Kanav approves executing it "
                             "(RECORDED_RUN_ENABLED = False)")
        from scripts.phase5_records import provenance, sha256_file, write_once

        provenance()  # refuse up front if the tree is dirty
        selection_path = RESULTS_DIR / SELECTION_RECORD
        selection = json.loads(selection_path.read_text(encoding="utf-8"))
        plans = selection["plans"]
        recorded, stratai = load_sources(args, [p["event_key"] for p in plans])
        run = run_plans(args, plans, recorded, stratai, "stratai_p5_m6_verification")
        log = run.pop("log")
        log_path = write_once(LOG_RECORD, {"milestone": "P5-M6", "entries": log})
        result = {"milestone": "P5-M6", "done_means": "DM2", "decision": "P5-D14", "supersedes": SUPERSEDES,
                  "selection_record_sha256": sha256_file(selection_path),
                  "population_fingerprint": selection["population_fingerprint"], "log_record": LOG_RECORD,
                  "log_record_sha256": sha256_file(log_path), **run}
        path = write_once(RECORD, result)
        print(json.dumps({k: result[k] for k in ("passed", "incomplete", "minutes", "checked_steps", "counts")},
                         indent=1, default=str))
        print(f"problems: {len(run['problems'])} -> {path}")
        return 0 if result["passed"] else 1
    recorded, stratai = load_sources(args, [args.debug_event])
    run = run_plans(args, [full_event_plan(recorded[args.debug_event])], recorded, stratai, "stratai_p5_replay_debug")
    run.pop("log")
    DEBUG_DIR.mkdir(parents=True, exist_ok=True)
    out = DEBUG_DIR / f"m6_debug_{args.debug_event}_{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}.json"
    out.write_text(json.dumps(run, indent=1, default=str) + "\n", encoding="utf-8")  # complete, never truncated
    print(json.dumps({k: run[k] for k in ("passed", "incomplete", "minutes", "checked_steps", "counts")}, indent=1,
                     default=str))
    print(f"problems: {len(run['problems'])} (full result -> {out})")
    for problem in run["problems"]:
        print("  " + problem)
    return 0


if __name__ == "__main__":
    sys.exit(main())
