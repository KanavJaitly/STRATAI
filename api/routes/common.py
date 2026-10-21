"""Shared pieces of the Phase 4/5 API routes: error codes and builders, the EPA-source
envelope, and roster checks. Moved here from api.routes.predictions when the Phase 5
routes needed them (one implementation, re-exported by predictions unchanged)."""

from __future__ import annotations

import hmac
from datetime import datetime, timedelta, timezone
from http import HTTPStatus

from typing import Any

from fastapi import Depends
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from starlette.requests import Request

from api.dependencies import get_settings
from api.errors import ApiError, http_exception_handler
from api.ml_loading import ServedEpaSource
from data.config import Settings
from database.connection import Database
from ml.features.roster import list_teams_at_event
from ml.features.score_breakdown import UnsupportedSeasonError
from ml.ratings.statbotics_primary import SilentFallbackError

CODE_EPA_SOURCE_NOT_LOADED = "epa_source_not_loaded"
CODE_EPA_SOURCE_INCOMPLETE = "epa_source_incomplete"
CODE_EPA_SOURCE_PENDING = "epa_source_pending"  # P5-M2 §5: a prior event ended < 72 h ago, unprocessed
CODE_EVENT_NOT_FOUND = "event_not_found"
CODE_TEAM_NOT_FOUND = "team_not_found"
CODE_INVALID_AS_OF = "invalid_as_of"

# The shared write-token mechanism (Phase 5; moved here from api.routes.human_inputs by P7-M5, behaviour unchanged).
WRITE_TOKEN_HEADER = "X-StratAI-Write-Token"
CODE_WRITES_DISABLED, CODE_WRITE_NOT_AUTHORIZED = "writes_disabled", "write_not_authorized"


def require_writer(request: Request, settings: Settings = Depends(get_settings)) -> None:
    """Fail closed: no configured token means no writes. A constant-time comparison against
    Settings.human_inputs_write_token. One shared secret: no per-user identity, rotation or rate limiting (P7-Q10)."""
    expected = settings.human_inputs_write_token
    if not expected:
        raise ApiError(status_code=HTTPStatus.FORBIDDEN, code=CODE_WRITES_DISABLED,
                       message="Writes are disabled: no human_inputs_write_token is configured.")
    supplied = request.headers.get(WRITE_TOKEN_HEADER, "")
    if not hmac.compare_digest(supplied.encode("utf-8"), expected.encode("utf-8")):
        raise ApiError(status_code=HTTPStatus.FORBIDDEN, code=CODE_WRITE_NOT_AUTHORIZED,
                       message=f"A valid {WRITE_TOKEN_HEADER} header is required for this write.")


CODE_MODEL_NOT_LOADED = "model_not_loaded"


def model_not_loaded_error(model_type: str, why: str = "") -> ApiError:
    """404 model_not_loaded: the route's model of record is not pinned or failed its checks. 404, not 503, because
    api.errors strips route codes at >= 500 (the metrics_not_computed precedent)."""
    message = f"No {model_type} model of record is pinned/loadable"
    return ApiError(status_code=HTTPStatus.NOT_FOUND, code=CODE_MODEL_NOT_LOADED,
                    message=message + (f": {why}" if why else "") + ".")


def problems_suffix(problems: Any, limit: int = 12) -> str:
    """Field-level problems appended to an error message (api.errors allow-lists `details` to request validation
    only, so a domain refusal carries its problems in the message)."""
    if not isinstance(problems, list) or not problems:
        return ""
    return " -- " + "; ".join(f"{p.get('field')}: {p.get('message')}" for p in problems[:limit] if isinstance(p, dict))


# A request's own clock may run slightly ahead of the server's; an as_of this far past "now" still counts as now.
AS_OF_CLOCK_SKEW = timedelta(minutes=5)
AS_OF_DESCRIPTION = ("ISO-8601 with a timezone offset (URL-encode + as %2B, or use Z); default: now. Not in the "
                     "future (P7-D1, P7-D4). Only data available before it is used.")


def parse_as_of(value: str | None) -> datetime:
    """A request's as_of: now when omitted; otherwise an ISO-8601 time with an offset (else invalid_as_of).

    A time later than now (beyond AS_OF_CLOCK_SKEW) is refused with invalid_as_of, and one within the skew is
    clamped to now, on every route (P7-D1 for the P7-M3 POST routes; P7-D4 for all). At a future as_of an event
    still in progress would count as a completed "prior event", so its mid-event EPA could be served as prior EPA
    and an output labelled as if it were inside its evaluated population
    (.agent/phase7/decisions/P7_D1_NO_FUTURE_AS_OF.md, P7_D4_MID_PHASE_AUDIT.md).
    """
    now = datetime.now(timezone.utc)
    if value is None:
        return now
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError as exc:
        raise ApiError(status_code=HTTPStatus.UNPROCESSABLE_ENTITY, code=CODE_INVALID_AS_OF,
                       message=f"as_of {value!r} is not an ISO-8601 timestamp (URL-encode a '+' offset as %2B, "
                               "or use 'Z')") from exc
    if parsed.tzinfo is None:
        raise ApiError(status_code=HTTPStatus.UNPROCESSABLE_ENTITY, code=CODE_INVALID_AS_OF,
                       message="as_of must include a timezone offset")
    if parsed > now:
        if parsed - now > AS_OF_CLOCK_SKEW:
            raise ApiError(status_code=HTTPStatus.UNPROCESSABLE_ENTITY, code=CODE_INVALID_AS_OF,
                           message="as_of may not be in the future: a later time would treat an event still in "
                                   "progress as a completed prior event")
        return now
    return parsed
