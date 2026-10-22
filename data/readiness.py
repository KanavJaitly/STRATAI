"""Season readiness: data coverage, human inputs, the feature dependency map and the Phase 6 task queue (2026-10-11).

Read-only. It reads the canonical tables, the human-input tables, the manual-processing ledger and the Phase 6
record files, and reports what exists. **It never runs, approves or authorizes anything.**

- `data_coverage`: what real season-specific data exists, with freshness.
- `features`: each user-facing feature, what it consumes, and whether it can work for the season, with the reason.
- `phase6_tasks`: the 2027 human inputs and authorizations of `.agent/phase6/P6_2027_AUTHORIZATION_REQUESTS.md`,
  each derived from the records that actually exist. A manual upload never changes any of them: only the named
  person's file, or the run's own write-once record, does.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from database.connection import Database

SUPPORTED_SEASONS = (2023, 2024, 2025, 2026, 2027)  # the product's seasons (Kanav, 2026-10-11)
HOLDOUT = 2027  # Phase 6's untouched acceptance season


def _one(cursor, sql: str, params: tuple) -> Any:
    cursor.execute(sql, params)
    row = cursor.fetchone()
    return row[0] if row else None


def data_coverage(database: Database, season: int) -> dict[str, Any]:
    """Counts of the real canonical data for one season. Nothing is inferred or filled in."""
    from ml.features.score_breakdown import SUPPORTED_SEASONS as ADAPTER_SEASONS

    with database.cursor() as c:
        coverage = {
            "events": _one(c, "SELECT count(*) FROM events WHERE season = %s", (season,)),
            "matches": _one(c, "SELECT count(*) FROM matches WHERE season = %s", (season,)),
            "matches_played": _one(c, "SELECT count(*) FROM matches WHERE season = %s AND score_red IS NOT NULL "
                                      "AND score_blue IS NOT NULL", (season,)),
            "qualification_matches_played": _one(
                c, "SELECT count(*) FROM matches WHERE season = %s AND competition_level = 'qualification' "
                   "AND score_red IS NOT NULL", (season,)),
            "playoff_matches_played": _one(
                c, "SELECT count(*) FROM matches WHERE season = %s AND competition_level <> 'qualification' "
                   "AND score_red IS NOT NULL", (season,)),
            "teams": _one(c, "SELECT count(DISTINCT mt.team_number) FROM match_teams mt JOIN matches m USING "
                             "(match_key) WHERE m.season = %s", (season,)),
            "team_event_epa_rows": _one(c, "SELECT count(*) FROM team_event_stats WHERE season = %s", (season,)),
            "team_metrics_rows": _one(c, "SELECT count(*) FROM team_metrics WHERE season = %s", (season,)),
            "events_with_metrics": _one(c, "SELECT count(DISTINCT event_key) FROM team_metrics WHERE season = %s",
                                        (season,)),
            "scouting_observations": _one(c, "SELECT count(*) FROM scouting_observations WHERE event_key LIKE %s",
                                          (f"{season}%",)),
            "latest_update": _one(c, "SELECT max(last_updated) FROM matches WHERE season = %s", (season,)),
            "latest_match": _one(c, "SELECT max(scheduled_time) FROM matches WHERE season = %s", (season,)),
        }
    coverage["score_breakdown_adapter"] = season in ADAPTER_SEASONS
    coverage["has_data"] = bool(coverage["events"])
    return coverage


def human_inputs(database: Database, store_dir: Path, season: int) -> dict[str, Any]:
    """The season's manuals (with processing state), game spec (P5-M8) and season ruleset (P6-M1)."""
    from data import manual_processing as mp
    from data.human_inputs import list_manuals

    manuals = [{**{k: v for k, v in m.items() if k != "storage_path"},
                "processing": {k: v for k, v in mp.status(store_dir, m).items() if k in ("status", "report")}}
               for m in list_manuals(database, season)]
    with database.cursor() as c:
        c.execute("SELECT id, version, status, complete, created_by, reviewed_by FROM game_spec_versions WHERE "
                  "season = %s ORDER BY version DESC LIMIT 1", (season,))
        spec = c.fetchone()
        c.execute("SELECT id, version, status, ruleset_sha256, created_by, reviewed_by FROM season_rulesets WHERE "
                  "season = %s ORDER BY version DESC", (season,))
        rulesets = c.fetchall()
    approved = next((r for r in rulesets if r[2] == "approved"), None)
    latest = rulesets[0] if rulesets else None
    return {
        "manuals": manuals,
        "game_spec": None if spec is None else {"id": spec[0], "version": spec[1], "status": spec[2],
                                                "complete": spec[3], "created_by": spec[4], "reviewed_by": spec[5]},
        "ruleset": {"approved": None if approved is None else {"id": approved[0], "version": approved[1],
                                                               "sha256": approved[3], "reviewed_by": approved[5]},
                    "latest": None if latest is None else {"id": latest[0], "version": latest[1], "status": latest[2],
                                                           "created_by": latest[4]}},
    }


