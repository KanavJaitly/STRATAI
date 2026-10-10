"""Which P6-M10 strategy model is served, and its status: the P6-M10b serving-switch guard (frozen spec
`.agent/phase6/P6_M10B_SPEC.md` §7, C11).

v2 (`p6m10b-v1`, the calibrated model) replaces v1 **only if all three hold**:
1. `results/p6_m10b_outcome_model.json` exists with `passed: true`.
2. Kanav's confirmation `decisions/p6_m10b_confirmation.json`: `confirmed: true`, `confirmed_by`, `date`,
   `record: "p6_m10b_outcome_model.json"`, and `record_sha256` equal to that file's sha256.
3. A passing P6-M13 parity rerun on v2, `results/p6_m13_parity_audit_m10b.json`: `p6_dm2_met: true`, and its audited
   model identity (base sha256 + calibrator sha256) equal to the identity the outcome record evaluated.

Otherwise v1 stays served with its current status (`not_validated`, `p6_m10_gate_failed`). No configuration
bypasses this. `load_served_strategy_model` is the one place a served strategy model is chosen.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

OUTCOME_RECORD = "p6_m10b_outcome_model.json"
CONFIRMATION = "p6_m10b_confirmation.json"
PARITY_RECORD = "p6_m13_parity_audit_m10b.json"


def _json(path: Path) -> dict[str, Any] | None:
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else None


def _identity(value: dict[str, Any] | None) -> tuple[str | None, str | None]:
    model = (value or {}).get("model_identity") or {}
    return model.get("base_sha256"), model.get("calibrator_sha256")


def m10b_serving_decision(results_dir: Path, decisions_dir: Path) -> dict[str, Any]:
    """§7's three conditions. `serve_v2` is true only when all hold; `refusals` names every one that does not."""
    refusals: list[str] = []
    outcome_path = Path(results_dir) / OUTCOME_RECORD
    outcome = _json(outcome_path)
    if outcome is None:
        refusals.append(f"{OUTCOME_RECORD} does not exist")
    elif outcome.get("passed") is not True:
        refusals.append(f"{OUTCOME_RECORD} did not pass")
    confirmation = _json(Path(decisions_dir) / CONFIRMATION)
    if confirmation is None:
        refusals.append(f"{CONFIRMATION} (Kanav's dated confirmation) does not exist")
    else:
        actual = hashlib.sha256(outcome_path.read_bytes()).hexdigest() if outcome_path.exists() else None
        if not (confirmation.get("confirmed") is True and confirmation.get("confirmed_by") and confirmation.get("date")
                and confirmation.get("record") == OUTCOME_RECORD and confirmation.get("record_sha256") == actual):
            refusals.append(f"{CONFIRMATION} does not confirm the current {OUTCOME_RECORD}")
    parity = _json(Path(results_dir) / PARITY_RECORD)
    if parity is None:
        refusals.append(f"{PARITY_RECORD} (the P6-M13 parity rerun on v2) does not exist")
    else:
        if parity.get("p6_dm2_met") is not True:
            refusals.append(f"{PARITY_RECORD} did not pass")
        if outcome is None or _identity(parity) != _identity(outcome) or None in _identity(parity):
            refusals.append(f"{PARITY_RECORD} audited a different model identity than {OUTCOME_RECORD}")
    return {"serve_v2": not refusals, "refusals": refusals,
            "model_identity": dict(zip(("base_sha256", "calibrator_sha256"), _identity(outcome)))}


def load_served_strategy_model(registry_dir: Path, results_dir: Path, decisions_dir: Path,
                               season_of: Callable[[str], int | None], *, v1_sha256: str | None = None):
    """The served strategy model: v2 with `validated` baseline status only when the guard passes, else v1 unchanged.
    When v2 is served, its base and calibrator are loaded only with the sha256 the outcome record evaluated."""
    from ml.registry import load_registered_model
    from ml.strategy.calibration import (CALIBRATOR_MODEL_TYPE, CALIBRATOR_VERSION_TAG, GROUPS, Calibrator,
                                         CalibratedOutcomeModel)
    from ml.strategy.outcome import VALIDATED, load_registered_strategy_model

    decision = m10b_serving_decision(results_dir, decisions_dir)
    if not decision["serve_v2"]:
        return load_registered_strategy_model(registry_dir, expected_sha256=v1_sha256), decision
    identity = decision["model_identity"]
    base = load_registered_strategy_model(registry_dir, expected_sha256=identity["base_sha256"])
    calibrator, _ = load_registered_model(Calibrator, registry_dir=registry_dir, model_type=CALIBRATOR_MODEL_TYPE,
                                          version_tag=CALIBRATOR_VERSION_TAG, current_feature_list=list(GROUPS),
                                          expected_sha256=identity["calibrator_sha256"])
    return CalibratedOutcomeModel(base, calibrator, season_of, baseline_status=(VALIDATED, None)), decision
