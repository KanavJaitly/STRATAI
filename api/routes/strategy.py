"""P7-M5: the match strategy endpoints -- the P6-M11 engine over HTTP, for the AI and coach paths (P7-Q9, P7-Q10).

    POST /strategy/matches/{match_key}/assess        a given strategy for a scheduled match
    POST /strategy/matches/{match_key}/recommend     the AI strategy (exhaustive search)
    POST /strategy/matches/{match_key}/compare       two strategies (e.g. the AI's and a coach's)
    POST /strategy/hypothetical/assess | recommend | compare   the same, for a hypothetical 3v3 alliance
    POST /strategy/coach-strategies                  store a coach strategy (write token; raw-first)
    POST /strategy/coach-observations                store a coach observation (write token; raw-first)

**One model, one path.** Every probability comes from the P6-M10 model through StrategyEngine.assess; the AI
recommender and the coach paths differ only in where the strategy came from, which no evaluation input carries
(P6-DM2). The routes never round, clip, cache or relabel a probability: odds are the engine's display strings
(P6-A5), in api.contract.StrategyOdds, with the engine's own status and reasons. No raw probability, mean
difference, sigma or component mean is ever serialized (R2, R13).

**What the odds are.** Every strategy probability is `not_validated`: the baseline carries `p6_m10_gate_failed`
(the model's calibration gate failed), and any other strategy adds `strategy_effect_unmeasured` (plus
`defense_effect_insufficient_data`, `feeding_effect_insufficient_data`, `coach_observation_effect_unmeasured` as
they apply). A playoff context returns no probability (`playoff_model_unavailable`); missing inputs return none
either (`insufficient_data`, `missing_input:*`). The recommendation is the maximum of many model estimates, which
is not an unbiased probability (`selection_note`).

**Contexts.** A scheduled match is evaluated at min(now, its scheduled time) (P7-D6). A hypothetical alliance needs an
explicit `match_context` (qualification or playoff; omitted is 422) and an optional `as_of` (default now; not in
the future, P7-D1). Both paths see the identical context, including the same coach observations
(ml.strategy.service).

**Coach writes** need the X-StratAI-Write-Token header (api.routes.common.require_writer: fail closed; one shared
secret, no per-user identity). The body is the raw JSON object: it is landed in raw_source_payloads before
validation, so a rejected submission (invalid_coach_input) stays recorded; a 403 or a non-object body is not
stored. `author` and `observer` are caller-asserted strings, not authenticated identities.
"""

from __future__ import annotations

from datetime import datetime, timezone
from http import HTTPStatus
from typing import Any, Literal

from fastapi import APIRouter, Body, Depends, Path, Query
from pydantic import BaseModel, Field, model_validator

from api.contract import StrategyOdds, error_responses
from api.dependencies import get_database, get_epa_source, get_strategy_model
from api.errors import ApiError
from api.ml_loading import ServedEpaSource
from api.routes.common import (
    AS_OF_DESCRIPTION,
    CODE_MODEL_NOT_LOADED,
    model_not_loaded_error,
    problems_suffix,
    CODE_EPA_SOURCE_INCOMPLETE,
    CODE_EPA_SOURCE_NOT_LOADED,
    CODE_EPA_SOURCE_PENDING,
    CODE_EVENT_NOT_FOUND,
    CODE_INVALID_AS_OF,
    CODE_TEAM_NOT_FOUND,
    CODE_WRITE_NOT_AUTHORIZED,
    CODE_WRITES_DISABLED,
    EpaSourceInfo,
    epa_info,
    epa_source_incomplete_error,
    event_not_found_error,
    parse_as_of,
    require_epa_source,
    require_teams_rostered,
    require_writer,
)
from api.strategy_shapes import AssessmentOut, StrategyContextOut, StrategyModelInfo
from api.strategy_shapes import assessment_out as _assessment_out
from api.strategy_shapes import context_out as _context_out
from api.strategy_shapes import model_info as _model_info
from database.connection import Database
from ml.features.roster import event_exists
from ml.ratings.statbotics_primary import SilentFallbackError
from ml.strategy.coach_inputs import CoachInputError, submit_coach_observation, submit_coach_strategy
from ml.strategy.display import compare_odds
from ml.strategy.engine import StrategyEngine
from ml.strategy.representation import CoachObservation, Strategy, StrategyError
from ml.strategy.service import (
    AllianceIncomplete,
    MatchContextUnknown,
    MatchNotFound,
    MatchNotScheduled,
    MixedSeasonScale,
    StrategyContext,
    StrategyContextError,
    context_for_alliances,
    context_for_match,
    evaluate_typed,
)

