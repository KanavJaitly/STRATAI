from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Any, ClassVar

import httpx

from data.clients.http_retry import request_with_retries
from data.clients.schemas import EventSummary, Match, TeamInfo
from data.clients.source_connector import SourceConnector
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
        return request_with_retries(
            self._client, method, url,
            max_retries=self.max_retries, backoff_factor=self.backoff_factor, params=params,
        )

    def fetch_event_list(self, year: int | None = None) -> list[EventSummary]:
        """Fetch a list of events for the specified year or current season."""
        if year is None:
            year = date.today().year

        data = self._request("GET", f"/events/{year}")
        return [EventSummary.model_validate(item) for item in data]

    def fetch_event_matches(self, event_key: str) -> list[Match]:
        """Fetch all matches for an event."""
        data = self._request("GET", f"/event/{event_key}/matches")
        return [Match.model_validate(item) for item in data]

    def fetch_team_info(self, team_number: int) -> TeamInfo:
        """Fetch team information by team number."""
        data = self._request("GET", f"/team/frc{team_number}")
        return TeamInfo.model_validate(data)

    def close(self) -> None:
        """Close the underlying HTTP client."""
        self._client.close()

    def __enter__(self) -> "TBAClient":
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.close()
