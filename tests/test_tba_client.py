from __future__ import annotations

from typing import Any
from unittest.mock import Mock

import httpx
import pytest

from data.clients.tba import TBAClient
from data.clients.schemas import EventSummary, Match, TeamInfo
from data.config import Settings


class DummyResponse(httpx.Response):
    def __init__(self, status_code: int, json_body: dict | list[Any]):
        super().__init__(status_code, request=httpx.Request("GET", "https://example.com"))
        self._json_body = json_body

    def json(self) -> Any:
        return self._json_body


@pytest.fixture(autouse=True)
def env_settings(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgresql://user:pass@localhost:5432/testdb")
    monkeypatch.setenv("TBA_API_KEY", "test-key")
    monkeypatch.setenv("ENV", "development")
    return Settings()


def test_tba_client_initializes_http_client(monkeypatch, env_settings):
    created: dict[str, Any] = {}

    def dummy_client(*args: Any, **kwargs: Any) -> Any:
        created["kwargs"] = kwargs

        class DummyClient:
            def request(self, method: str, url: str, params: dict[str, Any] | None = None) -> DummyResponse:
                return DummyResponse(200, [])

            def close(self) -> None:
                pass

        return DummyClient()

    monkeypatch.setattr("data.clients.tba.httpx.Client", dummy_client)
    client = TBAClient(settings=env_settings)

    assert created["kwargs"]["timeout"] == 10.0
    assert created["kwargs"]["headers"]["X-TBA-Auth-Key"] == "test-key"


def test_tba_client_request_urls(monkeypatch, env_settings):
    client = TBAClient(settings=env_settings)
    dummy_event_list = DummyResponse(200, [{"key": "2025casj", "name": "Sacramento", "season": 2025}])
    dummy_matches = DummyResponse(200, [{"key": "2025casj_qm1", "event_key": "2025casj"}])
    dummy_team = DummyResponse(200, {"key": "frc1114", "team_number": 1114})
    mock_request = Mock(side_effect=[dummy_event_list, dummy_matches, dummy_team])
    monkeypatch.setattr(client, "_client", Mock(request=mock_request))

    client.fetch_event_list(year=2025)
    client.fetch_event_matches("2025casj")
    client.fetch_team_info(1114)

    calls = mock_request.call_args_list
    assert calls[0][0][1].endswith("/events/2025")
    assert calls[1][0][1].endswith("/event/2025casj/matches")
    assert calls[2][0][1].endswith("/team/frc1114")


def test_fetch_event_list_parses_models(monkeypatch, env_settings):
    client = TBAClient(settings=env_settings)
    event_data = [{"key": "2025casj", "name": "Sacramento", "season": 2025}]
    mock_request = Mock(return_value=DummyResponse(200, event_data))
    monkeypatch.setattr(client, "_client", Mock(request=mock_request))

    events = client.fetch_event_list(year=2025)

    assert events == [EventSummary.model_validate(event_data[0])]


def test_fetch_event_matches_parses_models(monkeypatch, env_settings):
    client = TBAClient(settings=env_settings)
    match_data = [{"key": "2025casj_qm1", "event_key": "2025casj"}]
    mock_request = Mock(return_value=DummyResponse(200, match_data))
    monkeypatch.setattr(client, "_client", Mock(request=mock_request))

    matches = client.fetch_event_matches("2025casj")

    assert matches == [Match.model_validate(match_data[0])]


def test_fetch_team_info_parses_model(monkeypatch, env_settings):
    client = TBAClient(settings=env_settings)
    team_data = {"key": "frc1114", "team_number": 1114}
    mock_request = Mock(return_value=DummyResponse(200, team_data))
    monkeypatch.setattr(client, "_client", Mock(request=mock_request))

    team = client.fetch_team_info(1114)

    assert team == TeamInfo.model_validate(team_data)


def test_retry_on_transient_errors(monkeypatch, env_settings):
    client = TBAClient(settings=env_settings)
    retry_response = DummyResponse(429, [])
    success_response = DummyResponse(200, [])
    mock_request = Mock(side_effect=[retry_response, success_response])
    monkeypatch.setattr(client, "_client", Mock(request=mock_request))

    events = client.fetch_event_list(year=2025)

    assert events == []
    assert mock_request.call_count == 2


def test_retry_exhaustion_raises(monkeypatch, env_settings):
    client = TBAClient(settings=env_settings)
    retry_response = DummyResponse(503, [])
    mock_request = Mock(return_value=retry_response)
    monkeypatch.setattr(client, "_client", Mock(request=mock_request))
    monkeypatch.setattr("data.clients.http_retry.time.sleep", lambda *_args, **_kwargs: None)

    with pytest.raises(httpx.HTTPStatusError):
        client.fetch_event_list(year=2025)

    assert mock_request.call_count == client.max_retries


def test_http_error_raises(monkeypatch, env_settings):
    client = TBAClient(settings=env_settings)
    mock_request = Mock(side_effect=httpx.HTTPStatusError("Error", request=httpx.Request("GET", "https://example.com"), response=DummyResponse(404, {})))
    monkeypatch.setattr(client, "_client", Mock(request=mock_request))

    with pytest.raises(httpx.HTTPStatusError):
        client.fetch_event_list(year=2025)
