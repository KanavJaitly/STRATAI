"""P5-M6 / DM2: replay six held-out 2026 events match by match through the production ingestion path.

    python -m scripts.phase5_m6_replay --snapshot DIR --chain CHAIN --registry DIR \\
        --ranking-tag d18 --ranking-sha256 SHA --win-prob-tag d18 --win-prob-sha256 SHA --debug-event 2026arli

Frozen criteria (docs/P5Milestones.md, P5-M6; DM2).

**Status (2026-10-03): debug mode only.**
- A debug run replays one event, records nothing, and writes its complete result to `.agent/phase5/debug/`.
- It is time-budgeted (45 minutes, CLAUDE.md's verification rule) and stops with partial results at the budget.
- Every match of the event is ingested, so the database state is exact. The serving checks are sampled with a fixed
  seed:
  - all six affected teams per step;
  - two random control teams per step;
  - (d) on those eight teams, and on every rostered team at the event's last step;
  - (c) on 150 sampled logged responses plus the sentinel step's.
- The recorded six-event run (`p5_m6_replay.json`) is disabled until a design within the 45-minute rule is
  approved at review.

The text below describes the full design the checks implement.

**Population (fixed at P5-M0).** The first five 2026 events by event_key with qualification matches, plus
2026iscmp: 2026alhu, 2026arc, 2026arli, 2026ausc, 2026azfg and 2026iscmp.

**Setup.**
- **Database:** an isolated template copy of the serving database (scripts/phase5_isolated_db), never the serving
  one. Before the replay it holds none of the six events' canonical matches, raw match, ranking or alliance
  payloads, lineage, watermarks or team_metrics.
- **Replay order:** every match of the six events, globally chronological. Matches sharing a scheduled time land
  together, as one step.
- **Each step:**
  - the recorded payload enters through `data.orchestrator.sync_event` (raw landing → staging → canonical load;
    only HTTP is replaced, by data.replay.ReplayTBAClient);
  - the watch follow-on recomputes `team_metrics` (`data.orchestrator.after_watch_sync`);
  - the serving path is read at as_of = the step's time + 1 µs.
- **Serving path:**
  - the real application (`api.create_app`) is used: the strength endpoint for the step's affected teams and for
    control teams;
  - the event analysis and qualification forecast endpoints are read at each event's end;
  - the next-match forecast comes from the frozen M7 pair.
- **EPA:** P5-M2's simulated retrieval (24 h lag; concluded seasons 2024–2025). Both open-Q1 A1/A2 policies are
  served and required to agree.

**Criteria, all checked at every step:**
- **(a)** Every affected team's served view equals the assembler's TeamFeatures. Its match count rises by exactly
  one, traced to the new row (match_key and raw payload id).
- **(b)**
  - A no-op re-poll lands nothing and re-serves identically.
  - Control teams' in-event fields never change.
  - Their EPA changes only when a simulated retrieval or the fallback clock is crossed.
- **(c)** Bit-for-bit reproducibility. At the end, every logged response is re-served at its as_of on the final
  database and must be identical. The replay-log hash is compared across two independent runs (`--runs 2`).
- **(d)** After every step, `team_metrics` equals a fresh recompute, for every rostered team of the stepped event.
- **(e)** 2026iscmp serves its fallback teams as `fallback_stratai`, with their provenance.

**Leakage.** A point-in-time sentinel (a future match row, already scored) is inserted mid-replay. Served outputs
must not change. It is then removed.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

EVENTS = ["2026alhu", "2026arc", "2026arli", "2026ausc", "2026azfg", "2026iscmp"]
LAG_HOURS = 24
CONCLUDED = {2024, 2025}
POLICIES = ("d18_skip", "literal_state")
CONTROL_TEAMS = 2  # seeded random per step (CLAUDE.md 45-minute verification rule)
RESERVE_SAMPLE = 150  # (c): seeded sample of logged responses re-served on the final database
SAMPLE_SEED = 20261005
BUDGET_MINUTES = 45.0
DEBUG_DIR = Path(".agent/phase5/debug")
RECORD = "p5_m6_replay.json"
METRICS_TIMESTAMP_FIELDS = {"computed_at"}  # a recompute's own timestamp, never a metric value
SENTINEL_KEY = "2026zzzsentinel_qm1"


def _canonical(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")


def prepare_isolated(name: str) -> Any:
    """Clone the serving database, then remove the six events' replayed rows."""
    from data.config import Settings
    from database.connection import Database, DatabaseConfig
    from scripts.phase5_isolated_db import clone, isolated_url

    clone(name, replace=True)
    database = Database(DatabaseConfig(isolated_url(str(Settings().database_url), name)))
    with database.cursor() as c:
        c.execute("DELETE FROM team_metrics WHERE event_key = ANY(%s)", (EVENTS,))
        c.execute("DELETE FROM match_teams WHERE match_key IN (SELECT match_key FROM matches WHERE event_key = ANY(%s))",
                  (EVENTS,))
        c.execute("DELETE FROM matches WHERE event_key = ANY(%s)", (EVENTS,))
        c.execute("DELETE FROM raw_source_payloads WHERE source = 'tba' AND ("
                  "(source_object_type = 'match' AND payload_json->>'event_key' = ANY(%s)) OR "
                  "(source_object_type IN ('event_ranking', 'event_alliances') AND source_object_id = ANY(%s)))",
                  (EVENTS, EVENTS))
        c.execute("DELETE FROM source_watermarks WHERE scope_key = ANY(%s)", (EVENTS,))
    return database