router = APIRouter(prefix="/strategy", tags=["match strategy"])

CODE_MATCH_NOT_FOUND = MatchNotFound.code
CODE_MATCH_NOT_SCHEDULED = MatchNotScheduled.code
CODE_MATCH_CONTEXT_UNKNOWN = MatchContextUnknown.code
CODE_ALLIANCE_INCOMPLETE = AllianceIncomplete.code
CODE_MIXED_SEASON_SCALE = MixedSeasonScale.code
CODE_INVALID_STRATEGY = "invalid_strategy"
CODE_INVALID_COACH_INPUT = "invalid_coach_input"

_CONTEXT_STATUS = {
    MatchNotFound: HTTPStatus.NOT_FOUND,
    MatchNotScheduled: HTTPStatus.UNPROCESSABLE_ENTITY,
    MatchContextUnknown: HTTPStatus.UNPROCESSABLE_ENTITY,
    AllianceIncomplete: HTTPStatus.CONFLICT,
    MixedSeasonScale: HTTPStatus.CONFLICT,
}
_CONTEXT_MESSAGES = {
    MatchNotFound: "Match '{subject}' is not known to StratAI.",
    MatchNotScheduled: "Match '{subject}' has no scheduled time, so no pre-match moment exists to evaluate it at.",
    MatchContextUnknown: "Match '{subject}' has no competition level, so it is neither a qualification nor a known "
                         "playoff match.",
    AllianceIncomplete: "Match '{subject}' does not have three teams per alliance; the strategy model needs 3v3.",
    MixedSeasonScale: "The six teams disagree on the season scale, which the strategy model cannot combine.",
}


# --- shapes ---------------------------------------------------------------------------------------------------------


class AssessResponse(BaseModel):
    side: Literal["red", "blue"]
    context: StrategyContextOut
    model: StrategyModelInfo
    epa: EpaSourceInfo
    assessment: AssessmentOut


class RecommendResponse(BaseModel):
    side: Literal["red", "blue"]
    context: StrategyContextOut
    model: StrategyModelInfo
    epa: EpaSourceInfo
    recommended: AssessmentOut | None = Field(description="Null when the engine returns no probability "
                                                          "(see unavailable_reasons).")
    alternatives: list[AssessmentOut] = Field(description="The next-best distinct strategies, at most 5.")
    baseline: AssessmentOut | None = Field(description="Every robot scoring everything, under the same model.")
    vs_baseline_label: str | None = Field(description="The display rule's comparison of the recommendation with "
                                                      "the baseline; null when no recommendation exists.")
    candidates_evaluated: int
    selection_note: str = Field(description="The recommendation is the maximum of many model estimates, not an "
                                            "unbiased probability (P6-Q10).")
    unavailable_reasons: list[str] = Field(description="Why no recommendation exists; empty when one does.")


class CompareSide(BaseModel):
    strategy: Strategy
    odds: StrategyOdds


class CompareResponse(BaseModel):
    side: Literal["red", "blue"]
    context: StrategyContextOut
    model: StrategyModelInfo
    epa: EpaSourceInfo
    opponent_strategy: Strategy
    first: CompareSide
    second: CompareSide
    label: str = Field(description="indistinguishable at model resolution / differs by at least one display step "
                                   "(not a claim that either strategy is better) / not comparable: a probability is "
                                   "unavailable.")


