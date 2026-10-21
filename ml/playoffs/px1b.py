"""PX-1b: PX-1's model on causal-scale-normalized composition features, as `.agent/phase6/P6_M2_PX1B_SPEC.md`
(frozen v1) defines it.

- **Model:** `PlayoffLogisticModel.fit(rows, normalized=True)`. It is PX-1's design and fit, except that each team's
  point-unit fields are first divided by its causal scales (D16 `team_vector_v2`: EPA by `epa_scale`, in-event points
  by `score_scale`).
- **Rows:** PX-1's rows, minus `scale_absent` (§1.3). A scale is valid only when present, finite and > 0, and nothing
  is imputed. Every model in a comparison sees the same rows.
- **Development (DEV-1, §5):** fit on 2024, evaluate on 2025; proceed criteria DV1 and DV2. This is not acceptance.
- **Acceptance (FINAL-1, §6):** a held-out 2027 gate in P6-Q3 form. 2026 is never a PX-1b holdout.
"""

from __future__ import annotations

import hashlib
import json
import math
from collections import Counter
from collections.abc import Sequence
from typing import Any

from ml.backtest.metrics import brier_score, expected_calibration_error, log_loss, roc_auc
from ml.features.assembler import TeamFeatures
from ml.models.team_vector import TEAM_FEATURE_NAMES, team_features_to_vector
from ml.playoffs.evaluation import paired_log_loss_gate
from ml.playoffs.px1 import PX1B_SPEC_PATH, PlayoffLogisticModel, PlayoffRow

MODEL_TYPE, SEED_ONLY_MODEL_TYPE, VERSION_TAG = "playoff_px1b", "playoff_px1b_seed_only", "px1b-v1"
SPEC_PATH = PX1B_SPEC_PATH
SCALE_ABSENT = "scale_absent"
BOOTSTRAP_SEED = 20261010
EXTREME = 0.1  # share of predictions below 0.1 or above 0.9 (§5, reported)


def valid_scale(value: float | None, present: bool) -> bool:
    """§1.3: present, not None, finite and > 0. Anything else is absent."""
    return bool(present) and value is not None and math.isfinite(value) and value > 0


def has_valid_scales(team: TeamFeatures) -> bool:
    return valid_scale(team.score_scale, team.score_scale_present) and valid_scale(team.epa_scale,
                                                                                  team.epa_scale_present)


def drop_scale_absent(rows: Sequence[PlayoffRow]) -> tuple[list[PlayoffRow], Counter[str]]:
    """§1.3: a row where any of the six teams lacks a valid score_scale or epa_scale is excluded, counted."""
    kept = [r for r in rows if all(has_valid_scales(t) for t in (*r.red_teams, *r.blue_teams))]
    return kept, Counter({SCALE_ABSENT: len(rows) - len(kept)} if len(rows) > len(kept) else {})


def _number(value: float | None) -> float | None:
    return None if value is None or (isinstance(value, float) and math.isnan(value)) else float(value)


def _team_record(team: TeamFeatures) -> dict[str, Any]:
    vector = team_features_to_vector(team)
    return {"team": team.team_number, "values": [_number(v) for v in vector],
            "score_scale": _number(team.score_scale) if team.score_scale_present else None,
            "epa_scale": _number(team.epa_scale) if team.epa_scale_present else None}


def dataset_fingerprint(rows: Sequence[PlayoffRow]) -> str:
    """§7: sha256 of the canonical JSON of every row a run uses, sorted by match_key."""
    lines = []
    for r in sorted(rows, key=lambda r: r.match_key):
        lines.append(json.dumps({"match_key": r.match_key, "season": r.season, "round": r.round,
                                 "red_seed": r.red_seed, "blue_seed": r.blue_seed, "red_win": r.red_win,
                                 "red": [_team_record(t) for t in r.red_teams],
                                 "blue": [_team_record(t) for t in r.blue_teams],
                                 "fields": list(TEAM_FEATURE_NAMES)}, sort_keys=True))
    return hashlib.sha256("\n".join(lines).encode("utf-8")).hexdigest()


def summary(model: PlayoffLogisticModel, fit_rows: Sequence[PlayoffRow],
            eval_rows: Sequence[PlayoffRow]) -> dict[str, Any]:
    """§5's reported statistics for one model (every row must be predictable: the rows are complete by §1)."""
    p = [model.predict(r) for r in eval_rows]
    if any(v is None for v in p):
        raise ValueError("an evaluation row has an absent used input: §1 rows must be complete")
    y = [r.red_win for r in eval_rows]
    fit_z = sum(abs(model.margin(r)) for r in fit_rows) / len(fit_rows)
    eval_z = sum(abs(model.margin(r)) for r in eval_rows) / len(eval_rows)
    return {"log_loss": log_loss(p, y), "brier": brier_score(p, y), "roc_auc": roc_auc(p, y),
            "ece_10": expected_calibration_error(p, y, n_bins=10), "mean_abs_logit_fit": fit_z,
            "mean_abs_logit_eval": eval_z, "mean_abs_logit_ratio": eval_z / fit_z if fit_z else None,
            "share_extreme": sum(1 for v in p if v < EXTREME or v > 1 - EXTREME) / len(p),
            "columns": model.design.names(), "dropped": model.design.dropped, "coef": model.coef.tolist(),
            "scale": model.design.scale}


def paired(candidate: PlayoffLogisticModel, baseline: PlayoffLogisticModel,
           rows: Sequence[PlayoffRow]) -> dict[str, Any]:
    """The paired event-bootstrap log-loss comparison (`paired_log_loss_gate`'s procedure, seed 20261010)."""
    return paired_log_loss_gate([candidate.predict(r) for r in rows], [baseline.predict(r) for r in rows],
                                [r.red_win for r in rows], [r.event_key for r in rows], seed=BOOTSTRAP_SEED)


def development_decision(vs_seed_only: dict[str, Any], vs_px1_raw: dict[str, Any]) -> dict[str, Any]:
    """§5: DV1 = vs seed-only, CI entirely below 0; DV2 = vs PX-1 raw, point estimate <= 0. Both are required."""
    dv1 = vs_seed_only["ci_high"] < 0
    dv2 = vs_px1_raw["mean"] <= 0
    return {"DV1_vs_seed_only_ci_below_zero": dv1, "DV2_vs_px1_raw_point_estimate_not_worse": dv2,
            "proceed_to_final": dv1 and dv2, "acceptance": False}


def gate_2027(px1b: Sequence[float], m6m7: Sequence[float], seed_only: Sequence[float], labels: Sequence[bool],
              events: Sequence[str]) -> dict[str, Any]:
    """§6 FINAL-1 (the P6-Q3 form): PX-1b must beat both M6/M7 and the seed-only comparator, each paired CI < 0."""
    vs_m6m7 = paired_log_loss_gate(px1b, m6m7, labels, events, seed=BOOTSTRAP_SEED)
    vs_seed = paired_log_loss_gate(px1b, seed_only, labels, events, seed=BOOTSTRAP_SEED)
    return {"vs_m6m7": vs_m6m7, "vs_seed_only": vs_seed, "passed": vs_m6m7["passed"] and vs_seed["passed"]}
