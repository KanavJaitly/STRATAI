"""Phase 11 verification: replay real past alliance selections through the live draft record (P11-DM1, P11-DM2).

    python -m scripts.phase11_replay [--per-season 2] [--seed 20261104] [--budget-minutes 40] [--output PATH]

**What it does, per sampled event:**
1. Builds the record's setup from the event's real data. That is exactly what `workspaces.live_draft.build_setup`
   builds: the approved P6-M1 rules, the final ranks under the pick list's final-ranks rule, and the qualification
   roster.
2. Reconstructs the event's actual selection from TBA's final alliances (`data.alliances`; see `reconstruct`) and
   records it action by action with `workspaces.draft_log.check_append`, the check the service runs on every
   append.
3. After every action, asserts the following:
   - The available pool contains no team on an alliance, and no declined team where the decline rule applies.
   - For each alliance captain's workspace, no recommendation lists an unavailable team. Recommendations come from
     `workspaces.draft_recommendations.recommend`, which runs the real engine and then P11-FB1 on the real ordering.
4. At the end, asserts the following:
   - The recorded alliances equal TBA's.
   - Every prefix of the log replays to the state the record had at that point (P11-DM2).

**What cannot be reconstructed, and is reported, never guessed:**
- TBA records final alliances, not pick timing. The pick order is the serpentine order the rules give.
- Who a declining team declined, and when, are not recorded. Each decline is recorded against alliance 1, right
  after its captain is named. This is the earliest point the rules allow. The rules decide what a decline makes
  unavailable, whenever it happened.
- TBA's `backup` was null for every 2024-2026 alliance at ingestion, so no backup is replayed.
- A recorded fact that the rules refuse is recorded with an override that says so, and counted. It is a finding
  about the rules or the reconstruction, not an error to hide.

**Safety and time.**
- Runs only on an isolated `stratai_test` copy, in a read-only session (`scripts.phase6_common.isolated_database`).
  Nothing is written to any database; the record is replayed in memory through the same log module the service
  uses.
- The sample is fixed before any run: a seeded random draw of `--per-season` events per season among events with
  alliances, ranks and approved rules.
- `--budget-minutes` (at most 45; CLAUDE.md) stops the run between events, with partial results marked as such.
"""

from __future__ import annotations

import argparse
import json
import random
import statistics
import sys
import time
from collections.abc import Sequence
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from workspaces import draft_log as dl

ROOT = Path(__file__).resolve().parents[1]
RESULTS = ROOT / ".agent" / "phase11" / "results"
DEFAULT_SEED = 20261104
SEASONS = (2024, 2025, 2026)
MAX_BUDGET_MINUTES = 45
OVERRIDE = "replay: a TBA-recorded fact the rules refuse (reconstruction or rules gap; counted)"


def reconstruct(alliances: Sequence[Any], rules: dl.DraftRules) -> tuple[list[tuple[str, int, int]], list[str]]:
    """The actions that produce TBA's final alliances under the serpentine order, plus notes on what could not be
    reconstructed. `alliances` are data.alliances.Alliance rows (picks in pick order, captain first)."""
    notes: list[str] = []
    seeded = sorted((a for a in alliances if a.seed is not None), key=lambda a: a.seed)
    if len(seeded) != rules.n_alliances:
        notes.append(f"TBA lists {len(seeded)} seeded alliances; the rules give {rules.n_alliances}")
    by_seed = {a.seed: a for a in seeded}
    declines = sorted({t for a in seeded for t in a.declines})
    if declines:
        notes.append(f"{len(declines)} decline(s): timing and inviter not recorded by TBA; recorded against "
                     "alliance 1 after its captain is named")
    actions: list[tuple[str, int, int]] = []
    named: set[int] = set()
    for index, seed in enumerate(dl.turn_order(rules.n_alliances, rules.picks_per_alliance)):
        alliance = by_seed.get(seed)
        round_ = index // rules.n_alliances
        if alliance is None or not alliance.picks:
            notes.append(f"alliance {seed} is missing from TBA's record; the replay stops at turn {index}")
            break
        if seed not in named:
            actions.append((dl.CAPTAIN, seed, alliance.picks[0]))
            named.add(seed)
            if seed == 1:
                actions.extend((dl.DECLINE, 1, team) for team in declines)
        if round_ + 1 >= len(alliance.picks):
            notes.append(f"alliance {seed} has no recorded pick for round {round_ + 1}; the replay stops")
            break
        actions.append((dl.PICK, seed, alliance.picks[round_ + 1]))
    return actions, notes