class AssessBody(BaseModel):
    side: Literal["red", "blue"]
    strategy: Strategy
    opponent_strategy: Strategy | None = Field(default=None, description="Default: the opponent's baseline.")


class RecommendBody(BaseModel):
    side: Literal["red", "blue"]
    opponent_strategy: Strategy | None = Field(default=None, description="Default: the opponent's baseline.")


class CompareBody(BaseModel):
    side: Literal["red", "blue"]
    first: Strategy
    second: Strategy
    opponent_strategy: Strategy | None = Field(default=None, description="Default: the opponent's baseline.")


class HypotheticalAlliances(BaseModel):
    event_key: str = Field(min_length=1)
    red_team_numbers: list[int] = Field(min_length=3, max_length=3)
    blue_team_numbers: list[int] = Field(min_length=3, max_length=3)
    match_context: Literal["qualification", "playoff"] = Field(
        description="Required (P7-Q9): there is no silent qualification default.")

    @model_validator(mode="after")
    def _six_distinct_teams(self) -> "HypotheticalAlliances":
        """A real 3v3 has six distinct teams: none twice on one side, none on both (R14: a 422, never a 500 or
        odds for a match that cannot exist)."""
        if len(set(self.red_team_numbers) | set(self.blue_team_numbers)) != 6:
            raise ValueError("a hypothetical match needs six distinct teams, three per alliance")
        return self


class HypotheticalAssessBody(HypotheticalAlliances, AssessBody):
    pass


class HypotheticalRecommendBody(HypotheticalAlliances, RecommendBody):
    pass


class HypotheticalCompareBody(HypotheticalAlliances, CompareBody):
    pass


class CoachStrategyStored(BaseModel):
    event_key: str
    match_key: str | None
    strategy: Strategy
    strategy_sha256: str
    origin: Literal["human_entered"]
    author: str = Field(description="As supplied by the caller: not an authenticated identity.")
    created_at: datetime


class CoachObservationStored(BaseModel):
    observation: CoachObservation


# --- helpers --------------------------------------------------------------------------------------------------------


def _require_model(model: Any) -> Any:
    if model is None:
        raise model_not_loaded_error("strategy_outcome_component (P6-M10)")
    return model


def _context_error(exc: StrategyContextError, subject: str) -> ApiError:
    kind = type(exc)
    return ApiError(status_code=_CONTEXT_STATUS[kind], code=exc.code,
                    message=_CONTEXT_MESSAGES[kind].format(subject=subject))


def _epa(found: StrategyContext, epa_source: ServedEpaSource) -> EpaSourceInfo:
    """The EPA source envelope every EPA-backed route serves (P7-D3): its identity, whether it is the evaluated
    configuration, the P5-D3 adoption, and live_refresh_not_yet_validated when it applies to these six teams."""
    teams = (*found.context.red_teams, *found.context.blue_teams)
    return epa_info(epa_source, found.as_of, [t.epa_source_state for t in teams])


def _match_context(database: Database, match_key: str, epa_source: ServedEpaSource) -> StrategyContext:
    try:
        # P7-D6: the moment is min(now, scheduled_time); an upcoming match is evaluated now, never at its future time
        return context_for_match(database, match_key, epa_provider=epa_source.provider,
                                 as_of=datetime.now(timezone.utc))
    except StrategyContextError as exc:
        raise _context_error(exc, match_key) from exc
    except SilentFallbackError as exc:
        raise epa_source_incomplete_error(exc) from exc


def _hypothetical_context(database: Database, body: HypotheticalAlliances, as_of: str | None,
                          epa_source: ServedEpaSource) -> StrategyContext:
    when = parse_as_of(as_of)
    if not event_exists(database, body.event_key):
        raise event_not_found_error(body.event_key)
    require_teams_rostered(database, body.event_key, body.red_team_numbers + body.blue_team_numbers)
    try:
        return context_for_alliances(database, body.event_key, body.red_team_numbers, body.blue_team_numbers,
                                     body.match_context, when, epa_provider=epa_source.provider)
    except SilentFallbackError as exc:
        raise epa_source_incomplete_error(exc) from exc


