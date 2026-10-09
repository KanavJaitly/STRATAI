"""PX-1b runs under the frozen `.agent/phase6/P6_M2_PX1B_SPEC.md` (v1). Isolated `stratai_test` only.

    python -m scripts.phase6_px1b dev        # DEV-1 (§5): fit 2024, evaluate 2025 -- development, NOT acceptance
    python -m scripts.phase6_px1b final      # §6 final fit on 2024-2026, only if DEV-1 proceeds and before any 2027 data
    python -m scripts.phase6_px1b gate2027   # §6 FINAL-1 on held-out 2027 -- refuses until its prerequisites exist
    python -m scripts.phase6_px1b calbase    # PX-2b v2 §2.2: the calibration-base model, once, before any 2027 data

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

from scripts.phase6_common import REGISTRY_DIR, file_sha256, git_blob, isolated_database, read_record, write_once
from scripts.phase6_playoff_track import BUDGET_SECONDS, Blocked, assemble_rows, require_rulesets

DEV_RECORD, FINAL_RECORD, GATE_RECORD = "p6_px1b_dev.json", "p6_px1b_final_fit.json", "p6_px1b_gate_2027.json"
CALBASE_RECORD = "p6_px2b_calbase.json"
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


def run_gate2027(database, rulesets) -> dict[str, Any]:
    """§6 FINAL-1. Refuses, naming every unmet prerequisite, until all of them exist."""
    from data.rulesets import approved_seasons

    missing = []
    if read_record(FINAL_RECORD) is None:
        missing.append(f"{FINAL_RECORD} (the frozen final candidate)")
    if HOLDOUT not in approved_seasons(database):
        missing.append("an approved 2027 P6-M1 ruleset (human-entered; a qualified reviewer)")
    if not _playoff_matches(database, HOLDOUT):
        missing.append("2027 playoff data (the season complete and synced)")
    missing.append("the P6-M1 reproduction check for 2027 events, and a D18 EPA source covering 2027")
    raise Blocked("FINAL-1 cannot be evaluated yet; missing: " + "; ".join(missing))


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


RUNS = {"dev": (DEV_RECORD, run_dev), "final": (FINAL_RECORD, run_final), "gate2027": (GATE_RECORD, run_gate2027),
        "calbase": (CALBASE_RECORD, run_calbase)}


def main(argv: list[str] | None = None) -> int:
    args = argv if argv is not None else sys.argv[1:]
    if len(args) != 1 or args[0] not in RUNS:
        print(__doc__)
        return 2
    started = time.time()
    database = isolated_database()
    rulesets = require_rulesets(database)
    name, run = RUNS[args[0]]
    result = run(database, rulesets)
    result["minutes"] = round((time.time() - started) / 60, 1)
    result["over_budget"] = time.time() - started > BUDGET_SECONDS
    path = write_once(name, result)
    print(json.dumps({k: v for k, v in result.items() if k in ("decision", "minutes", "over_budget")}), "->", path)
    return 0


if __name__ == "__main__":
    sys.exit(main())
