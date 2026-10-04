"""Shared pieces of the Phase 4/5 API routes: error codes and builders, the EPA-source
envelope, and roster checks. Moved here from api.routes.predictions when the Phase 5
routes needed them (one implementation, re-exported by predictions unchanged)."""

from __future__ import annotations

from datetime import datetime
from http import HTTPStatus
from typing import Any

from pydantic import BaseModel, Field

from api.errors import ApiError
from api.ml_loading import ServedEpaSource
from database.connection import Database
from ml.features.roster import list_teams_at_event
from ml.ratings.statbotics_primary import SilentFallbackError

CODE_EPA_SOURCE_NOT_LOADED = "epa_source_not_loaded"
CODE_EPA_SOURCE_INCOMPLETE = "epa_source_incomplete"
CODE_EPA_SOURCE_PENDING = "epa_source_pending"  # P5-M2 §5: a prior event ended < 72 h ago, unprocessed
CODE_EVENT_NOT_FOUND = "event_not_found"
CODE_TEAM_NOT_FOUND = "team_not_found"


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
