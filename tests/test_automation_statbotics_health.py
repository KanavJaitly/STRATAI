"""Tests for automation.statbotics_health -- the monitor's two-stage probe.

All HTTP is served by httpx.MockTransport; nothing here reaches Statbotics.
The healthy body is the real captured 1678/2024casj response
(tests/fixtures/statbotics_team_event_2024casj.json) with its provenance
block removed, i.e. exactly what the live endpoint sent.
"""

from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any, Callable

import httpx
import pytest

from automation import statbotics_health as health
from data.clients.statbotics import StatboticsClient
from data.config import Settings

FIXTURE_PATH = Path(__file__).parent / "fixtures" / "statbotics_team_event_2024casj.json"


def live_body() -> dict[str, Any]:
    payload = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))
    payload.pop("_fixture_provenance")
    return payload


def client_for(handler: Callable[[httpx.Request], httpx.Response]) -> tuple[httpx.Client, list[httpx.Request]]:
    seen: list[httpx.Request] = []

    def recording(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return handler(request)

    return httpx.Client(transport=httpx.MockTransport(recording)), seen


def probe(handler: Callable[[httpx.Request], httpx.Response]) -> tuple[health.ReadinessResult, list[httpx.Request]]:
    client, seen = client_for(handler)
    return health.check_statbotics_readiness(client, backoff_seconds=0.0), seen


def json_response(body: Any, status: int = 200) -> Callable[[httpx.Request], httpx.Response]:
    return lambda request: httpx.Response(status, json=body)


def raw_response(content: bytes, status: int = 200) -> Callable[[httpx.Request], httpx.Response]:
    return lambda request: httpx.Response(status, content=content, headers={"content-type": "application/json"})


def mutated(mutate: Callable[[dict[str, Any]], None]) -> dict[str, Any]:
    body = copy.deepcopy(live_body())
    mutate(body)
    return body


# --- healthy path ---------------------------------------------------------


def test_real_captured_response_is_ready():
    result, seen = probe(json_response(live_body()))
    assert result.ready and result.stage_a_passed and result.stage_b_passed
    assert result.failure_code is None and result.failed_stage is None
    assert result.http_status == 200
    assert result.epa_total is not None and result.epa_total > 0
    assert result.matches_played and result.matches_played > 0
    assert len(seen) == 1


def test_probe_hits_the_exact_url_the_production_client_uses():
    """Guards against the probe drifting away from what the pipeline calls."""
    production_client = StatboticsClient(settings=Settings.model_construct(
        statbotics_api_key=None, statbotics_timeout=5.0,
        statbotics_max_retries=1, statbotics_backoff_factor=0.0,
    ))
    client, seen = client_for(json_response(live_body()))
    production_client._client = client
    production_client.fetch_team_event_metrics(health.PROBE_TEAM, health.PROBE_EVENT)

    assert str(seen[0].url) == health.probe_url()
    assert seen[0].method == "GET"


def test_probe_never_opens_a_database_connection(monkeypatch):
    import psycopg

    def forbidden(*args: Any, **kwargs: Any) -> None:
        raise AssertionError("the readiness probe must not touch the database")

    monkeypatch.setattr(psycopg, "connect", forbidden)
    monkeypatch.setattr(psycopg.Connection, "connect", forbidden)
    result, _ = probe(json_response(live_body()))
    assert result.ready


# --- Stage A: transport ---------------------------------------------------


@pytest.mark.parametrize("status", [500, 502, 503, 504, 429])
def test_transient_statuses_fail_stage_a_after_exactly_two_attempts(status):
    result, seen = probe(json_response({"detail": "error"}, status=status))
    assert not result.ready and not result.stage_a_passed
    assert (result.failed_stage, result.failure_code, result.http_status) == ("A", health.FAIL_HTTP_STATUS, status)
    assert len(seen) == health.DEFAULT_ATTEMPTS


@pytest.mark.parametrize("status", [401, 403, 404])
def test_non_transient_4xx_fails_stage_a_without_retry(status):
    result, seen = probe(json_response({"detail": "nope"}, status=status))
    assert not result.ready
    assert (result.failure_code, result.http_status) == (health.FAIL_HTTP_STATUS, status)
    assert len(seen) == 1


def test_timeout_fails_stage_a():
    def timeout(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("read timed out", request=request)

    result, seen = probe(timeout)
    assert (result.ready, result.failed_stage, result.failure_code) == (False, "A", health.FAIL_TIMEOUT)
    assert len(seen) == health.DEFAULT_ATTEMPTS


def test_dns_failure_fails_stage_a():
    def dns(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("[Errno -2] Name or service not known", request=request)

    result, _ = probe(dns)
    assert (result.ready, result.failed_stage, result.failure_code) == (False, "A", health.FAIL_NETWORK)


def test_remote_protocol_error_fails_stage_a():
    def broken(request: httpx.Request) -> httpx.Response:
        raise httpx.RemoteProtocolError("peer closed connection", request=request)

    result, _ = probe(broken)
    assert result.failure_code == health.FAIL_PROTOCOL


def test_malformed_json_fails_stage_a():
    result, _ = probe(raw_response(b"<html>Service Unavailable</html>"))
    assert (result.ready, result.failed_stage, result.failure_code) == (False, "A", health.FAIL_MALFORMED_JSON)


def test_empty_body_fails_stage_a():
    result, _ = probe(raw_response(b""))
    assert (result.ready, result.failed_stage, result.failure_code) == (False, "A", health.FAIL_EMPTY_BODY)


def test_json_null_body_fails_stage_a():
    result, _ = probe(raw_response(b"null"))
    assert (result.ready, result.failure_code) == (False, health.FAIL_EMPTY_BODY)


@pytest.mark.parametrize("body", [[], [live_body()], "ok", 1])
def test_non_object_body_fails_stage_a(body):
    result, _ = probe(json_response(body))
    assert (result.ready, result.failed_stage, result.failure_code) == (False, "A", health.FAIL_UNEXPECTED_SHAPE)


def test_generic_200_without_team_event_shape_is_not_ready():
    """An API-root style 200 must never count as readiness."""
    result, _ = probe(json_response({"name": "Statbotics API", "version": "v3"}))
    assert not result.ready
    assert result.stage_a_passed and not result.stage_b_passed
    assert result.failure_code == health.FAIL_SCHEMA_INVALID


# --- Stage B: data contract -----------------------------------------------


def test_schema_drift_fails_stage_b():
    result, _ = probe(json_response(mutated(lambda b: b.update(team="one-six-seven-eight"))))
    assert (result.ready, result.stage_a_passed, result.failed_stage) == (False, True, "B")
    assert result.failure_code == health.FAIL_SCHEMA_INVALID


def test_missing_required_identity_field_fails_stage_b():
    result, _ = probe(json_response(mutated(lambda b: b.pop("team"))))
    assert result.failure_code == health.FAIL_SCHEMA_INVALID


def test_wrong_record_fails_stage_b():
    result, _ = probe(json_response(mutated(lambda b: b.update(team=254))))
    assert result.failure_code == health.FAIL_IDENTITY_MISMATCH


def test_null_epa_fails_stage_b():
    result, _ = probe(json_response(mutated(lambda b: b["epa"].update(total_points=None))))
    assert (result.ready, result.failed_stage, result.failure_code) == (False, "B", health.FAIL_EPA_MISSING)


def test_epa_object_missing_fails_stage_b():
    result, _ = probe(json_response(mutated(lambda b: b.pop("epa"))))
    assert result.failure_code == health.FAIL_EPA_MISSING


@pytest.mark.parametrize("literal", [b"NaN", b"Infinity", b"-Infinity"])
def test_non_finite_epa_fails_stage_b(literal):
    body = json.dumps(live_body()).encode()
    total = json.dumps(live_body()["epa"]["total_points"]).encode()
    tampered = body.replace(b'"total_points": ' + total, b'"total_points": ' + literal, 1)
    assert tampered != body
    result, _ = probe(raw_response(tampered))
    assert not result.ready
    assert result.failure_code == health.FAIL_EPA_NOT_FINITE


def test_non_finite_breakdown_component_fails_stage_b():
    body = json.dumps(live_body()).encode()
    auto = json.dumps(live_body()["epa"]["breakdown"]["auto_points"]).encode()
    tampered = body.replace(b'"auto_points": ' + auto, b'"auto_points": NaN', 1)
    assert tampered != body
    result, _ = probe(raw_response(tampered))
    assert result.failure_code == health.FAIL_EPA_NOT_FINITE


def test_non_numeric_epa_fails_stage_b():
    result, _ = probe(json_response(mutated(lambda b: b["epa"].update(total_points="high"))))
    assert result.failure_code == health.FAIL_SCHEMA_INVALID


def test_zero_match_placeholder_fails_stage_b():
    def placeholder(body: dict[str, Any]) -> None:
        body["record"]["total"].update(wins=0, losses=0, ties=0, count=0)

    result, _ = probe(json_response(mutated(placeholder)))
    assert (result.ready, result.failure_code) == (False, health.FAIL_MATCH_COUNT_INVALID)


def test_missing_match_count_fails_stage_b():
    result, _ = probe(json_response(mutated(lambda b: b.pop("record"))))
    assert result.failure_code == health.FAIL_MATCH_COUNT_INVALID


def test_incoherent_record_fails_stage_b_via_production_quality_rules():
    def incoherent(body: dict[str, Any]) -> None:
        total = body["record"]["total"]
        total["count"] = total["wins"] + total["losses"] + total["ties"] + 3

    result, _ = probe(json_response(mutated(incoherent)))
    assert (result.ready, result.failure_code) == (False, health.FAIL_QUALITY_ERROR)
    assert "matches_played" in result.detail


def test_negative_record_fails_stage_b():
    result, _ = probe(json_response(mutated(lambda b: b["record"]["total"].update(losses=-1))))
    assert not result.ready
    assert result.failure_code in (health.FAIL_QUALITY_ERROR, health.FAIL_SCHEMA_INVALID)


def test_every_stage_b_failure_counts_toward_the_circuit_breaker():
    stage_b_codes = {
        health.FAIL_SCHEMA_INVALID, health.FAIL_IDENTITY_MISMATCH, health.FAIL_EPA_MISSING,
        health.FAIL_EPA_NOT_FINITE, health.FAIL_MATCH_COUNT_INVALID, health.FAIL_QUALITY_ERROR,
    }
    assert stage_b_codes <= health.DATA_CONTRACT_FAILURES
    assert health.FAIL_HTTP_STATUS not in health.DATA_CONTRACT_FAILURES
    assert health.FAIL_TIMEOUT not in health.DATA_CONTRACT_FAILURES


def test_result_carries_no_request_headers_or_credentials():
    result, _ = probe(json_response(live_body()))
    serialized = json.dumps(result.to_dict()).lower()
    assert "authorization" not in serialized and "bearer" not in serialized