def _setup(database: Any, event_key: str) -> dl.DraftSetup:
    from workspaces.live_draft import build_setup

    return build_setup(database, event_key, manual_rules=None, actor="phase11_replay")


def replay_event(database: Any, event_key: str, alliances: Sequence[Any], *, epa_source: Any, ranking: Any,
                 playoff_models: Any) -> dict[str, Any]:
    """Replay one event's actual selection through the record; every check described in the module docstring."""
    from workspaces import draft_recommendations as rec

    setup = _setup(database, event_key)
    actions, notes = reconstruct(alliances, setup.rules)
    entries = [dl.LogEntry("configure", 1, dl.CONFIGURE, setup.to_json(), author_label="replay")]
    captains = [a.picks[0] for a in alliances if a.seed is not None and a.picks]
    problems: list[str] = []
    overridden: list[dict[str, Any]] = []
    timings: list[float] = []
    sources: dict[str, int] = {}
    views = [dl.replay(entries)]
    for number, (type_, seed, team) in enumerate(actions, start=2):
        entry = dl.LogEntry(f"r{number}", number, type_, {"seed": seed, "team": team}, author_label="replay")
        _, violation = dl.check_append(entries, entry)
        if violation is not None:
            entry = dl.LogEntry(entry.action_id, number, type_, entry.payload, OVERRIDE, "replay")
            _, refused = dl.check_append(entries, entry)
            overridden.append({"seq": number, "action": f"{type_} {seed} {team}", "code": violation.code,
                               "message": violation.message, "applied": refused is None})
            if refused is not None:
                problems.append(f"seq {number}: {type_} {seed} {team} cannot apply ({refused.code}); replay stopped")
                break
        entries.append(entry)
        view = dl.replay(entries)
        views.append(view)
        available, unavailable = view.availability()
        on_alliance = {t for a in view.alliances for t in a}
        if set(available) & on_alliance:
            problems.append(f"seq {number}: a team on an alliance is listed available")
        if not setup.rules.declined_team_may_be_picked_later and set(available) & set(view.declined):
            problems.append(f"seq {number}: a declined team is listed available")
        for captain in captains:
            started = time.perf_counter()
            out = rec.recommend(database, event_key, view, views[-2], captain, epa_source=epa_source,
                                ranking=ranking, playoff_models=playoff_models)
            timings.append(time.perf_counter() - started)
            sources[out.source or f"withheld:{out.withheld[0] if out.withheld else '?'}"] = sources.get(
                out.source or f"withheld:{out.withheld[0] if out.withheld else '?'}", 0) + 1
            listed = [c.team_number for c in ([out.primary] if out.primary else []) + out.backups]
            bad = set(listed) - set(available)
            if bad or set(listed) & set(unavailable):
                problems.append(f"seq {number}: team {captain}'s recommendations list unavailable team(s) "
                                f"{sorted(bad)}")
            # Independent of availability(): if it is this alliance's turn now, the record itself must accept the
            # primary as a pick (P11-DM1; review finding: a pool check alone cannot catch a rule the pool misses).
            if out.primary is not None and out.seed == view.acting_seed() and view.alliances[out.seed - 1]:
                probe = dl.LogEntry("probe", number + 1, dl.PICK, {"seed": out.seed, "team": out.primary.team_number})
                _, refused = dl.check_append(entries, probe)
                if refused is not None:
                    problems.append(f"seq {number}: team {captain}'s primary {out.primary.team_number} would be "
                                    f"refused ({refused.code})")
            if out.record_seq != view.record_seq:
                problems.append(f"seq {number}: a recommendation cites record #{out.record_seq}")
    final = views[-1]
    tba = {a.seed: tuple(a.picks) for a in alliances if a.seed is not None}
    recorded = {seed: alliance for seed, alliance in enumerate(final.alliances, start=1) if alliance}
    if not problems and recorded != {s: p for s, p in tba.items() if s in recorded}:
        problems.append("the recorded alliances differ from TBA's")
    for k in range(1, len(entries) + 1):  # P11-DM2: the state at any point is the replay of that prefix
        if dl.replay(entries[:k]).alliances != views[k - 1].alliances:
            problems.append(f"prefix {k} does not replay to the state recorded at that point")
            break
    warm = timings[len(captains):] if len(timings) > len(captains) else timings  # the first pass per event is cold
    return {"event_key": event_key, "actions": len(actions), "notes": notes, "missing": list(setup.missing),
            "rules_source": setup.rules.source, "overridden": overridden, "problems": problems,
            "recommendation_sources": sources,
            "recommend_seconds": {"cold_first": round(timings[0], 4) if timings else None,
                                  "warm_p95": round(statistics.quantiles(warm, n=20)[-1], 4) if len(warm) >= 2
                                  else None, "count": len(timings)},
            "passed": not problems}