def features(season: int, coverage: dict[str, Any], inputs: dict[str, Any], serving: dict[str, bool]
             ) -> list[dict[str, Any]]:
    """Each user-facing feature, what it consumes, and whether it can work for this season (with the reasons).

    `serving` says which pinned models this API instance has loaded (`ranking_model`, `win_prob_model`). An EPA
    source is checked by the endpoint itself when called; its availability is reported, not assumed."""
    data = coverage["has_data"]
    played = bool(coverage["matches_played"])
    spec_ok = (inputs["game_spec"] or {}).get("status") == "approved"
    ruleset_ok = inputs["ruleset"]["approved"] is not None
    manual_done = any(m["processing"]["status"] == "succeeded" for m in inputs["manuals"])

    # What an available feature still cannot answer this season (2026-10-12): "available" means callable, not complete.
    in_event = [] if coverage["score_breakdown_adapter"] or not data else [
        f"no score-breakdown adapter for {season}: an answer that needs this event's played matches is refused "
        "(season_not_supported); a pre-event 'as of' still works"]
    no_epa = [] if coverage["team_event_epa_rows"] or not data else [
        f"no {season} team EPA is synced: an answer needing an EPA the source does not have is withheld or refused "
        "(epa_source_incomplete)"]

    def feature(key, name, consumes, ok, reasons, route=None, human=None, limits=()):
        return {"key": key, "name": name, "consumes": consumes, "available": bool(ok),
                "reasons": [] if ok else [r for r in reasons if r], "limitations": list(limits) if ok else [],
                "route": route, "requires_human": human}
    return [
        feature("event_browser", "Events, teams and matches", ["events", "matches", "match_teams"], data,
                [None if data else f"no {season} event data is synced"], "/explorer"),
        feature("team_event_epa", "Team EPA at an event (Statbotics)", ["team_event_stats"],
                coverage["team_event_epa_rows"], ["no team EPA rows are synced for this season"], "/explorer"),
        feature("team_metrics", "Team metrics (consistency, reliability; Phase 3)", ["team_metrics", "matches"],
                coverage["team_metrics_rows"], ["team metrics have not been computed for this season's events"],
                "/explorer"),
        feature("team_strength", "Team strength (EPA source)", ["EPA source", "team_event_stats"], data,
                [None if data else "no season data"], "/explorer", limits=in_event + no_epa),
        feature("event_analysis", "Event analysis and ranking (P5-M4..M6)", ["ranking model (pinned)", "EPA source"],
                data and serving.get("ranking_model"),
                [None if data else "no season data",
                 None if serving.get("ranking_model") else "no ranking model is pinned on this API instance"],
                "/explorer", limits=in_event + no_epa),
        feature("qualification_forecast", "Qualification forecast", ["win-probability model (pinned)", "EPA source"],
                data and serving.get("win_prob_model"),
                [None if data else "no season data",
                 None if serving.get("win_prob_model") else "no win-probability model is pinned on this API instance"],
                "/explorer", limits=in_event + no_epa),
        feature("match_win_probability", "Match win probability", ["win-probability model (pinned)", "EPA source"],
                played and serving.get("win_prob_model"),
                [None if played else "no played matches",
                 None if serving.get("win_prob_model") else "no win-probability model is pinned on this API instance"],
                "/explorer", limits=in_event + no_epa),
        feature("game_manual", "Game manual processing", ["uploaded manual"], manual_done,
                ["no manual has been uploaded and processed for this season"], "/manuals", "upload the official manual"),
        feature("game_analysis", "Game analysis and design recommendations (P5-M8/M9)", ["approved game spec"], spec_ok,
                ["no approved game spec: a person enters it from the manual and a reviewer approves it"], "/game",
                "enter and approve the game spec"),
        feature("season_ruleset", "Alliance-selection and playoff rules (P6-M1)", ["approved season ruleset"],
                ruleset_ok, ["no approved ruleset: a named, qualified reviewer must approve it"], "/rulesets",
                "enter and approve the ruleset"),
        feature("score_components", "Score components (P5-M7 adapters; used by the strategy model)",
                ["TBA score breakdowns", "a season adapter"], coverage["score_breakdown_adapter"] and played,
                [None if coverage["score_breakdown_adapter"] else
                 f"no score-breakdown adapter exists for {season}: it is written and verified against real {season} "
                 "match data (engineering, after matches exist)", None if played else "no played matches"]),
    ]


