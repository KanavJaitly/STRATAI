"""PX-1b runs under the frozen `.agent/phase6/P6_M2_PX1B_SPEC.md` (v1). Isolated `stratai_test` only.

    python -m scripts.phase6_px1b dev        # DEV-1 (§5): fit 2024, evaluate 2025 -- development, NOT acceptance
    python -m scripts.phase6_px1b final      # §6 final fit on 2024-2026, only if DEV-1 proceeds and before any 2027 data
    python -m scripts.phase6_px1b gate2027   # §6 FINAL-1 on held-out 2027 (scripts.phase6_px1b_final1): fail-closed
                                             # prerequisites, then the frozen gate; run once
    python -m scripts.phase6_px1b epa-pin-2027  # pin the 2027 D18 EPA source named in Kanav's config (write-once)
    python -m scripts.phase6_px1b calbase    # PX-2b v2 §2.2: the calibration-base model, once, before any 2027 data
    python -m scripts.phase6_px1b pins       # G1/G2: pin the three model files and the slice content (write-once; done)
    python -m scripts.phase6_px1b pins-v2    # G3: v1's pins re-verified and copied, plus ranking_xgb_v2/d18 (write-once)

- **Records:** write-once, in `.agent/phase6/results/`. Each carries the commit, the spec's blob and sha256, the
  dataset fingerprint, the seed and the runtime.
- **2026:** never a PX-1b holdout.
- **D9:** PX-2, PX-4 and P6-M8 are untouched (spec §8).
"""

from __future__ import annotations

import json
import sys
import time
from collections import Counter
from datetime import datetime, timezone
from typing import Any

from scripts.phase6_common import (REGISTRY_DIR, RESULTS_DIR, file_sha256, git_blob, isolated_database, read_record,
                                   write_once)
from scripts.phase6_playoff_track import BUDGET_SECONDS, Blocked, assemble_rows, require_rulesets

DEV_RECORD, FINAL_RECORD, GATE_RECORD = "p6_px1b_dev.json", "p6_px1b_final_fit.json", "p6_px1b_gate_2027.json"
CALBASE_RECORD = "p6_px2b_calbase.json"
PINNED_MODELS = (("playoff_px1b", "px1b-v1"), ("playoff_px1b_seed_only", "px1b-v1"), ("playoff_px1b_calbase", "px2b-v2"))
DEV_FIT, DEV_EVAL, FINAL_SEASONS, HOLDOUT = 2024, 2025, (2024, 2025, 2026), 2027


def _spec() -> dict[str, str]:
    from ml.playoffs.px1b import SPEC_PATH

    return {"path": SPEC_PATH, "blob": git_blob(SPEC_PATH), "sha256": file_sha256(SPEC_PATH)}


def _rows(database, rulesets, seasons) -> tuple[list, Counter, dict]:
    from ml.playoffs.px1b import drop_scale_absent

    m1 = read_record("p6_m1_ruleset_check.json")
    if m1 is None:
        raise Blocked("p6_m1_ruleset_check.json has not been recorded")
    rows, excluded, _, _, integrity, by_event = assemble_rows(database, rulesets, m1, seasons=seasons)
    rows, scale_excluded = drop_scale_absent(rows)
    excluded.update(scale_excluded)
    return rows, excluded, {"epa_integrity": integrity, "excluded_by_event": by_event}


def _playoff_matches(database, season: int) -> int:
    with database.cursor() as cursor:
        cursor.execute("SELECT count(*) FROM matches WHERE season = %s AND competition_level IN ('semifinal', 'final')",
                       (season,))
        return cursor.fetchone()[0]


