"""Two-stage Statbotics readiness check against one known-good real record.

Stage A (transport): can StratAI get a well-formed JSON object back from the
exact endpoint the pipeline calls?  Stage B (data): does that object pass the
production parse path -- StatboticsTeamEventMetrics, the staging normalizer,
and the staging quality rules -- and carry real, finite EPA and a real match
count?

Both stages run in memory. Nothing here lands a raw payload, stages a row, or
opens a database connection: a smoke test that wrote to raw_source_payloads
or team_event_stats would put a health-check artifact into the historical
record. Passing Stage B means "the pipe is clear", not "the historical data is
present" -- the latter is a separate gate this module does not answer.
"""

from __future__ import annotations

import json
import math
import time
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from typing import Any

import httpx

from data.clients.http_retry import request_with_retries
from data.clients.statbotics import StatboticsClient
from data.staging.normalizer import normalize_statbotics_team_event_stats
from data.staging.quality import SEVERITY_CRITICAL, SEVERITY_ERROR, check_entity
from data.staging.validator import PayloadValidationError

# Team 1678 at 2024casj backs tests/fixtures/statbotics_team_event_2024casj.json,
# captured live on 2026-08-01. The pair must be known to exist: Statbotics
# answers a nonexistent team-event with HTTP 500, indistinguishable from an
# outage (the 254/2024casj false alarm recorded in that fixture's provenance).
PROBE_TEAM = 1678
PROBE_EVENT = "2024casj"
PROBE_PATH = f"/team_event/{PROBE_TEAM}/{PROBE_EVENT}"

# Two attempts, not the pipeline's three: one retry is enough to absorb a
# single dropped connection, and a daily probe has no reason to lean on a
# service that is already failing.
DEFAULT_TIMEOUT_SECONDS = 15.0
DEFAULT_ATTEMPTS = 2
DEFAULT_BACKOFF_SECONDS = 2.0

STAGE_A = "A"
STAGE_B = "B"

FAIL_HTTP_STATUS = "http_status"
FAIL_TIMEOUT = "timeout"
FAIL_NETWORK = "network"
FAIL_PROTOCOL = "protocol"
FAIL_EMPTY_BODY = "empty_body"
FAIL_MALFORMED_JSON = "malformed_json"
FAIL_UNEXPECTED_SHAPE = "unexpected_shape"
FAIL_SCHEMA_INVALID = "schema_invalid"
FAIL_IDENTITY_MISMATCH = "identity_mismatch"
FAIL_EPA_MISSING = "epa_missing"
FAIL_EPA_NOT_FINITE = "epa_not_finite"
FAIL_MATCH_COUNT_INVALID = "match_count_invalid"
FAIL_QUALITY_ERROR = "quality_error"
FAIL_UNEXPECTED_ERROR = "unexpected_error"

# Failures that mean Statbotics answered 200 with content StratAI cannot use.
# Waiting does not fix these the way it fixes a 503, so repeated occurrences
# trip the monitor's circuit breaker instead of being retried forever.
DATA_CONTRACT_FAILURES = frozenset({
    FAIL_UNEXPECTED_SHAPE, FAIL_SCHEMA_INVALID, FAIL_IDENTITY_MISMATCH,
    FAIL_EPA_MISSING, FAIL_EPA_NOT_FINITE, FAIL_MATCH_COUNT_INVALID, FAIL_QUALITY_ERROR,
})


@dataclass(frozen=True)
class ReadinessResult:
    """Outcome of one probe. `ready` is True only if both stages passed."""

    checked_at: str
    url: str
    ready: bool
    stage_a_passed: bool
    stage_b_passed: bool
    failed_stage: str | None
    failure_code: str | None
    detail: str
    http_status: int | None
    elapsed_ms: int
    epa_total: float | None = None
    matches_played: int | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def probe_url(base_url: str = StatboticsClient.base_url) -> str:
    return f"{base_url}{PROBE_PATH}"


