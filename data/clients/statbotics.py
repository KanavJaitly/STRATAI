from __future__ import annotations

from dataclasses import dataclass
from typing import Any, ClassVar

import httpx

from data.clients.http_retry import request_with_retries
from data.clients.schemas import StatboticsMatchStats, StatboticsTeamEventMetrics
from data.clients.source_connector import SourceConnector
from data.config import Settings


@dataclass
class StatboticsClient(SourceConnector):
    """Statbotics API client for fetching EPA-based match statistics and team-event metrics.

    Statbotics's public API does not require authentication for standard
    usage, unlike TBA. If STATBOTICS_API_KEY is configured it is sent as a
    bearer token, so this client supports any future authenticated tier
    without requiring code changes; when no key is configured, requests are
    simply sent unauthenticated.

    Endpoint paths, query parameter names, and response field names below are
    a best-effort match to Statbotics's public architecture (FastAPI service,
    TBA-derived Matches/TeamEvents entities, no documented auth requirement)
    but have not been verified against a live response, since this connector
    was built and tested entirely against mocked HTTP responses. Confirm
    these against a real request before relying on this in production.

    For landing-layer integration: a team-event metrics record has no single
    natural string identifier the way a TBA match or team does, so callers
    should use a composite `source_object_id` of f"{team}_{event}".
    """

    settings: Settings
    timeout: float | None = None
    max_retries: int | None = None
    backoff_factor: float | None = None
    base_url: str = "https://api.statbotics.org/v3"
    source_name: ClassVar[str] = "statbotics"

    def __post_init__(self) -> None:
        self.timeout = self.timeout if self.timeout is not None else self.settings.statbotics_timeout
        self.max_retries = self.max_retries if self.max_retries is not None else self.settings.statbotics_max_retries
        self.backoff_factor = (
            self.backoff_factor if self.backoff_factor is not None else self.settings.statbotics_backoff_factor
        )
        self._headers = {"Accept": "application/json"}
        if self.settings.statbotics_api_key:
            self._headers["Authorization"] = f"Bearer {self.settings.statbotics_api_key}"
        self._client = httpx.Client(timeout=self.timeout, headers=self._headers)

    def _request(self, method: str, path: str, params: dict[str, Any] | None = None) -> Any:
        url = f"{self.base_url}{path}"
        return request_with_retries(
            self._client, method, url,
            max_retries=self.max_retries, backoff_factor=self.backoff_factor, params=params,
        )

    def fetch_event_match_stats(self, event_key: str) -> list[StatboticsMatchStats]:
        """Fetch EPA-based match statistics for every match at an event."""
        data = self._request("GET", "/matches", params={"event": event_key})
        # Some APIs return null rather than [] for "no results"; treat both as empty.
        return [StatboticsMatchStats.model_validate(item) for item in (data or [])]

    def fetch_team_event_metrics(self, team_number: int, event_key: str) -> StatboticsTeamEventMetrics:
        """Fetch a team's EPA-based performance metrics for a specific event."""
        data = self._request("GET", f"/team_event/{team_number}/{event_key}")
        return StatboticsTeamEventMetrics.model_validate(data)

    def close(self) -> None:
        """Close the underlying HTTP client."""
        self._client.close()

    def __enter__(self) -> "StatboticsClient":
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.close()
