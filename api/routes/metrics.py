"""The team metrics endpoint.

Phase 3 Milestone 13, and the literal answer to Phase 3's Definition of Done:
"given a team number and an event, return a complete metrics object."

  GET /teams/{team_number}/events/{event_key}/metrics  ->  TeamMetrics

Read-only. The handler reads team_metrics through data.metrics.read and never
computes anything: compute_team_metrics is deliberately not called here.
Metrics are produced by the pipeline (data.metrics.compute.
compute_event_team_metrics, a follow-on stage after a single-event sync), so a
request that arrives before that has run is answered honestly rather than by
computing on the caller's behalf. Nothing here writes, and there is no
authentication -- both are out of scope for this milestone, and the endpoint is
a pure read either way. Auth and rate limiting become real concerns when write
endpoints arrive (Milestone 7's submission path still has no HTTP route); that
is a separate, later piece of work.

Four ways to have no metrics, one status, four codes
===================================================
data.metrics.read distinguishes four reasons a metrics object does not exist,
and all four are 404: each one means the addressed resource is not there. The
request was well formed (that is 422's job), the server did not fail (500's),
and the service is perfectly able to serve (503's) -- it simply has no such
resource. What separates them is not existence but *actionability*:
metrics_not_computed resolves by waiting or triggering a compute, while
team_did_not_attend never resolves at all. HTTP status has no vocabulary for
that difference, so the distinction is carried by a stable machine-readable
code (api.errors.ApiError) rather than by contorting statuses or by a message
string clients would have to pattern-match.

Why "not computed" is not a 200 with an empty body
==================================================
Because a thin-data team *is* a 200 with a mostly-empty body, and the two must
not look alike. A team with one played match and no scouting returns the full
TeamMetrics with score_stddev/consistency_rating None and
defense_insufficient_data True -- "we measured this team and have little to
say". If an absent row also returned 200, a client would have to reconstruct
the difference between that and "we have not measured this team at all" from
which nullable fields happen to be set, which is precisely the confusion
DefenseFeedingProfile's insufficient_data flags exist to prevent. Absent is a
404; thin is a 200 carrying its own confidence signals intact. Neither is ever
an error about data quality: this endpoint reports low confidence, it never
converts it into a failure or fills it in.
"""

from __future__ import annotations

import logging
from http import HTTPStatus

from fastapi import APIRouter, Depends, Path
from starlette.requests import Request

from api.dependencies import get_database
from api.errors import ApiError, ErrorResponse
from api.request_id import get_request_id
from data.metrics.read import (
    STATUS_EVENT_NOT_FOUND,
    STATUS_METRICS_NOT_COMPUTED,
    STATUS_TEAM_DID_NOT_ATTEND,
    STATUS_TEAM_NOT_FOUND,
    look_up_team_metrics,
)
from data.metrics.schemas import TeamMetrics
from database.connection import Database


logger = logging.getLogger(__name__)

router = APIRouter(tags=["metrics"])


# Maps each of data.metrics.read's not-found statuses onto the response it
# produces: (error code, message template). The code deliberately matches the
# lookup status string -- the vocabulary is the same distinction, named once --
# but the mapping is explicit so the HTTP contract is readable in one place and
# the data layer stays free to name its statuses without that being an API
# change by accident.
_NOT_FOUND_RESPONSES: dict[str, tuple[str, str]] = {
    STATUS_TEAM_NOT_FOUND: (
        STATUS_TEAM_NOT_FOUND,
        "Team {team_number} is not known to StratAI.",
    ),
    STATUS_EVENT_NOT_FOUND: (
        STATUS_EVENT_NOT_FOUND,
        "Event '{event_key}' is not known to StratAI.",
    ),
    STATUS_TEAM_DID_NOT_ATTEND: (
        STATUS_TEAM_DID_NOT_ATTEND,
        "Team {team_number} is not rostered in any match at event '{event_key}'.",
    ),
    STATUS_METRICS_NOT_COMPUTED: (
        STATUS_METRICS_NOT_COMPUTED,
        "Metrics for team {team_number} at event '{event_key}' have not been computed yet.",
    ),
}


@router.get(
    "/teams/{team_number}/events/{event_key}/metrics",
    response_model=TeamMetrics,
    summary="Team metrics at one event",
    description=(
        "Returns the complete computed metrics object for one team at one event: "
        "scoring statistics from match history, and defense/feeding aggregated from "
        "scouting observations. Reads stored metrics directly and never recomputes. "
        "A team with thin data still returns the full object, with its confidence "
        "fields (matches_used, the insufficient_data flags, the agreement scores) "
        "reporting exactly how thin it is. reliability_score is an INTERIM "
        "placeholder: the attendance ratio 100 * matches_used / matches_scheduled, "
        "not a robot-failure or disqualification measure. Returns 404 with one of "
        "four distinct error codes -- team_not_found, event_not_found, "
        "team_did_not_attend, metrics_not_computed -- when no metrics object exists."
    ),
    responses={
        HTTPStatus.NOT_FOUND: {"model": ErrorResponse},
        # Declared explicitly, overriding the HTTPValidationError schema FastAPI
        # generates for any route with validated parameters. That default would
        # document {"detail": [...]}, which is not what this API returns:
        # api.errors renders a 422 into the same envelope as every other error.
        # The first route with path parameters is the first place that default
        # could have misdocumented the contract.
        HTTPStatus.UNPROCESSABLE_ENTITY: {"model": ErrorResponse},
    },
)
def team_metrics(
    request: Request,
    team_number: int = Path(gt=0, description="FRC team number, e.g. 1114."),
    event_key: str = Path(min_length=1, description="TBA event key, e.g. 2026casj."),
    database: Database = Depends(get_database),
) -> TeamMetrics:
    """Return one team's stored metrics at one event.

    Declared with def rather than async def for the same reason /ready is:
    psycopg is synchronous, so FastAPI runs this in a threadpool and a slow
    query cannot stall the event loop for every other in-flight request.

    team_number is constrained gt=0 to match TeamMetrics' own bound, so a
    request for team 0 is a 422 rather than a 404 -- it is not a missing team,
    it is not a team number.

    Raises:
        ApiError: 404, with one of four codes naming why no metrics exist.
    """
    lookup = look_up_team_metrics(database, team_number, event_key)
    if lookup.metrics is not None:
        return lookup.metrics

    code, message_template = _NOT_FOUND_RESPONSES[lookup.status]
    # Logged at info: a 404 here is an ordinary, expected answer (a client
    # polling for metrics mid-event will see metrics_not_computed), not a fault.
    # The reason is worth recording so "why is the frontend seeing 404s" is
    # answerable from the log without reproducing it.
    logger.info(
        "No metrics for team %d at event %s: %s request_id=%s",
        team_number, event_key, lookup.status, get_request_id(request),
    )
    raise ApiError(
        status_code=HTTPStatus.NOT_FOUND,
        code=code,
        message=message_template.format(team_number=team_number, event_key=event_key),
    )
