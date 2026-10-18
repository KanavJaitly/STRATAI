"""P5-M5: qualification match forecasts and expected qualification records.

    GET /events/{event_key}/qualification-forecast[?as_of=<ISO-8601 with offset>]

Qualification matches only; playoff matches are never included.

**Per match.** Features are built at min(as_of, scheduled time): a played match keeps its pre-match forecast. q
comes from the frozen D18 M7 pair, gated exactly as M12.
- An EPA-complete match is shown `red_win_probability`, rounded, labelled `approximately_calibrated_qualification`.
- Any other match gets only `unvalidated_red_win_probability`, labelled `not_validated` (`epa_incomplete`).

**Per team** (ml.views.qualification_forecast):
- expected qualification wins = Σ q;
- the central 80% Poisson-binomial range;
- a record label: `not_validated` if any of its matches is EPA-incomplete;
- a range label: P5-M5 (b) measured coverage 0.8532, outside [0.75, 0.85], so the range is served
  `not_validated`;
- `low_confidence` for Statbotics weeks 1–3.

There is no ranking-point projection.

Codes: event_not_found, model_not_loaded, epa_source_not_loaded / _incomplete / _pending, invalid_as_of.
"""

from __future__ import annotations

from datetime import datetime
from http import HTTPStatus

from fastapi import APIRouter, Depends, Path, Query
from pydantic import BaseModel, Field

from api.contract import REASON_EPA_INCOMPLETE as NOT_VALIDATED_EPA_INCOMPLETE
from api.contract import STATUS_NOT_VALIDATED as VALIDATION_NOT_VALIDATED
from api.contract import STATUS_VALIDATED_QUALIFICATION as VALIDATION_QUALIFICATION_APPROXIMATELY_CALIBRATED
from api.contract import CalibratedWinProbability, ServedModelInfo, calibrated_win_probability, error_responses
from api.dependencies import get_database, get_epa_source, get_win_prob_model
from api.ml_loading import ServedEpaSource, ServedModel
from api.routes.common import (
    CODE_EPA_SOURCE_INCOMPLETE,
    CODE_EPA_SOURCE_NOT_LOADED,
    CODE_EPA_SOURCE_PENDING,
    CODE_EVENT_NOT_FOUND,
    EpaSourceInfo,
    epa_info,
    epa_source_incomplete_error,
    event_not_found_error,
    require_epa_source,
)
from api.routes.common import AS_OF_DESCRIPTION, CODE_INVALID_AS_OF, CODE_MODEL_NOT_LOADED, model_not_loaded_error, parse_as_of
from database.connection import Database
from ml.calibration.display import display_probability
from ml.features.roster import event_exists
from ml.ratings.statbotics_primary import SilentFallbackError
from ml.views.qualification_forecast import LOW_CONFIDENCE_WEEKS, forecast_event_qualification

router = APIRouter(tags=["qualification forecast"])

EXPECTED_WINS_DECIMALS = 1  # never more precision than the evidence supports (MAE ~1.1 wins)
RECORD_EVIDENCE = ("Expected wins = sum of q (P5-M5). Held-out 2026, 7,845 EPA-complete team-events: mean actual "
                   "minus expected 0.0000, mean |actual - expected| 1.1207 (0.96 is irreducible).")
RANGE_EVIDENCE = ("Central 80% Poisson-binomial range. Coverage measured once on held-out 2026: 0.8532, outside "
                  "the pre-registered [0.75, 0.85], so the range is not validated (P5-M5 (b)).")


class MatchForecastOut(BaseModel):
    match_key: str
    scheduled_time: datetime
    features_as_of: datetime
    red_team_numbers: list[int]
    blue_team_numbers: list[int]
    validation_status: str
    not_validated_reason: str | None
    red_win_probability: float | None
    unvalidated_red_win_probability: float | None
    win_probability: CalibratedWinProbability = Field(
        description="P7-Q3: the same value as the fields above, in the shared M6/M7 probability object.")


class TeamRecordOut(BaseModel):
    team_number: int
    qualification_matches: int
    expected_wins: float
    range80_low: int
    range80_high: int
    record_validation_status: str
    record_not_validated_reason: str | None
    range_validation_status: str
    range_not_validated_reason: str | None


