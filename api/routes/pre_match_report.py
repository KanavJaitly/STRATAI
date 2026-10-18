"""P7-M7: pre-match report data (P7-Q12) -- one structured aggregate per scheduled match.

    GET /matches/{match_key}/pre-match-report[?as_of=...]

A Phase 8 report or a Phase 9 formatter can render this without calling the engines again. Every part is an existing
engine output at one moment, `min(as_of, scheduled_time)` (ml.views.pre_match_report), each with its source:
- `teams[]`: each team's P5-M3 strength view, including its EPA components (auto / teleop / endgame) with
  provenance, Phase 3 scoring statistics recomputed before the moment (reliability is INTERIM), and defense and
  feeding (null with the reason when the scouting observations are too few; never imputed);
- `synergy[]`: each alliance's Phase 4 M9 synergy (`not_validated_against_outcomes`);
- `win_probability`: the M6/M7 value in the shared CalibratedWinProbability object, gated exactly as
  /predictions/matches/{match_key}/win-probability gates it (P7-A7: never in the same field as a strategy odds);
- `strategy`: the P6-M11 engine's recommendation and baseline for each side, from the P6-M10 model (the roles come
  from these strategies); all `not_validated`, as the strategy routes serve them;
- `not_produced`: every ROADMAP Phase 8 report item no engine produces, as null with `not_produced_by_any_engine`
  and its meaning.

A missing model or an engine refusal drops only its own part, with the reason; the report never substitutes. The
stored team_metrics snapshot is never read, so later matches change nothing (tested). No field is free text
generated here: strings are engine labels, identifiers and documented constants.
"""

from __future__ import annotations

from datetime import datetime, timezone
from http import HTTPStatus
from typing import Any, Literal

from fastapi import APIRouter, Depends, Path, Query
from pydantic import BaseModel, Field

from api.contract import CalibratedWinProbability, Validation, error_responses
from api.dependencies import get_database, get_epa_source, get_strategy_model, get_win_prob_model
from api.errors import ApiError
from api.ml_loading import ServedEpaSource, ServedModel
from api.routes.common import (
    AS_OF_DESCRIPTION,
    CODE_EPA_SOURCE_INCOMPLETE,
    CODE_EPA_SOURCE_NOT_LOADED,
    CODE_EPA_SOURCE_PENDING,
    CODE_INVALID_AS_OF,
    EpaSourceInfo,
    epa_info,
    epa_source_incomplete_error,
    parse_as_of,
    require_epa_source,
)
from api.strategy_shapes import AssessmentOut, StrategyContextOut, StrategyModelInfo, assessment_out, context_out
from api.strategy_shapes import model_info as strategy_model_info
from api.win_probability import NoFeatures, evaluate_m6m7
from database.connection import Database
from ml.ratings.statbotics_primary import SilentFallbackError
from ml.strategy.service import MatchNotFound, MatchNotScheduled
from ml.synergy.score import SYNERGY_VALIDATION_STATUS, AllianceSynergyScore
from ml.views.pre_match_report import (
    NOT_PRODUCED,
    NOT_PRODUCED_BY_ANY_ENGINE,
    Absence,
    PreMatchInputs,
    pre_match_inputs,
)
from ml.views.strength import DESCRIPTIVE, RELIABILITY_INTERIM, TeamStrengthView

router = APIRouter(tags=["pre-match report"])

CODE_MATCH_NOT_FOUND = MatchNotFound.code
CODE_MATCH_NOT_SCHEDULED = MatchNotScheduled.code
WIN_PROB_MODEL_NOT_LOADED = Absence("model_not_loaded", "win_prob_xgb_calibrated (M6/M7) is not pinned/loadable")
INSUFFICIENT_FEATURES = Absence("insufficient_features", "every team has zero real features before the moment")

SOURCE_STRENGTH = "ml.views.strength.build_team_strength (P5-M3)"
SOURCE_SYNERGY = "ml.synergy.score.alliance_synergy (Phase 4 M9)"
SOURCE_WIN_PROBABILITY = ("win_prob_xgb_calibrated (Phase 4 M6/M7), gated as "
                          "/predictions/matches/{match_key}/win-probability")
SOURCE_STRATEGY = "ml.strategy.engine.StrategyEngine.recommend with the P6-M10 model (P6-M11, via P7-M5)"


# --- shapes ---------------------------------------------------------------------------------------------------------


class NotProduced(BaseModel):
    value: None = Field(default=None, description="Always null: no engine produces this item today (P7-Q12).")
    reason: Literal["not_produced_by_any_engine"] = NOT_PRODUCED_BY_ANY_ENGINE
    semantics: str = Field(description="What the item would mean, if an engine produced it.")


