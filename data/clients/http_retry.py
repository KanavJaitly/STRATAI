from __future__ import annotations

import logging
import time
from typing import Any

import httpx

logger = logging.getLogger(__name__)


def is_transient_status(status_code: int) -> bool:
    """Return True if an HTTP status code represents a transient, retryable failure."""
    return status_code == 429 or 500 <= status_code < 600


def request_with_retries(
    client: httpx.Client,
    method: str,
    url: str,
    *,
    max_retries: int,
    backoff_factor: float,
    params: dict[str, Any] | None = None,
) -> Any:
    """Perform an HTTP request, retrying transient failures with exponential backoff.

    Retries on connection/timeout errors and on 429/5xx responses. Any other
    HTTP error (e.g. 404, 401) is raised immediately without retrying. Shared
    by every source connector so retry/backoff behavior stays identical across
    TBA, Statbotics, and future sources instead of being reimplemented per client.
    """
    for attempt in range(1, max_retries + 1):
        try:
            response = client.request(method, url, params=params)
            response.raise_for_status()
            return response.json()
        except (httpx.TimeoutException, httpx.ConnectError) as exc:
            if attempt == max_retries:
                logger.warning("Request to %s failed after %d attempts: %s", url, attempt, exc)
                raise
            sleep_time = backoff_factor * (2 ** (attempt - 1))
            logger.warning(
                "Request to %s failed (attempt %d/%d): %s. Retrying in %.1fs",
                url, attempt, max_retries, exc, sleep_time,
            )
            time.sleep(sleep_time)
        except httpx.HTTPStatusError as exc:
            status_code = exc.response.status_code if exc.response is not None else None
            if status_code is not None and is_transient_status(status_code):
                if attempt == max_retries:
                    logger.warning(
                        "Request to %s failed after %d attempts (status %d)",
                        url, attempt, status_code,
                    )
                    raise
                sleep_time = backoff_factor * (2 ** (attempt - 1))
                logger.warning(
                    "Request to %s got status %d (attempt %d/%d). Retrying in %.1fs",
                    url, status_code, attempt, max_retries, sleep_time,
                )
                time.sleep(sleep_time)
                continue
            raise
        except httpx.HTTPError:
            raise
    raise RuntimeError("Request retry logic exhausted")
