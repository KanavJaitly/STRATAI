"""Shared response building blocks for the API's locked contracts (Phase 7, P7-M1).

docs/P7Milestones.md (frozen 2026-10-17) and .agent/phase7/P7_M0_DECISIONS.md P7-Q3 decide three things that every
Phase 7 endpoint family uses, defined once here so the families do not each invent their own:

* **Validation** -- the `validation` block on every new result: a status, the reasons behind it, and optional
  evidence. Statuses are inherited from the engine or record that produced the result; Phase 7 never upgrades one
  (no `validated` unless the source says so).
* **CalibratedWinProbability** -- the M6/M7 win probability, keeping the Phase 4 M12 safeguard: a validated value
  and an unvalidated value are different keys, and the validated key is null whenever the value is not validated.
  The values are the M6/M7 display rule's output (0.05 steps, clipped to [0.05, 0.95]); nothing more precise is
  served.
* **StrategyOdds** -- a P6-M10 (or playoff-track) probability as the P6-A5 display string only ("<5%", ">95%" or a
  0.05-step percentage). No raw probability is ever serialized for these engines (R2, R13).

Plus `error_responses`, which declares each route's error statuses and the exact codes each can carry, so the
OpenAPI document states the whole error contract (P7-M1 (f)).
"""

from __future__ import annotations

import re
from http import HTTPStatus
from typing import Any, Mapping, Sequence

from pydantic import BaseModel, Field, model_validator

from api.errors import INTERNAL_ERROR_CODE, VALIDATION_ERROR_CODE, ErrorResponse, error_code_for_status
from ml.calibration.display import PROBABILITY_DISPLAY_MAX, PROBABILITY_DISPLAY_MIN, PROBABILITY_DISPLAY_STEP

STATUS_VALIDATED_QUALIFICATION = "approximately_calibrated_qualification"
STATUS_NOT_VALIDATED = "not_validated"
# Why an M6/M7 value is outside M7's evaluated population (Phase 4 M12; docs/ml_models.md).
REASON_PLAYOFF_SCOPE = "playoff_scope"
REASON_UNSPECIFIED_CONTEXT = "unspecified_context"
REASON_EPA_INCOMPLETE = "epa_incomplete"
UNVALIDATED_REASONS = (REASON_PLAYOFF_SCOPE, REASON_UNSPECIFIED_CONTEXT, REASON_EPA_INCOMPLETE)
CALIBRATION_STATUS_M7_FAILED = "m7_gate_failed"
# The M6/M7 display rule's grid (ml.calibration.display): 0.05 steps within [0.05, 0.95].
M6M7_DISPLAY_STEP = PROBABILITY_DISPLAY_STEP
M6M7_DISPLAY_MIN = PROBABILITY_DISPLAY_MIN
M6M7_DISPLAY_MAX = PROBABILITY_DISPLAY_MAX
# A declared error code, as error_responses writes it into a response description ("Error codes: `a`, `b`.").
DECLARED_CODE_PATTERN = re.compile(r"`([a-z][a-z0-9_]*)`")


def _on_m6m7_grid(value: float) -> bool:
    steps = value / M6M7_DISPLAY_STEP
    return M6M7_DISPLAY_MIN - 1e-9 <= value <= M6M7_DISPLAY_MAX + 1e-9 and abs(steps - round(steps)) < 1e-9

# The P6-A5 display rule's possible outputs (ml.strategy.display.display_odds): the two bounds, or a whole
# percentage on the 0.05 grid between them.
_ODDS_DISPLAY = re.compile(r"^(<5%|>95%|5%|[1-9][05]%)$")


class ServedModelInfo(BaseModel):
    """A served model's identity, as recorded by the registry (api.ml_loading.ServedModel.identity)."""

    model_type: str
    model_version: str
    model_version_tag: str
    model_sha256: str = Field(description="sha256 of the served registry artifact")
    training_dataset_hash: str
    provenance: dict[str, Any] = Field(description="Where the artifact comes from (source version, frame, record)")