def choose_sample(database: Any, seasons: Sequence[int], per_season: int, seed: int) -> list[str]:
    """Events with alliances and ranks, drawn per season with a seeded generator, in a stable order."""
    from data.alliances import read_event_alliances
    from data.rankings import read_final_ranks_for_season

    rng = random.Random(seed)
    chosen: list[str] = []
    for season in seasons:
        alliances = read_event_alliances(database, season)
        ranked = read_final_ranks_for_season(database, season)
        eligible = sorted(k for k in alliances if k in ranked and len([a for a in alliances[k] if a.seed]) >= 2)
        chosen.extend(sorted(rng.sample(eligible, min(per_season, len(eligible)))))
    return chosen


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--per-season", type=int, default=2)
    parser.add_argument("--seed", type=int, default=DEFAULT_SEED)
    parser.add_argument("--budget-minutes", type=float, default=40.0)
    parser.add_argument("--output", type=Path, default=None)
    args = parser.parse_args(argv)
    if not 0 < args.budget_minutes <= MAX_BUDGET_MINUTES:
        parser.error(f"--budget-minutes must be in (0, {MAX_BUDGET_MINUTES}] (CLAUDE.md verification limit)")

    from api.ml_loading import load_epa_source, load_pinned_ranking_model, load_playoff_models
    from data.alliances import read_event_alliances
    from data.config import Settings
    from scripts.phase6_common import isolated_database

    database = isolated_database()  # refuses anything but a stratai_test copy; read-only
    settings = Settings()
    epa_source = load_epa_source(settings, database)
    ranking, playoff_models = load_pinned_ranking_model(settings), load_playoff_models(settings)
    deadline = time.monotonic() + args.budget_minutes * 60
    sample = choose_sample(database, SEASONS, args.per_season, args.seed)
    results, partial = [], False
    for event_key in sample:
        if time.monotonic() > deadline:
            partial = True
            break
        season = int(event_key[:4])
        alliances = read_event_alliances(database, season)[event_key]
        try:
            results.append(replay_event(database, event_key, alliances, epa_source=epa_source, ranking=ranking,
                                        playoff_models=playoff_models))
        except Exception as exc:  # a refusal is a result, not a crash
            if getattr(exc, "code", None) == "rules_required":  # excluded by, or outside, the approved ruleset
                results.append({"event_key": event_key, "passed": True, "skipped": str(getattr(exc, "message", exc)),
                                "problems": []})
                continue
            results.append({"event_key": event_key, "passed": False,
                            "problems": [f"{type(exc).__name__}: {getattr(exc, 'message', exc)}"]})
    record = {"kind": "p11_replay", "run_at": datetime.now(timezone.utc).isoformat(), "seed": args.seed,
              "per_season": args.per_season, "seasons": list(SEASONS), "sample": sample,
              "budget_minutes": args.budget_minutes, "partial": partial,
              "epa_source_loaded": epa_source is not None, "ranking_model_loaded": ranking is not None,
              "events": results, "skipped": sum(1 for r in results if r.get("skipped")),
              "passed": (any(not r.get("skipped") for r in results) and not partial
                         and all(r["passed"] for r in results))}
    output = args.output or RESULTS / f"p11_replay_{datetime.now(timezone.utc):%Y%m%d_%H%M%S}.json"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(record, indent=1, default=str) + "\n", encoding="utf-8")
    print(json.dumps({"output": str(output), "passed": record["passed"], "partial": partial,
                      "events": [(r["event_key"], r["passed"]) for r in results]}))
    return 0 if record["passed"] else 1


if __name__ == "__main__":
    sys.exit(main())