def run_dev(database, rulesets) -> dict[str, Any]:
    """§5 DEV-1: one run; 2024 fit, 2025 evaluation; PX-1b vs the seed-only comparator and the PX-1 raw design."""
    from ml.playoffs.px1 import PlayoffLogisticModel
    from ml.playoffs.px1b import (BOOTSTRAP_SEED, MODEL_TYPE, dataset_fingerprint, development_decision, paired,
                                  summary)

    rows, excluded, extra = _rows(database, rulesets, (DEV_FIT, DEV_EVAL))
    fit = sorted((r for r in rows if r.season == DEV_FIT), key=lambda r: r.match_key)
    evaluate = sorted((r for r in rows if r.season == DEV_EVAL), key=lambda r: r.match_key)
    temporal = max(r.scheduled_time for r in fit) < min(r.scheduled_time for r in evaluate)
    if not temporal:
        raise Blocked("DEV-1 fit rows do not all precede the evaluation rows")
    px1b = PlayoffLogisticModel.fit(fit, normalized=True, model_type=MODEL_TYPE)
    seed_only = PlayoffLogisticModel.fit(fit, seed_only=True)
    px1_raw = PlayoffLogisticModel.fit(fit)
    vs_seed, vs_raw = paired(px1b, seed_only, evaluate), paired(px1b, px1_raw, evaluate)
    return {"milestone": "PX-1b DEV-1", "label": "DEVELOPMENT RESULT (2024 -> 2025) -- not an acceptance result",
            "acceptance": False, "spec": _spec(), "dataset_fingerprint": dataset_fingerprint(fit + evaluate),
            "bootstrap_seed": BOOTSTRAP_SEED, "seasons": {"fit": DEV_FIT, "evaluate": DEV_EVAL},
            "temporal_fit_before_evaluation": temporal,
            "rows": {"fit": len(fit), "evaluate": len(evaluate), "events_evaluated": len({r.event_key for r in evaluate}),
                     "excluded": dict(excluded)}, **extra,
            "models": {"px1b": summary(px1b, fit, evaluate), "seed_only": summary(seed_only, fit, evaluate),
                       "px1_raw_design": summary(px1_raw, fit, evaluate)},
            "m6m7": "not a development comparator: d18 was fit on the 2024-2025 Phase 4 frame (in-sample on 2025)",
            "vs_seed_only": vs_seed, "vs_px1_raw_design": vs_raw, "decision": development_decision(vs_seed, vs_raw)}


def run_final(database, rulesets) -> dict[str, Any]:
    """§6: the final candidate, fit on 2024-2026, frozen in the registry before any 2027 outcome exists."""
    from ml.playoffs.px1 import PlayoffLogisticModel
    from ml.playoffs.px1b import MODEL_TYPE, SEED_ONLY_MODEL_TYPE, VERSION_TAG, dataset_fingerprint
    from ml.registry import register_model

    dev = read_record(DEV_RECORD)
    if dev is None or not dev["decision"]["proceed_to_final"]:
        raise Blocked(f"{DEV_RECORD} is missing or did not meet DV1 and DV2: PX-1b does not proceed (spec §5)")
    if _playoff_matches(database, HOLDOUT):
        raise Blocked("2027 playoff matches exist: the final candidate must be frozen before 2027 outcomes (§6)")
    rows, excluded, extra = _rows(database, rulesets, FINAL_SEASONS)
    px1b = PlayoffLogisticModel.fit(rows, normalized=True, model_type=MODEL_TYPE)
    seed_only = PlayoffLogisticModel.fit(rows, seed_only=True, model_type=SEED_ONLY_MODEL_TYPE)
    created = datetime.now(timezone.utc)
    fingerprint = dataset_fingerprint(rows)
    for model in (px1b, seed_only):
        register_model(model, registry_dir=REGISTRY_DIR, model_type=model.model_type, model_version="1.0.0",
                       version_tag=VERSION_TAG, training_dataset_hash=fingerprint,
                       feature_list=model.design.names(), created_at=created)
    return {"milestone": "PX-1b final fit", "acceptance": False, "spec": _spec(), "dataset_fingerprint": fingerprint,
            "rows": {"fit": len(rows), "by_season": dict(Counter(r.season for r in rows)), "excluded": dict(excluded)},
            **extra, "version_tag": VERSION_TAG, "columns": px1b.design.names(), "dropped": px1b.design.dropped}


