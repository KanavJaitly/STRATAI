"""P5-M3 team and robot strength view: equality with the assembler, point-in-time, contracts.

Real Postgres with sentinel rows (namespace 9982), the Statbotics reference EPA source,
and the real application for the endpoint. Synthetic data: no result here is evidence
about any real team.
"""

from __future__ import annotations

from datetime import date, datetime, timezone
from typing import Generator

import psycopg
import pytest
from fastapi.testclient import TestClient

from api import create_app
from api.dependencies import get_database, get_epa_source
from data.config import Settings
from data.metrics.statistics import classify_match_days
from database.connection import Database, DatabaseConfig
from ml.features.assembler import build_team_features
from ml.ratings.epa_states import CURRENT, WITHHELD_NO_PRIOR_EVENT
from ml.ratings.provider import StatboticsPointInTimeEpa
from ml.views.strength import (
    DEFINITION_PENDING,
    INSUFFICIENT_OBSERVATIONS,
    NO_BREAKDOWN,
    NOT_VALIDATED,
    TOO_FEW_MATCHES,
    Measure,
    Uncertainty,
    build_team_strength,
    matches_features,
)

_SEASON = 9982
_PRIOR, _TARGET = "9982zzzprior", "9982zzzstrength"
_TEAM_A, _TEAM_B = 998201, 998202
_FILLERS = [998203, 998204, 998205, 998206, 998207]
_ALL = [_TEAM_A, _TEAM_B, *_FILLERS]
_T = {k: datetime(2026, 3, 1, h, 0, tzinfo=timezone.utc) for k, h in (("q1", 9), ("q2", 10), ("q3", 11), ("q4", 13))}
_AS_OF = datetime(2026, 3, 1, 12, 0, tzinfo=timezone.utc)  # q4 is after as_of
_SCORES_A = {"q1": 40, "q2": 60, "q3": 50, "q4": 999}  # q4 must never be visible


@pytest.fixture(autouse=True)
def _reference_epa_source(monkeypatch):
    monkeypatch.setenv("EPA_SOURCE", "statbotics")


def _db_available() -> bool:
    try:
        with psycopg.connect(str(Settings().database_url), connect_timeout=3):
            return True
    except Exception:
        return False


pytestmark = pytest.mark.skipif(not _db_available(), reason="Requires a reachable PostgreSQL database")


def _cleanup(db: Database) -> None:
    with db.cursor() as c:
        c.execute("DELETE FROM scouting_observations WHERE event_key IN (%s, %s)", (_PRIOR, _TARGET))
        c.execute("DELETE FROM match_teams WHERE match_key LIKE '9982zzz%%'")
        c.execute("DELETE FROM matches WHERE event_key IN (%s, %s)", (_PRIOR, _TARGET))
        c.execute("DELETE FROM team_event_stats WHERE event_key IN (%s, %s)", (_PRIOR, _TARGET))
        c.execute("DELETE FROM teams WHERE team_number = ANY(%s)", (_ALL,))
        c.execute("DELETE FROM events WHERE event_key IN (%s, %s)", (_PRIOR, _TARGET))


def _match(c, key: str, event: str, when: datetime, red: list[int], blue: list[int], score_red, score_blue) -> None:
    c.execute("INSERT INTO matches (match_key, event_key, season, competition_level, match_number, scheduled_time, "
              "score_red, score_blue) VALUES (%s, %s, %s, 'qualification', 1, %s, %s, %s)",
              (key, event, _SEASON, when, score_red, score_blue))
    for team in red:
        c.execute("INSERT INTO match_teams (match_key, team_number, alliance_color) VALUES (%s, %s, 'red')", (key, team))
    for team in blue:
        c.execute("INSERT INTO match_teams (match_key, team_number, alliance_color) VALUES (%s, %s, 'blue')", (key, team))


@pytest.fixture
def database() -> Generator[Database, None, None]:
    from database.migrate import run_migrations

    settings = Settings()
    run_migrations(settings)
    db = Database(DatabaseConfig(settings.database_url))
    _cleanup(db)
    with db.cursor() as c:
        c.execute("INSERT INTO events (event_key, season, name, end_date) VALUES (%s, %s, 'Prior', %s), "
                  "(%s, %s, 'Strength', NULL)", (_PRIOR, _SEASON, date(2026, 2, 20), _TARGET, _SEASON))
        c.execute("INSERT INTO teams (team_number, name) VALUES " + ", ".join(["(%s, %s)"] * len(_ALL)),
                  [v for t in _ALL for v in (t, f"Team {t}")])
        _match(c, "9982zzzprior_qm1", _PRIOR, datetime(2026, 2, 19, 10, tzinfo=timezone.utc),
               [_TEAM_A, *_FILLERS[:2]], _FILLERS[2:], 55, 45)
        c.execute("INSERT INTO team_event_stats (team_number, event_key, season, epa_total, epa_auto, epa_teleop, "
                  "epa_endgame, matches_played) VALUES (%s, %s, %s, 42.0, 10.0, 25.0, 7.0, 1)", (_TEAM_A, _PRIOR, _SEASON))
        for q in ("q1", "q2", "q3", "q4"):
            red = [_TEAM_A, *_FILLERS[:2]] if q != "q1" else [_TEAM_A, _TEAM_B, _FILLERS[0]]
            _match(c, f"9982zzzstrength_{q}", _TARGET, _T[q], red, _FILLERS[2:], _SCORES_A[q], 30)
        for i, (rating, when) in enumerate(((3, _T["q1"]), (5, _T["q2"]), (1, _T["q4"]))):
            c.execute("INSERT INTO scouting_observations (match_key, event_key, team_number, scout_identifier, "
                      "defense_rating, feeding_rating, source, submitted_at) VALUES (%s, %s, %s, %s, %s, NULL, "
                      "'human_scout', %s)", (f"9982zzzstrength_q{i + 1}", _TARGET, _TEAM_A, f"s{i}", rating, when))
    try:
        yield db
    finally:
        _cleanup(db)


