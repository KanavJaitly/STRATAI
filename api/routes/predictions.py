"""ML prediction endpoints: win probability, team ranking, alliance synergy.

Phase 4 Milestone 12 (docs/P4Milestones.md), aligned on 2026-10-02 with the system
Phase 4 actually evaluated (D18) and with what that evaluation showed it can and
cannot support (docs/ml_models.md §10; .agent/phase4/D18_M07_DIAGNOSTIC.md):

* Served models are the D18 models of record only (api.ml_loading): M5 v2 for
  ranking, M6 + its symmetric isotonic calibrator for win probability. Every
  response carries the served model's identity -- type, version, version tag,
  artifact sha256, training-frame hash and provenance -- and the EPA source's
  identity, with per-team EPA provenance (epa_value_source, source event).
* Win probability. M7 FAILED: probabilities are not certified calibrated. In the
  D18 held-out season, qualification probabilities were approximately calibrated
  (ECE 0.015, bins within +-3.2 pts) -- measured on EPA-complete matches only (all
  six teams with prior EPA, M7's evaluation population); playoff probabilities were
  not (the higher seed was underestimated by ~15 pts). So:
    - qualification scope with every team EPA-present: ``red_win_probability`` is served, rounded to
      PROBABILITY_DISPLAY_STEP and clipped to [0.05, 0.95] -- never a precise
      decimal, never 0% or 100% -- with validation_status
      approximately_calibrated_qualification;
    - playoff scope, an ad-hoc pairing whose context the caller does not state, or
      any match with a team lacking prior EPA (outside the evaluated population;
      corrected 2026-10-02): ``red_win_probability`` is null, with
      ``not_validated_reason``; the model output is returned only
      as ``unvalidated_red_win_probability`` (same rounding) with
      validation_status not_validated and a warning. It must not be presented
      as a probability.
  No series, bracket or playoff-success probability is served anywhere.
* Ranking: an ordering with validation_status moderate_held_out (D18 per-event
  Spearman median 0.61; evaluated at the mid-qualification snapshot).
  predicted_rating is a relative score: only the ordering is meaningful.
* Alliance synergy: not validated against outcomes, and labelled so.

Outcome codes:
  * model_not_loaded (404) -- no model of record is pinned/loadable. 404, not
    503: api.errors strips route codes at >= 500 (api.routes.metrics's
    metrics_not_computed precedent).
  * epa_source_not_loaded (404) -- the configured EPA source is unconfigured or
    failed its integrity checks (same 404 reasoning).
  * epa_source_incomplete (422) -- the D18 source has no valid Statbotics row for
    a required prior event; D18 forbids silently using an older event.
  * event_not_found / match_not_found (404), team_not_found (404).
  * insufficient_features (422) -- every team involved has zero real features.
"""

from __future__ import annotations

import logging
import math
from datetime import datetime, timezone
from http import HTTPStatus
from typing import Any, Literal

from fastapi import APIRouter, Body, Depends, Path
from pydantic import BaseModel, Field
from starlette.requests import Request

from api.dependencies import get_database, get_epa_source, get_ranking_model, get_win_prob_model
from api.errors import ApiError, ErrorResponse
from api.routes.common import (
    CODE_EPA_SOURCE_INCOMPLETE,
    CODE_EPA_SOURCE_NOT_LOADED,
    CODE_EVENT_NOT_FOUND,
    CODE_TEAM_NOT_FOUND,
    EpaSourceInfo,
    epa_info,
    epa_source_incomplete_error,
    epa_source_not_loaded_error,
    event_not_found_error,
    require_epa_source,
    require_teams_rostered,
    team_not_found_error,
)
from api.ml_loading import ServedEpaSource, ServedModel
from database.connection import Database
from ml.features.assembler import MatchFeatureRow, TeamFeatures, build_match_feature_row, build_team_features
from ml.features.roster import (
    event_exists,
    get_event_season,
    get_match_competition_level,
    get_match_event_and_scheduled_time,
    list_teams_at_event,
)
from ml.features.scale import ScaleLookup
from ml.ratings.statbotics_primary import SilentFallbackError
from ml.synergy.score import alliance_synergy

