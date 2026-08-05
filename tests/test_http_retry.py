"""Direct tests for data.clients.http_retry.request_with_retries and is_transient_status.

Found during a system-wide audit: this shared utility (used by both TBAClient
and StatboticsClient) had never been tested directly, only indirectly through
each client's own retry tests -- which is why two real gaps went unnoticed:
max_retries=0 silently made zero requests, and several genuinely transient
httpx exceptions (ReadError, WriteError, RemoteProtocolError) were never
retried at all, falling straight through to the generic HTTPError handler.
"""

from __future__ import annotations

from unittest.mock import Mock

import httpx
import pytest

from data.clients.http_retry import is_transient_status, request_with_retries


class DummyResponse(httpx.Response):
    def __init__(self, status_code: int, json_body=None):
        super().__init__(status_code, request=httpx.Request("GET", "https://example.com"))
        self._json_body = json_body if json_body is not None else {}

    def json(self):
        return self._json_body


def _client(mock_request: Mock) -> httpx.Client:
    return Mock(request=mock_request)


# --- max_retries boundary ---------------------------------------------------

@pytest.mark.parametrize("bad_value", [0, -1, -5])
def test_rejects_non_positive_max_retries(bad_value):
    # Regression: range(1, max_retries + 1) with max_retries=0 previously
    # made zero requests and fell through to a generic RuntimeError instead
    # of ever calling client.request at all.
    with pytest.raises(ValueError, match="max_retries must be at least 1"):
        request_with_retries(Mock(), "GET", "https://example.com", max_retries=bad_value, backoff_factor=0.0)


def test_max_retries_one_makes_exactly_one_attempt_on_persistent_failure():
    mock_request = Mock(side_effect=httpx.ConnectError("refused"))
    with pytest.raises(httpx.ConnectError):
        request_with_retries(_client(mock_request), "GET", "https://example.com", max_retries=1, backoff_factor=0.0)
    assert mock_request.call_count == 1


# --- previously-unretried transient exceptions ------------------------------

@pytest.mark.parametrize("transient_exc", [
    httpx.ReadError("connection reset mid-read"),
    httpx.WriteError("connection reset mid-write"),
    httpx.RemoteProtocolError("server closed connection unexpectedly"),
    httpx.ConnectError("connection refused"),
    httpx.TimeoutException("timed out"),
])
def test_retries_on_transient_network_and_protocol_errors(monkeypatch, transient_exc):
    monkeypatch.setattr("data.clients.http_retry.time.sleep", lambda *_a, **_k: None)
    success = DummyResponse(200, {"ok": True})
    mock_request = Mock(side_effect=[transient_exc, success])

    result = request_with_retries(_client(mock_request), "GET", "https://example.com", max_retries=2, backoff_factor=0.0)

    assert result == {"ok": True}
    assert mock_request.call_count == 2


def test_does_not_retry_local_protocol_error():
    # LocalProtocolError means *this client* built a malformed request --
    # retrying repeats the identical bug rather than recovering from a
    # transient condition, so it must not be caught as retryable.
    mock_request = Mock(side_effect=httpx.LocalProtocolError("bad header"))
    with pytest.raises(httpx.LocalProtocolError):
        request_with_retries(_client(mock_request), "GET", "https://example.com", max_retries=3, backoff_factor=0.0)
    assert mock_request.call_count == 1


def test_does_not_retry_unsupported_protocol():
    mock_request = Mock(side_effect=httpx.UnsupportedProtocol("ftp:// unsupported"))
    with pytest.raises(httpx.UnsupportedProtocol):
        request_with_retries(_client(mock_request), "GET", "https://example.com", max_retries=3, backoff_factor=0.0)
    assert mock_request.call_count == 1


# --- existing behavior, still correct ---------------------------------------

def test_retries_on_429_and_5xx(monkeypatch):
    monkeypatch.setattr("data.clients.http_retry.time.sleep", lambda *_a, **_k: None)
    mock_request = Mock(side_effect=[DummyResponse(503), DummyResponse(200, [])])
    result = request_with_retries(_client(mock_request), "GET", "https://example.com", max_retries=2, backoff_factor=0.0)
    assert result == []
    assert mock_request.call_count == 2


def test_does_not_retry_ordinary_4xx():
    mock_request = Mock(return_value=DummyResponse(404))
    with pytest.raises(httpx.HTTPStatusError):
        request_with_retries(_client(mock_request), "GET", "https://example.com", max_retries=3, backoff_factor=0.0)
    assert mock_request.call_count == 1


def test_exhausts_after_max_retries(monkeypatch):
    monkeypatch.setattr("data.clients.http_retry.time.sleep", lambda *_a, **_k: None)
    mock_request = Mock(side_effect=httpx.TimeoutException("timed out"))
    with pytest.raises(httpx.TimeoutException):
        request_with_retries(_client(mock_request), "GET", "https://example.com", max_retries=3, backoff_factor=0.0)
    assert mock_request.call_count == 3


@pytest.mark.parametrize("status,expected", [
    (428, False), (429, True), (430, False),
    (499, False), (500, True), (599, True), (600, False),
])
def test_is_transient_status_boundaries(status, expected):
    assert is_transient_status(status) is expected
