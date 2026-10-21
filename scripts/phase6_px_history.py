"""HV-1: the PX historical validation study (`.agent/phase6/P6_PX_HISTORICAL_VALIDATION_SPEC_V1.md`, frozen at
7cf2ef7). Diagnostic only, never acceptance.

    python -m scripts.phase6_px_history   # DATABASE_URL = an isolated stratai_test copy (read-only selection times)

- **Folds:** F0 (2024, within season), F1 (2024 → 2025) and F2 (2024-2025 → 2026).
- **Models:** PX-1b, the PX-1 raw design and seed-only, each refit per fold on that fold's training rows only. The
  frozen M6/M7 d18 (sha-pinned) is valid in F2 only. The registered px1b-v1 is never scored on 2024-2026.
- **Record:** `.agent/phase6/results/p6_px_hv1.json`, write-once, within a 45-minute budget.
"""

from __future__ import annotations

import gzip
import hashlib
import json
import pickle
import sys
import time
from typing import Any

from scripts.phase6_common import M6M7_SHA256, git_blob, isolated_database, load_m6m7, write_once
from scripts.phase6_playoff_track import BUDGET_SECONDS, Blocked, ROWS_CACHE_DIR

SPEC = ".agent/phase6/P6_PX_HISTORICAL_VALIDATION_SPEC_V1.md"
SPEC_BLOB = "c03347aba840e9ad7766c8f27b5681b35cc4de06"
CACHE = ROWS_CACHE_DIR / "px_rows_px1-v2.pkl.gz"
CACHE_SHA256 = "d7809c5fd7d245f51676b1bcef6abff153528cd581b2af1a161a1f7ffc0627cf"
POPULATION = "52a4d7f0ac464886b0ea020b401b71f7f1d668c49a783bab4eb2ecf7b3f12c30"
RECORD = "p6_px_hv1.json"
M6M7_VALID_FOLDS = {"F2"}  # spec §3: d18 was fit on 2024-2025 rows of every competition level
SELECTION_SQL = """
SELECT event_key, max(scheduled_time) FROM matches
WHERE season IN (2024, 2025, 2026) AND competition_level = 'qualification' AND scheduled_time IS NOT NULL
GROUP BY event_key
"""


def load_rows() -> list:
    """Spec §1: the cached rows, verified by sha256, minus scale_absent, verified by the population fingerprint."""
    from ml.playoffs.px1b import dataset_fingerprint, drop_scale_absent

    data = CACHE.read_bytes()
    if hashlib.sha256(data).hexdigest() != CACHE_SHA256:
        raise Blocked(f"{CACHE} is not the specified rows cache (sha256 mismatch)")
    rows, _ = drop_scale_absent(pickle.loads(gzip.decompress(data)))
    if dataset_fingerprint(rows) != POPULATION:
        raise Blocked("the PX-1b §1 population differs from the specified fingerprint")
    return rows


def selection_moments(database, events) -> dict:
    from ml.playoffs.px1 import selection_moment

    with database.cursor() as cursor:
        cursor.execute(SELECTION_SQL)
        latest = dict(cursor.fetchall())
    missing = sorted(e for e in events if e not in latest)
    if missing:
        raise Blocked(f"no qualification schedule for {missing[:5]}")
    return {e: selection_moment(latest[e]) for e in events}


def _abs_logit(model, rows) -> float:
    return sum(abs(model.margin(r)) for r in rows) / len(rows)


