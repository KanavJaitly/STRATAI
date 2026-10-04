"""P5-M2 historical validation runs L3 and L4 (LIVE_EPA_REFRESH_DESIGN.md §10), recorded write-once.

    python -m scripts.phase5_m2_live_epa_checks l3 --isolated-db stratai_test
    python -m scripts.phase5_m2_live_epa_checks l4 --snapshot DIR --chain CHAIN --registry DIR \\
        --win-prob-tag d18 --win-prob-sha256 SHA

**L1 and L2 are not run here.** They wait for open decision Q1 (.agent/phase5/M02_DECISION_REQUIRED.md), which
must be made before their results exist.

Both runs below are policy-independent by construction, and they check it. Each runs under both candidate A1/A2
policies and requires identical outputs, so neither depends on how Q1 is decided.

**L3, the outage drill.** Synthetic season 9983, landed into an isolated database and never the serving one.
- The real refresher runs against a client that injects HTTP 503s and timeouts.
- The timeline crosses the 72 h fallback threshold.
- Pass:
  - no manifest is written for a failed refresh;
  - the previous snapshot serves, labelled `stale`;
  - `pending` before 72 h;
  - `fallback_stratai` after 72 h;
  - 0 unlabelled source mixing;
  - an unprocessed record is never served as `statbotics`.

**L4, atomicity and reproducibility.** A match-by-match replay of a real 2026 event.
- **Pre-declared, before running:** 2026iscmp, which exercises the per-team-event fallback, under simulated
  retrieval at a 24 h lag (L2's diagnostic lag), reading the serving database read-only.
- **Each prediction** is built through the serving path's feature assembly and the frozen D18 M7 pair (sha256
  checked), and logged (ml.ratings.prediction_log).
- **Pass:**
  - each response names one `snapshot_id`;
  - re-serving every logged prediction, with freshly loaded providers and model, is bit-for-bit identical;
  - a team's served features change only when its inputs change: a new canonical row, or a newly retrieved
    record or fallback clock.
"""

from __future__ import annotations

import argparse
import json
import sys
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

L4_EVENT = "2026iscmp"
L4_LAG_HOURS = 24
L3_SEASON = 9983
POLICIES = ("d18_skip", "literal_state")
# The first L4 record (p5_m2_l4_atomicity.json, commit 7b2d29c) failed only on an additional EPA-stability
# sub-check, which wrongly counted epa_scale as a provider output. epa_scale is the causal season scale, which
# moves with canonical rows: an allowed input change under L4's criterion. That record is kept unchanged. Its
# L4 criteria all passed: 0 re-serve mismatches, 0 feature changes without an input change, one snapshot_id.
L4_RECORD = "p5_m2_l4_atomicity_rerun1.json"
L4_SUPERSEDES = {
    "record": "p5_m2_l4_atomicity.json",
    "commit": "7b2d29c",
    "reason": "check defect: epa_scale (a canonical-row-dependent season scale) was counted as an EPA provider "
              "output in the additional EPA-stability sub-check; on the first run it was the only field that "
              "changed (324 times), and every L4 criterion passed",
}


# --- L3 ------------------------------------------------------------------------------------------


def _l3_record(team: int, event: str, total: float, status: str) -> dict[str, Any]:
    return {"team": team, "event": event, "year": L3_SEASON, "week": 2, "status": status,
            "epa": {"total_points": total, "breakdown": {"auto_points": 1.0, "teleop_points": total - 3.0,
                                                         "endgame_points": 2.0}},
            "record": {"qual": {"count": 10}, "total": {"count": 12, "wins": 6, "losses": 6, "ties": 0}}}


class _InjectingClient:
    """Plays a script: an exception to raise, or a list of raw records to return (with parsed responses)."""

    def __init__(self) -> None:
        self.next: Any = None

    def fetch_event_team_metrics(self, event_key: str):
        from data.clients.source_connector import SourceResponse
        from data.clients.schemas import StatboticsTeamEventMetrics

        if isinstance(self.next, Exception):
            raise self.next
        return self.next, [SourceResponse(r, StatboticsTeamEventMetrics.model_validate(r)) for r in self.next]