class NotProducedItems(BaseModel):
    strengths_and_weaknesses: NotProduced
    defensive_threats: NotProduced
    key_risks: NotProduced
    predicted_flow: NotProduced
    critical_matchups: NotProduced
    key_success_factors: NotProduced


class PreMatchTeam(BaseModel):
    team_number: int
    alliance: Literal["red", "blue"]
    strength: TeamStrengthView = Field(description="The P5-M3 view at the report's as_of; epa carries the EPA "
                                                   "components (auto / teleop / endgame) with provenance.")
    validation: Validation = Field(description="descriptive, with the INTERIM reliability caveat.")


class AllianceSynergyOut(BaseModel):
    alliance: Literal["red", "blue"]
    team_numbers: list[int]
    score: AllianceSynergyScore | None = Field(description="Null when the alliance does not have three teams.")
    absent_code: Literal["alliance_incomplete"] | None = Field(description="Why score is null; null when present.")
    absent_reason: str | None = Field(description="The same, in words.")
    validation: Validation


class WinProbabilitySection(BaseModel):
    probability_scope: Literal["qualification", "playoff", "unspecified"]
    value: CalibratedWinProbability | None = Field(description="Null when the model is not loaded or there are no "
                                                               "features (see absent_code).")
    absent_code: Literal["model_not_loaded", "insufficient_features"] | None = Field(
        description="Why value is null; null when present.")
    absent_reason: str | None = Field(description="The same, in words.")
    source: str = SOURCE_WIN_PROBABILITY


class StrategySide(BaseModel):
    side: Literal["red", "blue"]
    recommended: AssessmentOut | None = Field(description="Null when the engine returns no probability "
                                                          "(see unavailable_reasons).")
    baseline: AssessmentOut | None
    vs_baseline_label: str | None
    candidates_evaluated: int
    selection_note: str
    unavailable_reasons: list[str]


class StrategySection(BaseModel):
    model: StrategyModelInfo | None
    context: StrategyContextOut | None
    sides: list[StrategySide] = Field(description="Red, then blue; empty when the section is absent.")
    absent_code: Literal["model_not_loaded", "match_context_unknown", "alliance_incomplete",
                         "mixed_season_scale"] | None = Field(description="Why sides is empty; null when present.")
    absent_reason: str | None = Field(description="The same, in words.")
    source: str = SOURCE_STRATEGY


class PreMatchReportResponse(BaseModel):
    match_key: str
    event_key: str
    competition_level: str | None
    scheduled_time: datetime
    as_of: datetime = Field(description="The one moment every part is taken at: min(as_of, scheduled_time).")
    as_of_source: Literal["scheduled_time", "requested", "now"] = Field(
        description="scheduled_time: the match's scheduled time (the requested or current time is later); "
                    "requested: the caller's earlier as_of; now: the default, while the match is still ahead.")
    red_team_numbers: list[int]
    blue_team_numbers: list[int]
    epa: EpaSourceInfo
    teams: list[PreMatchTeam] = Field(description="Red, then blue. Source: " + SOURCE_STRENGTH + ".")
    synergy: list[AllianceSynergyOut] = Field(description="Red, then blue. Source: " + SOURCE_SYNERGY + ".")
    win_probability: WinProbabilitySection
    strategy: StrategySection
    not_produced: NotProducedItems


# --- serialization --------------------------------------------------------------------------------------------------


def _absent(absence: Absence | None) -> dict[str, str | None]:
    return {"absent_code": None if absence is None else absence.code,
            "absent_reason": None if absence is None else absence.reason}


def _win_probability(found: PreMatchInputs, served: ServedModel | None) -> WinProbabilitySection:
    """The one M6/M7 evaluation (api.win_probability), at the report's moment."""
    scope = found.probability_scope
    if served is None:
        return WinProbabilitySection(probability_scope=scope, value=None, **_absent(WIN_PROB_MODEL_NOT_LOADED))
    try:
        value = evaluate_m6m7(served, found.row, scope)
    except NoFeatures:
        return WinProbabilitySection(probability_scope=scope, value=None, **_absent(INSUFFICIENT_FEATURES))
    return WinProbabilitySection(probability_scope=scope, value=value.calibrated(), **_absent(None))


def _strategy(found: PreMatchInputs, model: Any) -> StrategySection:
    if found.strategy_absent is not None or found.strategy_context is None:
        return StrategySection(model=None if model is None else strategy_model_info(model), context=None, sides=[],
                               **_absent(found.strategy_absent))
    sides = []
    for side in found.strategies:
        result = side.recommendation
        sides.append(StrategySide(
            side=side.side,
            recommended=None if result.recommended is None else assessment_out(result.recommended),
            baseline=None if result.baseline is None else assessment_out(result.baseline),
            vs_baseline_label=result.vs_baseline.get("label") if result.recommended is not None else None,
            candidates_evaluated=result.candidates_evaluated, selection_note=result.selection_note,
            unavailable_reasons=[r for r in (result.unavailable_reason or "").split(",") if r]))
    return StrategySection(model=strategy_model_info(model), context=context_out(found.strategy_context),
                           sides=sides, **_absent(None))


