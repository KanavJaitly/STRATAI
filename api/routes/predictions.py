"""ML prediction endpoints: win probability, team ranking, alliance synergy.

Phase 4 Milestone 12 (docs/P4Milestones.md). Extends the Phase 3 api/
package additively -- no existing route or error-handling convention is
changed, only reused: the same structured error envelope (api.errors),
Depends(get_database) pattern (api.dependencies), and read-only, no-recompute
posture api.routes.metrics already established.

Read pinned model versions only -- no training or heavy recompute in the
request path. get_ranking_model/get_win_prob_model (api.dependencies) return
whatever api.ml_loading loaded once at startup, which may be None: this
project currently has no model accepted for production serving (M4-M7's
real, dated backtest numbers are blocked on a Statbotics outage, see
.agent/phase4/PHASE_STATUS.md), so model_not_loaded is this API's genuine
current answer for the two model-backed endpoints below, not a hypothetical
error path invented for test coverage. alliance_synergy (Milestone 9) needs
no model at all -- it is a pure function over team features -- so that
endpoint has no model_not_loaded case.

Four documented outcome codes, matching the milestone's own wording:
  * model_not_loaded (404) -- no model is currently pinned/loadable. 404,
    not 503: mirrors api.routes.metrics's own metrics_not_computed
    precedent ("the served computed thing does not exist yet" is a 404
    with a distinct code here, not a 5xx) -- see _model_not_loaded_error's
    own comment for why 503 would have silently discarded this code.
  * event_not_found / match_not_found (404) -- the addressed resource does
    not exist.
  * team_not_found (404) -- a supplied team_number is not rostered at the
    given event.
  * insufficient_features (422) -- every team involved has zero real
    features at all (no EPA, no scoring history, no scouting) -- an API-
    level policy this route enforces on top of the model's own permissive
    internal handling: RankingXGBModel/WinProbXGBModel both accept an
    all-absent input without raising (XGBoost's native NaN handling still
    returns a number), but serving a "confident" prediction built from
    literally zero real signal is a different, worse claim than serving one
    built from thin-but-real data, so this route refuses it explicitly
    rather than silently returning a number with no evidence behind it.

Every response echoes model_type/model_version/model_version_tag (or, for
alliance-synergy, nothing model-related at all) so a consumer knows exactly
what produced a number -- this milestone's own "response schemas ... echo
model version + calibration status" requirement. calibration_status is
"uncalibrated" for both model-backed endpoints: no real calibrator (M7) has
ever been fit on real data or registered, for the identical Statbotics
reason M4-M7 are unaccepted -- reported honestly rather than omitted.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from http import HTTPStatus

from fastapi import APIRouter, Body, Depends, Path
from pydantic import BaseModel, Field
from starlette.requests import Request

from api.dependencies import (
    get_database,
    get_ranking_model,
    get_ranking_model_manifest,
    get_settings,
    get_win_prob_model,
    get_win_prob_model_manifest,
)
from api.errors import ApiError, ErrorResponse
from api.request_id import get_request_id
from data.config import Settings
from database.connection import Database
from ml.backtest.harness import Model
from ml.features.assembler import MatchFeatureRow, TeamFeatures, build_match_feature_row, build_team_features
from ml.features.roster import event_exists, get_event_season, get_match_event_and_scheduled_time, list_teams_at_event
from ml.registry import ModelManifest
from ml.synergy.score import alliance_synergy

logger = logging.getLogger(__name__)

router = APIRouter(tags=["predictions"])

CALIBRATION_STATUS_UNCALIBRATED = "uncalibrated"

CODE_MODEL_NOT_LOADED = "model_not_loaded"
CODE_EVENT_NOT_FOUND = "event_not_found"
CODE_MATCH_NOT_FOUND = "match_not_found"
CODE_TEAM_NOT_FOUND = "team_not_found"
CODE_INSUFFICIENT_FEATURES = "insufficient_features"


class WinProbabilityResponse(BaseModel):
    match_key: str | None = Field(default=None, description="The real match this prediction is for, or null for an ad-hoc alliance pairing.")
    event_key: str
    red_team_numbers: list[int]
    blue_team_numbers: list[int]
    as_of: datetime
    red_win_probability: float = Field(ge=0.0, le=1.0)
    model_type: str
    model_version: str
    model_version_tag: str
    calibration_status: str


class TeamRankingEntry(BaseModel):
    team_number: int
    predicted_rating: float


class TeamRankingResponse(BaseModel):
    event_key: str
    as_of: datetime
    model_type: str
    model_version: str
    model_version_tag: str
    rankings: list[TeamRankingEntry] = Field(description="Sorted by predicted_rating, descending.")


class AllianceSynergyRequestBody(BaseModel):
    event_key: str = Field(min_length=1)
    team_numbers: list[int] = Field(min_length=3, max_length=3)


class WinProbabilityByAlliancesRequestBody(BaseModel):
    event_key: str = Field(min_length=1)
    red_team_numbers: list[int] = Field(min_length=3, max_length=3)
    blue_team_numbers: list[int] = Field(min_length=3, max_length=3)


class AllianceSynergyResponse(BaseModel):
    event_key: str
    team_numbers: list[int]
    as_of: datetime
    overall_score: float | None
    role_fit_term: float | None
    role_fit_axes_used: list[str]
    scoring_distribution_term: float | None
    scoring_distribution_axes_used: list[str]
    defense_feeding_coverage_term: float | None
    defense_feeding_coverage_present_count: int
    confidence: float


def _model_not_loaded_error(model_type: str) -> ApiError:
    # 404, not 503: mirrors api.routes.metrics's own metrics_not_computed
    # precedent exactly -- "the served computed thing does not exist yet"
    # is a 404 with a distinct code in this codebase's established
    # convention, not a 5xx. That convention exists for a real reason this
    # route must not violate: api.errors deliberately strips any
    # route-supplied code/message at status >= 500 (nothing route-specific
    # may cross the wire at that tier, a security boundary), so a custom
    # "model_not_loaded" code could never survive at 503 -- it would
    # silently render as the generic "service_unavailable" instead.
    return ApiError(
        status_code=HTTPStatus.NOT_FOUND,
        code=CODE_MODEL_NOT_LOADED,
        message=f"No {model_type} model is currently pinned/loadable -- this endpoint cannot serve a prediction.",
    )


def _event_not_found_error(event_key: str) -> ApiError:
    return ApiError(
        status_code=HTTPStatus.NOT_FOUND, code=CODE_EVENT_NOT_FOUND,
        message=f"Event '{event_key}' is not known to StratAI.",
    )


def _team_not_found_error(team_number: int, event_key: str) -> ApiError:
    return ApiError(
        status_code=HTTPStatus.NOT_FOUND, code=CODE_TEAM_NOT_FOUND,
        message=f"Team {team_number} is not rostered in any match at event '{event_key}'.",
    )


def _insufficient_features_error() -> ApiError:
    return ApiError(
        status_code=HTTPStatus.UNPROCESSABLE_ENTITY, code=CODE_INSUFFICIENT_FEATURES,
        message="Every team involved has zero real features available (no EPA, scoring history, or scouting data) -- refusing to serve a prediction built from no evidence.",
    )


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


def _require_teams_rostered(database: Database, event_key: str, team_numbers: list[int]) -> None:
    """Raises team_not_found for the first supplied team_number not on
    event_key's own roster. Checked against the event's real roster
    (ml.features.roster.list_teams_at_event) rather than a global teams
    table, since a real team not attending THIS event is exactly as
    unservable here as a team that does not exist at all."""
    roster = set(list_teams_at_event(database, event_key))
    for team_number in team_numbers:
        if team_number not in roster:
            raise _team_not_found_error(team_number, event_key)


def _win_probability_response(
    match_key: str | None, event_key: str, match_features: MatchFeatureRow, as_of: datetime,
    model: Model, manifest: ModelManifest, version_tag: str,
) -> WinProbabilityResponse:
    all_teams = list(match_features.red_teams) + list(match_features.blue_teams)
    if all_teams and all(_team_features_are_fully_absent(team) for team in all_teams):
        raise _insufficient_features_error()

    probability = model.predict_win_prob(match_features)
    return WinProbabilityResponse(
        match_key=match_key, event_key=event_key,
        red_team_numbers=[team.team_number for team in match_features.red_teams],
        blue_team_numbers=[team.team_number for team in match_features.blue_teams],
        as_of=as_of, red_win_probability=probability,
        model_type=manifest.model_type, model_version=manifest.model_version, model_version_tag=version_tag,
        calibration_status=CALIBRATION_STATUS_UNCALIBRATED,
    )


@router.get(
    "/predictions/matches/{match_key}/win-probability",
    response_model=WinProbabilityResponse,
    summary="Win probability for a real, scheduled match",
    description=(
        "Predicts P(red wins) for a real match already known to StratAI, using features "
        "as knowable strictly before that match's own scheduled_time -- the same point-in-time "
        "guarantee ml.features.assembler.build_match_feature_row enforces everywhere else it is used."
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
    model: Model | None = Depends(get_win_prob_model),
    manifest: ModelManifest | None = Depends(get_win_prob_model_manifest),
    settings: Settings = Depends(get_settings),
) -> WinProbabilityResponse:
    if model is None or manifest is None:
        raise _model_not_loaded_error("win_prob_xgb")

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

    match_features = build_match_feature_row(database, match_key, as_of=scheduled_time)
    return _win_probability_response(
        match_key, event_key, match_features, scheduled_time, model, manifest,
        settings.ml_win_prob_model_version_tag or "",
    )


@router.post(
    "/predictions/win-probability",
    response_model=WinProbabilityResponse,
    summary="Win probability for two supplied (possibly hypothetical) alliances",
    description=(
        "Predicts P(red wins) for two supplied 3-team alliances at a given event, evaluated "
        "as of the moment of the request -- for a hypothetical matchup that may not correspond "
        "to any single scheduled match."
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
    model: Model | None = Depends(get_win_prob_model),
    manifest: ModelManifest | None = Depends(get_win_prob_model_manifest),
    settings: Settings = Depends(get_settings),
) -> WinProbabilityResponse:
    if model is None or manifest is None:
        raise _model_not_loaded_error("win_prob_xgb")
    if not event_exists(database, body.event_key):
        raise _event_not_found_error(body.event_key)
    _require_teams_rostered(database, body.event_key, body.red_team_numbers + body.blue_team_numbers)

    as_of = datetime.now(timezone.utc)
    season = get_event_season(database, body.event_key)
    assert season is not None  # event_exists already confirmed above
    red_teams = [build_team_features(database, team_number, body.event_key, as_of) for team_number in body.red_team_numbers]
    blue_teams = [build_team_features(database, team_number, body.event_key, as_of) for team_number in body.blue_team_numbers]
    match_features = MatchFeatureRow(
        match_key=f"__adhoc__{body.event_key}", as_of=as_of, event_key=body.event_key,
        season=season, red_teams=red_teams, blue_teams=blue_teams,
    )
    return _win_probability_response(
        None, body.event_key, match_features, as_of, model, manifest,
        settings.ml_win_prob_model_version_tag or "",
    )


@router.get(
    "/predictions/events/{event_key}/ranking",
    response_model=TeamRankingResponse,
    summary="Predicted team ranking for an event",
    description=(
        "Predicts every rostered team's rating at one event, evaluated as of the moment "
        "of the request, sorted strongest to weakest. Unlike the win-probability endpoints, "
        "individual teams with thin data are still included -- ranking degrades per-team "
        "gracefully rather than needing every team to clear an insufficient_features bar."
    ),
    responses={
        HTTPStatus.NOT_FOUND: {"model": ErrorResponse},
    },
)
def event_team_ranking(
    request: Request,
    event_key: str = Path(min_length=1, description="TBA event key, e.g. 2026casj."),
    database: Database = Depends(get_database),
    model: Model | None = Depends(get_ranking_model),
    manifest: ModelManifest | None = Depends(get_ranking_model_manifest),
    settings: Settings = Depends(get_settings),
) -> TeamRankingResponse:
    if model is None or manifest is None:
        raise _model_not_loaded_error("ranking_xgb")
    if not event_exists(database, event_key):
        raise _event_not_found_error(event_key)

    team_numbers = list_teams_at_event(database, event_key)
    as_of = datetime.now(timezone.utc)
    entries = []
    for team_number in team_numbers:
        team_features = build_team_features(database, team_number, event_key, as_of)
        entries.append(TeamRankingEntry(team_number=team_number, predicted_rating=model.predict_rating(team_features)))
    entries.sort(key=lambda entry: entry.predicted_rating, reverse=True)

    return TeamRankingResponse(
        event_key=event_key, as_of=as_of,
        model_type=manifest.model_type, model_version=manifest.model_version,
        model_version_tag=settings.ml_ranking_model_version_tag or "", rankings=entries,
    )


@router.post(
    "/predictions/alliance-synergy",
    response_model=AllianceSynergyResponse,
    summary="Alliance synergy score for three supplied teams",
    description=(
        "Scores one three-team alliance's synergy (ml.synergy.score.alliance_synergy), "
        "evaluated as of the moment of the request. A pure function -- needs no model, so "
        "this endpoint has no model_not_loaded case."
    ),
    responses={
        HTTPStatus.NOT_FOUND: {"model": ErrorResponse},
    },
)
def alliance_synergy_score(
    request: Request,
    body: AllianceSynergyRequestBody = Body(...),
    database: Database = Depends(get_database),
) -> AllianceSynergyResponse:
    if not event_exists(database, body.event_key):
        raise _event_not_found_error(body.event_key)
    _require_teams_rostered(database, body.event_key, body.team_numbers)

    as_of = datetime.now(timezone.utc)
    team_a, team_b, team_c = (
        build_team_features(database, team_number, body.event_key, as_of) for team_number in body.team_numbers
    )
    result = alliance_synergy(team_a, team_b, team_c)

    return AllianceSynergyResponse(
        event_key=body.event_key, team_numbers=body.team_numbers, as_of=as_of,
        overall_score=result.overall_score,
        role_fit_term=result.role_fit_term, role_fit_axes_used=result.role_fit_axes_used,
        scoring_distribution_term=result.scoring_distribution_term,
        scoring_distribution_axes_used=result.scoring_distribution_axes_used,
        defense_feeding_coverage_term=result.defense_feeding_coverage_term,
        defense_feeding_coverage_present_count=result.defense_feeding_coverage_present_count,
        confidence=result.confidence,
    )