def _run(found: StrategyContext, call):
    """Run one engine call with its refusals typed: invalid_strategy (the engine's StrategyError) and
    mixed_season_scale (only where the engine itself refuses). Anything else is a fault (500)."""
    try:
        return evaluate_typed(found.context, call)
    except StrategyError as exc:
        raise ApiError(status_code=HTTPStatus.UNPROCESSABLE_ENTITY, code=CODE_INVALID_STRATEGY,
                       message=f"The strategy does not fit this match: {exc}") from exc
    except MixedSeasonScale as exc:
        raise _context_error(exc, found.match_key or found.event_key) from exc


def _assess(found: StrategyContext, model: Any, body: AssessBody, epa_source: ServedEpaSource) -> AssessResponse:
    assessment = _run(found, lambda: StrategyEngine(model).assess(found.context, body.side, body.strategy,
                                                                  body.opponent_strategy))
    return AssessResponse(side=body.side, context=_context_out(found), model=_model_info(model),
                          epa=_epa(found, epa_source),
                          assessment=_assessment_out(assessment))


def _recommend(found: StrategyContext, model: Any, body: RecommendBody,
               epa_source: ServedEpaSource) -> RecommendResponse:
    result = _run(found, lambda: StrategyEngine(model).recommend(found.context, body.side, body.opponent_strategy))
    vs = result.vs_baseline.get("label") if result.recommended is not None else None
    return RecommendResponse(
        side=body.side, context=_context_out(found), model=_model_info(model), epa=_epa(found, epa_source),
        recommended=None if result.recommended is None else _assessment_out(result.recommended),
        alternatives=[_assessment_out(a) for a in result.alternatives],
        baseline=None if result.baseline is None else _assessment_out(result.baseline),
        vs_baseline_label=vs, candidates_evaluated=result.candidates_evaluated, selection_note=result.selection_note,
        unavailable_reasons=[r for r in (result.unavailable_reason or "").split(",") if r])


def _compare(found: StrategyContext, model: Any, body: CompareBody, epa_source: ServedEpaSource) -> CompareResponse:
    engine = StrategyEngine(model)
    first = _run(found, lambda: engine.assess(found.context, body.side, body.first, body.opponent_strategy))
    second = _run(found, lambda: engine.assess(found.context, body.side, body.second, body.opponent_strategy))
    return CompareResponse(
        side=body.side, context=_context_out(found), model=_model_info(model), epa=_epa(found, epa_source),
        opponent_strategy=first.opponent_strategy,
        first=CompareSide(strategy=first.strategy, odds=_assessment_out(first).odds),
        second=CompareSide(strategy=second.strategy, odds=_assessment_out(second).odds),
        label=str(compare_odds(first.p_ours, second.p_ours)["label"]))


# --- declared errors ------------------------------------------------------------------------------------------------