def _report(found: PreMatchInputs, as_of_source: str, served: ServedModel | None, model: Any,
            epa_source: ServedEpaSource) -> PreMatchReportResponse:
    teams = (*found.row.red_teams, *found.row.blue_teams)
    synergy = [AllianceSynergyOut(alliance=colour, team_numbers=[t.team_number for t in members],
                                  score=found.synergy[colour], **_absent(found.synergy_absent[colour]),
                                  validation=Validation(status=SYNERGY_VALIDATION_STATUS))
               for colour, members in (("red", found.row.red_teams), ("blue", found.row.blue_teams))]
    return PreMatchReportResponse(
        match_key=found.match_key, event_key=found.event_key, competition_level=found.competition_level,
        scheduled_time=found.scheduled_time, as_of=found.moment, as_of_source=as_of_source,
        red_team_numbers=[t.team_number for t in found.row.red_teams],
        blue_team_numbers=[t.team_number for t in found.row.blue_teams],
        epa=epa_info(epa_source, found.moment, [t.epa_source_state for t in teams]),
        teams=[PreMatchTeam(team_number=view.team_number, alliance=colour, strength=view,
                            validation=Validation(status=DESCRIPTIVE, reasons=[RELIABILITY_INTERIM]))
               for colour, view in found.strengths],
        synergy=synergy, win_probability=_win_probability(found, served), strategy=_strategy(found, model),
        not_produced=NotProducedItems(**{item: NotProduced(semantics=meaning)
                                         for item, meaning in NOT_PRODUCED.items()}),
    )


# --- route ----------------------------------------------------------------------------------------------------------


@router.get(
    "/matches/{match_key}/pre-match-report",
    response_model=PreMatchReportResponse,
    summary="Pre-match report data for one scheduled match (P7-Q12)",
    description="Every part of a pre-match report that an engine produces, at min(as_of, scheduled_time), from "
                "point-in-time sources only (never the stored team_metrics snapshot): team strength with EPA "
                "components, alliance synergy, the M6/M7 win probability, and the P6-M10 strategy for each side. "
                "Items no engine produces are null with not_produced_by_any_engine. A missing model drops only its "
                "own part, with the reason. reliability_score is an INTERIM placeholder (an attendance ratio, not a "
                "robot-failure measure).",
    responses=error_responses({
        HTTPStatus.NOT_FOUND: [CODE_MATCH_NOT_FOUND, CODE_EPA_SOURCE_NOT_LOADED],
        HTTPStatus.UNPROCESSABLE_ENTITY: [CODE_MATCH_NOT_SCHEDULED, CODE_INVALID_AS_OF, CODE_EPA_SOURCE_INCOMPLETE,
                                          CODE_EPA_SOURCE_PENDING],
    }, validates_input=False),  # match_key is a non-empty path segment; a malformed as_of is invalid_as_of
)
def pre_match_report(
    match_key: str = Path(min_length=1, description="TBA match key, e.g. 2026casj_qm12."),
    as_of: str | None = Query(default=None, description=AS_OF_DESCRIPTION + " The report is taken at "
                                                                             "min(as_of, scheduled_time)."),
    database: Database = Depends(get_database),
    served: ServedModel | None = Depends(get_win_prob_model),
    strategy_model: Any = Depends(get_strategy_model),
    epa_source: ServedEpaSource | None = Depends(get_epa_source),
) -> PreMatchReportResponse:
    epa_source = require_epa_source(epa_source)
    requested = parse_as_of(as_of) if as_of is not None else None
    when = requested or datetime.now(timezone.utc)
    try:
        found = pre_match_inputs(database, match_key, when, epa_provider=epa_source.provider,
                                 strategy_model=strategy_model)
    except MatchNotFound as exc:
        raise ApiError(status_code=HTTPStatus.NOT_FOUND, code=CODE_MATCH_NOT_FOUND,
                       message=f"Match '{match_key}' is not known to StratAI.") from exc
    except MatchNotScheduled as exc:
        raise ApiError(status_code=HTTPStatus.UNPROCESSABLE_ENTITY, code=CODE_MATCH_NOT_SCHEDULED,
                       message=f"Match '{match_key}' has no scheduled time, so no pre-match moment exists.") from exc
    except SilentFallbackError as exc:
        raise epa_source_incomplete_error(exc) from exc
    source = "scheduled_time" if found.moment == found.scheduled_time else ("requested" if requested else "now")
    return _report(found, source, served, strategy_model, epa_source)


__all__ = ["router"]