TASKS = (
    # (id, title, actor, kind, evidence (relative to .agent/phase6), depends_on, automatic, authorizes)
    ("R1", "Approve the 2027 season ruleset (P6-M1)", "named, qualified FRC reviewer", "approval",
     None, (), False, "nothing by itself; FINAL-1 and the C0 check read it"),
    ("R2", "Write the 2027 EPA-source config, then pin it (epa-pin-2027)", "Kanav", "authorization",
     "results/p6_px1b_epa_source_2027.json", ("data",), False, "the EPA source every 2027 run uses"),
    ("R3", "Run the 2027 ruleset reproduction check (C0, m1-2027) and commit it", "operator command",
     "preparation_check", "results/p6_m1_ruleset_check_2027.json", ("R1", "data"), True,
     "nothing: a check, not an acceptance run"),
    ("R4", "Authorize FINAL-1 (PX-1b's 2027 acceptance run)", "Kanav", "authorization",
     "decisions/p6_px1b_final1_authorization.json", ("R1", "R2", "R3"), False, "one FINAL-1 run"),
    ("R5", "Run FINAL-1 (gate2027)", "operator command", "acceptance_run", "results/p6_px1b_gate_2027.json",
     ("R4",), False, "nothing: its result needs R6"),
    ("R6", "Confirm the FINAL-1 result (after a pass only)", "Kanav", "confirmation",
     "decisions/p6_px1b_final1_confirmation.json", ("R5",), False, "PX-1b's acceptance"),
    ("R7", "Run PX-2b, then PX-4b", "operator command", "acceptance_run", "results/p6_px4b.json", ("R6",), False,
     "nothing by itself"),
    ("R8", "Adopt the M8b pre-run record", "Kanav", "approval", "decisions/p6_m8b_pre_run.json", (), False,
     "the M8b sample (no run)"),
    ("R9", "Run M8b (projected runtime must fit 45 minutes)", "operator command", "acceptance_run",
     "results/p6_m8b_dm1_run.json", ("R7", "R8"), False, "nothing: every miss needs R10"),
    ("R10", "Review every M8b miss", "Mr. Biery", "review", "decisions/p6_m8b_mentor_review.json", ("R9",), False,
     "P6-DM1's decision (m8b-review)"),
    ("M1", "Authorize and build the 2027 M10b frame (frame-2027), then commit it", "Kanav, then operator",
     "authorization", "results/p6_m10b_frame_2027.json", ("R2", "data"), False, "one frame build"),
    ("M2", "Authorize and run the M10b 2027 acceptance run", "Kanav, then operator", "acceptance_run",
     "results/p6_m10b_outcome_model.json", ("M1",), False, "one run; no serving change"),
    ("M3", "Confirm the M10b result (after a pass only)", "Kanav", "confirmation",
     "decisions/p6_m10b_confirmation.json", ("M2",), False, "one of the serving guard's three conditions"),
    ("M4", "Authorize and run the M10b parity rerun (P6-M13)", "Kanav, then operator", "acceptance_run",
     "results/p6_m13_parity_audit_m10b.json", ("M2",), False, "one of the serving guard's three conditions"),
)
PASS_KEYS = {"R5": "passed", "R7": "passed", "M2": "passed", "M4": "p6_dm2_met"}


