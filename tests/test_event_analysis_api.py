"""P5-M4 event analysis endpoint: policy switching, labels, refusals.

Real Postgres sentinel rows (namespace 9984), only on an isolated stratai_* database copy, the reference
Statbotics EPA source, and a stub ranking model. Synthetic data: no result here is evidence about any real team.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from types import SimpleNamespace
from typing import Generator

import pytest
from fastapi.testclient import TestClient

from api import create_app
from api.dependencies import get_database, get_ranking_model
from data.config import Settings
from database.connection import Database, DatabaseConfig
from ml.views.event_analysis import POLICY_M5V2, POLICY_RAW_EPA, VALIDATED_AS_MEASURED, VALIDATED_RAW_EPA, serving_switch
from tests.test_live_epa import _isolated_db_name

_SEASON = 9984
_PRIOR, _EVENT = "9984zzzprior", "9984zzzevent"
_TEAMS = [998401, 998402, 998403, 998404, 998405, 998406]
_EPA = {998401: 30.0, 998402: 50.0, 998403: 10.0, 998404: 40.0, 998405: 20.0}  # 998406: no prior EPA
_T0 = datetime(2026, 3, 1, 9, tzinfo=timezone.utc)
_Q = [_T0 + timedelta(hours=h) for h in range(4)]  # four quals; ceil(4/2) = 2nd match is the switch

pytestmark = pytest.mark.skipif(_isolated_db_name() is None, reason="needs an isolated stratai_* database copy")


@pytest.fixture(autouse=True)
def _reference_epa_source(monkeypatch):
    monkeypatch.setenv("EPA_SOURCE", "statbotics")


def _cleanup(db: Database) -> None:
    with db.cursor() as c:
        c.execute("DELETE FROM match_teams WHERE match_key LIKE '9984zzz%%'")
        c.execute("DELETE FROM matches WHERE event_key IN (%s, %s)", (_PRIOR, _EVENT))
        c.execute("DELETE FROM team_event_stats WHERE event_key IN (%s, %s)", (_PRIOR, _EVENT))
        c.execute("DELETE FROM teams WHERE team_number = ANY(%s)", (_TEAMS,))
        c.execute("DELETE FROM events WHERE event_key IN (%s, %s)", (_PRIOR, _EVENT))


def _match(c, key, event, when, red, blue, scores=(50, 40)) -> None:
    c.execute("INSERT INTO matches (match_key, event_key, season, competition_level, match_number, scheduled_time, "
              "score_red, score_blue) VALUES (%s, %s, %s, 'qualification', 1, %s, %s, %s)",
              (key, event, _SEASON, when, *scores))
    for color, teams in (("red", red), ("blue", blue)):
        for team in teams:
            c.execute("INSERT INTO match_teams (match_key, team_number, alliance_color) VALUES (%s, %s, %s)",
                      (key, team, color))


@pytest.fixture
def database() -> Generator[Database, None, None]:
    db = Database(DatabaseConfig(Settings().database_url))
    _cleanup(db)
    with db.cursor() as c:
        c.execute("INSERT INTO events (event_key, season, name, end_date) VALUES (%s, %s, 'Prior', %s), "
                  "(%s, %s, 'Event', %s)", (_PRIOR, _SEASON, date(2026, 2, 20), _EVENT, _SEASON, date(2026, 3, 2)))
        c.execute("INSERT INTO teams (team_number, name) VALUES " + ", ".join(["(%s, %s)"] * len(_TEAMS)),
                  [v for t in _TEAMS for v in (t, f"Team {t}")])
        _match(c, "9984zzzprior_qm1", _PRIOR, datetime(2026, 2, 19, 10, tzinfo=timezone.utc), _TEAMS[:3], _TEAMS[3:5])
        for team, epa in _EPA.items():
            c.execute("INSERT INTO team_event_stats (team_number, event_key, season, epa_total, epa_auto, epa_teleop, "
                      "epa_endgame, matches_played) VALUES (%s, %s, %s, %s, 1, 1, 1, 1)", (team, _PRIOR, _SEASON, epa))
        for i, when in enumerate(_Q, start=1):
            scores = (None, None) if i == 4 else (50 + i, 40)  # q4 unplayed
            _match(c, f"9984zzzevent_qm{i}", _EVENT, when, _TEAMS[:3], _TEAMS[3:], scores)
    try:
        yield db
    finally:
        _cleanup(db)


def _client(database, model=None) -> TestClient:
    app = create_app(Settings())
    app.dependency_overrides[get_database] = lambda: database
    app.dependency_overrides[get_ranking_model] = lambda: model
    return TestClient(app)


def test_switch_point_from_the_canonical_schedule(database):
    assert not serving_switch(database, _EVENT, _Q[1]).passed  # the 2nd match itself is not before as_of
    state = serving_switch(database, _EVENT, _Q[1] + timedelta(minutes=1))
    assert state.passed and state.switch_time == _Q[1] and state.teams == 6


def test_pre_event_serves_raw_epa_labelled_validated(database):
    with _client(database) as client:
        body = client.get(f"/events/{_EVENT}/analysis", params={"as_of": _T0.isoformat()}).json()
    ordering = body["ordering"]
    assert ordering["model"] == POLICY_RAW_EPA and ordering["validation_status"] == VALIDATED_RAW_EPA
    assert [t["team_number"] for t in ordering["teams"]] == [998402, 998404, 998401, 998405, 998403, 998406]
    assert ordering["teams"][-1]["score"] is None  # no prior EPA: last, never a fabricated number
    assert body["captain_candidates"]["validation_status"] == VALIDATED_AS_MEASURED
    assert body["captain_candidates"]["team_numbers"] == [t["team_number"] for t in ordering["teams"]][:8]
    assert "playoff" in body["strongest_teams"]["evidence"]
    assert body["team_comparison"]["validation_status"] == "descriptive" and len(body["team_comparison"]["teams"]) == 6
    assert body["ranking_model_sha256"] is None


def test_after_the_switch_serves_one_model_m5v2(database):
    stub = SimpleNamespace(model=SimpleNamespace(predict_rating=lambda f: -f.team_number), sha256="stub")
    with _client(database, stub) as client:
        body = client.get(f"/events/{_EVENT}/analysis",
                          params={"as_of": (_Q[1] + timedelta(minutes=1)).isoformat()}).json()
    assert body["ordering"]["model"] == POLICY_M5V2 and body["ordering"]["switch_point_passed"]
    assert body["ordering"]["validation_status"] == VALIDATED_AS_MEASURED and body["ranking_model_sha256"] == "stub"
    assert [t["team_number"] for t in body["ordering"]["teams"]] == sorted(_TEAMS)  # the stub's scores only


@pytest.mark.parametrize(("params", "status", "code"), [
    ({"as_of": (_Q[1] + timedelta(minutes=1)).isoformat()}, 404, "model_not_loaded"),
    ({"as_of": "2026-03-01T09:00:00"}, 422, "invalid_as_of"),
])
def test_refusals(database, params, status, code):
    with _client(database) as client:
        response = client.get(f"/events/{_EVENT}/analysis", params=params)
    assert response.status_code == status and response.json()["error"]["code"] == code


def test_unknown_event(database):
    with _client(database) as client:
        response = client.get("/events/9984zzznosuch/analysis")
    assert response.status_code == 404 and response.json()["error"]["code"] == "event_not_found"
