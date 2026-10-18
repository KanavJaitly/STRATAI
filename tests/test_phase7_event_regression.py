"""P7-M4 regression: extracting event analysis and the qualification forecast into services changes nothing served.

tests/fixtures/p7_m4_event_golden.json was captured from both routes *before* the P7-M4 extraction (after P7-M3,
the spec's baseline), at fixed as_of values, on the Phase 5 sentinel fixtures (namespace 9984,
tests/test_event_analysis_api.py), with feature-dependent model stubs so the values are not constants. The
responses must be identical, key for key and value for value.

Regenerate only on purpose, and only before changing the routes: P7_M4_WRITE_GOLDEN=1 pytest <this file>.
"""

from __future__ import annotations

import json
import math
import os
from datetime import timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from api import create_app
from api.dependencies import get_database, get_ranking_model, get_win_prob_model
from data.config import Settings
from tests.phase7_support import stub_served_model
from tests.test_event_analysis_api import _EVENT, _Q, _T0, _isolated_db_name, database  # noqa: F401

GOLDEN = Path(__file__).resolve().parent / "fixtures" / "p7_m4_event_golden.json"

pytestmark = pytest.mark.skipif(_isolated_db_name() is None, reason="needs an isolated stratai_* database copy")


@pytest.fixture(autouse=True)
def _reference_epa_source(monkeypatch):
    monkeypatch.setenv("EPA_SOURCE", "statbotics")


def _q(row) -> float:
    """Red/blue-asymmetric and point-in-time feature-dependent (EPA plus each team's average score so far, which
    changes as qualification matches are played), so the golden pins real, varied values."""
    def strength(team) -> float:
        return (team.epa_total or 0.0) + (team.average_score or 0.0)

    red = sum(strength(t) for t in row.red_teams)
    blue = sum(strength(t) for t in row.blue_teams)
    return 1.0 / (1.0 + math.exp(-(red - blue) / 25.0))


RANKING = stub_served_model(predict_rating=lambda f: (f.epa_total or 0.0) - f.team_number / 1e6, sha256="stub-ranking")
WIN_PROB = stub_served_model(predict_win_prob=_q, sha256="stub-win", model_type="win_prob_xgb_calibrated")


def _capture(database) -> dict:  # noqa: F811
    app = create_app(Settings())
    app.dependency_overrides[get_database] = lambda: database
    app.dependency_overrides[get_ranking_model] = lambda: RANKING
    app.dependency_overrides[get_win_prob_model] = lambda: WIN_PROB
    cases = {
        "analysis_pre_event": (f"/events/{_EVENT}/analysis", _T0),
        "analysis_after_switch": (f"/events/{_EVENT}/analysis", _Q[1] + timedelta(minutes=1)),
        "forecast_pre_event": (f"/events/{_EVENT}/qualification-forecast", _T0),
        "forecast_after_all": (f"/events/{_EVENT}/qualification-forecast", _Q[3] + timedelta(hours=1)),
    }
    out = {}
    with TestClient(app) as client:
        for name, (url, as_of) in cases.items():
            response = client.get(url, params={"as_of": as_of.isoformat()})
            out[name] = {"status": response.status_code, "body": response.json()}
    return out


def test_extracted_services_serve_exactly_what_the_routes_served(database):  # noqa: F811
    captured = _capture(database)
    assert {name: r["status"] for name, r in captured.items() if r["status"] != 200} == {}
    probabilities = {m["red_win_probability"] or m["unvalidated_red_win_probability"]
                     for name in ("forecast_pre_event", "forecast_after_all") for m in captured[name]["body"]["matches"]}
    assert len(probabilities) > 1, "the stub must produce varied values, or the golden pins nothing"
    if os.environ.get("P7_M4_WRITE_GOLDEN") == "1":
        GOLDEN.parent.mkdir(exist_ok=True)
        GOLDEN.write_text(json.dumps(captured, indent=1, sort_keys=True) + "\n", encoding="utf-8")
        pytest.skip("golden written")
    golden = json.loads(GOLDEN.read_text(encoding="utf-8"))
    assert captured == golden
