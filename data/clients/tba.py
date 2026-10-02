from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Any, ClassVar

import httpx

from data.clients.http_retry import request_with_retries
from data.clients.schemas import EventAlliance, EventRankings, EventSummary, Match, TeamInfo
from data.clients.source_connector import SourceConnector, SourceResponse
from data.config import Settings


@dataclass
class TBAClient(SourceConnector):
    """TBA API client for fetching events, matches, and team information."""

    settings: Settings
    timeout: float | None = None
    max_retries: int | None = None
    backoff_factor: float | None = None
    base_url: str = "https://www.thebluealliance.com/api/v3"
    source_name: ClassVar[str] = "tba"

    def __post_init__(self) -> None:
        self.timeout = self.timeout if self.timeout is not None else self.settings.tba_timeout
        self.max_retries = self.max_retries if self.max_retries is not None else self.settings.tba_max_retries
        self.backoff_factor = self.backoff_factor if self.backoff_factor is not None else self.settings.tba_backoff_factor
        self._headers = {
            "X-TBA-Auth-Key": self.settings.tba_api_key,
            "Accept": "application/json",
        }
        self._client = httpx.Client(timeout=self.timeout, headers=self._headers)

    def _request(self, method: str, path: str, params: dict[str, Any] | None = None) -> Any:
        url = f"{self.base_url}{path}"
        # max_retries/backoff_factor are typed Optional only to let a caller
        # override the Settings default; __post_init__ always resolves both
        # to a concrete value before any request can be made.
        assert self.max_retries is not None
        assert self.backoff_factor is not None
        return request_with_retries(
            self._client, method, url,
            max_retries=self.max_retries, backoff_factor=self.backoff_factor, params=params,
        )

    def fetch_event_list(self, year: int | None = None) -> list[SourceResponse[EventSummary]]:
        """Fetch a list of events for the specified year or current season."""
        if year is None:
            year = date.today().year

        data = self._request("GET", f"/events/{year}")
        return [SourceResponse(item, EventSummary.model_validate(item)) for item in (data or [])]

    def fetch_event(self, event_key: str) -> SourceResponse[EventSummary]:
        """Fetch a single event by key.

        fetch_event_list only exposes a whole season at once; syncing one event
        would otherwise mean downloading every event of that year and filtering
        client-side.
        """
        data = self._request("GET", f"/event/{event_key}")
        return SourceResponse(data, EventSummary.model_validate(data))

    def fetch_event_teams(self, event_key: str) -> list[SourceResponse[TeamInfo]]:
        """Fetch every team attending an event.

        One request for the full roster, versus one fetch_team_info call per
        team (~40 requests for a typical regional).
        """
        data = self._request("GET", f"/event/{event_key}/teams")
        return [SourceResponse(item, TeamInfo.model_validate(item)) for item in (data or [])]

    def fetch_event_matches(self, event_key: str) -> list[SourceResponse[Match]]:
        """Fetch all matches for an event."""
        data = self._request("GET", f"/event/{event_key}/matches")
        return [SourceResponse(item, Match.model_validate(item)) for item in (data or [])]

    def fetch_event_rankings(self, event_key: str) -> SourceResponse[EventRankings]:
        """Fetch an event's qualification ranking.

        TBA returns a bare `null` body, not an empty {"rankings": []}, for an
        event with no computed ranking yet (unplayed, or very early in a
        multi-day event before quals conclude) -- confirmed against TBA's
        live OpenAPI spec, not assumed. That null is preserved verbatim in
        the returned SourceResponse.raw (the landing layer's own "store
        exactly what the API sent" rule applies here too), while `parsed`
        degrades to an empty EventRankings rather than failing to validate.
        """
        data = self._request("GET", f"/event/{event_key}/rankings")
        parsed = EventRankings.model_validate(data) if data is not None else EventRankings(rankings=[])
        return SourceResponse(data, parsed)

    def fetch_event_alliances(self, event_key: str) -> SourceResponse[list[EventAlliance]]:
        """Fetch an event's playoff alliances (seed order). TBA's bare `null` for an
        event without alliance selection is preserved in SourceResponse.raw; `parsed`
        is then an empty list."""
        data = self._request("GET", f"/event/{event_key}/alliances")
        return SourceResponse(data, [EventAlliance.model_validate(item) for item in (data or [])])

    def fetch_team_info(self, team_number: int) -> SourceResponse[TeamInfo]:
        """Fetch team information by team number."""
        data = self._request("GET", f"/team/frc{team_number}")
        return SourceResponse(data, TeamInfo.model_validate(data))

    def close(self) -> None:
        """Close the underlying HTTP client."""
        self._client.close()