logger = logging.getLogger(__name__)

router = APIRouter(tags=["predictions"])

PROBABILITY_DISPLAY_STEP = 0.05
PROBABILITY_DISPLAY_MIN = 0.05
PROBABILITY_DISPLAY_MAX = 0.95

SCOPE_QUALIFICATION = "qualification"
SCOPE_PLAYOFF = "playoff"
SCOPE_UNSPECIFIED = "unspecified"
VALIDATION_QUALIFICATION_APPROXIMATELY_CALIBRATED = "approximately_calibrated_qualification"
VALIDATION_NOT_VALIDATED = "not_validated"
NOT_VALIDATED_PLAYOFF = "playoff_scope"
NOT_VALIDATED_UNSPECIFIED = "unspecified_context"
NOT_VALIDATED_EPA_INCOMPLETE = "epa_incomplete"
CALIBRATION_STATUS_M7_FAILED = "m7_gate_failed"
RANKING_VALIDATION_STATUS = "moderate_held_out"
SYNERGY_VALIDATION_STATUS = "not_validated_against_outcomes"

WIN_PROBABILITY_EVIDENCE = (
    "D18 held-out 2026: qualification probabilities approximately calibrated (ECE 0.015, bins within "
    "+-3.2 pts); playoff probabilities not calibrated (higher seed underestimated ~15 pts); the M7 "
    "calibration gate FAILED overall. See docs/ml_models.md sections 7 and 10."
)
UNVALIDATED_WARNING = (
    "Not a validated probability. Phase 4 validated qualification probabilities only for matches where every "
    "team has prior EPA; playoff, unspecified-context and EPA-incomplete probabilities were not validated. Do "
    "not present this value as a probability or use it for series, bracket or playoff-success estimates."
)
RANKING_EVIDENCE = (
    "D18 held-out 2026: per-event Spearman vs final qualification rank median 0.61 (10th-90th pct 0.46-0.78), "
    "+0.016 over raw EPA, evaluated at each team's mid-qualification snapshot. Treat as an ordering with "
    "uncertainty; predicted_rating is a relative score. See docs/ml_models.md section 10."
)

CODE_MODEL_NOT_LOADED = "model_not_loaded"
CODE_MATCH_NOT_FOUND = "match_not_found"
CODE_INSUFFICIENT_FEATURES = "insufficient_features"


class ServedModelInfo(BaseModel):
    model_type: str
    model_version: str
    model_version_tag: str
    model_sha256: str = Field(description="sha256 of the served registry artifact")
    training_dataset_hash: str
    provenance: dict[str, Any] = Field(description="Where the artifact comes from (source version, frame, record)")


class TeamEpaProvenance(BaseModel):
    team_number: int
    alliance: str | None = None
    epa_value_source: str | None = Field(description="statbotics, stratai_fallback, ... ; null when EPA is withheld")
    epa_source_state: str | None = Field(description="current / stale / fallback_stratai / withheld_no_prior_event")
    epa_source_event_key: str | None
    epa_withheld_reason: str | None


class WinProbabilityResponse(BaseModel):
    match_key: str | None = Field(default=None, description="The real match this prediction is for, or null for an ad-hoc alliance pairing.")
    event_key: str
    red_team_numbers: list[int]
    blue_team_numbers: list[int]
    as_of: datetime
    probability_scope: str = Field(description="qualification, playoff, or unspecified")
    competition_level: str | None = Field(default=None, description="matches.competition_level for a real match")
    validation_status: str
    not_validated_reason: str | None = Field(
        default=None, description="playoff_scope, unspecified_context or epa_incomplete; null when validated")
    red_win_probability: float | None = Field(
        default=None, ge=0.0, le=1.0,
        description="Served only for qualification scope, rounded to probability_rounding; null otherwise.")
    unvalidated_red_win_probability: float | None = Field(
        default=None, ge=0.0, le=1.0,
        description="Model output for an unvalidated scope (rounded). Not a validated probability.")
    probability_rounding: float
    calibration_status: str
    evidence: str
    warning: str | None = None
    model_type: str
    model_version: str
    model_version_tag: str
    model: ServedModelInfo
    epa: EpaSourceInfo
    teams: list[TeamEpaProvenance]


