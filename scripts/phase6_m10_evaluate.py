"""P6-M10 evaluation: one run, exactly as `.agent/phase6/P6_M10_MODEL_SPEC.md` §5 (P6-Q9).

    python -m scripts.phase6_m10_evaluate

- **Population:** held-out 2026 EPA-complete qualification matches in the D18 frame.
  - **Excluded, counted:** ties, and matches with an absent model input.
- **Gate:** the M7/D16 gate with its constants unchanged (G1–G4).
- **Reported, not gated:** the paired log-loss vs M6/M7 (`win_prob_xgb_calibrated` `d18`) on the same rows, with
  an event-bootstrap 95% CI.
- **Record:** `.agent/phase6/results/p6_m10_outcome_model.json`, write-once. D9 applies to a gate failure.
"""

from __future__ import annotations

import sys
import time
from collections import Counter, defaultdict
from datetime import datetime

from scripts.phase6_common import (HELD_OUT_SEASON, P6_M10_VERSION_TAG, REGISTRY_DIR, file_sha256, git_blob,
                                   load_frame, load_m6m7, read_record, write_once)

BOOTSTRAP_SEED = 20261005


def main() -> int:
    from ml.backtest.bootstrap import ci_excludes_zero, event_bootstrap_mean_ci
    from ml.backtest.harness import _match_features
    from ml.backtest.metrics import brier_score, expected_calibration_error, log_loss
    from ml.calibration.gate import evaluate_calibration_gate
    from ml.dataset.builder import LABEL_RED_WIN, LABEL_TIE
    from ml.registry import load_registered_model
    from ml.strategy.outcome import FEATURE_LIST, MODEL_TYPE, SPEC_PATH, ComponentOutcomeModel, MatchContext
    from ml.strategy.representation import Strategy

    started = time.time()
    fit = read_record("p6_m10_fit.json")
    if fit is None:
        raise SystemExit("no P6-M10 fit record: run scripts.phase6_m10_fit first")
    model, _ = load_registered_model(ComponentOutcomeModel, registry_dir=REGISTRY_DIR, model_type=MODEL_TYPE,
                                     version_tag=P6_M10_VERSION_TAG, current_feature_list=FEATURE_LIST,
                                     expected_sha256=fit["registry"]["model_sha256"])
    if model.spec_sha256 != file_sha256(SPEC_PATH):
        raise SystemExit("the model specification changed after the fit: refusing to evaluate")
    m6m7 = load_m6m7()
    rows, frame_hash = load_frame()

    excluded: Counter[str] = Counter()
    evaluated = []
    for row in rows:
        if row.season != HELD_OUT_SEASON or row.comp_level != "qualification":
            continue
        teams = [*row.red_teams, *row.blue_teams]
        if len(teams) != 6 or not all(t.epa_total_present for t in teams):
            continue  # not in the EPA-complete population
        if row.label == LABEL_TIE:
            excluded["tie"] += 1
            continue
        evaluated.append(row)

    q, labels, symmetry, events, m6m7_q, kept = [], [], [], [], [], []
    for row in evaluated:
        context = MatchContext(tuple(row.red_teams), tuple(row.blue_teams))
        red = Strategy.baseline([t.team_number for t in row.red_teams])
        blue = Strategy.baseline([t.team_number for t in row.blue_teams])
        forward = model.evaluate(context, red, blue)
        if forward.p_red is None:
            excluded["model_input_absent"] += 1
            continue
        backward = model.evaluate(context.swapped(), blue, red)
        q.append(forward.p_red)
        symmetry.append(abs(forward.p_red + backward.p_red - 1.0))
        labels.append(row.label == LABEL_RED_WIN)
        events.append(row.event_key)
        m6m7_q.append(m6m7.predict_win_prob(_match_features(row)))
        kept.append(row)
    backward_order = [model.evaluate(MatchContext(tuple(r.red_teams), tuple(r.blue_teams)),
                                     Strategy.baseline([t.team_number for t in r.red_teams]),
                                     Strategy.baseline([t.team_number for t in r.blue_teams])).p_red
                      for r in reversed(kept)]
    order_independent = q == list(reversed(backward_order))
    earliest_evaluated = min(r.scheduled_time for r in kept)
    fit_seasons = set(model.fit_info["seasons"])
    fit_isolated = (fit_seasons <= {2024, 2025} and HELD_OUT_SEASON not in fit_seasons
                    and fit["frame_content_hash"] == frame_hash
                    and datetime.fromisoformat(fit["latest_fit_row"]) < earliest_evaluated)
    gate = evaluate_calibration_gate(q, labels, symmetry_errors=symmetry, order_independent=order_independent,
                                     fit_isolated=fit_isolated)

    paired: dict[str, list[float]] = defaultdict(list)
    for p10, p67, y, event in zip(q, m6m7_q, labels, events):
        paired[event].append(log_loss([p10], [y]) - log_loss([p67], [y]))
    comparison = event_bootstrap_mean_ci(paired, seed=BOOTSTRAP_SEED)

    record = {
        "milestone": "P6-M10", "decision": "P6-Q9", "spec": SPEC_PATH, "spec_blob": git_blob(SPEC_PATH),
        "spec_sha256": model.spec_sha256, "frame_content_hash": frame_hash,
        "model": {"model_type": MODEL_TYPE, "version_tag": P6_M10_VERSION_TAG, "model_sha256": model.artifact_sha256,
                  "beta": model.beta, "sigma": model.sigma},
        "population": {"season": HELD_OUT_SEASON, "comp_level": "qualification", "epa_complete": True,
                       "evaluated": len(q), "excluded": dict(excluded)},
        "gate": gate.to_dict(), "gate_passed": gate.passed,
        "metrics": {"ece": expected_calibration_error(q, labels), "log_loss": log_loss(q, labels),
                    "brier": brier_score(q, labels)},
        "m6m7_same_rows": {"version_tag": "d18", "ece": expected_calibration_error(m6m7_q, labels),
                           "log_loss": log_loss(m6m7_q, labels), "brier": brier_score(m6m7_q, labels)},
        "paired_log_loss_minus_m6m7": {**comparison, "ci_excludes_zero": ci_excludes_zero(comparison),
                                       "gated": False},
        "fit_isolation": {"latest_fit_row": fit["latest_fit_row"],
                          "earliest_evaluated_row": earliest_evaluated.isoformat(), "fit_seasons": sorted(fit_seasons),
                          "fit_isolated": fit_isolated},
        "served_baseline_status": "validated" if gate.passed else "not_validated (p6_m10_gate_failed)",
        "minutes": round((time.time() - started) / 60, 2),
    }
    path = write_once("p6_m10_outcome_model.json", record)
    print({"gate_passed": gate.passed, "ece": record["metrics"]["ece"], "g2": gate.g2.status,
           "evaluated": len(q), "excluded": dict(excluded), "paired": comparison}, "->", path)
    return 0


if __name__ == "__main__":
    sys.exit(main())