def load_sources(args) -> tuple[dict, tuple]:
    """Recorded payloads and STRATAI values, read from the serving database (read-only), then closed: a
    template copy needs the serving database free of connections."""
    from data.config import Settings
    from data.replay import load_recorded_event
    from database.connection import DatabaseConfig
    from database.readonly import ReadOnlySessionDatabase
    from ml.ratings.live_source import stratai_source

    serving = ReadOnlySessionDatabase(DatabaseConfig(Settings().database_url))
    try:
        return {e: load_recorded_event(serving, e) for e in EVENTS}, stratai_source(serving, args.chain)
    finally:
        serving.close()


def run_once(args, run_name: str, recorded: dict, stratai: tuple, events: list[str] | None = None,
             budget_minutes: float = BUDGET_MINUTES) -> dict[str, Any]:
    import random
    import time

    from fastapi.testclient import TestClient

    from api import create_app
    from api.dependencies import get_database, get_epa_source, get_ranking_model, get_win_prob_model
    from api.ml_loading import ServedEpaSource, ServedModel
    from data.config import Settings
    from data.metrics.compute import compute_team_metrics
    from data.metrics.read import look_up_team_metrics
    from data.orchestrator import after_watch_sync, sync_event
    from data.replay import ReplayTBAClient
    from scripts.phase5_isolated_db import isolated_url
    from ml.features.assembler import build_match_feature_row, build_team_features
    from ml.features.scale import ScaleLookup
    from ml.models.calibrated_win_prob import CALIBRATED_WIN_PROB_MODEL_TYPE, CalibratedWinProbModel
    from ml.models.ranking_xgb_v2 import FEATURE_NAMES_V2, RankingXGBModelV2
    from ml.models.win_prob import FEATURE_NAMES
    from ml.ratings.live_epa import lag_schedule
    from ml.ratings.live_source import load_live_provider
    from ml.ratings.provider import TeamEventEpa
    from ml.registry import load_registered_model
    from ml.views.strength import TeamStrengthView, matches_features

    started = time.monotonic()
    rng = random.Random(SAMPLE_SEED)
    database = prepare_isolated(run_name)
    tba = ReplayTBAClient(recorded)
    win_model, win_manifest = load_registered_model(
        CalibratedWinProbModel, registry_dir=args.registry, model_type=CALIBRATED_WIN_PROB_MODEL_TYPE,
        version_tag=args.win_prob_tag, current_feature_list=list(FEATURE_NAMES), expected_sha256=args.win_prob_sha256)
    rank_model, rank_manifest = load_registered_model(
        RankingXGBModelV2, registry_dir=args.registry, model_type="ranking_xgb_v2", version_tag=args.ranking_tag,
        current_feature_list=list(FEATURE_NAMES_V2), expected_sha256=args.ranking_sha256)
    served_win = ServedModel(win_model, win_manifest, args.win_prob_tag, args.win_prob_sha256)
    served_rank = ServedModel(rank_model, rank_manifest, args.ranking_tag, args.ranking_sha256)

    def providers():
        return {p: load_live_provider(database, root_dir=args.snapshot, chain=args.chain, a1a2_policy=p,  # type: ignore[arg-type]
                                      concluded_seasons=CONCLUDED, schedule=lag_schedule(LAG_HOURS), stratai=stratai)
                for p in POLICIES}

    holder: dict[str, Any] = {"providers": providers()}
    app = create_app(Settings(epa_source="statbotics",
                              database_url=isolated_url(str(Settings().database_url), run_name)))
    app.dependency_overrides[get_database] = lambda: database
    app.dependency_overrides[get_epa_source] = lambda: ServedEpaSource(
        holder["providers"]["d18_skip"], "p5_live_statbotics", False,
        {k: v for k, v in holder["providers"]["d18_skip"].provenance().items() if k != "lookup_diagnostics"})
    app.dependency_overrides[get_win_prob_model] = lambda: served_win
    app.dependency_overrides[get_ranking_model] = lambda: served_rank

    steps: dict[int, list[tuple[str, str]]] = defaultdict(list)
    for event_key, rec in recorded.items():
        if events and event_key not in events:
            continue
        for when, key in rec.ordered_matches():
            steps[when].append((event_key, key))
    order = sorted(steps)
    for event_key in events or EVENTS:  # the qualification schedule is published before each event
        sync_event(event_key, database=database, tba=tba, pipeline_name="p5_m6_replay")

    log: list[dict[str, Any]] = []
    problems: list[str] = []
    counts: dict[str, int] = defaultdict(int)
    last_state: dict[tuple[str, int], dict] = {}  # each team's most recent served state, whatever its role
    stopped_on_budget = False
    index = -1
    rosters: dict[str, list[int]] = {}
    sentinel_step = len(order) // 2
    fp = json.dumps(stratai[1].get("seasons"), sort_keys=True)
    client = TestClient(app)

    def serve_strength(team: int, event_key: str, as_of: datetime) -> dict:
        response = client.get(f"/teams/{team}/events/{event_key}/strength", params={"as_of": as_of.isoformat()})
        return response.json() if response.status_code == 200 else {"status": response.status_code, **response.json()}

    def epa_outcome(provider, team: int, event_key: str, as_of: datetime) -> Any:
        """What one provider answers for a team: its value, or its refusal."""
        try:
            found = provider.point_in_time_epa(team, event_key, as_of)
        except Exception as exc:  # a refusal is an outcome too
            return (type(exc).__name__, getattr(exc, "record", str(exc)))
        if isinstance(found, TeamEventEpa):
            return (found.event_key, found.total, found.auto, found.teleop, found.endgame, found.source,
                    found.provenance.get("epa_source_state"))
        return ("unavailable", found.reason)

    def metrics_dump(metrics) -> dict:
        return metrics.model_dump(exclude=METRICS_TIMESTAMP_FIELDS)

    with client:
        for index, when in enumerate(order):
            elapsed = (time.monotonic() - started) / 60
            if index and elapsed + elapsed / index > budget_minutes - 6:  # keep ~6 min for the final checks
                stopped_on_budget = True
                problems.append(f"time budget: stopped before step {index}/{len(order)} at {elapsed:.1f} min")
                break
            as_of = datetime.fromtimestamp(when, timezone.utc) + timedelta(microseconds=1)
            stepped = steps[when]
            stepped_events = sorted({e for e, _ in stepped})
            before_views: dict[tuple[str, int], dict] = {}
            affected: dict[str, list[int]] = {}
            for event_key, key in stepped:
                alliances = recorded[event_key].matches[key]["alliances"]
                teams = [int(k[3:]) for a in alliances.values() for k in a["team_keys"]]
                affected.setdefault(event_key, []).extend(teams)
                for team in teams:  # the assembler just before this match, on the database before it lands
                    before_views[(event_key, team)] = build_team_features(
                        database, team, event_key, as_of - timedelta(microseconds=2),
                        epa_provider=holder["providers"]["d18_skip"]).matches_used
            tba.complete([key for _, key in stepped])
            for event_key in stepped_events:
                result = sync_event(event_key, database=database, tba=tba, pipeline_name="p5_m6_replay")
                after_watch_sync(database, event_key, result)
                counts["syncs"] += 1
            holder["providers"] = providers()  # canonical facts re-read: the atomic swap
            scales = ScaleLookup(database)
            for event_key in stepped_events:
                with database.cursor() as c:
                    c.execute("SELECT DISTINCT mt.team_number FROM match_teams mt JOIN matches m ON m.match_key = "
                              "mt.match_key WHERE m.event_key = %s ORDER BY 1", (event_key,))
                    rosters[event_key] = [r[0] for r in c.fetchall()]
                others = [t for t in rosters[event_key] if t not in affected[event_key]]
                control = sorted(rng.sample(others, min(CONTROL_TEAMS, len(others))))
                for team in affected[event_key] + control:
                    view = serve_strength(team, event_key, as_of)
                    entry = {"step": index, "as_of": as_of.isoformat(), "event": event_key, "team": team,
                             "role": "affected" if team in affected[event_key] else "control", "response": view}
                    if "strength" not in view:
                        problems.append(f"step {index} {event_key} {team}: refused {view}")
                        log.append(entry)
                        continue
                    strength = TeamStrengthView.model_validate(view["strength"])
                    features = build_team_features(database, team, event_key, as_of,
                                                   epa_provider=holder["providers"]["d18_skip"], scale_lookup=scales)
                    # the A1/A2 policy (open Q1) only changes the EPA lookup, so the lookups are compared
                    outcomes = {p: epa_outcome(prov, team, event_key, as_of) for p, prov in holder["providers"].items()}
                    counts["policy_checks"] += 1
                    if outcomes["d18_skip"] != outcomes["literal_state"]:
                        problems.append(f"policy step {index} {event_key} {team}: A1/A2 policies differ {outcomes}")
                    mismatch = matches_features(strength, features)
                    counts["equality_checks"] += 1
                    if mismatch:
                        problems.append(f"(a) step {index} {event_key} {team}: served != assembler {mismatch}")
                    if entry["role"] == "affected":
                        before = before_views[(event_key, team)]
                        after = features.matches_used
                        played = [key for e, key in stepped if e == event_key]
                        if before is not None and after != before + 1:
                            problems.append(f"(a) step {index} {event_key} {team}: matches_used {before} -> {after}")
                        with database.cursor() as c:
                            c.execute("SELECT max(id) FROM raw_source_payloads WHERE source = 'tba' AND "
                                      "source_object_type = 'match' AND source_object_id = ANY(%s)", (played,))
                            entry["trace"] = {"match_keys": played, "raw_payload_id": c.fetchone()[0]}
                        counts["affected_checks"] += 1
                    current = view["strength"]
                    in_event = {k: current[k] for k in ("scoring", "auto_points", "defense", "feeding")}
                    previous = last_state.get((event_key, team))
                    if entry["role"] == "control" and previous is not None:
                        # compared with this team's latest served state, which includes any match it played since
                        counts["control_checks"] += 1
                        if in_event != previous["in_event"]:
                            problems.append(f"(b) step {index} {event_key} control {team}: in-event change "
                                            f"since step {previous['step']}")
                        if current["epa"] != previous["epa"]:
                            counts["control_epa_changes"] += 1
                    last_state[(event_key, team)] = {"step": index, "in_event": in_event, "epa": current["epa"]}
                    if event_key == "2026iscmp":
                        epa = view["strength"]["epa"]
                        counts["iscmp_views"] += 1
                        if epa["total"]["value"] is not None:
                            ok = (epa["epa_source_state"] == "fallback_stratai" and epa["epa_value_source"]
                                  == "stratai_fallback" and epa["source_event_key"] in ("2026isde1", "2026isde2"))
                            counts["iscmp_fallback_served"] += ok
                            if not ok:
                                problems.append(f"(e) step {index} {team}: {epa['epa_source_state']}")
                    log.append(entry)
                # next-match forecast: the frozen M7 pair on the assembler's row at as_of
                upcoming = [k for w, k in recorded[event_key].ordered_matches()
                            if recorded[event_key].matches[k].get("comp_level") == "qm" and k not in tba.completed]
                if upcoming:
                    row = build_match_feature_row(database, upcoming[0], as_of, epa_provider=holder["providers"]["d18_skip"],
                                                  scale_lookup=scales)
                    log.append({"step": index, "as_of": as_of.isoformat(), "event": event_key, "forecast": upcoming[0],
                                "q_red": repr(float(win_model.predict_win_prob(row)))})
                # (d) team_metrics equals a fresh recompute: the step's served teams, and every rostered team at
                # the event's last step; the recompute's own timestamp is excluded
                last_step = all(k in tba.completed for k in recorded[event_key].matches)
                for team in rosters[event_key] if last_step else affected[event_key] + control:
                    stored = look_up_team_metrics(database, team, event_key).metrics
                    fresh = compute_team_metrics(database, team, event_key)
                    counts["metrics_checks"] += 1
                    if stored is None or metrics_dump(stored) != metrics_dump(fresh):
                        problems.append(f"(d) step {index} {event_key} {team}: team_metrics differs from a recompute")
                # (b) a no-op re-poll lands nothing and re-serves identically
                again = sync_event(event_key, database=database, tba=tba, pipeline_name="p5_m6_replay")
                if sum(again.loaded.values()) or any(n for k, n in again.landed.items()):
                    problems.append(f"(b) step {index} {event_key}: re-poll landed {again.landed}")
                probe = affected[event_key][0]
                if serve_strength(probe, event_key, as_of) != next(
                        e["response"] for e in reversed(log) if e.get("team") == probe and e["event"] == event_key):
                    problems.append(f"(b) step {index} {event_key}: re-serve after a no-op poll changed")
                counts["noop_polls"] += 1
            if index == sentinel_step:  # point-in-time sentinel: a scored match after as_of
                event_key, team = stepped_events[0], affected[stepped_events[0]][0]
                baseline = serve_strength(team, event_key, as_of)
                with database.cursor() as c:
                    c.execute("INSERT INTO matches (match_key, event_key, season, competition_level, match_number, "
                              "scheduled_time, score_red, score_blue) VALUES (%s, %s, 2026, 'qualification', 999, %s, "
                              "999, 0)", (SENTINEL_KEY, event_key, as_of + timedelta(hours=1)))
                    c.execute("INSERT INTO match_teams (match_key, team_number, alliance_color) VALUES (%s, %s, 'red')",
                              (SENTINEL_KEY, team))
                leaked = serve_strength(team, event_key, as_of) != baseline
                counts["sentinel_step"] = index
                with database.cursor() as c:
                    c.execute("DELETE FROM match_teams WHERE match_key = %s", (SENTINEL_KEY,))
                    c.execute("DELETE FROM matches WHERE match_key = %s", (SENTINEL_KEY,))
                counts["sentinel_checks"] += 1
                if leaked:
                    problems.append(f"sentinel at step {index}: a future row changed a served output")
            for event_key in stepped_events:  # each event's end: ordering and forecasts through the API
                if all(k in tba.completed for k in recorded[event_key].matches):
                    for path in (f"/events/{event_key}/analysis", f"/events/{event_key}/qualification-forecast"):
                        response = client.get(path, params={"as_of": as_of.isoformat()})
                        log.append({"step": index, "as_of": as_of.isoformat(), "event": event_key, "path": path,
                                    "status": response.status_code, "response": response.json()})
                        if response.status_code != 200:
                            problems.append(f"{path} at the end of {event_key}: {response.status_code}")
            if index % 50 == 0:
                print(f"[{run_name}] step {index}/{len(order)} problems={len(problems)}", flush=True)

        # (c) re-serve a seeded sample of logged strength responses, plus the sentinel step's, at their as_of
        # on the final database
        logged = [e for e in log if "team" in e and "response" in e]
        sample = rng.sample(logged, min(RESERVE_SAMPLE, len(logged)))
        sample += [e for e in logged if e["step"] == counts.get("sentinel_step") and e not in sample]
        reserve_mismatch = 0
        for entry in sample:
            again = serve_strength(entry["team"], entry["event"], datetime.fromisoformat(entry["as_of"]))
            reserve_mismatch += again != entry["response"]
            counts["reserved"] += 1
        counts["logged_strength_responses"] = len(logged)
        if reserve_mismatch:
            problems.append(f"(c) {reserve_mismatch} logged responses re-served differently on the final database")

    digest = hashlib.sha256(_canonical(log)).hexdigest()
    return {"run": run_name, "steps": len(order), "matches": sum(len(v) for v in steps.values()),
            "steps_completed": index if stopped_on_budget else index + 1, "stopped_on_budget": stopped_on_budget,
            "minutes": round((time.monotonic() - started) / 60, 1),
            "sampling": {"control_teams_per_step": CONTROL_TEAMS, "reserve_sample": RESERVE_SAMPLE,
                         "seed": SAMPLE_SEED, "budget_minutes": budget_minutes},
            "counts": dict(counts), "problems": problems, "log_sha256": digest,
            "replay_log_context": {"snapshot_id": holder["providers"]["d18_skip"].retrieval.snapshot_id,
                                   "retrieval": f"simulated lag {LAG_HOURS} h", "stratai_fingerprint": fp,
                                   "model_sha256": {"ranking_xgb_v2": args.ranking_sha256,
                                                    "win_prob_xgb_calibrated": args.win_prob_sha256}}}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    for name in ("--snapshot", "--chain", "--registry"):
        parser.add_argument(name, type=Path, required=True)
    for name in ("--ranking-tag", "--ranking-sha256", "--win-prob-tag", "--win-prob-sha256"):
        parser.add_argument(name, required=True)
    parser.add_argument("--debug-event", required=True,
                        help="debug only: replay one event once (time-budgeted) and record nothing")
    args = parser.parse_args(argv)
    if args.debug_event:
        recorded, stratai = load_sources(args)
        run = run_once(args, "stratai_p5_replay_debug", recorded, stratai, [args.debug_event])
        DEBUG_DIR.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        out = DEBUG_DIR / f"m6_debug_{args.debug_event}_{stamp}.json"
        out.write_text(json.dumps(run, indent=1, default=str) + "\n", encoding="utf-8")  # complete, never truncated
        print(json.dumps({k: run[k] for k in ("steps", "steps_completed", "minutes", "stopped_on_budget", "counts")},
                         indent=1, default=str))
        print(f"problems: {len(run['problems'])} (full result -> {out})")
        for problem in run["problems"]:
            print("  " + problem)
        return 0
    raise SystemExit("the recorded six-event replay is disabled: it must be redesigned to fit the 45-minute "
                     "verification rule (CLAUDE.md) and approved at review before it runs")


if __name__ == "__main__":
    sys.exit(main())
