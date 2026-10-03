"""P5-M5 qualification forecast endpoint: gating, Σ q records, labels, point-in-time.

Reuses the P5-M4 endpoint test's sentinel event (namespace 9984, isolated database only), a stub
win-probability model and the reference Statbotics EPA source. Synthetic data.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from api import create_app
from api.dependencies import get_database, get_win_prob_model
from data.config import Settings
from ml.views import qualification_forecast as qf
from tests.test_event_analysis_api import _EVENT, _Q, _T0, _TEAMS, _isolated_db_name, database  # noqa: F401

pytestmark = pytest.mark.skipif(_isolated_db_name() is None, reason="needs an isolated stratai_* database copy")


@pytest.fixture(autouse=True)
def _reference_epa_source(monkeypatch):
    monkeypatch.setenv("EPA_SOURCE", "statbotics")


def _client(database, model) -> TestClient:  # noqa: F811
    app = create_app(Settings())
    app.dependency_overrides[get_database] = lambda: database
    app.dependency_overrides[get_win_prob_model] = lambda: model
    return TestClient(app)


STUB = SimpleNamespace(model=SimpleNamespace(predict_win_prob=lambda row: 0.6), sha256="stub")


def test_forecast_records_and_labels(database):  # noqa: F811
    with _client(database, STUB) as client:
        body = client.get(f"/events/{_EVENT}/qualification-forecast", params={"as_of": _T0.isoformat()}).json()
    assert [m["match_key"] for m in body["matches"]] == [f"9984zzzevent_qm{i}" for i in range(1, 5)]
    match = body["matches"][0]  # team 998406 has no prior EPA: every match is EPA-incomplete
    assert match["validation_status"] == "not_validated" and match["not_validated_reason"] == "epa_incomplete"
    assert match["red_win_probability"] is None and match["unvalidated_red_win_probability"] == 0.6
    red = next(t for t in body["teams"] if t["team_number"] == _TEAMS[0])
    assert red["qualification_matches"] == 4 and red["expected_wins"] == 2.4  # 4 x 0.6
    assert red["record_validation_status"] == qf.NOT_VALIDATED
    assert red["range_validation_status"] == qf.NOT_VALIDATED
    blue = next(t for t in body["teams"] if t["team_number"] == _TEAMS[3])
    assert blue["expected_wins"] == 1.6 and blue["range80_low"] <= 1.6 <= blue["range80_high"]
    assert body["low_confidence"] is None and body["statbotics_week"] is None  # no Statbotics record landed


def test_played_matches_keep_their_pre_match_features(database):  # noqa: F811
    as_of = _Q[3] + timedelta(hours=1)
    with _client(database, STUB) as client:
        body = client.get(f"/events/{_EVENT}/qualification-forecast", params={"as_of": as_of.isoformat()}).json()
    assert [datetime.fromisoformat(m["features_as_of"]) for m in body["matches"]] == _Q


def test_range_is_served_not_validated_by_the_measurement():
    assert qf.RANGE_COVERAGE_VALIDATED is False
    record = qf.team_records([qf.MatchForecast("m", (1,), (2,), 0.6, True)])[1]
    assert record.range_status() == (qf.NOT_VALIDATED, qf.REASON_RANGE_COVERAGE)
    assert record.record_status() == (qf.RECORD_VALIDATED, None)


def test_model_not_loaded(database):  # noqa: F811
    with _client(database, None) as client:
        response = client.get(f"/events/{_EVENT}/qualification-forecast")
    assert response.status_code == 404 and response.json()["error"]["code"] == "model_not_loaded"
