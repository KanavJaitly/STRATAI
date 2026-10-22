"""P6-M13 parity rerun for P6-M10b: the P6-DM2 audit on the v2 model (frozen spec `P6_M10B_SPEC.md` §7, condition 3).

    python -m scripts.phase6_m13_parity_audit_m10b      # isolated DATABASE_URL (stratai_test) required

**Implemented 2026-10-10. Not run.** It runs only on Kanav's separate authorization, and only after a passed P6-M10b
2027 run. Plan: `.agent/phase6/decisions/P6_M13_M10B_RERUN_PLAN.md`, pinned by blob in the authorization.

- **Prerequisites, all before any data is read:** absent items are refused together, inconsistent ones at once.
  - the frozen P6-M10b spec blob, and the v1 audit plan unchanged since the v1 audit;
  - `p6_m10b_outcome_model.json` with `passed: true`, and its model identity equal to `p6_m10b_pins.json`'s;
  - the registered base and calibrator files' sha256 equal to that identity;
  - Kanav's authorization `decisions/p6_m13_m10b_rerun_authorization.json`, naming the spec and plan blobs;
  - no existing rerun record (once only; write-once).
- **Model:** `ml.strategy.serving.load_v2_model`, the loader the served path uses, with the status v2 would be served
  with. The loaded base and calibrator sha256 are checked against the identity again.
- **Contexts:** the v1 plan's selection (`select_contexts`: the same frame, seed and counts), each with
  `prediction_season` set to its row's season. A preflight refuses if v2 cannot score a planned context, or if the
  missing-data defect's imputed source key would not resolve (the defect would then be uncatchable for the wrong
  reason).
- **Checks:** S1–S3 and M1–M7 on the real engine; the 7 defects of `PLANTED_DEFECTS_V2`, each of which must fail its
  target check.
- **Record:** write-once `p6_m13_parity_audit_m10b.json`. The v1 audit records are never touched.
- **Serving:** a pass alone switches nothing. The §7 guard also needs the passed outcome record and Kanav's
  sha-matched confirmation, and it compares this record's identity with the outcome record's.
- **Time budget:** a hard 45 minutes; on overrun the planted defects not yet run are recorded as not caught.
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path
from typing import Any

from scripts import phase6_common as common
from scripts.phase6_common import file_sha256, git_blob, isolated_database, read_record, write_once
from scripts.phase6_playoff_track import Blocked

RERUN_PLAN = ".agent/phase6/decisions/P6_M13_M10B_RERUN_PLAN.md"
V1_PLAN = ".agent/phase6/decisions/P6_M13_AUDIT_PLAN.md"
V1_RECORD = "p6_m13_parity_audit_rerun1.json"
AUTHORIZATION = Path(".agent/phase6/decisions/p6_m13_m10b_rerun_authorization.json")
CODE_FILES = ("ml/strategy/parity_audit.py", "ml/strategy/engine.py", "ml/strategy/outcome.py",
              "ml/strategy/calibration.py", "ml/strategy/serving.py", "ml/strategy/display.py",
              "scripts/phase6_m13_parity_audit.py", "scripts/phase6_m13_parity_audit_m10b.py")


def check_authorization(value: dict[str, Any], plan_blob: str) -> None:
    from ml.strategy.calibration import SPEC_BLOB

    if not (value.get("authorized") is True and value.get("authorized_by") and value.get("date")
            and value.get("scope") == "P6-M13-M10b" and value.get("spec_blob") == SPEC_BLOB
            and value.get("plan_blob") == plan_blob):
        raise Blocked(f"{AUTHORIZATION} does not authorize the P6-M10b parity rerun (authorized, authorized_by, date, "
                      "scope=P6-M13-M10b, spec_blob, plan_blob)")


def rerun_prerequisites() -> dict[str, Any]:
    from ml.registry import model_file_sha256
    from ml.strategy.calibration import CALIBRATOR_MODEL_TYPE, CALIBRATOR_VERSION_TAG
    from ml.strategy.outcome import MODEL_TYPE
    from ml.strategy.serving import OUTCOME_RECORD, PARITY_RECORD
    from scripts.phase6_m10b import PINS_RECORD, _spec

    if read_record(PARITY_RECORD) is not None:
        raise Blocked(f"{PARITY_RECORD} already exists: the rerun is once only and never overwritten")
    provenance: dict[str, Any] = {"spec": _spec()}
    missing: list[str] = []
    v1 = read_record(V1_RECORD)
    if v1 is None or v1.get("plan_blob") != git_blob(V1_PLAN):
        raise Blocked(f"{V1_PLAN} is not the plan the v1 audit ran under: the P6-DM2 procedure must be unchanged")
    provenance["v1_plan"] = {"path": V1_PLAN, "blob": v1["plan_blob"], "v1_record": V1_RECORD,
                             "frame_content_hash": v1["frame_content_hash"]}
    plan_blob = git_blob(RERUN_PLAN) if Path(RERUN_PLAN).exists() else None
    if plan_blob is None:
        missing.append(f"{RERUN_PLAN} (the dated rerun plan)")
    else:
        provenance["rerun_plan"] = {"path": RERUN_PLAN, "blob": plan_blob}
    outcome = read_record(OUTCOME_RECORD)
    if outcome is None:
        missing.append(f"{OUTCOME_RECORD} (a passed P6-M10b 2027 run)")
    else:
        if outcome.get("passed") is not True:
            raise Blocked(f"{OUTCOME_RECORD} did not pass: there is no accepted v2 model to audit")
        identity = outcome.get("model_identity") or {}
        pins = read_record(PINS_RECORD)
        if pins is None or pins.get("model_identity") != identity:
            raise Blocked(f"{OUTCOME_RECORD}'s model identity is not the pinned identity in {PINS_RECORD}")
        actual = {"base_sha256": model_file_sha256(common.REGISTRY_DIR, MODEL_TYPE, "p6m10-v1"),
                  "calibrator_sha256": model_file_sha256(common.REGISTRY_DIR, CALIBRATOR_MODEL_TYPE,
                                                         CALIBRATOR_VERSION_TAG)}
        if actual != identity:
            raise Blocked("the registered base or calibrator is not the model the P6-M10b run evaluated")
        provenance["model_identity"] = identity
        provenance["outcome_record"] = {"name": OUTCOME_RECORD, "sha256": file_sha256(common.RESULTS_DIR / OUTCOME_RECORD)}
    authorization = json.loads(AUTHORIZATION.read_text(encoding="utf-8")) if AUTHORIZATION.exists() else None
    if authorization is None:
        missing.append(f"{AUTHORIZATION} (Kanav's authorization to run the rerun)")
    elif plan_blob is not None:
        check_authorization(authorization, plan_blob)
        provenance["authorization"] = {"path": str(AUTHORIZATION), "sha256": file_sha256(AUTHORIZATION)}
    if missing:
        raise Blocked("the P6-M10b parity rerun cannot be run yet; missing: " + "; ".join(missing))
    return provenance


def context_preflight(model, contexts, season_of) -> dict[str, Any]:
    """v2 must score every planned ordinary and low-odds context and refuse the missing-input one, and the planted
    missing-data defect's imputed source key must resolve, or the audit would test the wrong thing."""
    from ml.strategy.parity_audit import _ImputingEngineV2
    from ml.strategy.representation import Strategy

    def baseline(context):
        return model.evaluate(context, Strategy.baseline([t.team_number for t in context.red_teams]),
                              Strategy.baseline([t.team_number for t in context.blue_teams]))

    unscorable = [i for i, c in enumerate(contexts.ordinary) if baseline(c).p_red is None]
    low_context, low_side = contexts.low_odds
    low = baseline(low_context)
    imputed = _ImputingEngineV2(model)._imputed_source_key(contexts.missing_input)
    result = {"ordinary_scorable": not unscorable, "missing_input_refused": baseline(contexts.missing_input).p_red is None,
              "low_odds_below_0_05": low.p_red is not None and (low.p_red if low_side == "red" else low.p_blue) < 0.05,
              "imputed_source_key": imputed, "imputed_source_resolves": season_of(imputed) is not None,
              "prediction_seasons": sorted({c.prediction_season for c in contexts.ordinary})}
    failed = [k for k in ("ordinary_scorable", "missing_input_refused", "low_odds_below_0_05",
                          "imputed_source_resolves") if not result[k]]
    if failed or None in result["prediction_seasons"]:
        raise Blocked(f"the planned contexts do not support the v2 audit: {failed or 'prediction_season absent'}")
    return result