def pinned_px1b_models():
    """px1b-v1 and its seed-only comparator, loaded only after each file hashes to its G1 pin (FINAL-1's models)."""
    from scripts.phase6_playoff_track import PX1B_TRACK, _models

    assert PX1B_TRACK.pins_record is not None
    return _models(PX1B_TRACK)


def run_gate2027(database, rulesets) -> dict[str, Any]:
    """§6 FINAL-1: the frozen 2027 acceptance evaluation (`scripts.phase6_px1b_final1`). Fail-closed prerequisites,
    then the gate; run once."""
    from scripts.phase6_px1b_final1 import run_gate2027 as final1

    return final1(database, rulesets)


def run_epa_pin_2027(database, rulesets) -> dict[str, Any]:
    """Pin the 2027 D18 EPA source named in Kanav's config (a FINAL-1 prerequisite)."""
    from scripts.phase6_px1b_final1 import run_epa_pin_2027 as pin

    return pin(database, rulesets)


def run_calbase(database, rulesets) -> dict[str, Any]:
    """PX-2b v2 §2.2 (approved 2026-10-08): the calibration-base model, fit once and registered write-once before any
    2027 data exists. The rows are px1b-v1's own population (proven by fingerprint); the slice must be the frozen 526
    keys; the fit set is the rows strictly before the slice from no slice event, proven isolated row by row."""
    import hashlib

    from ml.playoffs.px1b import dataset_fingerprint
    from ml.playoffs.px2b import (CALBASE_MODEL_TYPE, CALBASE_VERSION_TAG, SLICE_PROVENANCE, SPEC_BLOB, SPEC_PATH,
                                  calibration_base_rows, calibration_slice, fit_calibration_base, frozen_slice_keys,
                                  isolation_report, require_frozen_slice, require_isolated, straddling_events)
    from ml.registry import register_model

    if git_blob(SPEC_PATH) != SPEC_BLOB:
        raise Blocked(f"{SPEC_PATH} is not the approved PX-2b v2 blob {SPEC_BLOB}")
    final = read_record(FINAL_RECORD)
    if final is None:
        raise Blocked(f"{FINAL_RECORD} (px1b-v1) is required")
    if _playoff_matches(database, HOLDOUT):
        raise Blocked("2027 playoff matches exist: the calibration base must be frozen before any 2027 data (v2 §2.2)")
    rows, excluded, extra = _rows(database, rulesets, FINAL_SEASONS)
    population = dataset_fingerprint(rows)
    if population != final["dataset_fingerprint"]:
        raise Blocked("the 2024-2026 rows differ from px1b-v1's training population (fingerprint mismatch)")
    slice_rows = calibration_slice(rows)
    frozen = frozen_slice_keys()
    require_frozen_slice(slice_rows, frozen)
    base = calibration_base_rows(rows, slice_rows)
    base_latest = max(r.scheduled_time for r in base)
    report = isolation_report([r.match_key for r in base], [r.event_key for r in base], base_latest, slice_rows)
    require_isolated(report)
    model = fit_calibration_base(base)
    fingerprint = dataset_fingerprint(base)
    register_model(model, registry_dir=REGISTRY_DIR, model_type=CALBASE_MODEL_TYPE, model_version="1.0.0",
                   version_tag=CALBASE_VERSION_TAG, training_dataset_hash=fingerprint,
                   feature_list=model.design.names(), created_at=datetime.now(timezone.utc))
    return {"milestone": "PX-2b v2 calibration base", "acceptance": False,
            "spec": {"path": SPEC_PATH, "blob": SPEC_BLOB, "sha256": file_sha256(SPEC_PATH)},
            "population": {"rows": len(rows), "fingerprint": population, "equals_px1b_v1_training": True},
            "slice": {"rows": len(slice_rows), "provenance": str(SLICE_PROVENANCE),
                      "provenance_sha256": file_sha256(SLICE_PROVENANCE), "equals_frozen_keys": True,
                      "keys_sha256": hashlib.sha256("\n".join(frozen).encode("utf-8")).hexdigest()},
            "base": {"rows": len(base), "fingerprint": fingerprint, "by_season": dict(Counter(r.season for r in base)),
                     "latest": base_latest.isoformat(), "events": sorted({r.event_key for r in base}),
                     "match_keys": [r.match_key for r in base]},
            "straddling_events_excluded": straddling_events(rows, slice_rows), "isolation": report,
            "registry": {"model_type": CALBASE_MODEL_TYPE, "version_tag": CALBASE_VERSION_TAG},
            "columns": model.design.names(), "excluded": dict(excluded), **extra}