def test_view_equals_the_assembler_and_is_point_in_time(database):
    provider = StatboticsPointInTimeEpa(database)
    view = build_team_strength(database, _TEAM_A, _TARGET, _AS_OF, epa_provider=provider)
    features = build_team_features(database, _TEAM_A, _TARGET, _AS_OF, epa_provider=provider)
    assert matches_features(view, features) == []
    assert view.scoring.average_score.value == 50.0 and view.scoring.average_score.n == 3  # q4 (999) excluded
    assert view.scoring.average_score.uncertainty.kind == "sd"
    days = classify_match_days([40, 60, 50])
    assert (view.scoring.good_day_count.value, view.scoring.average_day_count.value, view.scoring.bad_day_count.value) \
        == (days["good"], days["average"], days["bad"])
    assert view.epa.total.value == 42.0 and view.epa.epa_value_source == "statbotics"
    assert view.epa.epa_source_state == CURRENT and view.epa.source_event_key == _PRIOR and view.epa.total.n == 1
    assert view.defense.score.value == 4.0 and view.defense.score.n == 2  # the rating after as_of is excluded
    assert view.defense.validation_status == DEFINITION_PENDING
    assert view.feeding.validation_status == NOT_VALIDATED
    assert view.feeding.score.absent_reason == INSUFFICIENT_OBSERVATIONS


def test_season_auto_points_are_listed_per_event_never_pooled(database):
    view = build_team_strength(database, _TEAM_A, _TARGET, _AS_OF, epa_provider=StatboticsPointInTimeEpa(database))
    assert [e.event_key for e in view.auto_points.season_by_event] == [_PRIOR, _TARGET]
    assert all(e.average_auto_points.absent_reason == NO_BREAKDOWN for e in view.auto_points.season_by_event)


def test_absent_values_carry_reasons(database):
    view = build_team_strength(database, _TEAM_B, _TARGET, _AS_OF, epa_provider=StatboticsPointInTimeEpa(database))
    assert view.epa.total.value is None and view.epa.total.absent_reason == view.epa.withheld_reason
    assert view.epa.epa_source_state == WITHHELD_NO_PRIOR_EVENT
    assert view.scoring.score_stddev.absent_reason == TOO_FEW_MATCHES  # one completed match
    assert view.scoring.average_score.uncertainty.kind == "none"


def test_measure_and_uncertainty_contracts():
    with pytest.raises(ValueError):
        Measure(value=None, n=0, uncertainty=Uncertainty(kind="none", reason="x"))  # absent without a reason
    with pytest.raises(ValueError):
        Uncertainty(kind="sd")  # an SD without its value
    with pytest.raises(ValueError):
        Uncertainty(kind="none")  # a 'none' without its reason


@pytest.fixture
def client(database) -> Generator[TestClient, None, None]:
    app = create_app(Settings())
    app.dependency_overrides[get_database] = lambda: database
    with TestClient(app) as test_client:
        yield test_client


def test_endpoint_serves_the_view_with_epa_provenance(client):
    response = client.get(f"/teams/{_TEAM_A}/events/{_TARGET}/strength", params={"as_of": _AS_OF.isoformat()})
    assert response.status_code == 200
    body = response.json()
    assert body["strength"]["scoring"]["average_score"]["value"] == 50.0
    assert body["strength"]["epa"]["epa_source_state"] == CURRENT
    assert body["epa"]["epa_source"] == "statbotics" and body["epa"]["evaluated_configuration"] is False


@pytest.mark.parametrize(("path", "params", "status", "code"), [
    (f"/teams/{_TEAM_A}/events/9982zzznosuch/strength", {}, 404, "event_not_found"),
    (f"/teams/998299/events/{_TARGET}/strength", {}, 404, "team_not_found"),
    (f"/teams/{_TEAM_A}/events/{_TARGET}/strength", {"as_of": "2026-03-01T12:00:00"}, 422, "invalid_as_of"),
    (f"/teams/{_TEAM_A}/events/{_TARGET}/strength", {"as_of": "yesterday"}, 422, "invalid_as_of"),
])
def test_endpoint_error_codes(client, path, params, status, code):
    response = client.get(path, params=params)
    assert response.status_code == status and response.json()["error"]["code"] == code


def test_endpoint_refuses_without_an_epa_source(database):
    app = create_app(Settings())
    app.dependency_overrides[get_database] = lambda: database
    app.dependency_overrides[get_epa_source] = lambda: None
    with TestClient(app) as test_client:
        response = test_client.get(f"/teams/{_TEAM_A}/events/{_TARGET}/strength")
    assert response.status_code == 404 and response.json()["error"]["code"] == "epa_source_not_loaded"
