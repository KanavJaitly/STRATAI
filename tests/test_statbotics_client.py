from __future__ import annotations

from typing import Any
from unittest.mock import Mock

import httpx
import pytest
from pydantic import ValidationError

from data.clients.schemas import StatboticsMatchStats, StatboticsTeamEventMetrics
from data.clients.statbotics import StatboticsClient
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
    monkeypatch.delenv("STATBOTICS_API_KEY", raising=False)
    monkeypatch.setenv("ENV", "development")
    return Settings()


# --- initialization / authentication --------------------------------------

def test_statbotics_client_initializes_without_auth_header_by_default(monkeypatch, env_settings):
    created: dict[str, Any] = {}

    def dummy_client(*args: Any, **kwargs: Any) -> Any:
        created["kwargs"] = kwargs

        class DummyClient:
            def request(self, method: str, url: str, params: dict[str, Any] | None = None) -> DummyResponse:
                return DummyResponse(200, [])

            def close(self) -> None:
                pass

        return DummyClient()

    monkeypatch.setattr("data.clients.statbotics.httpx.Client", dummy_client)
    client = StatboticsClient(settings=env_settings)

    assert created["kwargs"]["timeout"] == 10.0
    assert "Authorization" not in created["kwargs"]["headers"]


def test_statbotics_client_sends_bearer_token_when_api_key_configured(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgresql://user:pass@localhost:5432/testdb")
    monkeypatch.setenv("TBA_API_KEY", "test-key")
    monkeypatch.setenv("STATBOTICS_API_KEY", "sb-secret")
    monkeypatch.setenv("ENV", "development")
    settings = Settings()

    created: dict[str, Any] = {}

    def dummy_client(*args: Any, **kwargs: Any) -> Any:
        created["kwargs"] = kwargs

        class DummyClient:
            def request(self, method: str, url: str, params: dict[str, Any] | None = None) -> DummyResponse:
                return DummyResponse(200, [])

            def close(self) -> None:
                pass

        return DummyClient()

    monkeypatch.setattr("data.clients.statbotics.httpx.Client", dummy_client)
    StatboticsClient(settings=settings)

    assert created["kwargs"]["headers"]["Authorization"] == "Bearer sb-secret"


def test_statbotics_client_source_name_is_statbotics(env_settings):
    client = StatboticsClient(settings=env_settings)
    assert client.source_name == "statbotics"
    client.close()


# --- request construction / parsing ---------------------------------------

def test_statbotics_client_request_urls(monkeypatch, env_settings):
    client = StatboticsClient(settings=env_settings)
    dummy_matches = DummyResponse(200, [{"key": "2025casj_qm1", "event": "2025casj"}])
    dummy_team_event = DummyResponse(200, {"team": 1114, "event": "2025casj"})
    mock_request = Mock(side_effect=[dummy_matches, dummy_team_event])
    monkeypatch.setattr(client, "_client", Mock(request=mock_request))

    client.fetch_event_match_stats("2025casj")
    client.fetch_team_event_metrics(1114, "2025casj")

    calls = mock_request.call_args_list
    assert calls[0][0][1].endswith("/matches")
    assert calls[0][1]["params"] == {"event": "2025casj"}
    assert calls[1][0][1].endswith("/team_event/1114/2025casj")


def test_fetch_event_match_stats_parses_models(monkeypatch, env_settings):
    client = StatboticsClient(settings=env_settings)
    match_data = [
        {
            "key": "2025casj_qm1",
            "event": "2025casj",
            "predicted_winner": "red",
            "red_win_prob": 0.63,
            "red_score_pred": 112.4,
            "blue_score_pred": 98.1,
        }
    ]
    mock_request = Mock(return_value=DummyResponse(200, match_data))
    monkeypatch.setattr(client, "_client", Mock(request=mock_request))

    stats = client.fetch_event_match_stats("2025casj")

    assert stats == [StatboticsMatchStats.model_validate(match_data[0])]


def test_fetch_team_event_metrics_parses_model(monkeypatch, env_settings):
    client = StatboticsClient(settings=env_settings)
    team_event_data = {
        "team": 1114,
        "event": "2025casj",
        "epa_total": 45.2,
        "epa_auto": 10.1,
        "epa_teleop": 28.4,
        "epa_endgame": 6.7,
        "wins": 8,
        "losses": 2,
        "ties": 0,
    }
    mock_request = Mock(return_value=DummyResponse(200, team_event_data))
    monkeypatch.setattr(client, "_client", Mock(request=mock_request))

    metrics = client.fetch_team_event_metrics(1114, "2025casj")

    assert metrics == StatboticsTeamEventMetrics.model_validate(team_event_data)


# --- edge cases / malformed responses --------------------------------------

def test_fetch_event_match_stats_handles_null_response_body(monkeypatch, env_settings):
    # Some APIs return null rather than [] for "no results" - must not raise TypeError.
    client = StatboticsClient(settings=env_settings)
    mock_request = Mock(return_value=DummyResponse(200, None))
    monkeypatch.setattr(client, "_client", Mock(request=mock_request))

    stats = client.fetch_event_match_stats("2025nonexistent")

    assert stats == []


def test_fetch_event_match_stats_handles_empty_event(monkeypatch, env_settings):
    client = StatboticsClient(settings=env_settings)
    mock_request = Mock(return_value=DummyResponse(200, []))
    monkeypatch.setattr(client, "_client", Mock(request=mock_request))

    stats = client.fetch_event_match_stats("2025nonexistent")

    assert stats == []


def test_fetch_event_match_stats_raises_on_malformed_item(monkeypatch, env_settings):
    # Missing the required "event" field for one item in the list.
    client = StatboticsClient(settings=env_settings)
    malformed_data = [{"key": "2025casj_qm1"}]
    mock_request = Mock(return_value=DummyResponse(200, malformed_data))
    monkeypatch.setattr(client, "_client", Mock(request=mock_request))

    with pytest.raises(ValidationError):
        client.fetch_event_match_stats("2025casj")


def test_fetch_team_event_metrics_raises_on_malformed_response(monkeypatch, env_settings):
    # Missing the required "team" field entirely.
    client = StatboticsClient(settings=env_settings)
    malformed_data = {"event": "2025casj"}
    mock_request = Mock(return_value=DummyResponse(200, malformed_data))
    monkeypatch.setattr(client, "_client", Mock(request=mock_request))

    with pytest.raises(ValidationError):
        client.fetch_team_event_metrics(1114, "2025casj")


# --- retry / error handling (shared http_retry helper) ----------------------

def test_retry_on_transient_errors(monkeypatch, env_settings):
    client = StatboticsClient(settings=env_settings)
    retry_response = DummyResponse(503, [])
    success_response = DummyResponse(200, [])
    mock_request = Mock(side_effect=[retry_response, success_response])
    monkeypatch.setattr(client, "_client", Mock(request=mock_request))
    monkeypatch.setattr("data.clients.http_retry.time.sleep", lambda *_args, **_kwargs: None)

    stats = client.fetch_event_match_stats("2025casj")

    assert stats == []
    assert mock_request.call_count == 2


def test_retry_exhaustion_raises(monkeypatch, env_settings):
    client = StatboticsClient(settings=env_settings)
    retry_response = DummyResponse(429, [])
    mock_request = Mock(return_value=retry_response)
    monkeypatch.setattr(client, "_client", Mock(request=mock_request))
    monkeypatch.setattr("data.clients.http_retry.time.sleep", lambda *_args, **_kwargs: None)

    with pytest.raises(httpx.HTTPStatusError):
        client.fetch_event_match_stats("2025casj")

    assert mock_request.call_count == client.max_retries


def test_http_error_raises_without_retry(monkeypatch, env_settings):
    client = StatboticsClient(settings=env_settings)
    mock_request = Mock(
        side_effect=httpx.HTTPStatusError(
            "Error", request=httpx.Request("GET", "https://example.com"), response=DummyResponse(404, {})
        )
    )
    monkeypatch.setattr(client, "_client", Mock(request=mock_request))

    with pytest.raises(httpx.HTTPStatusError):
        client.fetch_event_match_stats("2025casj")

    assert mock_request.call_count == 1
