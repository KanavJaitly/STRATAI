"""P7-M4: discovery reads -- the events of a season, an event's teams, an event's matches (point in time).

Real Postgres sentinel rows from tests/test_event_analysis_api.py (namespace 9984), only on an isolated stratai_*
database copy. Synthetic data.
"""

from __future__ import annotations

from datetime import timedelta

import pytest
from fastapi.testclient import TestClient

from api import create_app
from api.dependencies import get_database
from data.config import Settings
from ml.views.discovery import RESULT_NOT_BEFORE_AS_OF, RESULT_NOT_PLAYED
from tests.phase7_support import assert_declared_error, stub_served_model
from tests.test_event_analysis_api import _EVENT, _PRIOR, _Q, _SEASON, _T0, _TEAMS, _isolated_db_name, database  # noqa: F401

pytestmark = pytest.mark.skipif(_isolated_db_name() is None, reason="needs an isolated stratai_* database copy")

EVENTS, TEAMS, MATCHES = "/events", "/events/{event_key}/teams", "/events/{event_key}/matches"


@pytest.fixture(autouse=True)
def _reference_epa_source(monkeypatch):
    monkeypatch.setenv("EPA_SOURCE", "statbotics")  # the analysis and forecast refusal tests need a loaded source


@pytest.fixture
def client(database):  # noqa: F811
    app = create_app(Settings())
    app.dependency_overrides[get_database] = lambda: database
    with TestClient(app) as test_client:
        yield test_client


def _openapi(client):
    return client.app.openapi()


# --- events ---------------------------------------------------------------------------------------------------------


def test_a_season_lists_its_events(client):
    body = client.get(EVENTS, params={"season": _SEASON}).json()
    assert [e["event_key"] for e in body["events"]] == sorted([_EVENT, _PRIOR])  # no start dates: by key
    assert body["validation"] == {"status": "descriptive", "reasons": ["canonical_tba_record"], "evidence": None}
    assert body["events"][0]["season"] == _SEASON


def test_a_season_without_events_is_an_empty_list_not_an_error(client):
    response = client.get(EVENTS, params={"season": 1993})
    assert response.status_code == 200 and response.json()["events"] == []


@pytest.mark.parametrize("params", [{}, {"season": "abc"}, {"season": 1900}])
def test_a_bad_or_missing_season_is_a_declared_validation_error(client, params):
    assert_declared_error(_openapi(client), client.get(EVENTS, params=params), "GET", EVENTS, code="validation_error")


# --- teams ----------------------------------------------------------------------------------------------------------


def test_an_events_teams_are_its_roster_with_details(client):
    body = client.get(TEAMS.format(event_key=_EVENT)).json()
    assert [t["team_number"] for t in body["teams"]] == sorted(_TEAMS)
    assert body["teams"][0]["name"] == f"Team {sorted(_TEAMS)[0]}"


def test_an_unknown_events_teams_are_a_declared_not_found(client):
    response = client.get(TEAMS.format(event_key="9984zzznosuch"))
    assert_declared_error(_openapi(client), response, "GET", TEAMS, code="event_not_found")


def test_an_event_with_no_matches_has_an_empty_roster(client, database):  # noqa: F811
    with database.cursor() as c:
        c.execute("INSERT INTO events (event_key, season, name) VALUES ('9984zzzempty', %s, 'Empty')", (_SEASON,))
    try:
        response = client.get(TEAMS.format(event_key="9984zzzempty"))
        assert response.status_code == 200 and response.json()["teams"] == []
    finally:
        with database.cursor() as c:
            c.execute("DELETE FROM events WHERE event_key = '9984zzzempty'")


# --- matches: point in time -----------------------------------------------------------------------------------------


def _matches(client, as_of):
    return client.get(MATCHES.format(event_key=_EVENT), params={"as_of": as_of.isoformat()}).json()