class TeamRankingEntry(BaseModel):
    rank: int
    team_number: int
    predicted_rating: float = Field(description="Relative score; only the ordering is meaningful.")
    epa_value_source: str | None
    epa_source_event_key: str | None
    epa_withheld_reason: str | None


class TeamRankingResponse(BaseModel):
    event_key: str
    as_of: datetime
    validation_status: str
    evidence: str
    model_type: str
    model_version: str
    model_version_tag: str
    model: ServedModelInfo
    epa: EpaSourceInfo
    rankings: list[TeamRankingEntry] = Field(description="Sorted by predicted_rating, descending.")


class AllianceSynergyRequestBody(BaseModel):
    event_key: str = Field(min_length=1)
    team_numbers: list[int] = Field(min_length=3, max_length=3)


class WinProbabilityByAlliancesRequestBody(BaseModel):
    event_key: str = Field(min_length=1)
    red_team_numbers: list[int] = Field(min_length=3, max_length=3)
    blue_team_numbers: list[int] = Field(min_length=3, max_length=3)
    match_context: Literal["qualification", "playoff"] | None = Field(
        default=None, description="The context of the hypothetical match. Only 'qualification' is a validated "
                                  "scope; omitted is treated as unvalidated.")


class AllianceSynergyResponse(BaseModel):
    event_key: str
    team_numbers: list[int]
    as_of: datetime
    validation_status: str
    overall_score: float | None
    role_fit_term: float | None
    role_fit_axes_used: list[str]
    scoring_distribution_term: float | None
    scoring_distribution_axes_used: list[str]
    defense_feeding_coverage_term: float | None
    defense_feeding_coverage_present_count: int
    confidence: float
    epa: EpaSourceInfo
    teams: list[TeamEpaProvenance]


def display_probability(probability: float) -> float:
    """Round to PROBABILITY_DISPLAY_STEP, symmetrically about 0.5, and clip to
    [PROBABILITY_DISPLAY_MIN, PROBABILITY_DISPLAY_MAX]: display(1 - p) = 1 - display(p),
    so the swapped matchup always shows the complement, and nothing reads as certain."""
    offset = probability - 0.5
    steps = math.floor(abs(offset) / PROBABILITY_DISPLAY_STEP + 0.5)
    shown = 0.5 + math.copysign(steps * PROBABILITY_DISPLAY_STEP, offset)
    return round(min(max(shown, PROBABILITY_DISPLAY_MIN), PROBABILITY_DISPLAY_MAX), 2)


def _model_not_loaded_error(model_type: str) -> ApiError:
    return ApiError(
        status_code=HTTPStatus.NOT_FOUND, code=CODE_MODEL_NOT_LOADED,
        message=f"No {model_type} model of record is currently pinned/loadable -- this endpoint cannot serve a prediction.",
    )


def _insufficient_features_error() -> ApiError:
    return ApiError(
        status_code=HTTPStatus.UNPROCESSABLE_ENTITY, code=CODE_INSUFFICIENT_FEATURES,
        message="Every team involved has zero real features available (no EPA, scoring history, or scouting data) -- refusing to serve a prediction built from no evidence.",
    )


def _model_info(served: ServedModel) -> ServedModelInfo:
    return ServedModelInfo(**served.identity())


def _team_provenance(team: TeamFeatures, alliance: str | None = None) -> TeamEpaProvenance:
    return TeamEpaProvenance(team_number=team.team_number, alliance=alliance, epa_value_source=team.epa_value_source,
                             epa_source_state=team.epa_source_state,
                             epa_source_event_key=team.epa_source_event_key, epa_withheld_reason=team.epa_withheld_reason)