def run_pins(database, rulesets) -> dict[str, Any]:
    """G1/G2 (approved 2026-10-08): one additive, write-once pin record.
    - The sha256 of each pinned model file, after checking that its registry training hash is the recorded population.
    - The content fingerprint of the 526-row slice, rebuilt from px1b-v1's own population (proven by fingerprint),
      with the exact serialization (name, method, code signature)."""
    from ml.playoffs.pins import (PIN_VERSION_V1 as PIN_VERSION, SERIALIZATION_NAME, model_key,
                                  serialization_signature, slice_content_fingerprint)
    from ml.playoffs.px1b import dataset_fingerprint
    from ml.playoffs.px2b import SLICE_PROVENANCE, calibration_slice, frozen_slice_keys, require_frozen_slice
    from ml.registry import model_file_sha256

    final, calbase = read_record(FINAL_RECORD), read_record(CALBASE_RECORD)
    if final is None or calbase is None:
        raise Blocked(f"{FINAL_RECORD} and {CALBASE_RECORD} are required")
    if _playoff_matches(database, HOLDOUT):
        raise Blocked("2027 playoff matches exist: the pins are taken before any 2027 data")
    expected_training = {"playoff_px1b": final["dataset_fingerprint"],
                         "playoff_px1b_seed_only": final["dataset_fingerprint"],
                         "playoff_px1b_calbase": calbase["base"]["fingerprint"]}
    models = {}
    for model_type, tag in PINNED_MODELS:
        manifest = json.loads((REGISTRY_DIR / model_type / tag / "manifest.json").read_text(encoding="utf-8"))
        if manifest["training_dataset_hash"] != expected_training[model_type]:
            raise Blocked(f"{model_key(model_type, tag)}: its registry training hash is not the recorded population")
        models[model_key(model_type, tag)] = model_file_sha256(REGISTRY_DIR, model_type, tag)
    rows, _, _ = _rows(database, rulesets, FINAL_SEASONS)
    if dataset_fingerprint(rows) != final["dataset_fingerprint"]:
        raise Blocked("the 2024-2026 rows differ from px1b-v1's training population")
    slice_rows = calibration_slice(rows)
    require_frozen_slice(slice_rows, frozen_slice_keys())
    return {"pin_version": PIN_VERSION, "approved": "Kanav 2026-10-08 (G1/G2)", "acceptance": False,
            "models": models,
            "slice_content": {
                "rows": len(slice_rows), "fingerprint": slice_content_fingerprint(slice_rows),
                "keys_from": str(SLICE_PROVENANCE), "keys_sha256": calbase["slice"]["keys_sha256"],
                "serialization": {
                    "name": SERIALIZATION_NAME, "function": "ml.playoffs.px1b.dataset_fingerprint",
                    "signature_sha256": serialization_signature(),
                    "method": "rows sorted by match_key; per row json.dumps(sort_keys=True) of {match_key, season, "
                              "round, red_seed, blue_seed, red_win, red, blue, fields}; red/blue = per member "
                              "{team, values (TEAM_FEATURE_NAMES order, NaN -> null), score_scale, epa_scale (null "
                              "unless present)}; fields = TEAM_FEATURE_NAMES; lines joined with '\\n', UTF-8, sha256",
                    "scope": "the 526 PX-2b v2 calibration-slice rows (PX-1b spec §1 rows of 2026, the last 20% by "
                             "(scheduled_time, match_key)), as assembled from the isolated database at the selection "
                             "moment"}},
            "population_fingerprint": final["dataset_fingerprint"]}