def run_l3(isolated_db: str) -> dict[str, Any]:
    import gzip
    import hashlib

    import httpx

    from data.config import Settings
    from database.connection import Database, DatabaseConfig
    from ml.ratings.epa_states import CURRENT, FALLBACK_STRATAI, STALE
    from ml.ratings.live_epa import (
        EpaSourcePendingError,
        LiveRetrieval,
        LiveStatboticsEpa,
    )
    from ml.ratings.live_snapshots import SnapshotLog, canonical
    from ml.ratings.live_source import LiveEpaRefresher, read_event_ends
    from ml.ratings.provider import StrataiTeamEventValue, TeamEventEpa, read_team_event_facts
    from scripts.phase5_isolated_db import isolated_url, serving_name

    serving = str(Settings().database_url)
    if isolated_db == serving_name(serving):
        raise SystemExit("L3 writes rows: refusing the serving database")
    database = Database(DatabaseConfig(isolated_url(serving, isolated_db)))
    prior, other, target = f"{L3_SEASON}zzzl3prior", f"{L3_SEASON}zzzl3other", f"{L3_SEASON}zzzl3target"
    team_a, team_b = 998301, 998302
    end = datetime(2027, 3, 7, 20, tzinfo=timezone.utc)  # prior's last completed match
    other_end = end - timedelta(days=7)

    def cleanup() -> None:
        with database.cursor() as c:
            c.execute("DELETE FROM team_event_stats WHERE event_key IN (%s, %s, %s)", (prior, other, target))
            c.execute("DELETE FROM match_teams WHERE match_key LIKE %s", (f"{L3_SEASON}zzzl3%",))
            c.execute("DELETE FROM matches WHERE event_key IN (%s, %s, %s)", (prior, other, target))
            c.execute("DELETE FROM events WHERE event_key IN (%s, %s, %s)", (prior, other, target))
            c.execute("DELETE FROM teams WHERE team_number = ANY(%s)", ([team_a, team_b],))
            c.execute("DELETE FROM raw_source_payloads WHERE source_object_id LIKE %s", (f"%{L3_SEASON}zzzl3%",))
            c.execute("DELETE FROM canonical_lineage WHERE entity_key LIKE %s", (f"%{L3_SEASON}zzzl3%",))
            c.execute("DELETE FROM pipeline_runs WHERE scope_key LIKE %s", (f"{L3_SEASON}zzzl3%",))
            c.execute("DELETE FROM source_watermarks WHERE scope_key LIKE %s", (f"{L3_SEASON}zzzl3%",))

    cleanup()
    with database.cursor() as c:
        c.execute("INSERT INTO teams (team_number, name) VALUES (%s, 'L3 A'), (%s, 'L3 B')", (team_a, team_b))
        for key, when in ((other, other_end), (prior, end), (target, end + timedelta(days=10))):
            c.execute("INSERT INTO events (event_key, season, name, end_date) VALUES (%s, %s, %s, %s)",
                      (key, L3_SEASON, key, when.date()))
        for key, event, when, team in ((f"{prior}_qm1", prior, end, team_a), (f"{other}_qm1", other, other_end, team_b)):
            c.execute("INSERT INTO matches (match_key, event_key, season, competition_level, match_number, "
                      "scheduled_time, score_red, score_blue) VALUES (%s, %s, %s, 'qualification', 1, %s, 50, 40)",
                      (key, event, L3_SEASON, when))
            c.execute("INSERT INTO match_teams (match_key, team_number, alliance_color) VALUES (%s, %s, 'red')",
                      (key, team))
    try:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "root"
            (root / "raw").mkdir(parents=True)
            data = canonical([_l3_record(team_b, other, 55.0, "Completed")])
            (root / "raw" / f"{other}.json.gz").write_bytes(gzip.compress(data, mtime=0))
            (root / "manifest.json").write_text(json.dumps({
                "failures": [], "events_requested": 1, "events_fetched": 1,
                "finished_at": (other_end + timedelta(days=1)).isoformat(),
                "events": [{"event_key": other, "raw_file": f"raw/{other}.json.gz",
                            "raw_sha256": hashlib.sha256(data).hexdigest(),
                            "retrieved_at": (other_end + timedelta(days=1)).isoformat()}]}), encoding="utf-8")
            log = SnapshotLog.create_from_root(Path(tmp) / "log", root)
            client = _InjectingClient()
            refresher = LiveEpaRefresher(log, database, client, sleep=lambda s: None)
            stratai = {(team_a, prior): StrataiTeamEventValue(33.0, 4.0, 25.0, 4.0, int(end.timestamp()) + 60, False)}
            facts = read_team_event_facts(database, [team_a, team_b])
            ends, _ = read_event_ends(database)
            week_one = {L3_SEASON: end - timedelta(days=30)}
            request = httpx.Request("GET", "https://api.statbotics.io/v3/team_events")
            steps = [
                (1, httpx.HTTPStatusError("503", request=request, response=httpx.Response(503, request=request))),
                (3, httpx.ReadTimeout("injected timeout")),
                (73, httpx.HTTPStatusError("503", request=request, response=httpx.Response(503, request=request))),
                (80, [_l3_record(team_a, prior, 41.0, "Upcoming")]),
                (90, [_l3_record(team_a, prior, 42.0, "Completed")]),
            ]
            expected = {  # (team_a state, team_b state) half an hour after each step
                1: ("pending", STALE), 3: ("pending", STALE), 73: (FALLBACK_STRATAI, STALE),
                80: (FALLBACK_STRATAI, CURRENT), 90: (CURRENT, CURRENT),
            }
            timeline, problems = [], []
            for hours, outcome in steps:
                now = end + timedelta(hours=hours)
                head_before = log.head()
                client.next = outcome
                result = refresher.refresh([prior], now=now)
                failed = isinstance(outcome, Exception)
                manifest_written = log.head() != head_before
                if failed and (manifest_written or result.ok):
                    problems.append(f"+{hours}h: a failed refresh wrote a manifest")
                if not failed and not (manifest_written and result.ok):
                    problems.append(f"+{hours}h: a successful refresh wrote no manifest: {result.check_failures}")
                as_of = now + timedelta(minutes=30)
                per_policy = {}
                for policy in POLICIES:
                    provider = LiveStatboticsEpa(LiveRetrieval(log), facts, ends, week_one, {}, stratai,
                                                 {"replay": "l3-synthetic"}, policy)  # type: ignore[arg-type]
                    states = []
                    for team in (team_a, team_b):
                        try:
                            found = provider.point_in_time_epa(team, target, as_of)
                        except EpaSourcePendingError:
                            states.append(("pending", None, None))
                            continue
                        assert isinstance(found, TeamEventEpa)
                        state = found.provenance["epa_source_state"]
                        labelled = (found.source == "statbotics" and state in (CURRENT, STALE)) or (
                            found.source == "stratai_fallback" and state == FALLBACK_STRATAI)
                        if not labelled:
                            problems.append(f"+{hours}h team {team}: unlabelled mixing {found.source}/{state}")
                        states.append((state, found.source, found.total))
                    per_policy[policy] = states
                if per_policy["d18_skip"] != per_policy["literal_state"]:
                    problems.append(f"+{hours}h: policies differ {per_policy}")
                observed = tuple(s[0] for s in per_policy["d18_skip"])
                if observed != expected[hours]:
                    problems.append(f"+{hours}h: states {observed}, expected {expected[hours]}")
                a = per_policy["d18_skip"][0]
                if hours == 80 and a[1] == "statbotics":
                    problems.append("+80h: an unprocessed record was served as statbotics")
                timeline.append({"refresh_at_hours": hours, "injected": type(outcome).__name__ if failed else "records",
                                 "refresh_ok": result.ok, "manifest_written": manifest_written,
                                 "states_30min_later": {"team_a": a, "team_b": per_policy["d18_skip"][1]}})
            log_entries = log.entries()
            return {"milestone": "P5-M2", "check": "L3 outage drill (synthetic season 9983, isolated database)",
                    "database": isolated_db, "timeline": timeline,
                    "manifests": sum(e["kind"] == "snapshot" for e in log_entries),
                    "refresh_entries": sum(e["kind"] == "refresh" for e in log_entries),
                    "policies_compared": list(POLICIES), "problems": problems, "passed": not problems}
    finally:
        cleanup()