def run_fold(fold, selection, m6m7) -> dict[str, Any]:
    from ml.playoffs.history import fold_assertions, model_summary, paired, per_event
    from ml.playoffs.px1 import PlayoffLogisticModel
    from scripts.phase6_playoff_track import _m6m7_on
    import scripts.phase6_playoff_track as track

    assertions = fold_assertions(fold, selection)
    train, test = list(fold.train), list(fold.test)
    models = {"px1b": PlayoffLogisticModel.fit(train, normalized=True, model_type="hv1_px1b"),
              "px1_raw": PlayoffLogisticModel.fit(train, model_type="hv1_px1_raw"),
              "seed_only": PlayoffLogisticModel.fit(train, seed_only=True, model_type="hv1_seed_only")}
    predictions = {name: [m.predict(r) for r in test] for name, m in models.items()}
    missing = {name: sum(p is None for p in ps) for name, ps in predictions.items()}
    if any(missing.values()):
        raise Blocked(f"{fold.name}: absent inputs in test rows {missing} (spec §1 rows must be complete)")
    labels, events = [r.red_win for r in test], [r.event_key for r in test]
    summaries = {name: model_summary(predictions[name], labels, events, train_abs_logit=_abs_logit(models[name], train))
                 for name in models}
    m6m7_valid = fold.name in M6M7_VALID_FOLDS
    if m6m7_valid:
        track.M6M7 = m6m7
        predictions["m6m7"] = [_m6m7_on(r) for r in test]
        summaries["m6m7"] = model_summary(predictions["m6m7"], labels, events)
    comparators = ["seed_only", "px1_raw"] + (["m6m7"] if m6m7_valid else [])
    return {"fold": fold.name, "cutoff": fold.cutoff.isoformat() if fold.cutoff else None,
            "train_rows": len(train), "train_events": len({r.event_key for r in train}),
            "test_rows": len(test), "test_events": len(set(events)), "excluded_rows": fold.excluded,
            "train_seasons": sorted({r.season for r in train}), "test_seasons": sorted({r.season for r in test}),
            "assertions": assertions, "models": summaries,
            "m6m7": "valid (2026 held out of d18)" if m6m7_valid else
                    "not valid: in-sample (d18 was fit on 2024-2025 rows of every competition level)",
            "paired_px1b_vs": {c: paired(predictions["px1b"], predictions[c], labels, events) for c in comparators},
            "per_event": per_event(predictions, labels, events),
            "fold_models": {name: {"columns": m.design.names(), "coef": m.coef.tolist(),
                                   "dropped": m.design.dropped} for name, m in models.items()},
            "_pooled_inputs": (predictions, labels, events)}


def run(database) -> dict[str, Any]:
    from ml.playoffs.history import paired, season_fold, within_season_fold

    if git_blob(SPEC) != SPEC_BLOB:
        raise Blocked(f"{SPEC} is not the frozen HV-1 spec blob {SPEC_BLOB}")
    started = time.time()
    rows = load_rows()
    selection = selection_moments(database, {r.event_key for r in rows})
    m6m7 = load_m6m7()  # pinned: refuses an artifact other than sha256 M6M7_SHA256
    folds = [within_season_fold("F0", rows, 2024, selection), season_fold("F1", rows, (2024,), 2025),
             season_fold("F2", rows, (2024, 2025), 2026)]
    results = {}
    for fold in folds:
        if time.time() - started > BUDGET_SECONDS:
            raise SystemExit("HV-1 exceeded its 45-minute budget: nothing recorded")
        results[fold.name] = run_fold(fold, selection, m6m7)
    pooled = {}
    preds, labels, events = {}, [], []
    for name in ("F1", "F2"):
        p, y, e = results[name].pop("_pooled_inputs")
        for model in ("px1b", "px1_raw", "seed_only"):
            preds.setdefault(model, []).extend(p[model])
        labels.extend(y)
        events.extend(e)
    results["F0"].pop("_pooled_inputs")
    for comparator in ("seed_only", "px1_raw"):
        pooled[comparator] = paired(preds["px1b"], preds[comparator], labels, events)
    return {"study": "HV-1 PX historical validation (diagnostic; NOT acceptance)", "acceptance": False,
            "spec": {"path": SPEC, "blob": SPEC_BLOB}, "rows_cache_sha256": CACHE_SHA256,
            "population_fingerprint": POPULATION, "m6m7_sha256": M6M7_SHA256, "bootstrap_seed": 20261010,
            "folds": results, "pooled_F1_F2": pooled}


def main() -> int:
    started = time.time()
    database = isolated_database()
    result = run(database)
    result["minutes"] = round((time.time() - started) / 60, 1)
    result["over_budget"] = time.time() - started > BUDGET_SECONDS
    path = write_once(RECORD, result)
    print(json.dumps({"minutes": result["minutes"], "over_budget": result["over_budget"]}), "->", path)
    return 0


if __name__ == "__main__":
    sys.exit(main())