# The ranking_xgb_v2 d18 file identity already recorded by Phase 5 (p5_m4/p5_m6 records; ML_RANKING_MODEL_SHA256).
RANKING_D18_RECORDED_SHA256 = "1f0fe5aae90244e2736950928a88e733c85214b8def547b399b87c0cdd136312"


def run_pins_v2(database, rulesets) -> dict[str, Any]:
    """G3 (approved 2026-10-09): an additive, write-once v2 pin record. Each v1 pin is re-verified against its file
    and copied unchanged; ranking_xgb_v2/d18 (M8b's ordering model) is added after its file is checked against the
    sha256 Phase 5 recorded. v1 is never modified."""
    from ml.playoffs.pins import (PIN_RECORD_V1, PIN_VERSION, PIN_VERSION_V1, RANKING_D18, model_key, read_pins,
                                  serialization_signature)
    from ml.registry import model_file_sha256

    v1_path = RESULTS_DIR / PIN_RECORD_V1
    v1 = read_pins(v1_path, version=PIN_VERSION_V1)
    if _playoff_matches(database, HOLDOUT):
        raise Blocked("2027 playoff matches exist: the pins are taken before any 2027 data")
    for key, sha in v1["models"].items():
        if model_file_sha256(REGISTRY_DIR, *key.split("/")) != sha:
            raise Blocked(f"{key} no longer matches its v1 pin: refusing to copy it")
    if v1["slice_content"]["serialization"]["signature_sha256"] != serialization_signature():
        raise Blocked("the slice serialization changed since v1: refusing to copy its content pin")
    ranking = model_file_sha256(REGISTRY_DIR, *RANKING_D18)
    if ranking != RANKING_D18_RECORDED_SHA256:
        raise Blocked(f"{model_key(*RANKING_D18)} sha256 {ranking} is not the Phase 5 recorded identity")
    return {"pin_version": PIN_VERSION, "approved": "Kanav 2026-10-09 (G3)", "acceptance": False,
            "derived_from": {"record": PIN_RECORD_V1, "sha256": file_sha256(v1_path), "pin_version": PIN_VERSION_V1},
            "models": {**v1["models"], model_key(*RANKING_D18): ranking},
            "ranking_cross_check": {"recorded_by": "Phase 5 p5_m4 / p5_m6 records and ML_RANKING_MODEL_SHA256",
                                    "sha256": RANKING_D18_RECORDED_SHA256, "matches": True},
            "slice_content": v1["slice_content"], "population_fingerprint": v1["population_fingerprint"],
            "calibrator": "not pinned here: PX-2b's own write-once record carries its sha256 (it does not exist yet)"}


RUNS = {"dev": (DEV_RECORD, run_dev), "final": (FINAL_RECORD, run_final), "gate2027": (GATE_RECORD, run_gate2027),
        "calbase": (CALBASE_RECORD, run_calbase), "pins": ("p6_px1b_chain_pins.json", run_pins),
        "pins-v2": ("p6_px1b_chain_pins_v2.json", run_pins_v2),
        "epa-pin-2027": ("p6_px1b_epa_source_2027.json", run_epa_pin_2027)}
# The seasons whose approved rulesets a run needs (default 2024-2026). FINAL-1 needs the approved 2027 ruleset.
RUN_SEASONS = {"gate2027": (HOLDOUT,)}


def main(argv: list[str] | None = None) -> int:
    args = argv if argv is not None else sys.argv[1:]
    if len(args) != 1 or args[0] not in RUNS:
        print(__doc__)
        return 2
    started = time.time()
    database = isolated_database()
    rulesets = require_rulesets(database, RUN_SEASONS.get(args[0]))
    name, run = RUNS[args[0]]
    result = run(database, rulesets)
    result["minutes"] = round((time.time() - started) / 60, 1)
    result["over_budget"] = time.time() - started > BUDGET_SECONDS
    path = write_once(name, result)
    print(json.dumps({k: v for k, v in result.items() if k in ("decision", "minutes", "over_budget")}), "->", path)
    return 0


if __name__ == "__main__":
    sys.exit(main())
