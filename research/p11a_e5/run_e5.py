"""P11A E5: the end-to-end comparison, DESCRIPTIVE AND OBSERVATIONAL ONLY (spec §20, E5).

E5 never supports a claim that the plan would have selected superior alliances, or that following it causes better
outcomes. Regret under AS-1 is disagreement with AS-1's own valuation, not evidence about real outcomes. The
association with playoff results is observational: selection effects (stronger captains pick earlier, from better
pools) and confounding (seed, captain strength, bracket, opponents) are not removed.

    python -m research.p11a_e5.run_e5 --protocol research/p11a_e5/PROTOCOL.json --run R1 [--output PATH]

**Refusals, before any data is read:**
- The protocol is not registered. Registration needs:
  - `status: registered`;
  - a write-once decision record in `.agent/phase11/decisions/` naming the protocol file's sha256;
  - the human decisions it lists.
  A draft is refused, so no result can be seen before the criteria are fixed (spec §20, pre-registration).
- The run is longer than 45 minutes, or names a season outside 2024–2026. 2027 is the protected holdout and is
  never read.
- The database is not an isolated stratai_test copy (`scripts.phase6_common.isolated_database`, read-only).

**Per event in the run's frozen sample:**
1. The setup (`workspaces.live_draft.build_setup`), TBA's final alliances and outcomes (`data.alliances`), and the
   snapshot at the protocol's `as_of` rule (`ml.alliance.snapshot.build_event_snapshot`, read-only).
   - The snapshot carries the scoring configuration only if it is registered and approved for the season.
   - Without it, the event is `not_evaluable: scoring_config_not_approved`. That is the state of every season today.
2. The actual selection is replayed (`scripts.phase11_replay.reconstruct`; declines' timing is not recorded by TBA).
   Before each actual pick, for the picking captain:
   - the served plan (`build_plan`): its top choice and value V;
   - the AS-1 value of the actual pick (the same V);
   - regret = V(plan top) − V(actual), with the actual pick's rank in the plan;
   - the same values for each baseline's top available choice: individual EPA ranking, the P5-M4 ordering and
     P11-FB1.
3. Each alliance's realized playoff result (TBA's status: elimination level, wins and losses), as a **label**, never
   a feature.

**Summary** (`summarise`): per stage, mean regret and agreement rates with event-cluster bootstrap 95% intervals,
the baselines' differences, and the regret/playoff association (Spearman, event bootstrap), each labelled
observational.

The core (`evaluate_event`, `summarise`) is pure and is tested on synthetic data (tests/test_p11a_e5.py). The database
part is UNVERIFIED on the build machine (no PostgreSQL).
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import time
from collections.abc import Mapping, Sequence
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
DECISIONS = ROOT / ".agent" / "phase11" / "decisions"
ALLOWED_SEASONS = (2024, 2025, 2026)
MAX_MINUTES = 45
STATEMENT = ("E5 is descriptive and observational. It does not show that the plan selects superior alliances or "
             "that following it causes better playoff outcomes. Regret is measured under AS-1's own valuation.")


class E5Refused(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


# --- protocol -------------------------------------------------------------------------------------------------------


def load_registered_protocol(path: Path, decisions: Path = DECISIONS) -> dict[str, Any]:
    """The protocol, only if registered: status `registered`, and a decision record naming its exact sha256."""
    raw = path.read_bytes()
    protocol = json.loads(raw)
    sha = hashlib.sha256(raw).hexdigest()
    if protocol.get("status") != "registered":
        raise E5Refused("protocol_not_registered", f"{path.name} is {protocol.get('status')!r}; register it first")
    records = [p for p in decisions.glob("P11A_E5_REGISTRATION_*.md") if sha in p.read_text(encoding="utf-8")]
    if not records:
        raise E5Refused("protocol_not_registered", f"no decision record names this protocol's sha256 {sha[:12]}…")
    open_decisions = [d for d in protocol.get("decisions_required", []) if not d.get("decided")]
    if open_decisions:
        raise E5Refused("protocol_not_registered", f"undecided: {[d['id'] for d in open_decisions]}")
    return {**protocol, "sha256": sha, "registration_record": records[0].name}


def check_run(protocol: Mapping[str, Any], run_id: str) -> dict[str, Any]:
    run = next((r for r in protocol.get("runs", []) if r["id"] == run_id), None)
    if run is None:
        raise E5Refused("unknown_run", f"the protocol has no run {run_id!r}")
    if not 0 < float(run["budget_minutes"]) <= MAX_MINUTES:
        raise E5Refused("budget", f"run {run_id} budget must be in (0, {MAX_MINUTES}] minutes")
    events = list(run["events"])
    bad = [e for e in events if int(e[:4]) not in ALLOWED_SEASONS]
    if bad:
        raise E5Refused("holdout", f"events outside 2024-2026 (2027 is the protected holdout): {bad}")
    return {**run, "events": events}


# --- the core (pure) --------------------------------------------------------------------------------------------------


def _values(model: Any, members: Sequence[int], candidates: Sequence[int]) -> dict[int, float]:
    """AS-1 value of picking each candidate now: with one member, the best value over every second robot (as the
    plan's first-pick V1); otherwise the best three-robot lineup of members + candidate."""
    from itertools import combinations

    out: dict[int, float] = {}
    if len(members) == 1:
        me = model.index[members[0]]
        pairs = list(combinations(candidates, 2))
        if not pairs:
            return out
        values = model.value(np.array([[me, model.index[c], model.index[d]] for c, d in pairs]))
        for (c, d), v in zip(pairs, values):
            out[c] = max(out.get(c, -np.inf), float(v))
            out[d] = max(out.get(d, -np.inf), float(v))
        return out
    for c in candidates:
        out[c] = model.best_lineup_value([*members, c])[0]
    return out


def evaluate_event(snapshot: Any, setup: Any, alliances: Sequence[Any], outcomes: Mapping[int, Any],
                   orderings: Mapping[str, Sequence[int]], *, scoring_dir: Path | None = None) -> dict[str, Any]:
    """E5 for one event (see the module docstring). Orderings: baseline name -> team order (best first)."""
    from ml.alliance.estimator import EstimatorPolicy
    from ml.alliance.planner import PlanWithheld, _model, build_plan
    from scripts.phase11_replay import OVERRIDE, reconstruct
    from workspaces import draft_log as dl
    from workspaces.alliance_plan import position_from_view
    from workspaces.draft_recommendations import fallback_lists, selectable_teams

    try:
        model = _model(snapshot, EstimatorPolicy(), scoring_dir)
    except PlanWithheld as exc:
        return {"event_key": snapshot.event_key, "evaluable": False, "reason": f"{exc.code}: {exc.message}"}
    actions, notes = reconstruct(alliances, setup.rules)
    entries = [dl.LogEntry("configure", 1, dl.CONFIGURE, setup.to_json(), author_label="e5")]
    picks: list[dict[str, Any]] = []
    known = set(model.index)
    for number, (type_, seed, team) in enumerate(actions, start=2):
        view = dl.replay(entries)
        if type_ == dl.PICK and view.alliances[seed - 1]:
            members = list(view.alliances[seed - 1])
            captain = members[0]
            selectable, _ = selectable_teams(view, seed, captain)
            candidates = [t for t in selectable if t in known]
            row: dict[str, Any] = {"seed": seed, "captain": captain, "actual": team,
                                   "stage": "first_pick" if len(members) == 1 else "later_pick"}
            try:
                plan = build_plan(snapshot, position_from_view(view, captain), scoring_dir=scoring_dir)
            except PlanWithheld as exc:
                row["evaluable"], row["reason"] = False, f"{exc.code}: {exc.message}"
                picks.append(row)
            else:
                values = _values(model, members, candidates)
                top = plan["cards"][0]["team_number"] if plan.get("cards") else None
                order = sorted(values, key=lambda t: (-values[t], t))
                row.update({"plan_top": top, "v_plan_top": None if top is None else values.get(top)})
                if team in values and top is not None:
                    row.update({"evaluable": True, "v_actual": values[team], "regret": values[top] - values[team],
                                "actual_rank": order.index(team) + 1, "agree_top1": team == top,
                                "agree_top3": team in order[:3]})
                else:
                    row.update({"evaluable": False, "reason": "actual pick not selectable or without an estimate"})
                baselines = {}
                for name, ordering in orderings.items():
                    if name == "p11_fb1":
                        ranked, _, _ = fallback_lists(view, seed, captain, ordering)
                        choice = next((t for t in ranked if t in values), None)
                    else:
                        choice = next((t for t in ordering if t in values), None)
                    baselines[name] = None if choice is None or top is None else {
                        "choice": choice, "v": values[choice], "v_plan_minus_baseline": values[top] - values[choice],
                        "agrees_with_actual": choice == team}
                row["baselines"] = baselines
                picks.append(row)
        entry = dl.LogEntry(f"e{number}", number, type_, {"seed": seed, "team": team}, author_label="e5")
        _, violation = dl.check_append(entries, entry)
        if violation is not None:
            entry = dl.LogEntry(entry.action_id, number, type_, entry.payload, OVERRIDE, "e5")
            if dl.check_append(entries, entry)[1] is not None:
                notes.append(f"action {number} ({type_} {seed} {team}) cannot apply; the replay stopped")
                break
        entries.append(entry)
    alliance_rows = []
    for a in alliances:
        if a.seed is None:
            continue
        mine = [p for p in picks if p["seed"] == a.seed and p.get("evaluable")]
        out = outcomes.get(a.seed)
        games = None if out is None or out.wins is None else (out.wins or 0) + (out.losses or 0) + (out.ties or 0)
        alliance_rows.append({
            "seed": a.seed, "picks": list(a.picks),
            "mean_regret": None if not mine else float(np.mean([p["regret"] for p in mine])),
            "label_playoff_level": None if out is None else out.level,
            "label_win_share": None if not games else (out.wins or 0) / games})
    return {"event_key": snapshot.event_key, "evaluable": True, "snapshot_id": snapshot.snapshot_id(),
            "as_of": snapshot.as_of, "notes": notes, "picks": picks, "alliances": alliance_rows}


def _bootstrap(by_event: Mapping[str, list[float]], stat, seed: int, n: int) -> list[float] | None:
    keys = [k for k, v in by_event.items() if v]
    if len(keys) < 2:
        return None
    rng = np.random.default_rng(seed)
    draws = []
    for _ in range(n):
        sample = [x for k in rng.choice(keys, size=len(keys), replace=True) for x in by_event[k]]
        value = stat(sample)
        if value is not None and np.isfinite(value):
            draws.append(value)
    return None if len(draws) < n // 2 else [float(np.percentile(draws, 2.5)), float(np.percentile(draws, 97.5))]


def _spearman(pairs: Sequence[tuple[float, float]]) -> float | None:
    if len(pairs) < 4:
        return None
    from scipy.stats import spearmanr

    x, y = zip(*pairs)
    if len(set(x)) < 2 or len(set(y)) < 2:
        return None
    return float(spearmanr(x, y).statistic)


def summarise(events: Sequence[Mapping[str, Any]], *, seed: int = 20261106, n_boot: int = 2000) -> dict[str, Any]:
    """Point estimates with event-cluster bootstrap 95% intervals. Every quantity is model-internal (regret) or
    observational (association); see STATEMENT."""
    usable = [e for e in events if e.get("evaluable")]
    out: dict[str, Any] = {"statement": STATEMENT, "events": len(events), "evaluable_events": len(usable),
                           "not_evaluable": {e["event_key"]: e.get("reason") for e in events if not e.get("evaluable")}}
    for stage in ("first_pick", "later_pick"):
        rows = {e["event_key"]: [p for p in e["picks"] if p.get("evaluable") and p["stage"] == stage] for e in usable}
        n = sum(len(v) for v in rows.values())
        block: dict[str, Any] = {"picks": n}
        if n:
            for key, field in (("mean_regret", "regret"), ("agree_top1", "agree_top1"), ("agree_top3", "agree_top3")):
                vals = {k: [float(p[field]) for p in v] for k, v in rows.items()}
                block[key] = float(np.mean([x for v in vals.values() for x in v]))
                block[key + "_ci95"] = _bootstrap(vals, lambda s: float(np.mean(s)) if s else None, seed, n_boot)
            names = sorted({b for v in rows.values() for p in v for b in p["baselines"]})
            for name in names:
                diffs = {k: [p["baselines"][name]["v_plan_minus_baseline"] for p in v if p["baselines"].get(name)]
                         for k, v in rows.items()}
                agree = {k: [float(p["baselines"][name]["agrees_with_actual"]) for p in v
                             if p["baselines"].get(name)] for k, v in rows.items()}
                flat = [x for v in diffs.values() for x in v]
                block[f"baseline_{name}"] = {
                    "n": len(flat),
                    "mean_v_plan_minus_baseline": float(np.mean(flat)) if flat else None,
                    "ci95": _bootstrap(diffs, lambda s: float(np.mean(s)) if s else None, seed, n_boot),
                    "agrees_with_actual": float(np.mean([x for v in agree.values() for x in v])) if flat else None,
                    "note": "difference of AS-1 values (model-internal); not a real-outcome comparison"}
        out[stage] = block
    pairs = {e["event_key"]: [(a["mean_regret"], a["label_win_share"]) for a in e["alliances"]
                              if a["mean_regret"] is not None and a["label_win_share"] is not None] for e in usable}
    flat_pairs = [p for v in pairs.values() for p in v]
    out["association_regret_vs_playoff_win_share"] = {
        "kind": "observational", "alliances": len(flat_pairs), "spearman": _spearman(flat_pairs),
        "ci95": _bootstrap(pairs, _spearman, seed, n_boot),
        "note": "confounded by seed, captain strength, pool, bracket and opponents; not causal"}
    return out


# --- the database run (UNVERIFIED here: no PostgreSQL) ---------------------------------------------------------------


def stratum(event_type: str | None, teams: int, median_teams: float) -> str:
    """The sampling stratum: championship divisions apart, other events split at the season's median team count."""
    if event_type and "division" in event_type.lower():
        return "championship_division"
    return "large" if teams > median_teams else "small"


def draw_sample(database: Any, seasons: Sequence[int], per_stratum: int, seed: int) -> dict[str, list[str]]:
    """A seeded stratified sample (season x stratum) of events with seeded alliances. Reads event metadata, alliance
    presence and rosters only: no score, ranking or outcome, so it can be drawn before registration."""
    import random

    from data.alliances import read_event_alliances

    if any(s not in ALLOWED_SEASONS for s in seasons):
        raise E5Refused("holdout", "only 2024-2026 may be sampled (2027 is the protected holdout)")
    rng = random.Random(seed)
    out: dict[str, list[str]] = {}
    for season in seasons:
        alliances = read_event_alliances(database, season)
        with database.cursor() as c:
            c.execute("SELECT e.event_key, e.event_type, count(DISTINCT mt.team_number) FROM events e "
                      "JOIN matches m ON m.event_key = e.event_key AND m.competition_level = 'qualification' "
                      "JOIN match_teams mt ON mt.match_key = m.match_key WHERE e.season = %s "
                      "GROUP BY e.event_key, e.event_type", (season,))
            rows = [r for r in c.fetchall() if len([a for a in alliances.get(r[0], []) if a.seed]) >= 2]
        median = float(np.median([r[2] for r in rows])) if rows else 0.0
        strata: dict[str, list[str]] = {}
        for key, kind, teams in sorted(rows):
            strata.setdefault(stratum(kind, teams, median), []).append(key)
        for name in sorted(strata):
            out[f"{season}/{name}"] = sorted(rng.sample(strata[name], min(per_stratum, len(strata[name]))))
    return out




def _as_of(database: Any, event_key: str, rule: str) -> datetime:
    from ml.playoffs.service import event_selection_moment

    if rule != "selection_moment":
        raise E5Refused("as_of_rule", f"unknown as_of rule {rule!r}")
    return event_selection_moment(database, event_key)


def _orderings(database: Any, event_key: str, at: datetime, epa_source: Any, ranking: Any) -> dict[str, list[int]]:
    from ml.views.event_analysis import analyze_event

    out: dict[str, list[int]] = {}
    if epa_source is None:
        return out
    raw = analyze_event(database, event_key, at, epa_provider=epa_source.provider, m5v2_predict_rating=None)
    out["individual_epa"] = [o.team_number for o in raw.ordering]
    if ranking is not None:
        p5 = analyze_event(database, event_key, at, epa_provider=epa_source.provider,
                           m5v2_predict_rating=ranking.model.predict_rating)
        out["p5_m4"] = [o.team_number for o in p5.ordering]
    else:
        out["p5_m4"] = out["individual_epa"]  # no pinned ranking model: P5-M4 serves raw EPA (recorded)
    out["p11_fb1"] = out["p5_m4"]  # P11-FB1 = the P5-M4 ordering under the record's exclusions, per turn
    return out


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--protocol", type=Path)
    parser.add_argument("--run")
    parser.add_argument("--output", type=Path)
    parser.add_argument("--draw-sample", action="store_true", help="print a stratified sample (no outcomes read)")
    parser.add_argument("--per-stratum", type=int, default=2)
    parser.add_argument("--seed", type=int, default=20261106)
    args = parser.parse_args(argv)
    if args.draw_sample:
        from scripts.phase6_common import isolated_database

        print(json.dumps(draw_sample(isolated_database(), ALLOWED_SEASONS, args.per_stratum, args.seed), indent=1))
        return 0
    if args.protocol is None or args.run is None:
        parser.error("--protocol and --run are required (or --draw-sample)")
    try:
        protocol = load_registered_protocol(args.protocol)
        run = check_run(protocol, args.run)
    except E5Refused as exc:
        print(json.dumps({"status": "refused", "code": exc.code, "message": str(exc)}))
        return 3

    from api.ml_loading import load_epa_source, load_pinned_ranking_model
    from data.alliances import read_event_alliance_outcomes, read_event_alliances
    from data.config import Settings
    from ml.alliance.snapshot import build_event_snapshot
    from scripts.phase6_common import isolated_database
    from scripts.phase11_replay import _setup

    database = isolated_database()  # refuses anything but an isolated stratai_test copy; read-only
    settings = Settings()
    epa_source, ranking = load_epa_source(settings, database), load_pinned_ranking_model(settings)
    deadline = time.monotonic() + float(run["budget_minutes"]) * 60
    results, partial = [], False
    for event_key in run["events"]:
        if time.monotonic() > deadline:
            partial = True
            break
        season = int(event_key[:4])
        try:
            as_of = _as_of(database, event_key, protocol["as_of_rule"])
            snapshot = build_event_snapshot(database, event_key, as_of)
            alliances = read_event_alliances(database, season).get(event_key, [])
            outcomes = {o.seed: o for o in read_event_alliance_outcomes(database, season).get(event_key, [])}
            results.append(evaluate_event(snapshot, _setup(database, event_key), alliances, outcomes,
                                          _orderings(database, event_key, as_of, epa_source, ranking)))
        except Exception as exc:  # a refusal is a result, not a crash
            results.append({"event_key": event_key, "evaluable": False,
                            "reason": f"{type(exc).__name__}: {getattr(exc, 'message', exc)}"})
    record = {"statement": STATEMENT, "kind": "p11a_e5", "protocol_sha256": protocol["sha256"],
              "registration_record": protocol["registration_record"], "run": run["id"],
              "run_at": datetime.now(timezone.utc).isoformat(), "partial": partial,
              "epa_source_loaded": epa_source is not None, "ranking_model_loaded": ranking is not None,
              "summary": summarise(results, seed=int(protocol["bootstrap_seed"]),
                                   n_boot=int(protocol["bootstrap_draws"])),
              "events": results}
    output = args.output or ROOT / ".agent" / "phase11" / "results" / f"p11a_e5_{run['id']}.json"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(record, indent=1, default=str) + "\n", encoding="utf-8")
    print(json.dumps({"output": str(output), "partial": partial,
                      "evaluable_events": record["summary"]["evaluable_events"]}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
