"""P6-M13 / P6-DM2: run the odds-parity audit, as `.agent/phase6/decisions/P6_M13_AUDIT_PLAN.md` fixes it.

    python -m scripts.phase6_m13_parity_audit

- Runs on the real engine with the registered P6-M10 artifact, on real held-out 2026 contexts.
- Also runs on the 7 planted-defect engines.
- **P6-DM2 is met** only if every check passes on the real engine and every planted defect is caught.
- **Record:** write-once `.agent/phase6/results/p6_m13_parity_audit.json`.
- **Time budget:** a hard 45 minutes.
"""

from __future__ import annotations

import random
import sys
import time

from scripts.phase6_common import REGISTRY_DIR, git_blob, load_frame, read_record, write_once

PLAN = ".agent/phase6/decisions/P6_M13_AUDIT_PLAN.md"
SEED = 20261007
ORDINARY, FULL_SEARCH, PLANTED_CONTEXTS = 10, 2, 3
BUDGET_SECONDS = 45 * 60
RECORD = "p6_m13_parity_audit_rerun1.json"
SUPERSEDES = {"record": "p6_m13_parity_audit.json", "failure_record": ".agent/phase6/P6_M13_RUN1_FAILURE.md",
              "reason": "two objectively demonstrated defects fixed (order-free alliance sum; planted missing-data fixture coverage); same plan, contexts, seed and checks"}


def main() -> int:
    from ml.strategy.engine import StrategyEngine
    from ml.strategy.outcome import MatchContext, load_registered_strategy_model, missing_inputs
    from ml.strategy.parity_audit import PLANTED_DEFECTS, AuditContexts, run_audit
    from ml.strategy.representation import Strategy

    started = time.time()
    fit = read_record("p6_m10_fit.json")
    model = load_registered_strategy_model(REGISTRY_DIR, expected_sha256=fit["registry"]["model_sha256"])
    rows, frame_hash = load_frame()
    population = sorted((r for r in rows if r.season == 2026 and r.comp_level == "qualification"
                         and len(r.red_teams) == 3 and len(r.blue_teams) == 3
                         and all(t.epa_total_present for t in (*r.red_teams, *r.blue_teams))),
                        key=lambda r: r.match_key)

    def context(row):
        return MatchContext(tuple(row.red_teams), tuple(row.blue_teams))

    complete = [r for r in population if not missing_inputs(context(r))]
    ordinary_rows = random.Random(SEED).sample(complete, ORDINARY)
    missing_row = next(r for r in population if missing_inputs(context(r)))
    low = None
    for row in complete:
        e = model.evaluate(context(row), Strategy.baseline([t.team_number for t in row.red_teams]),
                           Strategy.baseline([t.team_number for t in row.blue_teams]))
        if e.p_red < 0.05 or e.p_blue < 0.05:
            low = (context(row), "red" if e.p_red < 0.05 else "blue", row.match_key)
            break
    contexts = AuditContexts([context(r) for r in ordinary_rows], context(missing_row), (low[0], low[1]),
                             full_search=[context(r) for r in ordinary_rows[:FULL_SEARCH]])

    real = run_audit(StrategyEngine(model), contexts)
    planted_contexts = AuditContexts(contexts.ordinary[:PLANTED_CONTEXTS], contexts.missing_input, contexts.low_odds,
                                     full_search=contexts.full_search[:1])
    planted, over_budget = {}, False
    for name, (factory, target) in PLANTED_DEFECTS.items():
        if time.time() - started > BUDGET_SECONDS:
            over_budget = True
            planted[name] = {"run": False, "caught": False, "target_check": target}
            continue
        results = run_audit(factory(model), planted_contexts)
        failed = [r.name for r in results if not r.passed]
        planted[name] = {"run": True, "caught": bool(failed), "target_check": target, "target_caught": target in failed,
                         "failed_checks": failed}

    real_passed = all(r.passed for r in real)
    all_caught = all(p.get("target_caught") for p in planted.values())
    record = {
        "milestone": "P6-M13", "done_means": "P6-DM2", "supersedes": SUPERSEDES, "plan": PLAN, "plan_blob": git_blob(PLAN),
        "frame_content_hash": frame_hash,
        "model": {"version_tag": model.version_tag, "model_sha256": model.artifact_sha256,
                  "served_baseline_status": list(model.baseline_status)},
        "contexts": {"seed": SEED, "ordinary": [r.match_key for r in ordinary_rows],
                     "full_search": [r.match_key for r in ordinary_rows[:FULL_SEARCH]],
                     "missing_input": missing_row.match_key, "low_odds": {"match_key": low[2], "side": low[1]}},
        "real_engine": [{"check": r.name, "passed": r.passed, "detail": r.detail, "cases": r.cases} for r in real],
        "real_engine_passed": real_passed,
        "planted_defects": planted, "every_planted_defect_caught": all_caught,
        "over_budget": over_budget, "minutes": round((time.time() - started) / 60, 1),
        "p6_dm2_met": real_passed and all_caught and not over_budget,
    }
    path = write_once(RECORD, record)
    print({"real_engine_passed": real_passed, "every_planted_defect_caught": all_caught,
           "p6_dm2_met": record["p6_dm2_met"], "minutes": record["minutes"]}, "->", path)
    return 0 if record["p6_dm2_met"] else 1


if __name__ == "__main__":
    sys.exit(main())