# --- L4 ------------------------------------------------------------------------------------------


def run_l4(snapshot: Path, chain: Path, registry: Path, tag: str, sha256: str) -> dict[str, Any]:
    from api.routes.predictions import display_probability
    from data.config import Settings
    from database.connection import DatabaseConfig
    from database.readonly import ReadOnlySessionDatabase
    from ml.features.assembler import build_match_feature_row
    from ml.features.scale import ScaleLookup
    from ml.models.calibrated_win_prob import CALIBRATED_WIN_PROB_MODEL_TYPE, CalibratedWinProbModel
    from ml.models.win_prob import FEATURE_NAMES
    from ml.ratings.live_epa import EpaSourcePendingError, EpaSourceUnavailableError
    from ml.ratings.live_source import load_live_provider, stratai_source
    from ml.ratings.live_epa import lag_schedule
    from ml.ratings.prediction_log import LoggedPrediction, PredictionLog, reserve_matches
    from ml.ratings.provider import TeamEventEpa
    from ml.registry import load_registered_model
    from scripts.phase5_records import provenance

    database = ReadOnlySessionDatabase(DatabaseConfig(Settings().database_url))
    commit = provenance()["commit"]

    def load_all():
        model, _ = load_registered_model(CalibratedWinProbModel, registry_dir=registry,
                                         model_type=CALIBRATED_WIN_PROB_MODEL_TYPE, version_tag=tag,
                                         current_feature_list=list(FEATURE_NAMES), expected_sha256=sha256)
        stratai = stratai_source(database, chain)
        providers = {p: load_live_provider(database, root_dir=snapshot, chain=chain, a1a2_policy=p,  # type: ignore[arg-type]
                                           concluded_seasons={2024, 2025, 2026}, schedule=lag_schedule(L4_LAG_HOURS),
                                           stratai=stratai) for p in POLICIES}
        return model, providers, stratai[1]

    with database.cursor() as cursor:
        cursor.execute("SELECT match_key, scheduled_time FROM matches WHERE event_key = %s AND "
                       "competition_level = 'qualification' AND scheduled_time IS NOT NULL "
                       "ORDER BY scheduled_time, match_key", (L4_EVENT,))
        quals = cursor.fetchall()
    scales = ScaleLookup(database)

    def serve(model, provider, match_key: str, as_of: datetime) -> dict[str, Any]:
        view = provider.snapshot_view(as_of)
        try:
            row = build_match_feature_row(database, match_key, as_of, epa_provider=provider, scale_lookup=scales)
        except (EpaSourcePendingError, EpaSourceUnavailableError) as exc:
            return {"match_key": match_key, "snapshot_id": view.snapshot_id, "refused": type(exc).__name__,
                    "record": exc.record}
        teams = sorted((t.model_dump(mode="json") for t in (*row.red_teams, *row.blue_teams)),
                       key=lambda t: t["team_number"])
        probability = model.predict_win_prob(row)
        return {"match_key": match_key, "snapshot_id": view.snapshot_id, "red_win_probability_raw": repr(probability),
                "red_win_probability": display_probability(probability), "teams": teams}

    model, providers, stratai_info = load_all()
    fingerprint = json.dumps(stratai_info.get("seasons"), sort_keys=True)
    problems: list[str] = []
    responses: dict[str, list[dict[str, Any]]] = {}
    with tempfile.TemporaryDirectory() as tmp:
        log = PredictionLog(Path(tmp) / "predictions.jsonl")
        for policy, provider in providers.items():
            responses[policy] = []
            for match_key, as_of in quals:
                response = serve(model, provider, match_key, as_of)
                ids = set()
                for team in (t["team_number"] for t in response.get("teams", [])):
                    found = provider.point_in_time_epa(team, L4_EVENT, as_of)
                    if isinstance(found, TeamEventEpa):
                        ids.add(found.provenance["snapshot_id"])
                if ids - {response["snapshot_id"]}:
                    problems.append(f"{policy} {match_key}: response names {sorted(ids | {response['snapshot_id']})}")
                responses[policy].append(response)
                log.append(LoggedPrediction(as_of.isoformat(), response["snapshot_id"], fingerprint,
                                            {"win_prob_xgb_calibrated": sha256}, commit,
                                            {"match_key": match_key, "policy": policy}, response))
        if responses["d18_skip"] != responses["literal_state"]:
            problems.append("the two A1/A2 policies served different responses")

        fresh_model, fresh_providers, _ = load_all()
        entries = log.entries()
        mismatched = [e.request for e in entries if not reserve_matches(
            e, lambda req, as_of, sid: serve(fresh_model, fresh_providers[req["policy"]], req["match_key"], as_of))]
        problems += [f"re-serve differs: {m}" for m in mismatched]

    # inputs-only change: a team's features may change between consecutive appearances only when its inputs did
    provider = providers["d18_skip"]
    with database.cursor() as cursor:
        cursor.execute("SELECT m.scheduled_time FROM matches m JOIN events e ON e.event_key = m.event_key "
                       "WHERE e.season = 2026 AND m.scheduled_time IS NOT NULL AND m.score_red IS NOT NULL "
                       "AND m.score_blue IS NOT NULL ORDER BY 1")
        completed = [row[0] for row in cursor.fetchall()]
    retrieval_times = sorted(set(provider.retrieval.retrieved_at.values()))  # type: ignore[attr-defined]
    clock_times = sorted(e + timedelta(hours=72) for e in provider.event_end.values())

    def signature(as_of: datetime) -> tuple[int, int, int]:
        from bisect import bisect_left
        return (bisect_left(completed, as_of), bisect_left(retrieval_times, as_of), bisect_left(clock_times, as_of))

    last: dict[int, tuple[Any, Any]] = {}
    last_epa: dict[int, tuple[Any, Any]] = {}
    unexplained, epa_unexplained = [], []
    for (match_key, as_of), response in zip(quals, responses["d18_skip"]):
        sig = signature(as_of)
        epa_sig = sig[1:]  # EPA depends on retrievals and the fallback clock, not on in-event rows
        for team in response.get("teams", []):
            number = team["team_number"]
            previous = last.get(number)
            if previous is not None and previous[0] == sig and previous[1] != team:
                unexplained.append([number, match_key])
            last[number] = (sig, team)
            # provider outputs only: epa_scale / epa_scale_present are the causal season scale
            # (ml/features/scale.py), which moves with canonical rows and is covered by `sig` above
            epa = {k: v for k, v in team.items() if k.startswith("epa_") and not k.startswith("epa_scale")}
            previous_epa = last_epa.get(number)
            if previous_epa is not None and previous_epa[0] == epa_sig and previous_epa[1] != epa:
                epa_unexplained.append([number, match_key])
            last_epa[number] = (epa_sig, epa)
    problems += [f"feature change without an input change: {u}" for u in unexplained]
    problems += [f"EPA change without a retrieval or clock change: {u}" for u in epa_unexplained]
    served = [r for r in responses["d18_skip"] if "refused" not in r]
    states: dict[str, int] = {}
    for r in served:
        for t in r["teams"]:
            states[str(t["epa_source_state"])] = states.get(str(t["epa_source_state"]), 0) + 1
    return {"milestone": "P5-M2", "check": "L4 atomicity and reproducibility",
            "pre_declared": {"event": L4_EVENT, "retrieval": f"simulated lag {L4_LAG_HOURS} h",
                             "policies_compared": list(POLICIES)},
            "qualification_matches": len(quals), "served": len(served),
            "refused": len(responses["d18_skip"]) - len(served), "team_epa_states": states,
            "logged_predictions": len(entries), "reserve_mismatches": len(mismatched),
            "feature_changes_without_input_change": len(unexplained),
            "epa_changes_without_retrieval_or_clock_change": len(epa_unexplained),
            "snapshot_ids": sorted({r["snapshot_id"] for r in responses["d18_skip"]}),
            "model_sha256": sha256, "stratai": stratai_info, "problems": problems[:50], "passed": not problems}


def main(argv: list[str] | None = None) -> int:
    from scripts.phase5_records import write_once

    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    sub = parser.add_subparsers(dest="check", required=True)
    l3 = sub.add_parser("l3")
    l3.add_argument("--isolated-db", required=True)
    l4 = sub.add_parser("l4")
    for name in ("--snapshot", "--chain", "--registry"):
        l4.add_argument(name, type=Path, required=True)
    l4.add_argument("--win-prob-tag", required=True)
    l4.add_argument("--win-prob-sha256", required=True)
    args = parser.parse_args(argv)
    if args.check == "l3":
        result, name = run_l3(args.isolated_db), "p5_m2_l3_outage_drill.json"
    else:
        result, name = run_l4(args.snapshot, args.chain, args.registry, args.win_prob_tag,
                              args.win_prob_sha256), L4_RECORD
        result["supersedes"] = L4_SUPERSEDES
    path = write_once(name, result)
    print(json.dumps({k: v for k, v in result.items() if k in ("problems", "passed", "timeline", "served",
                                                                "refused", "team_epa_states")}, indent=1, default=str))
    print(f"-> {path}")
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    sys.exit(main())
