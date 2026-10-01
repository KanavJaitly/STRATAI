from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from unittest.mock import Mock

import httpx
import pytest
from pydantic import ValidationError

from data.clients.schemas import StatboticsMatchStats, StatboticsTeamEventMetrics
from data.clients.statbotics import StatboticsClient
from data.config import Settings

FIXTURE_PATH = Path(__file__).parent / "fixtures" / "statbotics_team_event_2024casj.json"


def real_team_event_payload() -> dict[str, Any]:
    """Statbotics's real nested /team_event response shape.

    Mirrors the recorded fixture. Nested exactly as their response serializer
    emits it -- EPA under `epa`/`epa.breakdown`, the match record under
    `record.total` -- because mocking the flat shape this client originally
    assumed is what let the wrong shape survive unnoticed.
    """
    return {
        "team": 1114, "year": 2025, "event": "2025casj",
        "team_name": "Simbotics", "event_name": "Silicon Valley Regional",
        "country": "Canada", "state": "ON", "district": "ONT",
        "type": "regional", "week": 3, "status": "Completed", "first_event": True,
        "epa": {
            "total_points": 45.2,
            "unitless": 1650.0,
            "norm": 1780.0,
            "breakdown": {
                "total_points": 45.2,
                "auto_points": 10.1,
                "teleop_points": 28.4,
                "endgame_points": 6.7,
                "auto_rp": 0.55,
                "coral_rp": 0.48,
            },
            "stats": {"start": 40.0, "pre_elim": 44.1, "mean": 43.2, "max": 47.0},
        },
        "record": {
            "qual": {"wins": 8, "losses": 2, "ties": 0, "count": 10, "winrate": 0.8,
                     "rps": 22, "rps_per_match": 2.2, "rank": 3, "num_teams": 40},
            "elim": {"wins": 2, "losses": 2, "ties": 0, "count": 4, "winrate": 0.5,
                     "alliance": "2", "is_captain": False},
            "total": {"wins": 10, "losses": 4, "ties": 0, "count": 14, "winrate": 0.7143},
        },
    }


def real_match_payload() -> dict[str, Any]:
    """Statbotics's real nested /matches item shape (predictions under `pred`)."""
    return {
        "key": "2025casj_qm1", "year": 2025, "event": "2025casj", "week": 3,
        "elim": False, "comp_level": "qm", "set_number": 1, "match_number": 1,
        "match_name": "Qual 1", "time": 1710374400, "status": "Completed",
        "alliances": {
            "red": {"team_keys": ["frc1114", "frc254", "frc604"]},
            "blue": {"team_keys": ["frc118", "frc330", "frc973"]},
        },
        "pred": {
            "winner": "red", "red_win_prob": 0.63,
            "red_score": 112.4, "blue_score": 98.1,
        },
        "result": {"winner": "red", "red_score": 120, "blue_score": 95},
    }


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

def test_statbotics_base_url_uses_the_host_that_actually_resolves(env_settings):
    # api.statbotics.org does not resolve at all; every lookup failed with a DNS
    # error until this was corrected, and team_event_stats was never populated.
    client = StatboticsClient(settings=env_settings)
    try:
        assert client.base_url == "https://api.statbotics.io/v3"
        assert "statbotics.org" not in client.base_url
    finally:
        client.close()


def test_statbotics_client_request_urls(monkeypatch, env_settings):
    client = StatboticsClient(settings=env_settings)
    dummy_matches = DummyResponse(200, [real_match_payload()])
    dummy_team_event = DummyResponse(200, real_team_event_payload())
    mock_request = Mock(side_effect=[dummy_matches, dummy_team_event])
    monkeypatch.setattr(client, "_client", Mock(request=mock_request))

    client.fetch_event_match_stats("2025casj")
    client.fetch_team_event_metrics(1114, "2025casj")

    calls = mock_request.call_args_list
    assert calls[0][0][1] == "https://api.statbotics.io/v3/matches"
    assert calls[0][1]["params"] == {"event": "2025casj"}
    assert calls[1][0][1] == "https://api.statbotics.io/v3/team_event/1114/2025casj"


def test_fetch_event_match_stats_flattens_the_nested_prediction_object(monkeypatch, env_settings):
    client = StatboticsClient(settings=env_settings)
    mock_request = Mock(return_value=DummyResponse(200, [real_match_payload()]))
    monkeypatch.setattr(client, "_client", Mock(request=mock_request))

    responses = client.fetch_event_match_stats("2025casj")

    assert len(responses) == 1
    # raw keeps the nested `pred` object exactly as sent; parsed is flattened.
    assert responses[0].raw["pred"]["winner"] == "red"
    match = responses[0].parsed
    assert match.key == "2025casj_qm1"
    assert match.event == "2025casj"
    assert match.predicted_winner == "red"       # <- pred.winner
    assert match.red_win_prob == 0.63            # <- pred.red_win_prob
    assert match.red_score_pred == 112.4         # <- pred.red_score
    assert match.blue_score_pred == 98.1         # <- pred.blue_score