def _team_features_are_fully_absent(team_features: TeamFeatures) -> bool:
    """True if literally none of a team's optional features are present --
    the API-level "no real evidence at all" case, distinct from thin-but-
    real data (which the underlying models already handle gracefully)."""
    return not any((
        team_features.epa_total_present, team_features.epa_auto_present,
        team_features.epa_teleop_present, team_features.epa_endgame_present,
        team_features.average_score_present, team_features.average_auto_points_present,
        team_features.defense_score_present,
        team_features.feeding_score_present,
    ))


def _teams(database: Database, team_numbers: list[int], event_key: str, as_of: datetime,
           epa_source: ServedEpaSource, scales: ScaleLookup) -> list[TeamFeatures]:
    try:
        return [build_team_features(database, team_number, event_key, as_of, epa_provider=epa_source.provider,
                                    scale_lookup=scales) for team_number in team_numbers]
    except SilentFallbackError as exc:
        raise epa_source_incomplete_error(exc) from exc


def _win_probability_response(
    match_key: str | None, event_key: str, match_features: MatchFeatureRow, as_of: datetime,
    served: ServedModel, epa_source: ServedEpaSource, scope: str, competition_level: str | None,
) -> WinProbabilityResponse:
    all_teams = list(match_features.red_teams) + list(match_features.blue_teams)
    if all_teams and all(_team_features_are_fully_absent(team) for team in all_teams):
        raise _insufficient_features_error()

    shown = display_probability(served.model.predict_win_prob(match_features))
    # M7's evaluated population: qualification matches whose two non-empty alliances all have
    # prior EPA (scripts/run_m4_baseline_backtest._team_epa_complete). Anything else is outside it.
    epa_complete = bool(match_features.red_teams) and bool(match_features.blue_teams) and all(
        team.epa_total_present for team in all_teams)
    if scope == SCOPE_PLAYOFF:
        reason = NOT_VALIDATED_PLAYOFF
    elif scope != SCOPE_QUALIFICATION:
        reason = NOT_VALIDATED_UNSPECIFIED
    elif not epa_complete:
        reason = NOT_VALIDATED_EPA_INCOMPLETE
    else:
        reason = None
    validated = reason is None
    identity = served.identity()
    return WinProbabilityResponse(
        match_key=match_key, event_key=event_key,
        red_team_numbers=[team.team_number for team in match_features.red_teams],
        blue_team_numbers=[team.team_number for team in match_features.blue_teams],
        as_of=as_of, probability_scope=scope, competition_level=competition_level,
        validation_status=VALIDATION_QUALIFICATION_APPROXIMATELY_CALIBRATED if validated else VALIDATION_NOT_VALIDATED,
        not_validated_reason=reason,
        red_win_probability=shown if validated else None,
        unvalidated_red_win_probability=None if validated else shown,
        probability_rounding=PROBABILITY_DISPLAY_STEP, calibration_status=CALIBRATION_STATUS_M7_FAILED,
        evidence=WIN_PROBABILITY_EVIDENCE, warning=None if validated else UNVALIDATED_WARNING,
        model_type=identity["model_type"], model_version=identity["model_version"],
        model_version_tag=identity["model_version_tag"], model=_model_info(served), epa=epa_info(epa_source),
        teams=[_team_provenance(t, "red") for t in match_features.red_teams]
        + [_team_provenance(t, "blue") for t in match_features.blue_teams],
    )