_MATCH_ERRORS = error_responses({
    HTTPStatus.NOT_FOUND: [CODE_MODEL_NOT_LOADED, CODE_EPA_SOURCE_NOT_LOADED, CODE_MATCH_NOT_FOUND],
    HTTPStatus.CONFLICT: [CODE_ALLIANCE_INCOMPLETE, CODE_MIXED_SEASON_SCALE],
    HTTPStatus.UNPROCESSABLE_ENTITY: [CODE_MATCH_NOT_SCHEDULED, CODE_MATCH_CONTEXT_UNKNOWN, CODE_INVALID_STRATEGY,
                                      CODE_EPA_SOURCE_INCOMPLETE, CODE_EPA_SOURCE_PENDING],
})
_HYPOTHETICAL_ERRORS = error_responses({
    HTTPStatus.NOT_FOUND: [CODE_MODEL_NOT_LOADED, CODE_EPA_SOURCE_NOT_LOADED, CODE_EVENT_NOT_FOUND,
                           CODE_TEAM_NOT_FOUND],
    HTTPStatus.CONFLICT: [CODE_MIXED_SEASON_SCALE],
    HTTPStatus.UNPROCESSABLE_ENTITY: [CODE_INVALID_AS_OF, CODE_INVALID_STRATEGY, CODE_EPA_SOURCE_INCOMPLETE,
                                      CODE_EPA_SOURCE_PENDING],
})
_WRITE_ERRORS = error_responses({
    HTTPStatus.FORBIDDEN: [CODE_WRITES_DISABLED, CODE_WRITE_NOT_AUTHORIZED],
    HTTPStatus.UNPROCESSABLE_ENTITY: [CODE_INVALID_COACH_INPUT],
})
_STATUS_NOTE = (" Every probability is not_validated (p6_m10_gate_failed for the baseline; strategy_effect_unmeasured "
                "for any other strategy); a playoff context or missing inputs give no probability, with the reason. "
                "Odds are display strings only.")


# --- scheduled match ------------------------------------------------------------------------------------------------


@router.post("/matches/{match_key}/assess", response_model=AssessResponse, responses=_MATCH_ERRORS,
             summary="Assess a given strategy for a scheduled match",
             description="One side's strategy against the opponent's (default: baseline), as of the match's "
                         "scheduled time, through the single engine path." + _STATUS_NOTE)
def assess_match(body: AssessBody, match_key: str = Path(min_length=1), database: Database = Depends(get_database),
                 model: Any = Depends(get_strategy_model),
                 epa_source: ServedEpaSource | None = Depends(get_epa_source)) -> AssessResponse:
    model = _require_model(model)
    found = _match_context(database, match_key, require_epa_source(epa_source))
    return _assess(found, model, body, epa_source)


@router.post("/matches/{match_key}/recommend", response_model=RecommendResponse, responses=_MATCH_ERRORS,
             summary="The AI strategy for a scheduled match",
             description="An exhaustive search over the side's strategy space, every candidate through the same "
                         "engine path as a coach assessment." + _STATUS_NOTE)
def recommend_match(body: RecommendBody, match_key: str = Path(min_length=1),
                    database: Database = Depends(get_database), model: Any = Depends(get_strategy_model),
                    epa_source: ServedEpaSource | None = Depends(get_epa_source)) -> RecommendResponse:
    model = _require_model(model)
    found = _match_context(database, match_key, require_epa_source(epa_source))
    return _recommend(found, model, body, epa_source)


@router.post("/matches/{match_key}/compare", response_model=CompareResponse, responses=_MATCH_ERRORS,
             summary="Compare two strategies (e.g. the AI's and a coach's) for a scheduled match",
             description="Both strategies under the same model and inputs, with the display rule's label; neither "
                         "is claimed better." + _STATUS_NOTE)
def compare_match(body: CompareBody, match_key: str = Path(min_length=1), database: Database = Depends(get_database),
                  model: Any = Depends(get_strategy_model),
                  epa_source: ServedEpaSource | None = Depends(get_epa_source)) -> CompareResponse:
    model = _require_model(model)
    found = _match_context(database, match_key, require_epa_source(epa_source))
    return _compare(found, model, body, epa_source)


# --- hypothetical alliance ------------------------------------------------------------------------------------------


@router.post("/hypothetical/assess", response_model=AssessResponse, responses=_HYPOTHETICAL_ERRORS,
             summary="Assess a given strategy for a hypothetical alliance",
             description="As the scheduled-match route, for two supplied 3-team alliances at an event; match_context "
                         "is required." + _STATUS_NOTE)