def test_fetch_team_event_metrics_flattens_the_nested_epa_and_record(monkeypatch, env_settings):
    client = StatboticsClient(settings=env_settings)
    mock_request = Mock(return_value=DummyResponse(200, real_team_event_payload()))
    monkeypatch.setattr(client, "_client", Mock(request=mock_request))

    response = client.fetch_team_event_metrics(1114, "2025casj")

    # The nested body is preserved for landing...
    assert response.raw["epa"]["breakdown"]["auto_points"] == 10.1
    assert response.raw["record"]["total"]["count"] == 14
    # ...while parsed exposes it flattened.
    metrics = response.parsed
    assert (metrics.team, metrics.event) == (1114, "2025casj")
    assert metrics.epa_total == 45.2      # <- epa.total_points
    assert metrics.epa_auto == 10.1       # <- epa.breakdown.auto_points
    assert metrics.epa_teleop == 28.4     # <- epa.breakdown.teleop_points
    assert metrics.epa_endgame == 6.7     # <- epa.breakdown.endgame_points
    # The record comes from record.total, NOT record.qual -- qual would silently
    # undercount every playoff match a team played.
    assert (metrics.wins, metrics.losses, metrics.ties) == (10, 4, 0)
    assert metrics.count == 14            # <- record.total.count


def test_already_flat_payloads_are_still_accepted():
    # Keeps hand-built fixtures and any payload landed by the pre-fix client valid.
    metrics = StatboticsTeamEventMetrics.model_validate({
        "team": 1114, "event": "2025casj", "epa_total": 45.2,
        "wins": 8, "losses": 2, "ties": 0,
    })
    assert metrics.epa_total == 45.2
    assert (metrics.wins, metrics.losses, metrics.ties) == (8, 2, 0)
    assert metrics.count is None  # absent from a flat payload, so left unset

    match = StatboticsMatchStats.model_validate({
        "key": "2025casj_qm1", "event": "2025casj", "predicted_winner": "blue",
    })
    assert match.predicted_winner == "blue"


def test_partial_nesting_does_not_raise():
    # An event with no EPA breakdown yet (early in competition) still parses.
    metrics = StatboticsTeamEventMetrics.model_validate({
        "team": 1114, "event": "2025casj",
        "epa": {"total_points": 12.0},
        "record": {"total": {"wins": 0, "losses": 0, "ties": 0, "count": 0}},
    })
    assert metrics.epa_total == 12.0
    assert metrics.epa_auto is None
    assert metrics.count == 0


def test_model_matches_recorded_statbotics_response():
    """Validate against the recorded response fixture.

    The fixture is CAPTURED -- a verbatim live api.statbotics.io response
    recorded 2026-08-01, once their API recovered from the outage that had made
    every /v3/* endpoint return HTTP 500. It replaced a source-derived stand-in
    built from Statbotics's published response serializer, and confirmed that
    stand-in's shape was right: all 61 leaf paths matched exactly.

    It records team 1678 rather than 254 because team 254 never attended
    2024casj -- see the fixture's _fixture_provenance block.
    """
    payload = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))
    assert payload["_fixture_provenance"]["status"] == "CAPTURED FROM LIVE API"

    metrics = StatboticsTeamEventMetrics.model_validate(payload)

    assert (metrics.team, metrics.event) == (1678, "2024casj")
    assert metrics.epa_total == 49.22
    assert metrics.epa_auto == 19.59
    assert metrics.epa_teleop == 22.99
    assert metrics.epa_endgame == 6.63
    # A real event can produce ties, which the previous invented numbers did not.
    assert (metrics.wins, metrics.losses, metrics.ties) == (14, 2, 1)
    assert metrics.count == 17
    # The extra keys Statbotics sends (year, team_name, epa.stats, record.qual,
    # the game-specific breakdown) are ignored rather than causing a failure.
    assert not hasattr(metrics, "year")


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
    # Missing the required "event" field for one item in the list. Note the
    # nested-prediction flattening must not swallow a genuinely invalid payload.
    client = StatboticsClient(settings=env_settings)
    malformed_data = [{"key": "2025casj_qm1", "pred": {"winner": "red"}}]
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


def test_fetch_event_team_metrics_parses_every_record_and_keeps_the_body(monkeypatch, env_settings):
    client = StatboticsClient(settings=env_settings)
    body = [real_team_event_payload(), {**real_team_event_payload(), "team": 254}]
    mock_request = Mock(return_value=DummyResponse(200, body))
    monkeypatch.setattr(client, "_client", Mock(request=mock_request))

    raw, responses = client.fetch_event_team_metrics("2025casj")

    assert raw == body  # the body lands exactly as sent
    assert [r.parsed.team for r in responses] == [1114, 254]
    assert [r.raw for r in responses] == body
    assert mock_request.call_args.kwargs["params"] == {"event": "2025casj", "limit": 1000}


def test_fetch_event_team_metrics_refuses_a_full_page(monkeypatch, env_settings):
    client = StatboticsClient(settings=env_settings)
    body = [real_team_event_payload(), {**real_team_event_payload(), "team": 254}]
    monkeypatch.setattr(client, "_client", Mock(request=Mock(return_value=DummyResponse(200, body))))
    with pytest.raises(ValueError, match="paginate"):
        client.fetch_event_team_metrics("2025casj", limit=2)