def test_results_appear_only_once_a_match_is_scheduled_before_as_of(client):
    before = _matches(client, _T0)  # q1 is scheduled at _T0 itself: not before
    assert [m["result"] for m in before["matches"]] == [None] * 4
    assert {m["result_withheld_reason"] for m in before["matches"]} == {RESULT_NOT_BEFORE_AS_OF}

    middle = _matches(client, _Q[1] + timedelta(minutes=1))
    assert [m["result"] is not None for m in middle["matches"]] == [True, True, False, False]
    assert middle["matches"][0]["result"] == {"score_red": 51, "score_blue": 40, "winning_alliance": None}

    after = _matches(client, _Q[3] + timedelta(hours=1))
    assert [m["result_withheld_reason"] for m in after["matches"]] == [None, None, None, RESULT_NOT_PLAYED]


def test_the_schedule_is_always_visible(client):
    body = _matches(client, _T0)
    assert [m["match_key"] for m in body["matches"]] == [f"9984zzzevent_qm{i}" for i in range(1, 5)]
    assert body["matches"][0]["red_team_numbers"] == _TEAMS[:3]
    assert body["matches"][0]["blue_team_numbers"] == _TEAMS[3:]


def test_playoff_matches_and_their_alliances_appear_only_once_available(client, database):  # noqa: F811
    """P7-D2: a playoff match's alliances are the selection outcome, so before the match is scheduled the match
    is not listed at all; a playoff match with no scheduled time is never listed."""
    playoff_time = _Q[3] + timedelta(hours=3)
    with database.cursor() as c:
        c.execute("INSERT INTO matches (match_key, event_key, season, competition_level, set_number, match_number, "
                  "scheduled_time, score_red, score_blue, winning_alliance) VALUES "
                  "('9984zzzevent_sf1m1', %s, %s, 'semifinal', 1, 1, %s, 60, 60, 'tie'), "
                  "('9984zzzevent_f1m1', %s, %s, 'final', 1, 1, NULL, NULL, NULL, NULL)",
                  (_EVENT, _SEASON, playoff_time, _EVENT, _SEASON))
        for color, teams in (("red", _TEAMS[:3]), ("blue", _TEAMS[3:])):
            for team in teams:
                for key in ("9984zzzevent_sf1m1", "9984zzzevent_f1m1"):
                    c.execute("INSERT INTO match_teams (match_key, team_number, alliance_color) VALUES (%s, %s, %s)",
                              (key, team, color))
    try:
        before = _matches(client, playoff_time - timedelta(minutes=1))
        assert [m["match_key"] for m in before["matches"]] == [f"9984zzzevent_qm{i}" for i in range(1, 5)]
        after = _matches(client, playoff_time + timedelta(minutes=1))
        keys = [m["match_key"] for m in after["matches"]]
        assert keys == [f"9984zzzevent_qm{i}" for i in range(1, 5)] + ["9984zzzevent_sf1m1"]  # f1m1: never
        semifinal = after["matches"][-1]
        assert semifinal["red_team_numbers"] == _TEAMS[:3]
        assert semifinal["result"] == {"score_red": 60, "score_blue": 60, "winning_alliance": "tie"}
    finally:
        with database.cursor() as c:
            c.execute("DELETE FROM match_teams WHERE match_key IN ('9984zzzevent_sf1m1', '9984zzzevent_f1m1')")
            c.execute("DELETE FROM matches WHERE match_key IN ('9984zzzevent_sf1m1', '9984zzzevent_f1m1')")


def test_an_event_has_no_event_type_field(client):
    """P7-D2: nothing writes events.event_type, so it is not served."""
    assert "event_type" not in client.get(EVENTS, params={"season": _SEASON}).json()["events"][0]