def check_statbotics_readiness(
    http_client: httpx.Client | None = None,
    *,
    base_url: str = StatboticsClient.base_url,
    attempts: int = DEFAULT_ATTEMPTS,
    backoff_seconds: float = DEFAULT_BACKOFF_SECONDS,
    now: datetime | None = None,
) -> ReadinessResult:
    """Run Stage A then, only if it passed, Stage B. Never raises."""
    url = probe_url(base_url)
    checked_at = (now or datetime.now(timezone.utc)).isoformat()
    owns_client = http_client is None
    client = http_client or httpx.Client(
        timeout=DEFAULT_TIMEOUT_SECONDS, headers={"Accept": "application/json"},
    )
    started = time.monotonic()

    def result(**fields: Any) -> ReadinessResult:
        return ReadinessResult(
            checked_at=checked_at, url=url,
            elapsed_ms=int((time.monotonic() - started) * 1000), **fields,
        )

    try:
        try:
            body = request_with_retries(
                client, "GET", url, max_retries=attempts, backoff_factor=backoff_seconds,
            )
        except Exception as exc:  # classified below; the monitor must never crash on a probe
            code, status, detail = _classify_transport_failure(exc)
            return result(
                ready=False, stage_a_passed=False, stage_b_passed=False,
                failed_stage=STAGE_A, failure_code=code, detail=detail, http_status=status,
            )

        if body is None:
            return result(
                ready=False, stage_a_passed=False, stage_b_passed=False, failed_stage=STAGE_A,
                failure_code=FAIL_EMPTY_BODY, detail="HTTP 200 with a JSON null body", http_status=200,
            )
        if not isinstance(body, dict):
            return result(
                ready=False, stage_a_passed=False, stage_b_passed=False, failed_stage=STAGE_A,
                failure_code=FAIL_UNEXPECTED_SHAPE,
                detail=f"HTTP 200 with a JSON {type(body).__name__}, expected an object", http_status=200,
            )

        code, detail, epa_total, matches_played = _check_data_contract(body)
        return result(
            ready=code is None, stage_a_passed=True, stage_b_passed=code is None,
            failed_stage=None if code is None else STAGE_B, failure_code=code,
            detail=detail, http_status=200, epa_total=epa_total, matches_played=matches_played,
        )
    finally:
        if owns_client:
            client.close()


def _classify_transport_failure(exc: Exception) -> tuple[str, int | None, str]:
    if isinstance(exc, httpx.HTTPStatusError):
        status = exc.response.status_code
        return FAIL_HTTP_STATUS, status, f"HTTP {status}"
    if isinstance(exc, httpx.TimeoutException):
        return FAIL_TIMEOUT, None, f"timed out: {type(exc).__name__}"
    if isinstance(exc, httpx.RemoteProtocolError):
        return FAIL_PROTOCOL, None, f"protocol error: {exc}"
    if isinstance(exc, httpx.NetworkError):
        # DNS resolution failures surface as ConnectError, a NetworkError.
        return FAIL_NETWORK, None, f"{type(exc).__name__}: {exc}"
    if isinstance(exc, json.JSONDecodeError):
        if not (exc.doc or "").strip():
            return FAIL_EMPTY_BODY, 200, "HTTP 200 with an empty body"
        return FAIL_MALFORMED_JSON, 200, f"HTTP 200 with a body that is not JSON: {exc.msg}"
    return FAIL_UNEXPECTED_ERROR, None, f"{type(exc).__name__}: {exc}"


def _check_data_contract(body: dict[str, Any]) -> tuple[str | None, str, float | None, int | None]:
    """Stage B. Returns (failure_code or None, detail, epa_total, matches_played)."""
    try:
        staged = normalize_statbotics_team_event_stats(body)
    except PayloadValidationError as exc:
        fields = sorted({issue.field for issue in exc.issues})
        return FAIL_SCHEMA_INVALID, f"production schema rejected the payload (fields: {fields})", None, None

    epa_total = staged.epa_total
    matches_played = staged.matches_played

    if staged.team_number != PROBE_TEAM or staged.event_key != PROBE_EVENT:
        return (
            FAIL_IDENTITY_MISMATCH,
            f"asked for {PROBE_TEAM}/{PROBE_EVENT}, got {staged.team_number}/{staged.event_key}",
            epa_total, matches_played,
        )
    if epa_total is None:
        return FAIL_EPA_MISSING, "epa_total is absent or null", None, matches_played

    for name in ("epa_total", "epa_auto", "epa_teleop", "epa_endgame"):
        value = getattr(staged, name)
        if value is not None and not math.isfinite(float(value)):
            return FAIL_EPA_NOT_FINITE, f"{name}={value} is not a finite number", None, matches_played

    if matches_played is None or matches_played <= 0:
        return (
            FAIL_MATCH_COUNT_INVALID,
            f"matches_played={matches_played}; a team that played {PROBE_EVENT} must have a positive count",
            float(epa_total), matches_played,
        )

    blocking = [
        issue for issue in check_entity(staged, source="statbotics")
        if issue.severity in (SEVERITY_ERROR, SEVERITY_CRITICAL)
    ]
    if blocking:
        described = "; ".join(f"{issue.field}: {issue.description}" for issue in blocking)
        return FAIL_QUALITY_ERROR, f"staging quality rules rejected the payload: {described}", float(epa_total), matches_played

    return None, "real EPA data retrieved and accepted by the production parse path", float(epa_total), matches_played
