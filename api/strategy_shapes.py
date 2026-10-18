"""The P6-M10 / P6-M11 strategy response shapes and their builders, shared by the match strategy routes (P7-M5) and
the pre-match report (P7-M7), so the report reuses them without importing a route (P7-A3). Moved here unchanged from
api.routes.strategy in P7-M7; the OpenAPI schema names are unchanged.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field

from api.contract import StrategyOdds, Validation
from ml.strategy.engine import Assessment
from ml.strategy.outcome import MODEL_TYPE, MODEL_VERSION
from ml.strategy.representation import Strategy
from ml.strategy.service import StrategyContext


class StrategyModelInfo(BaseModel):
    model_type: str
    model_version: str
    model_version_tag: str
    model_sha256: str = Field(description="sha256 of the served registry artifact (required by the pin)")
    spec_sha256: str = Field(description="sha256 of the frozen P6-M10 model specification")


class StrategyContextOut(BaseModel):
    match_key: str | None = Field(description="The scheduled match, or null for a hypothetical alliance.")
    event_key: str
    as_of: datetime = Field(description="The moment the inputs are taken at: for a scheduled match "
                                         "min(now or the requested as_of, its scheduled time).")
    match_context: Literal["qualification", "playoff"]
    competition_level: str | None = Field(description="The scheduled match's TBA level; null for a hypothetical.")
    red_team_numbers: list[int]
    blue_team_numbers: list[int]
    coach_observations_applied: int = Field(
        description="Valid coach observations for this event, observed and stored before as_of, in the context "
                    "every strategy sees. Only those about these six teams change odds; any of them adds the "
                    "coach_observation_effect_unmeasured reason (the engine's rule).")
    coach_observations_invalid_ignored: int = Field(description="Submissions for this event stored before as_of that "
                                                                "failed validation; recorded, never applied.")


class AssessmentOut(BaseModel):
    strategy: Strategy
    opponent_strategy: Strategy
    odds: StrategyOdds = Field(description="The advised side's odds of winning: a display string, never a raw "
                                           "probability, with the engine's status and reasons.")


def model_info(model: Any) -> StrategyModelInfo:
    return StrategyModelInfo(model_type=MODEL_TYPE, model_version=MODEL_VERSION, model_version_tag=model.version_tag,
                             model_sha256=model.artifact_sha256, spec_sha256=model.spec_sha256)


def context_out(found: StrategyContext) -> StrategyContextOut:
    return StrategyContextOut(
        match_key=found.match_key, event_key=found.event_key, as_of=found.as_of, match_context=found.match_context,
        competition_level=found.competition_level,
        red_team_numbers=[t.team_number for t in found.context.red_teams],
        blue_team_numbers=[t.team_number for t in found.context.blue_teams],
        coach_observations_applied=found.observations_applied,
        coach_observations_invalid_ignored=found.observations_invalid_ignored)


def odds(display: str | None, status: str, reasons: list[str]) -> StrategyOdds:
    return StrategyOdds(display=display, validation=Validation(status=status, reasons=reasons))


def assessment_out(assessment: Assessment) -> AssessmentOut:
    evaluation = assessment.evaluation
    return AssessmentOut(strategy=assessment.strategy, opponent_strategy=assessment.opponent_strategy,
                         odds=odds(assessment.display_ours, evaluation.validation_status, list(evaluation.reasons)))


__all__ = ["AssessmentOut", "StrategyContextOut", "StrategyModelInfo", "assessment_out", "context_out", "model_info",
           "odds"]