def phase6_tasks(database: Database, phase6_dir: Path) -> list[dict[str, Any]]:
    """The 2027 human inputs and authorizations, each derived only from what exists."""
    from data.rulesets import approved_seasons

    with database.cursor() as c:
        data_2027 = _one(c, "SELECT count(*) FROM matches WHERE season = %s", (HOLDOUT,))
    ruleset_2027 = HOLDOUT in approved_seasons(database)
    done: dict[str, bool] = {"data": bool(data_2027)}
    tasks = []
    for task_id, title, actor, kind, evidence, depends, automatic, authorizes in TASKS:
        path = None if evidence is None else Path(phase6_dir) / evidence
        exists = ruleset_2027 if task_id == "R1" else bool(path and path.exists())
        failed = False
        if exists and task_id in PASS_KEYS:
            record = json.loads(path.read_text(encoding="utf-8"))
            failed = record.get(PASS_KEYS[task_id]) is not True
        done[task_id] = exists and not failed
        waiting = [d for d in depends if not done.get(d)]
        if exists:
            state = "failed" if failed else "done"
        elif "data" in waiting:
            state = "waiting_for_2027_data"
        elif waiting:
            state = "blocked"
        else:
            state = "ready_for_human" if not automatic else "ready_to_run"
        tasks.append({"id": task_id, "title": title, "actor": actor, "kind": kind, "status": state,
                      "evidence": evidence, "evidence_exists": exists, "depends_on": list(depends),
                      "waiting_on": waiting, "automatic": automatic, "authorizes": authorizes,
                      "never_by_manual_upload": True})
    return tasks


def season_readiness(database: Database, store_dir: Path, phase6_dir: Path, season: int,
                     serving: dict[str, bool]) -> dict[str, Any]:
    coverage = data_coverage(database, season)
    inputs = human_inputs(database, store_dir, season)
    report = {"season": season, "coverage": coverage, "human_inputs": inputs,
              "features": features(season, coverage, inputs, serving),
              "automation_boundary": {
                  "automatic": ["manual validation, hashing, text and page extraction, identity detection, section "
                                "and topic indexing, unverified suggestions, readiness reporting"],
                  "never_automatic": ["game spec approval (P5-M8)", "season ruleset approval (P6-M1)",
                                      "every Phase 6 authorization, acceptance run, confirmation and review",
                                      "model registration or serving changes"]}}
    if season == HOLDOUT:
        from scripts.phase6_done_means import dm1, dm2

        results = Path(phase6_dir) / "results"
        report["phase6"] = {"tasks": phase6_tasks(database, phase6_dir),
                            "done_means": [dm1(results), dm2(results)],
                            "status": "waiting for the 2027 manual, the 2027 ruleset and 2027 data; Phase 6 is "
                                      "not complete (P6-DM1 not met)"}
    return report