class Validation(BaseModel):
    """How far a result may be trusted, as its producing engine or record states it.

    `status` repeats a label the engine or a write-once record already assigns; the API never assigns a stronger
    one. `reasons` lists every qualifier (for example `p6_m10_gate_failed`, `strategy_effect_unmeasured`, or the
    INTERIM reliability caveat), most important first. `evidence` cites the record or document behind the status.
    """

    status: str = Field(min_length=1, description="The inherited validation label, e.g. not_validated.")
    reasons: list[str] = Field(default_factory=list, description="Qualifiers behind the status; empty when none.")
    evidence: str | None = Field(default=None, description="The record or document the status comes from.")


class CalibratedWinProbability(BaseModel):
    """P(red wins) from the M6/M7 pair (win_prob_xgb_calibrated), keeping the M12 validated/unvalidated split.

    Exactly one of `validated_value` and `unvalidated_value` is set. `validated_value` is set only when the value is
    inside M7's evaluated population (an EPA-complete qualification match); then `validation.status` is
    approximately_calibrated_qualification and `unvalidated_reason` is null. Otherwise `validated_value` is null,
    the model output is in `unvalidated_value`, and `unvalidated_reason` says why (playoff_scope,
    unspecified_context or epa_incomplete). It must not be presented as a probability in that case.
    """

    validated_value: float | None = Field(
        ge=0.0, le=1.0, description="The rounded probability when validated; null otherwise.")
    unvalidated_value: float | None = Field(
        ge=0.0, le=1.0, description="The rounded model output when not validated; null when validated.")
    unvalidated_reason: str | None = Field(
        description="playoff_scope, unspecified_context or epa_incomplete; null when validated.")
    rounding: float = Field(description="The display step both values are rounded to (0.05).")
    calibration_status: str = Field(description="m7_gate_failed: M7 did not pass its calibration gate.")
    validation: Validation
    model: ServedModelInfo

    @model_validator(mode="after")
    def _one_value_and_a_consistent_status(self) -> "CalibratedWinProbability":
        validated = self.validated_value is not None
        if validated == (self.unvalidated_value is not None):
            raise ValueError("exactly one of validated_value and unvalidated_value must be set")
        if validated != (self.unvalidated_reason is None):
            raise ValueError("unvalidated_reason is set exactly when the value is not validated")
        if self.unvalidated_reason is not None and self.unvalidated_reason not in UNVALIDATED_REASONS:
            raise ValueError(f"unvalidated_reason must be one of {UNVALIDATED_REASONS}")
        value = self.validated_value if validated else self.unvalidated_value
        if value is None or not _on_m6m7_grid(value):
            raise ValueError(f"{value} is not an output of the M6/M7 display rule (0.05 steps in [0.05, 0.95]); "
                             "no route may serve more precision than that")
        if self.rounding != M6M7_DISPLAY_STEP or self.calibration_status != CALIBRATION_STATUS_M7_FAILED:
            raise ValueError("rounding is the M6/M7 display step and calibration_status is m7_gate_failed")
        expected = STATUS_VALIDATED_QUALIFICATION if validated else STATUS_NOT_VALIDATED
        if self.validation.status != expected:
            raise ValueError(f"validation.status must be {expected!r} here, not {self.validation.status!r}")
        return self


def m6m7_unvalidated_reason(scope: str, red_teams: Sequence[Any], blue_teams: Sequence[Any]) -> str | None:
    """Why an M6/M7 value is outside M7's evaluated population, or None when it is inside: a qualification match
    whose two non-empty alliances all have prior EPA (scripts/run_m4_baseline_backtest._team_epa_complete). `scope`
    is qualification, playoff or unspecified. One rule for every route that serves the M6/M7 value."""
    epa_complete = bool(red_teams) and bool(blue_teams) and all(t.epa_total_present for t in (*red_teams, *blue_teams))
    if scope == "playoff":
        return REASON_PLAYOFF_SCOPE
    if scope != "qualification":
        return REASON_UNSPECIFIED_CONTEXT
    return None if epa_complete else REASON_EPA_INCOMPLETE


