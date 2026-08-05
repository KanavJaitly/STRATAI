from __future__ import annotations

from dataclasses import dataclass
from typing import Any, ClassVar

import httpx

from data.clients.http_retry import request_with_retries
from data.clients.schemas import StatboticsMatchStats, StatboticsTeamEventMetrics
from data.clients.source_connector import SourceConnector, SourceResponse
from data.config import Settings


@dataclass
class StatboticsClient(SourceConnector):
    """Statbotics API client for fetching EPA-based match statistics and team-event metrics.

    Statbotics's public API does not require authentication for standard
    usage, unlike TBA. If STATBOTICS_API_KEY is configured it is sent as a
    bearer token, so this client supports any future authenticated tier
    without requiring code changes; when no key is configured, requests are
    simply sent unauthenticated.

    The base URL was wrong until 2026-07-25: it pointed at api.statbotics.org,
    a host that does not resolve at all, so every Statbotics lookup failed with
    a DNS error and team_event_stats was never populated. The real service is
    api.statbotics.io, whose FastAPI app self-identifies as the "API V3 Router".

    Endpoint paths below (/team_event/{team}/{event} and /matches?event=) are
    confirmed against Statbotics's published route definitions. The response
    shape is deeply nested -- EPA under `epa`/`epa.breakdown`, the match record
    under `record.total` -- and the flattening lives in the response models (see
    data/clients/schemas.py) so this client and everything downstream keep
    working in flat fields.

    Still unverified against a live response: at the time of the fix every
    api.statbotics.io/v3/* endpoint was returning HTTP 500 from Statbotics's own
    infrastructure, so the shape below is derived from their source rather than
    captured from a real request. Re-verify once their API recovers; see
    tests/fixtures/statbotics_team_event_2024casj.json.

    For landing-layer integration: a team-event metrics record has no single
    natural string identifier the way a TBA match or team does, so callers
    should use a composite `source_object_id` of f"{team}_{event}".
    """

    settings: Settings
    timeout: float | None = None
    max_retries: int | None = None
    backoff_factor: float | None = None
    base_url: str = "https://api.statbotics.io/v3"
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
        # max_retries/backoff_factor are typed Optional only to let a caller
        # override the Settings default; __post_init__ always resolves both
        # to a concrete value before any request can be made.
        assert self.max_retries is not None
        assert self.backoff_factor is not None
        return request_with_retries(
            self._client, method, url,
            max_retries=self.max_retries, backoff_factor=self.backoff_factor, params=params,
        )

    def fetch_event_match_stats(self, event_key: str) -> list[SourceResponse[StatboticsMatchStats]]:
        """Fetch EPA-based match statistics for every match at an event."""
        data = self._request("GET", "/matches", params={"event": event_key})
        # Some APIs return null rather than [] for "no results"; treat both as empty.
        return [SourceResponse(item, StatboticsMatchStats.model_validate(item)) for item in (data or [])]

    def fetch_team_event_metrics(self, team_number: int, event_key: str) -> SourceResponse[StatboticsTeamEventMetrics]:
        """Fetch a team's EPA-based performance metrics for a specific event.

        `raw` keeps Statbotics's nested response exactly as sent (`epa.total_points`,
        `record.total.wins`, ...) so that is what lands; `parsed` is the same data
        flattened by StatboticsTeamEventMetrics's validator. The staging normalizer
        re-validates the landed nested body through that same validator, so both
        paths agree.
        """
        data = self._request("GET", f"/team_event/{team_number}/{event_key}")
        return SourceResponse(data, StatboticsTeamEventMetrics.model_validate(data))

    def close(self) -> None:
        """Close the underlying HTTP client."""
        self._client.close()