def run_rerun(database) -> dict[str, Any]:
    from ml.strategy.calibration import V2_VERSION_TAG
    from ml.strategy.engine import StrategyEngine
    from ml.strategy.outcome import VALIDATED, MatchContext
    from ml.strategy.parity_audit import PLANTED_DEFECTS_V2, run_audit
    from ml.strategy.serving import PARITY_MILESTONE, load_v2_model
    from scripts.phase6_m10b import season_resolver
    from scripts.phase6_m13_parity_audit import run_planted, select_contexts

    started = time.time()
    provenance = rerun_prerequisites()
    identity = provenance["model_identity"]
    season_of = season_resolver(database)
    model = load_v2_model(common.REGISTRY_DIR, identity, season_of, baseline_status=(VALIDATED, None))
    if (model.base.artifact_sha256, model.calibrator.artifact_sha256) != (identity["base_sha256"],
                                                                          identity["calibrator_sha256"]):
        raise Blocked("the loaded v2 model is not the identity the P6-M10b run evaluated")
    rows, frame_hash = common.load_frame()
    if frame_hash != provenance["v1_plan"]["frame_content_hash"]:
        raise Blocked("the D18 frame is not the frame the v1 audit's plan names")
    contexts, selected = select_contexts(rows, model, lambda row: MatchContext(
        tuple(row.red_teams), tuple(row.blue_teams), prediction_season=row.season))
    preflight = context_preflight(model, contexts, season_of)
    real = run_audit(StrategyEngine(model), contexts)
    planted, over_budget = run_planted(model, contexts, PLANTED_DEFECTS_V2, started)
    real_passed = all(r.passed for r in real)
    all_caught = all(p.get("target_caught") for p in planted.values())
    return {
        "milestone": PARITY_MILESTONE, "done_means": "P6-DM2", "spec": provenance["spec"],
        "plan": provenance["v1_plan"], "rerun_plan": provenance["rerun_plan"], "model_identity": identity,
        "model": {"version_tag": V2_VERSION_TAG, "served_baseline_status": [VALIDATED, None]},
        "code": {path: git_blob(path) for path in CODE_FILES}, "frame_content_hash": frame_hash,
        "contexts": {**selected, "prediction_season": "each context's row season"}, "preflight": preflight,
        "real_engine": [{"check": r.name, "passed": r.passed, "detail": r.detail, "cases": r.cases} for r in real],
        "real_engine_passed": real_passed, "planted_defects": planted, "every_planted_defect_caught": all_caught,
        "over_budget": over_budget, "minutes": round((time.time() - started) / 60, 1),
        "p6_dm2_met": real_passed and all_caught and not over_budget,
        "authorizes_serving_alone": False, "provenance_inputs": provenance}


def main() -> int:
    from ml.strategy.serving import PARITY_RECORD

    record = run_rerun(isolated_database())
    path = write_once(PARITY_RECORD, record)
    print({k: record[k] for k in ("real_engine_passed", "every_planted_defect_caught", "p6_dm2_met", "minutes")},
          "->", path)
    return 0 if record["p6_dm2_met"] else 1


if __name__ == "__main__":
    sys.exit(main())