@router.get(
    "/predictions/matches/{match_key}/win-probability",
    response_model=WinProbabilityResponse,
    summary="Win probability for a real, scheduled match",
    description=(
        "P(red wins) for a real match, from features knowable strictly before its scheduled_time. "
        "Served as a rounded probability for qualification matches only; for playoff matches the model "
        "output is returned only as an explicitly unvalidated value (see validation_status)."
    ),
    responses={
        HTTPStatus.NOT_FOUND: {"model": ErrorResponse},
        HTTPStatus.UNPROCESSABLE_ENTITY: {"model": ErrorResponse},
    },
)
def match_win_probability(
    request: Request,
    match_key: str = Path(min_length=1, description="TBA match key, e.g. 2026casj_qm12."),
    database: Database = Depends(get_database),
    served: ServedModel | None = Depends(get_win_prob_model),
    epa_source: ServedEpaSource | None = Depends(get_epa_source),
) -> WinProbabilityResponse:
    if served is None:
        raise _model_not_loaded_error("win_prob_xgb_calibrated")
    epa_source = require_epa_source(epa_source)

    context = get_match_event_and_scheduled_time(database, match_key)
    if context is None:
        raise ApiError(
            status_code=HTTPStatus.NOT_FOUND, code=CODE_MATCH_NOT_FOUND,
            message=f"Match '{match_key}' is not known to StratAI.",
        )
    event_key, scheduled_time = context
    if scheduled_time is None:
        raise ApiError(
            status_code=HTTPStatus.UNPROCESSABLE_ENTITY, code=CODE_INSUFFICIENT_FEATURES,
            message=f"Match '{match_key}' has no scheduled_time yet -- a point-in-time prediction cannot be built for it.",
        )

    level = get_match_competition_level(database, match_key)
    scope = SCOPE_QUALIFICATION if level == "qualification" else (SCOPE_PLAYOFF if level else SCOPE_UNSPECIFIED)
    try:
        match_features = build_match_feature_row(database, match_key, as_of=scheduled_time,
                                                 epa_provider=epa_source.provider, scale_lookup=ScaleLookup(database))
    except SilentFallbackError as exc:
        raise epa_source_incomplete_error(exc) from exc
    return _win_probability_response(match_key, event_key, match_features, scheduled_time, served, epa_source,
                                     scope, level)


@router.post(
    "/predictions/win-probability",
    response_model=WinProbabilityResponse,
    summary="Win probability for two supplied (possibly hypothetical) alliances",
    description=(
        "P(red wins) for two supplied 3-team alliances at an event, evaluated as of the request. "
        "Served as a rounded probability only when match_context is 'qualification'; otherwise the "
        "model output is returned only as an explicitly unvalidated value."
    ),
    responses={
        HTTPStatus.NOT_FOUND: {"model": ErrorResponse},
        HTTPStatus.UNPROCESSABLE_ENTITY: {"model": ErrorResponse},
    },
)
def win_probability_for_alliances(
    request: Request,
    body: WinProbabilityByAlliancesRequestBody = Body(...),
    database: Database = Depends(get_database),
    served: ServedModel | None = Depends(get_win_prob_model),
    epa_source: ServedEpaSource | None = Depends(get_epa_source),
) -> WinProbabilityResponse:
    if served is None:
        raise _model_not_loaded_error("win_prob_xgb_calibrated")
    epa_source = require_epa_source(epa_source)
    if not event_exists(database, body.event_key):
        raise event_not_found_error(body.event_key)
    require_teams_rostered(database, body.event_key, body.red_team_numbers + body.blue_team_numbers)

    as_of = datetime.now(timezone.utc)
    season = get_event_season(database, body.event_key)
    assert season is not None  # event_exists already confirmed above
    scales = ScaleLookup(database)
    red_teams = _teams(database, body.red_team_numbers, body.event_key, as_of, epa_source, scales)
    blue_teams = _teams(database, body.blue_team_numbers, body.event_key, as_of, epa_source, scales)
    match_features = MatchFeatureRow(
        match_key=f"__adhoc__{body.event_key}", as_of=as_of, event_key=body.event_key,
        season=season, red_teams=red_teams, blue_teams=blue_teams,
    )
    scope = body.match_context or SCOPE_UNSPECIFIED
    return _win_probability_response(None, body.event_key, match_features, as_of, served, epa_source, scope, None)