CODE_SEASON_NOT_SUPPORTED = "season_not_supported"  # 2026-10-12: no score_breakdown adapter for the season


class EpaSourceInfo(BaseModel):
    epa_source: str
    evaluated_configuration: bool = Field(description="True only for d18_statbotics_primary, the evaluated source")
    provenance: dict[str, Any]
    adoption: dict[str, Any] | None = Field(
        default=None, description="P5-D3: the live source is adopted for production after passing its historical "
                                  "acceptance (P5-M2 L1-L4); prospective 2027 validation is pending")
    validation_flags: list[str] = Field(
        default_factory=list,
        description="live_refresh_not_yet_validated when this response used a value from a non-root live snapshot "
                    "or a live STRATAI fallback (LIVE_EPA_REFRESH_DESIGN.md §9); outputs keep their base status")


def epa_source_not_loaded_error() -> ApiError:
    return ApiError(
        status_code=HTTPStatus.NOT_FOUND, code=CODE_EPA_SOURCE_NOT_LOADED,
        message="The configured EPA source is not loaded (unconfigured or failed its integrity checks).",
    )


def event_not_found_error(event_key: str) -> ApiError:
    return ApiError(
        status_code=HTTPStatus.NOT_FOUND, code=CODE_EVENT_NOT_FOUND,
        message=f"Event '{event_key}' is not known to StratAI.",
    )


def team_not_found_error(team_number: int, event_key: str) -> ApiError:
    return ApiError(
        status_code=HTTPStatus.NOT_FOUND, code=CODE_TEAM_NOT_FOUND,
        message=f"Team {team_number} is not rostered in any match at event '{event_key}'.",
    )


def epa_source_incomplete_error(exc: SilentFallbackError) -> ApiError:
    from ml.ratings.live_epa import EpaSourcePendingError

    if isinstance(exc, EpaSourcePendingError):
        return ApiError(
            status_code=HTTPStatus.UNPROCESSABLE_ENTITY, code=CODE_EPA_SOURCE_PENDING,
            message=f"A required prior event ({exc.record['candidate']}) ended less than 72 h ago and Statbotics "
                    "has not processed it yet; no older event is substituted.",
        )
    return ApiError(
        status_code=HTTPStatus.UNPROCESSABLE_ENTITY, code=CODE_EPA_SOURCE_INCOMPLETE,
        message=f"The EPA source has no valid value for a required prior event ({exc.record['candidate']}); "
                "it does not silently substitute an older event.",
    )


def season_not_supported_error(exc: UnsupportedSeasonError) -> ApiError:
    return ApiError(
        status_code=HTTPStatus.UNPROCESSABLE_ENTITY, code=CODE_SEASON_NOT_SUPPORTED,
        message=f"Season {exc.season} has no verified score_breakdown adapter, so its features are not built "
                "(never a guessed value).",
    )


async def unsupported_season_handler(request: Request, exc: Exception) -> JSONResponse:
    """An UnsupportedSeasonError from feature assembly, as an explained 422 rather than a 500 (2026-10-12).

    Any route that builds features can meet a season without an adapter (for example a 2023 event); the
    fail-closed adapter is correct, and this only reports it in the error envelope.
    """
    assert isinstance(exc, UnsupportedSeasonError)
    return await http_exception_handler(request, season_not_supported_error(exc))


def require_epa_source(epa_source: ServedEpaSource | None) -> ServedEpaSource:
    if epa_source is None:
        raise epa_source_not_loaded_error()
    return epa_source


def epa_info(epa_source: ServedEpaSource, as_of: datetime | None = None,
             states: list[str | None] | None = None) -> EpaSourceInfo:
    """The EPA envelope. For the adopted live source, `live_refresh_not_yet_validated` is added when the
    response's as_of reads a non-root snapshot or any team was served `fallback_stratai` (§9)."""
    flags: list[str] = []
    if epa_source.adoption is not None:
        from ml.ratings.live_epa import LIVE_REFRESH_NOT_YET_VALIDATED

        view = epa_source.provider.snapshot_view(as_of) if as_of is not None else None
        if (view is not None and not view.is_root) or "fallback_stratai" in (states or []):
            flags.append(LIVE_REFRESH_NOT_YET_VALIDATED)
    return EpaSourceInfo(epa_source=epa_source.epa_source, evaluated_configuration=epa_source.evaluated_configuration,
                         provenance=epa_source.provenance, adoption=epa_source.adoption, validation_flags=flags)


def require_teams_rostered(database: Database, event_key: str, team_numbers: list[int]) -> None:
    """Raises team_not_found for the first supplied team_number not on
    event_key's own roster (ml.features.roster.list_teams_at_event)."""
    roster = set(list_teams_at_event(database, event_key))
    for team_number in team_numbers:
        if team_number not in roster:
            raise team_not_found_error(team_number, event_key)