@pytest.mark.parametrize("route, service", [
    ("/events/{event_key}/analysis", "api.routes.event_analysis.analyze_event"),
    ("/events/{event_key}/qualification-forecast", "api.routes.qualification_forecast.forecast_event_qualification"),
])
@pytest.mark.parametrize("pending, code", [(False, "epa_source_incomplete"), (True, "epa_source_pending")])
def test_extracted_services_map_epa_source_refusals(database, monkeypatch, route, service, pending, code):  # noqa: F811
    """The extracted services let SilentFallbackError propagate; both routes still map it to the declared code."""
    from api.dependencies import get_ranking_model, get_win_prob_model
    from ml.ratings.live_epa import EpaSourcePendingError
    from ml.ratings.statbotics_primary import SilentFallbackError

    error = (EpaSourcePendingError if pending else SilentFallbackError)(_TEAMS[0], _EVENT, _T0, _PRIOR, "missing")

    def refuse(*args, **kwargs):
        raise error

    monkeypatch.setattr(service, refuse)
    app = create_app(Settings())
    app.dependency_overrides[get_database] = lambda: database
    stub = stub_served_model()
    app.dependency_overrides[get_ranking_model] = lambda: stub
    app.dependency_overrides[get_win_prob_model] = lambda: stub
    with TestClient(app) as test_client:
        response = test_client.get(route.format(event_key=_EVENT), params={"as_of": _T0.isoformat()})
        assert_declared_error(app.openapi(), response, "GET", route, code=code)


@pytest.mark.parametrize("week, low_confidence", [(None, None), (1, True), (3, True), (4, False), (6, False)])
def test_the_forecast_labels_early_season_weeks_low_confidence(database, monkeypatch, week, low_confidence):  # noqa: F811
    """The Statbotics week flows from the extracted service to the route, and weeks 1-3 are low_confidence
    (P5-M5); no other test drives a real week through the route."""
    from api.dependencies import get_win_prob_model
    from ml.views.qualification_forecast import EventQualificationForecast

    monkeypatch.setattr("api.routes.qualification_forecast.forecast_event_qualification",
                        lambda *a, **k: EventQualificationForecast([], {}, week, []))
    app = create_app(Settings())
    app.dependency_overrides[get_database] = lambda: database
    app.dependency_overrides[get_win_prob_model] = lambda: stub_served_model()
    with TestClient(app) as test_client:
        body = test_client.get(f"/events/{_EVENT}/qualification-forecast").json()
    assert body["statbotics_week"] == week and body["low_confidence"] is low_confidence


def test_match_refusals_are_declared(client):
    openapi = _openapi(client)
    assert_declared_error(openapi, client.get(MATCHES.format(event_key="9984zzznosuch")), "GET", MATCHES,
                          code="event_not_found")
    assert_declared_error(openapi, client.get(MATCHES.format(event_key=_EVENT), params={"as_of": "2026-03-01"}),
                          "GET", MATCHES, code="invalid_as_of")


@pytest.mark.parametrize("url, template", [
    (f"/events/{_EVENT}/analysis", "/events/{event_key}/analysis"),
    (f"/events/{_EVENT}/qualification-forecast", "/events/{event_key}/qualification-forecast"),
    (f"/events/{_EVENT}/matches", "/events/{event_key}/matches"),
    (f"/teams/{_TEAMS[0]}/events/{_EVENT}/strength", "/teams/{team_number}/events/{event_key}/strength"),
])
def test_no_route_accepts_a_future_as_of(database, url, template):  # noqa: F811
    """P7-D4: one rule everywhere. At a future as_of an in-progress event would count as a completed prior event."""
    from datetime import datetime, timezone

    from api.dependencies import get_ranking_model, get_win_prob_model

    app = create_app(Settings())
    app.dependency_overrides[get_database] = lambda: database
    app.dependency_overrides[get_ranking_model] = lambda: stub_served_model()
    app.dependency_overrides[get_win_prob_model] = lambda: stub_served_model()
    future = (datetime.now(timezone.utc) + timedelta(days=1)).isoformat()
    with TestClient(app) as test_client:
        response = test_client.get(url, params={"as_of": future})
        assert_declared_error(app.openapi(), response, "GET", template, code="invalid_as_of")