@router.get(
    "/predictions/events/{event_key}/ranking",
    response_model=TeamRankingResponse,
    summary="Predicted team ranking for an event",
    description=(
        "Every rostered team's M5 v2 rating at one event, as of the request, sorted strongest to weakest. "
        "An ordering with moderate held-out accuracy (see evidence); predicted_rating is a relative score."
    ),
    responses={
        HTTPStatus.NOT_FOUND: {"model": ErrorResponse},
        HTTPStatus.UNPROCESSABLE_ENTITY: {"model": ErrorResponse},
    },
)
def event_team_ranking(
    request: Request,
    event_key: str = Path(min_length=1, description="TBA event key, e.g. 2026casj."),
    database: Database = Depends(get_database),
    served: ServedModel | None = Depends(get_ranking_model),
    epa_source: ServedEpaSource | None = Depends(get_epa_source),
) -> TeamRankingResponse:
    if served is None:
        raise _model_not_loaded_error("ranking_xgb_v2")
    epa_source = require_epa_source(epa_source)
    if not event_exists(database, event_key):
        raise event_not_found_error(event_key)

    as_of = datetime.now(timezone.utc)
    teams = _teams(database, list_teams_at_event(database, event_key), event_key, as_of, epa_source,
                   ScaleLookup(database))
    scored = sorted(((served.model.predict_rating(team), team) for team in teams), key=lambda pair: -pair[0])
    identity = served.identity()
    return TeamRankingResponse(
        event_key=event_key, as_of=as_of, validation_status=RANKING_VALIDATION_STATUS, evidence=RANKING_EVIDENCE,
        model_type=identity["model_type"], model_version=identity["model_version"],
        model_version_tag=identity["model_version_tag"], model=_model_info(served), epa=epa_info(epa_source),
        rankings=[TeamRankingEntry(rank=position, team_number=team.team_number, predicted_rating=rating,
                                   epa_value_source=team.epa_value_source,
                                   epa_source_event_key=team.epa_source_event_key,
                                   epa_withheld_reason=team.epa_withheld_reason)
                  for position, (rating, team) in enumerate(scored, start=1)],
    )


@router.post(
    "/predictions/alliance-synergy",
    response_model=AllianceSynergyResponse,
    summary="Alliance synergy score for three supplied teams",
    description=(
        "Scores one three-team alliance's synergy (ml.synergy.score.alliance_synergy), as of the request. "
        "A documented, deterministic heuristic that has not been validated against match outcomes."
    ),
    responses={
        HTTPStatus.NOT_FOUND: {"model": ErrorResponse},
        HTTPStatus.UNPROCESSABLE_ENTITY: {"model": ErrorResponse},
    },
)
def alliance_synergy_score(
    request: Request,
    body: AllianceSynergyRequestBody = Body(...),
    database: Database = Depends(get_database),
    epa_source: ServedEpaSource | None = Depends(get_epa_source),
) -> AllianceSynergyResponse:
    epa_source = require_epa_source(epa_source)
    if not event_exists(database, body.event_key):
        raise event_not_found_error(body.event_key)
    require_teams_rostered(database, body.event_key, body.team_numbers)

    as_of = datetime.now(timezone.utc)
    team_a, team_b, team_c = _teams(database, body.team_numbers, body.event_key, as_of, epa_source,
                                    ScaleLookup(database))
    result = alliance_synergy(team_a, team_b, team_c)

    return AllianceSynergyResponse(
        event_key=body.event_key, team_numbers=body.team_numbers, as_of=as_of,
        validation_status=SYNERGY_VALIDATION_STATUS,
        overall_score=result.overall_score,
        role_fit_term=result.role_fit_term, role_fit_axes_used=result.role_fit_axes_used,
        scoring_distribution_term=result.scoring_distribution_term,
        scoring_distribution_axes_used=result.scoring_distribution_axes_used,
        defense_feeding_coverage_term=result.defense_feeding_coverage_term,
        defense_feeding_coverage_present_count=result.defense_feeding_coverage_present_count,
        confidence=result.confidence, epa=epa_info(epa_source),
        teams=[_team_provenance(t) for t in (team_a, team_b, team_c)],
    )
