"""P6-M10 fit, exactly as `.agent/phase6/P6_M10_MODEL_SPEC.md` §4. Training seasons only (2024, 2025).

    python -m scripts.phase6_m10_fit        # isolated DATABASE_URL (stratai_test) required

- Reads the D18 frame rows and the score breakdowns from the isolated copy.
- Fits beta (OLS without an intercept, per component) and Σ (the uncentred residual second moment).
- Registers the artifact write-once as `strategy_outcome_component` / `p6m10-v1`.
- Writes `.agent/phase6/results/p6_m10_fit.json`, write-once.

Deterministic, with no randomness. This is a training step that never reads 2026.
"""

from __future__ import annotations

import sys
import time
from collections import Counter
from datetime import datetime, timezone

from scripts.phase6_common import (P6_M10_VERSION_TAG, REGISTRY_DIR, TRAIN_SEASONS, file_sha256, git_blob,
                                   isolated_database, load_frame, write_once)

BREAKDOWN_SQL = """
SELECT r.source_object_id, r.payload_json->'score_breakdown'
FROM raw_source_payloads r
WHERE r.source = 'tba' AND r.source_object_type = 'match' AND r.is_current AND r.source_object_id = ANY(%s)
"""


def main() -> int:
    from ml.features.score_breakdown import ScoreBreakdownSchemaError, UnsupportedSeasonError
    from ml.features.score_components import score_components
    from ml.registry import register_model
    from ml.strategy.outcome import (FEATURE_LIST, MODEL_TYPE, MODEL_VERSION, SPEC_PATH, ComponentOutcomeModel,
                                     MatchContext, fit_sample, missing_inputs)

    started = time.time()
    rows, frame_hash = load_frame()
    excluded: Counter[str] = Counter()
    candidates = []
    for row in rows:
        if row.season not in TRAIN_SEASONS or row.comp_level != "qualification":
            continue
        teams = [*row.red_teams, *row.blue_teams]
        if len(teams) != 6 or not all(t.epa_total_present for t in teams):
            excluded["epa_incomplete"] += 1
            continue
        if missing_inputs(MatchContext(tuple(row.red_teams), tuple(row.blue_teams))):
            excluded["model_input_absent"] += 1
            continue
        candidates.append(row)

    database = isolated_database()
    breakdowns: dict[str, dict] = {}
    keys = [r.match_key for r in candidates]
    with database.cursor() as cursor:
        for start in range(0, len(keys), 2000):
            cursor.execute(BREAKDOWN_SQL, (keys[start:start + 2000],))
            breakdowns.update({key: value for key, value in cursor.fetchall()})

    samples, used_rows = [], []
    for row in candidates:
        breakdown = breakdowns.get(row.match_key)
        if not isinstance(breakdown, dict) or "red" not in breakdown or "blue" not in breakdown:
            excluded["breakdown_missing"] += 1
            continue
        try:
            red = score_components(row.season, breakdown["red"])
            blue = score_components(row.season, breakdown["blue"])
        except (ScoreBreakdownSchemaError, UnsupportedSeasonError):
            excluded["breakdown_invalid"] += 1
            continue
        if (red.total, blue.total) != (row.score_red, row.score_blue):
            excluded["breakdown_score_mismatch"] += 1
            continue
        samples.append(fit_sample(row.red_teams, row.blue_teams, red, blue))
        used_rows.append(row)

    spec_sha = file_sha256(SPEC_PATH)
    info = {"frame_content_hash": frame_hash, "seasons": list(TRAIN_SEASONS), "comp_level": "qualification",
            "excluded": dict(excluded), "latest_fit_row": max(r.scheduled_time for r in used_rows).isoformat(),
            "spec_blob": git_blob(SPEC_PATH)}
    model = ComponentOutcomeModel.fit(samples, fit_info=info, spec_sha256=spec_sha)
    created = datetime.now(timezone.utc)
    target = register_model(model, registry_dir=REGISTRY_DIR, model_type=MODEL_TYPE, model_version=MODEL_VERSION,
                            version_tag=P6_M10_VERSION_TAG, training_dataset_hash=frame_hash,
                            feature_list=FEATURE_LIST, created_at=created,
                            provenance={"spec": SPEC_PATH, "spec_sha256": spec_sha, "fit_rows": len(samples)})
    artifact_sha = file_sha256(target / "model.json")
    record = {"milestone": "P6-M10", "step": "fit", "spec": SPEC_PATH, "spec_sha256": spec_sha,
              "registry": {"model_type": MODEL_TYPE, "version_tag": P6_M10_VERSION_TAG, "path": str(target),
                           "model_sha256": artifact_sha},
              "beta": model.beta, "sigma_matrix": model.sigma_matrix.tolist(), "sigma": model.sigma,
              "fit_rows": len(samples), "excluded": dict(excluded), "frame_content_hash": frame_hash,
              "latest_fit_row": info["latest_fit_row"], "seconds": round(time.time() - started, 1)}
    path = write_once("p6_m10_fit.json", record)
    print({k: record[k] for k in ("beta", "sigma", "fit_rows", "excluded")}, "->", path)
    return 0


if __name__ == "__main__":
    sys.exit(main())
