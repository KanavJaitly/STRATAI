"""P5-M3: the team and robot strength view endpoint.

    GET /teams/{team_number}/events/{event_key}/strength[?as_of=<ISO-8601 with offset>]

Returns ml.views.strength.TeamStrengthView. as_of defaults to the request time and
must be timezone-aware. Read-only and point-in-time, with every EPA value carrying its
provenance. Codes: event_not_found, team_not_found, epa_source_not_loaded,
epa_source_incomplete (api.routes.common), and invalid_as_of (422).
"""

from __future__ import annotations

from datetime import datetime, timezone
from http import HTTPStatus

from fastapi import APIRouter, Depends, Path, Query
from pydantic import BaseModel

from api.dependencies import get_database, get_epa_source
from api.errors import ApiError, ErrorResponse
from api.ml_loading import ServedEpaSource
from api.routes.common import (
    EpaSourceInfo,
    epa_info,
    epa_source_incomplete_error,
    event_not_found_error,
    require_epa_source,
    require_teams_rostered,
)
from database.connection import Database
from ml.features.roster import event_exists
from ml.ratings.statbotics_primary import SilentFallbackError
from ml.views.strength import TeamStrengthView, build_team_strength

router = APIRouter(tags=["strength"])

CODE_INVALID_AS_OF = "invalid_as_of"


class TeamStrengthResponse(BaseModel):
    strength: TeamStrengthView
    epa: EpaSourceInfo


def parse_as_of(value: str | None) -> datetime:
    """The request's as_of: now when omitted; otherwise an ISO-8601 time with an offset."""
    if value is None:
        return datetime.now(timezone.utc)
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError as exc:
        raise ApiError(status_code=HTTPStatus.UNPROCESSABLE_ENTITY, code=CODE_INVALID_AS_OF,
                       message=f"as_of {value!r} is not an ISO-8601 timestamp") from exc
    if parsed.tzinfo is None:
        raise ApiError(status_code=HTTPStatus.UNPROCESSABLE_ENTITY, code=CODE_INVALID_AS_OF,
                       message="as_of must include a timezone offset")
    return parsed


@router.get(
    "/teams/{team_number}/events/{event_key}/strength",
    response_model=TeamStrengthResponse,
    summary="Team and robot strength view (descriptive)",
    description="EPA (with provenance), Phase 3 scoring statistics, auto points and scouting ratings for one team "
                "at one event as of a point in time. Every numeric field has n and an explicit uncertainty."
                " reliability_score is an INTERIM placeholder (100 * matches_used / matches_scheduled, an attendance "
                "ratio, not a robot-failure measure; docs/metrics_pipeline.md section 6.3).",
    responses={HTTPStatus.NOT_FOUND: {"model": ErrorResponse}, HTTPStatus.UNPROCESSABLE_ENTITY: {"model": ErrorResponse}},
)
def team_strength(
    team_number: int = Path(ge=1),
    event_key: str = Path(min_length=1),
    as_of: str | None = Query(default=None, description="ISO-8601 with offset; default: now"),
    database: Database = Depends(get_database),
    epa_source: ServedEpaSource | None = Depends(get_epa_source),
) -> TeamStrengthResponse:
    epa_source = require_epa_source(epa_source)
    when = parse_as_of(as_of)
    if not event_exists(database, event_key):
        raise event_not_found_error(event_key)
    require_teams_rostered(database, event_key, [team_number])
    try:
        view = build_team_strength(database, team_number, event_key, when, epa_provider=epa_source.provider)
    except SilentFallbackError as exc:
        raise epa_source_incomplete_error(exc) from exc
    return TeamStrengthResponse(strength=view, epa=epa_info(epa_source, when, [view.epa.epa_source_state]))
