from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from datetime import date
from typing import Any

import httpx

from data.clients.schemas import EventSummary, Match, TeamInfo
from data.clients.source_connector import SourceConnector
from data.config import Settings

logger = logging.getLogger(__name__)


@dataclass
class TBAClient(SourceConnector):
    """TBA API client for fetching events, matches, and team information."""

    settings: Settings
    timeout: float | None = None
    max_retries: int | None = None
    backoff_factor: float | None = None
    base_url: str = "https://www.thebluealliance.com/api/v3"

    def __post_init__(self) -> None:
        self.timeout = self.timeout if self.timeout is not None else self.settings.tba_timeout
        self.max_retries = self.max_retries if self.max_retries is not None else self.settings.tba_max_retries
        self.backoff_factor = self.backoff_factor if self.backoff_factor is not None else self.settings.tba_backoff_factor
        self._headers = {
            "X-TBA-Auth-Key": self.settings.tba_api_key,
            "Accept": "application/json",
        }
        self._client = httpx.Client(timeout=self.timeout, headers=self._headers)

    def _is_transient_status(self, status_code: int) -> bool:
        return status_code == 429 or 500 <= status_code < 600

    def _request(self, method: str, path: str, params: dict[str, Any] | None = None) -> Any:
        url = f"{self.base_url}{path}"
        for attempt in range(1, self.max_retries + 1):
            try:
                response = self._client.request(method, url, params=params)
                response.raise_for_status()
                return response.json()
            except (httpx.TimeoutException, httpx.ConnectError) as exc:
                if attempt == self.max_retries:
                    logger.warning("TBA request to %s failed after %d attempts: %s", url, attempt, exc)
                    raise
                sleep_time = self.backoff_factor * (2 ** (attempt - 1))
                logger.warning(
                    "TBA request to %s failed (attempt %d/%d): %s. Retrying in %.1fs",
                    url, attempt, self.max_retries, exc, sleep_time,
                )
                time.sleep(sleep_time)
            except httpx.HTTPStatusError as exc:
                status_code = exc.response.status_code if exc.response is not None else None
                if status_code is not None and self._is_transient_status(status_code):
                    if attempt == self.max_retries:
                        logger.warning(
                            "TBA request to %s failed after %d attempts (status %d)",
                            url, attempt, status_code,
                        )
                        raise
                    sleep_time = self.backoff_factor * (2 ** (attempt - 1))
                    logger.warning(
                        "TBA request to %s got status %d (attempt %d/%d). Retrying in %.1fs",
                        url, status_code, attempt, self.max_retries, sleep_time,
                    )
                    time.sleep(sleep_time)
                    continue
                raise
            except httpx.HTTPError:
                raise
        raise RuntimeError("TBA request retry logic exhausted")

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