def assess_hypothetical(body: HypotheticalAssessBody, as_of: str | None = Query(default=None,
                                                                                 description=AS_OF_DESCRIPTION),
                        database: Database = Depends(get_database), model: Any = Depends(get_strategy_model),
                        epa_source: ServedEpaSource | None = Depends(get_epa_source)) -> AssessResponse:
    model = _require_model(model)
    found = _hypothetical_context(database, body, as_of, require_epa_source(epa_source))
    return _assess(found, model, body, epa_source)


@router.post("/hypothetical/recommend", response_model=RecommendResponse, responses=_HYPOTHETICAL_ERRORS,
             summary="The AI strategy for a hypothetical alliance",
             description="As the scheduled-match route, for two supplied 3-team alliances at an event." + _STATUS_NOTE)
def recommend_hypothetical(body: HypotheticalRecommendBody,
                           as_of: str | None = Query(default=None, description=AS_OF_DESCRIPTION),
                           database: Database = Depends(get_database), model: Any = Depends(get_strategy_model),
                           epa_source: ServedEpaSource | None = Depends(get_epa_source)) -> RecommendResponse:
    model = _require_model(model)
    found = _hypothetical_context(database, body, as_of, require_epa_source(epa_source))
    return _recommend(found, model, body, epa_source)


@router.post("/hypothetical/compare", response_model=CompareResponse, responses=_HYPOTHETICAL_ERRORS,
             summary="Compare two strategies for a hypothetical alliance",
             description="As the scheduled-match route, for two supplied 3-team alliances at an event." + _STATUS_NOTE)
def compare_hypothetical(body: HypotheticalCompareBody,
                         as_of: str | None = Query(default=None, description=AS_OF_DESCRIPTION),
                         database: Database = Depends(get_database), model: Any = Depends(get_strategy_model),
                         epa_source: ServedEpaSource | None = Depends(get_epa_source)) -> CompareResponse:
    model = _require_model(model)
    found = _hypothetical_context(database, body, as_of, require_epa_source(epa_source))
    return _compare(found, model, body, epa_source)


# --- coach writes (P7-Q10) ------------------------------------------------------------------------------------------


def _coach_error(exc: CoachInputError) -> ApiError:
    return ApiError(status_code=HTTPStatus.UNPROCESSABLE_ENTITY, code=CODE_INVALID_COACH_INPUT,
                    message=str(exc) + problems_suffix(exc.problems))


@router.post("/coach-strategies", status_code=HTTPStatus.CREATED, response_model=CoachStrategyStored,
             responses=_WRITE_ERRORS, summary="Store a coach strategy (raw-first; write token)",
             description="Body: {event_key, match_key?, author, strategy}. Landed raw before validation, so a rejected "
                         "submission (invalid_coach_input) stays recorded. author is caller-asserted, not "
                         "authenticated.")
def post_coach_strategy(payload: dict[str, Any] = Body(...), database: Database = Depends(get_database),
                        _: None = Depends(require_writer)) -> CoachStrategyStored:
    try:
        record = submit_coach_strategy(database, payload)
    except CoachInputError as exc:
        raise _coach_error(exc) from exc
    return CoachStrategyStored(event_key=record.event_key, match_key=record.match_key, strategy=record.strategy,
                               strategy_sha256=record.strategy.sha256(), origin=record.provenance.origin,
                               author=record.provenance.author, created_at=record.provenance.created_at)


@router.post("/coach-observations", status_code=HTTPStatus.CREATED, response_model=CoachObservationStored,
             responses=_WRITE_ERRORS, summary="Store a coach observation (raw-first; write token)",
             description="Body: {event_key, team_number, kind, component?, observed_at, observer}. Applied to every "
                         "strategy evaluated after observed_at. Landed raw before validation; free text never reaches "
                         "a model. observer is caller-asserted, not authenticated.")
def post_coach_observation(payload: dict[str, Any] = Body(...), database: Database = Depends(get_database),
                           _: None = Depends(require_writer)) -> CoachObservationStored:
    try:
        return CoachObservationStored(observation=submit_coach_observation(database, payload))
    except CoachInputError as exc:
        raise _coach_error(exc) from exc


__all__ = ["router"]