def calibrated_win_probability(shown: float, unvalidated_reason: str | None,
                               model: ServedModelInfo) -> CalibratedWinProbability:
    """The P7-Q3 object for one M6/M7 value already passed through the display rule: validated exactly when no
    reason excludes it from M7's evaluated population (the same decision the route's legacy fields carry)."""
    validated = unvalidated_reason is None
    return CalibratedWinProbability(
        validated_value=shown if validated else None,
        unvalidated_value=None if validated else shown,
        unvalidated_reason=unvalidated_reason,
        rounding=M6M7_DISPLAY_STEP,
        calibration_status=CALIBRATION_STATUS_M7_FAILED,
        # The overall M7 calibration gate failed, so even a validated qualification value carries that qualifier.
        validation=Validation(status=STATUS_VALIDATED_QUALIFICATION if validated else STATUS_NOT_VALIDATED,
                              reasons=([] if validated else [unvalidated_reason]) + [CALIBRATION_STATUS_M7_FAILED],
                              evidence="docs/ml_models.md sections 7 and 10"),
        model=model,
    )


class StrategyOdds(BaseModel):
    """A strategy-conditional (P6-M10) or playoff-track probability, as displayed and never as a raw number.

    `display` is the P6-A5 rule's output ("<5%", ">95%" or a 0.05-step percentage), or null when the engine
    returns no probability (for example a playoff context, `playoff_model_unavailable`, or `insufficient_data`).
    """

    display: str | None = Field(description="'<5%', '>95%', a 0.05-step percentage such as '55%', or null.")
    validation: Validation

    @model_validator(mode="after")
    def _display_is_the_p6_a5_rule(self) -> "StrategyOdds":
        if self.display is not None and not _ODDS_DISPLAY.match(self.display):
            raise ValueError(f"{self.display!r} is not an output of the P6-A5 display rule")
        if self.display is None and not self.validation.reasons:
            raise ValueError("a missing probability must carry the engine's reason")
        return self


def error_responses(codes: Mapping[int, Sequence[str]], *, validates_input: bool = True) -> dict[int | str, Any]:
    """OpenAPI `responses` declaring every error status a route can return and the codes each can carry.

    Every route can fail unexpectedly, so 500 (`internal_error`) is always declared. A route with validated path,
    query or body input also declares 422 `validation_error` unless `validates_input` is False. Each declared
    response uses the one error envelope (api.errors.ErrorResponse), and its description lists the codes as
    `code` literals, which tests/test_phase7_contract.py checks against the code that raises them.
    """
    merged: dict[int, list[str]] = {int(status): list(values) for status, values in codes.items()}
    for status, values in merged.items():
        # api.errors builds every >= 500 body from constants, so a route-specific code there can never be served.
        if status >= 500 and any(code != error_code_for_status(status) for code in values):
            raise ValueError(f"status {status} can only carry {error_code_for_status(status)!r}, not {values}")
    if validates_input:
        merged.setdefault(int(HTTPStatus.UNPROCESSABLE_ENTITY), [])
        if VALIDATION_ERROR_CODE not in merged[int(HTTPStatus.UNPROCESSABLE_ENTITY)]:
            merged[int(HTTPStatus.UNPROCESSABLE_ENTITY)].append(VALIDATION_ERROR_CODE)
    merged.setdefault(int(HTTPStatus.INTERNAL_SERVER_ERROR), [INTERNAL_ERROR_CODE])
    responses: dict[int | str, Any] = {}
    for status in sorted(merged):
        listed = ", ".join(f"`{code}`" for code in merged[status])
        responses[status] = {"model": ErrorResponse,
                             "description": f"{HTTPStatus(status).phrase}. Error codes: {listed}."}
    return responses


__all__ = [
    "CALIBRATION_STATUS_M7_FAILED",
    "CalibratedWinProbability",
    "DECLARED_CODE_PATTERN",
    "M6M7_DISPLAY_MAX",
    "M6M7_DISPLAY_MIN",
    "M6M7_DISPLAY_STEP",
    "REASON_EPA_INCOMPLETE",
    "REASON_PLAYOFF_SCOPE",
    "REASON_UNSPECIFIED_CONTEXT",
    "UNVALIDATED_REASONS",
    "calibrated_win_probability",
    "m6m7_unvalidated_reason",
    "STATUS_NOT_VALIDATED",
    "STATUS_VALIDATED_QUALIFICATION",
    "ServedModelInfo",
    "StrategyOdds",
    "Validation",
    "error_responses",
]
