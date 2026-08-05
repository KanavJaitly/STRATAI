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

    max_retries must be at least 1 (it is the total attempt count, not a count
    of retries *after* a first attempt -- attempt ranges over [1, max_retries]):
    found during a system-wide audit that `range(1, max_retries + 1)` silently
    makes zero requests for max_retries=0 and falls through to a generic,
    unhelpful RuntimeError instead of either trying once or failing loudly
    about the misconfiguration. Settings itself now rejects a configured value
    below 1 (data/config.py), but this function validates independently since
    it is a shared utility any future caller could invoke directly.

    Retries on httpx.NetworkError (covers ConnectError/ReadError/WriteError/
    CloseError) and httpx.RemoteProtocolError, not just ConnectError -- a
    dropped connection mid-read/write or a malformed response from a flaky
    server/proxy (e.g. venue wifi during a live event) is exactly as
    transient as a failed initial connect, and previously fell through to the
    generic `except httpx.HTTPError: raise` below with no retry at all.
    Deliberately NOT httpx.ProtocolError as a whole: its other subclass,
    LocalProtocolError, means *this client* built a malformed request, which
    retrying would only repeat identically, not recover from.
    """
    if max_retries < 1:
        raise ValueError(f"max_retries must be at least 1 (a value of {max_retries!r} would make zero requests)")

    for attempt in range(1, max_retries + 1):
        try:
            response = client.request(method, url, params=params)
            response.raise_for_status()
            return response.json()
        except (httpx.TimeoutException, httpx.NetworkError, httpx.RemoteProtocolError) as exc:
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