class QualificationForecastResponse(BaseModel):
    event_key: str
    as_of: datetime
    statbotics_week: int | None
    low_confidence: bool | None  # None when the event's Statbotics week is unknown
    record_evidence: str
    range_evidence: str
    matches: list[MatchForecastOut]
    teams: list[TeamRecordOut]
    epa: EpaSourceInfo
    win_prob_model_sha256: str


@router.get(
    "/events/{event_key}/qualification-forecast",
    response_model=QualificationForecastResponse,
    summary="Qualification match forecasts and expected qualification records",
    description="Per-match probabilities gated as M12 and per-team expected qualification wins with an 80% range; "
                "every element labelled. Qualification only.",
    responses=error_responses({
        HTTPStatus.NOT_FOUND: [CODE_MODEL_NOT_LOADED, CODE_EPA_SOURCE_NOT_LOADED, CODE_EVENT_NOT_FOUND],
        HTTPStatus.UNPROCESSABLE_ENTITY: [CODE_INVALID_AS_OF, CODE_EPA_SOURCE_INCOMPLETE, CODE_EPA_SOURCE_PENDING],
    }, validates_input=False),  # a path segment and a raw as_of string (checked by parse_as_of: invalid_as_of)
)
def qualification_forecast(
    event_key: str = Path(min_length=1),
    as_of: str | None = Query(default=None, description=AS_OF_DESCRIPTION),
    database: Database = Depends(get_database),
    served: ServedModel | None = Depends(get_win_prob_model),
    epa_source: ServedEpaSource | None = Depends(get_epa_source),
) -> QualificationForecastResponse:
    if served is None:
        raise model_not_loaded_error("win_prob_xgb_calibrated")
    epa_source = require_epa_source(epa_source)
    when = parse_as_of(as_of)
    if not event_exists(database, event_key):
        raise event_not_found_error(event_key)
    model_info = ServedModelInfo(**served.identity())
    try:
        forecast = forecast_event_qualification(database, event_key, when, epa_provider=epa_source.provider,
                                                predict_win_prob=served.model.predict_win_prob)
    except SilentFallbackError as exc:
        raise epa_source_incomplete_error(exc) from exc
    out_matches = []
    for match in forecast.matches:
        complete = match.epa_complete
        shown = display_probability(match.q)
        out_matches.append(MatchForecastOut(
            match_key=match.match_key, scheduled_time=match.scheduled_time, features_as_of=match.features_as_of,
            red_team_numbers=list(match.red), blue_team_numbers=list(match.blue),
            validation_status=VALIDATION_QUALIFICATION_APPROXIMATELY_CALIBRATED if complete
            else VALIDATION_NOT_VALIDATED,
            not_validated_reason=None if complete else NOT_VALIDATED_EPA_INCOMPLETE,
            red_win_probability=shown if complete else None,
            unvalidated_red_win_probability=None if complete else shown,
            win_probability=calibrated_win_probability(
                shown, None if complete else NOT_VALIDATED_EPA_INCOMPLETE, model_info)))
    records = forecast.records
    teams_out = []
    for team in sorted(records):
        record = records[team]
        low, high = record.range80
        record_status, record_reason = record.record_status()
        range_status, range_reason = record.range_status()
        teams_out.append(TeamRecordOut(
            team_number=team, qualification_matches=record.matches,
            expected_wins=round(record.expected_wins, EXPECTED_WINS_DECIMALS), range80_low=low, range80_high=high,
            record_validation_status=record_status, record_not_validated_reason=record_reason,
            range_validation_status=range_status, range_not_validated_reason=range_reason))
    week = forecast.statbotics_week
    states = forecast.epa_source_states
    return QualificationForecastResponse(
        event_key=event_key, as_of=when, statbotics_week=week,
        low_confidence=None if week is None else week in LOW_CONFIDENCE_WEEKS,
        record_evidence=RECORD_EVIDENCE, range_evidence=RANGE_EVIDENCE, matches=out_matches, teams=teams_out,
        epa=epa_info(epa_source, when, states), win_prob_model_sha256=served.sha256)
