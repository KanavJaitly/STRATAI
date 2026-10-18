"""P7-M3: win probability and rankings -- the shared probability object, `as_of` on the POST routes, the ranking
route's deprecation, and every declared error. (Served values are pinned separately against their pre-Phase 7
form by tests/test_phase7_predictions_regression.py.)

Uses the synthetic fixtures of tests/test_api_predictions.py (real registry-load-predict pipeline, synthetic models
and sentinel rows; no result here is evidence about model quality).
"""

from __future__ import annotations

from typing import Any

import pytest
from fastapi.testclient import TestClient

from api import create_app
from api.dependencies import get_database, get_epa_source
from tests.phase7_support import assert_declared_error
from tests.test_api_predictions import (  # noqa: F401  (fixtures)
    _MATCH_PLAYED,
    _MATCH_PLAYOFF,
    _MATCH_UNPLAYED,
    _S_EVENT,
    _S_EVENT_UNKNOWN,
    _TEAM_BLUE,
    _TEAM_EMPTY,
    _TEAM_RED,
    _TEAM_UNKNOWN,
    _settings,
    _statbotics_reference_epa_source,
    client,
    client_no_models,
    database,
    registry_dir,
    requires_db,
)

pytestmark = requires_db

MATCH = "/predictions/matches/{match_key}/win-probability"
ADHOC = "/predictions/win-probability"
RANKING = "/predictions/events/{event_key}/ranking"
SYNERGY = "/predictions/alliance-synergy"
FORECAST = "/events/{event_key}/qualification-forecast"
ALLIANCES = {"event_key": _S_EVENT, "red_team_numbers": _TEAM_RED, "blue_team_numbers": _TEAM_BLUE}
BEFORE_PRIOR_EVENT = "2026-02-18T00:00:00+00:00"   # the prior event (EPA source) has not happened yet
AFTER_PRIOR_EVENT = "2026-03-05T00:00:00+00:00"


def _openapi(client: TestClient) -> dict[str, Any]:
    return client.app.openapi()


def _assert_object_matches_legacy(body: dict[str, Any]) -> None:
    """The shared object carries exactly the legacy fields' decision and value (P7-Q3, R7)."""
    probability = body["win_probability"]
    assert probability["validated_value"] == body["red_win_probability"]
    assert probability["unvalidated_value"] == body["unvalidated_red_win_probability"]
    assert probability["unvalidated_reason"] == body["not_validated_reason"]
    assert probability["validation"]["status"] == body["validation_status"]
    assert probability["calibration_status"] == "m7_gate_failed"
    assert "m7_gate_failed" in probability["validation"]["reasons"]
    if "model" in body:
        assert probability["model"] == body["model"]


# --- the shared probability object -------------------------------------------------------------------------------


@pytest.mark.parametrize("request_args, reason", [
    (("GET", MATCH.format(match_key=_MATCH_PLAYED), None), None),
    (("GET", MATCH.format(match_key=_MATCH_PLAYOFF), None), "playoff_scope"),
    (("POST", ADHOC, ALLIANCES), "unspecified_context"),
    (("POST", ADHOC, {**ALLIANCES, "match_context": "playoff"}), "playoff_scope"),
    (("POST", ADHOC, {**ALLIANCES, "match_context": "qualification"}), None),
    (("POST", ADHOC, {**ALLIANCES, "blue_team_numbers": _TEAM_EMPTY, "match_context": "qualification"}),
     "epa_incomplete"),
])
def test_the_probability_object_equals_the_legacy_fields_in_every_gating_branch(client, request_args, reason):
    method, url, body = request_args
    response = client.get(url) if method == "GET" else client.post(url, json=body)
    assert response.status_code == 200
    payload = response.json()
    _assert_object_matches_legacy(payload)
    assert payload["win_probability"]["unvalidated_reason"] == reason
    assert (payload["win_probability"]["validated_value"] is None) == (reason is not None)


def test_every_forecast_match_carries_the_same_object(client):
    body = client.get(FORECAST.format(event_key=_S_EVENT), params={"as_of": AFTER_PRIOR_EVENT}).json()
    assert body["matches"]
    for match in body["matches"]:
        _assert_object_matches_legacy(match)
        assert match["win_probability"]["model"]["model_sha256"] == body["win_prob_model_sha256"]


# --- as_of on the POST routes (P7-Q7) -----------------------------------------------------------------------------


def test_win_probability_as_of_is_point_in_time(client):
    """Before the prior event these teams have no features at all, so the route refuses to predict from nothing
    (insufficient_features); after it, the same pairing is inside M7's evaluated population."""
    body = {**ALLIANCES, "match_context": "qualification"}
    before = client.post(ADHOC, json=body, params={"as_of": BEFORE_PRIOR_EVENT})
    assert_declared_error(_openapi(client), before, "POST", ADHOC, code="insufficient_features")
    after = client.post(ADHOC, json=body, params={"as_of": AFTER_PRIOR_EVENT}).json()
    assert after["as_of"].startswith("2026-03-05") and after["not_validated_reason"] is None
    assert after["win_probability"]["validated_value"] is not None


def test_synergy_as_of_is_echoed_and_used(client):
    before = client.post(SYNERGY, json={"event_key": _S_EVENT, "team_numbers": _TEAM_RED},
                         params={"as_of": BEFORE_PRIOR_EVENT}).json()
    after = client.post(SYNERGY, json={"event_key": _S_EVENT, "team_numbers": _TEAM_RED},
                        params={"as_of": AFTER_PRIOR_EVENT}).json()
    assert before["as_of"].startswith("2026-02-18") and after["as_of"].startswith("2026-03-05")
    assert [t["epa_value_source"] for t in before["teams"]] == [None, None, None]  # nothing known yet
    assert all(t["epa_value_source"] for t in after["teams"])


@pytest.mark.parametrize("url, body", [(ADHOC, ALLIANCES), (SYNERGY, {"event_key": _S_EVENT,
                                                                        "team_numbers": _TEAM_RED})])
@pytest.mark.parametrize("as_of", ["soon", "2026-03-05T00:00:00"])
def test_a_bad_as_of_is_a_declared_invalid_as_of(client, url, body, as_of):
    response = client.post(url, json=body, params={"as_of": as_of})
    assert_declared_error(_openapi(client), response, "POST", url, code="invalid_as_of")


@pytest.mark.parametrize("url, body", [(ADHOC, ALLIANCES), (SYNERGY, {"event_key": _S_EVENT,
                                                                        "team_numbers": _TEAM_RED})])
def test_a_future_as_of_is_refused_on_the_post_routes(client, url, body):
    """P7-D1: a future as_of would treat an event still in progress as a completed prior event."""
    from datetime import datetime, timedelta, timezone

    future = (datetime.now(timezone.utc) + timedelta(days=1)).isoformat()
    response = client.post(url, json=body, params={"as_of": future})
    assert_declared_error(_openapi(client), response, "POST", url, code="invalid_as_of")
    within_skew = (datetime.now(timezone.utc) + timedelta(minutes=1)).isoformat()
    ok = client.post(url, json=body, params={"as_of": within_skew})
    assert ok.status_code == 200
    assert datetime.fromisoformat(ok.json()["as_of"].replace("Z", "+00:00")) <= datetime.now(timezone.utc)


def test_an_explicit_as_of_equal_to_now_matches_the_default(client, monkeypatch):
    from datetime import datetime, timezone

    import api.routes.common as common

    frozen = datetime(2026, 3, 5, 12, tzinfo=timezone.utc)

    class _Frozen(datetime):
        @classmethod
        def now(cls, tz=None):
            return frozen

    monkeypatch.setattr(common, "datetime", _Frozen)
    body = {**ALLIANCES, "match_context": "qualification"}
    omitted = client.post(ADHOC, json=body).json()
    explicit = client.post(ADHOC, json=body, params={"as_of": frozen.isoformat()}).json()
    assert omitted == explicit


# --- the M6/M7 display rule through the routes ---------------------------------------------------------------------


def _frozen_head_display_probability(probability: float) -> float:
    """A verbatim copy of api.routes.predictions.display_probability as it was before P7-M3 moved it."""
    import math

    offset = probability - 0.5
    steps = math.floor(abs(offset) / 0.05 + 0.5)
    shown = 0.5 + math.copysign(steps * 0.05, offset)
    return round(min(max(shown, 0.05), 0.95), 2)


def test_the_moved_display_rule_is_identical_to_the_pre_phase7_rule():
    from ml.calibration.display import display_probability

    grid = [i / 100_000 for i in range(100_001)]
    assert [display_probability(p) for p in grid] == [_frozen_head_display_probability(p) for p in grid]


def test_routes_serve_exactly_the_display_rule_of_a_feature_dependent_model(client, monkeypatch):
    """The synthetic fixture model outputs a constant 0.5, so this replaces it with a deterministic,
    red/blue-asymmetric function of the features that reaches both clips, and checks the routes serve exactly
    display_probability(f(features)) -- the parity check scripts/verify_d18_production.py runs in production."""
    import math

    from ml.calibration.display import display_probability
    from ml.features.assembler import build_match_feature_row

    def score(row) -> float:
        red = sum((t.average_score or 0.0) for t in row.red_teams)
        blue = sum((t.average_score or 0.0) for t in row.blue_teams)
        return 1.0 / (1.0 + math.exp(-(red - blue) / 15.0))

    served = client.app.state.win_prob_model
    monkeypatch.setattr(served.model, "predict_win_prob", score)
    seen = set()
    for red, blue in ((_TEAM_RED, _TEAM_BLUE), (_TEAM_BLUE, _TEAM_RED)):
        body = client.post(ADHOC, json={"event_key": _S_EVENT, "red_team_numbers": red, "blue_team_numbers": blue,
                                        "match_context": "qualification"},
                           params={"as_of": AFTER_PRIOR_EVENT}).json()
        shown = body["red_win_probability"] or body["unvalidated_red_win_probability"]
        seen.add(shown)
        assert body["win_probability"]["validated_value"] == body["red_win_probability"]
    assert len(seen) == 2 and sum(seen) == pytest.approx(1.0)  # asymmetric, and the swap shows the complement
    assert seen == {0.05, 0.95}  # both clips are exercised: raw values beyond [0.05, 0.95] are never served
    match = client.get(MATCH.format(match_key=_MATCH_PLAYED)).json()
    row = build_match_feature_row(client.app.dependency_overrides[get_database](), _MATCH_PLAYED,
                                  as_of=datetime_from(match["as_of"]),
                                  epa_provider=client.app.state.epa_source.provider)
    assert (match["red_win_probability"] or match["unvalidated_red_win_probability"]) == display_probability(score(row))


def datetime_from(text: str):
    from datetime import datetime

    return datetime.fromisoformat(text.replace("Z", "+00:00"))


# --- the deprecated ranking route (P7-Q2) -------------------------------------------------------------------------


def test_the_ranking_route_is_deprecated_but_unchanged(client):
    operation = _openapi(client)["paths"][RANKING]["get"]
    assert operation["deprecated"] is True and "DEPRECATED (P7-Q2" in operation["description"]
    assert "/events/{event_key}/analysis" in operation["description"]
    response = client.get(RANKING.format(event_key=_S_EVENT))
    assert response.status_code == 200 and response.json()["validation_status"] == "moderate_held_out"
    params = {p["name"] for p in operation.get("parameters", [])}
    assert params == {"event_key"}  # no as_of: no new features on a deprecated route


def test_the_canonical_ranking_surface_is_not_deprecated(client):
    assert not _openapi(client)["paths"]["/events/{event_key}/analysis"]["get"].get("deprecated", False)


# --- declared errors ------------------------------------------------------------------------------------------------


def test_model_not_loaded_is_declared_on_each_model_route(client_no_models):
    openapi = _openapi(client_no_models)
    for method, path, url, body in (
        ("GET", MATCH, MATCH.format(match_key=_MATCH_PLAYED), None),
        ("POST", ADHOC, ADHOC, ALLIANCES),
        ("GET", RANKING, RANKING.format(event_key=_S_EVENT), None),
        ("GET", FORECAST, FORECAST.format(event_key=_S_EVENT), None),
    ):
        response = client_no_models.get(url) if method == "GET" else client_no_models.post(url, json=body)
        assert_declared_error(openapi, response, method, path, code="model_not_loaded")


def test_epa_source_not_loaded_is_declared_on_each_route(database, registry_dir):
    app = create_app(_settings(registry_dir))
    app.dependency_overrides[get_database] = lambda: database
    app.dependency_overrides[get_epa_source] = lambda: None
    with TestClient(app) as client:
        openapi = app.openapi()
        for method, path, url, body in (
            ("GET", MATCH, MATCH.format(match_key=_MATCH_PLAYED), None),
            ("POST", ADHOC, ADHOC, ALLIANCES),
            ("GET", RANKING, RANKING.format(event_key=_S_EVENT), None),
            ("POST", SYNERGY, SYNERGY, {"event_key": _S_EVENT, "team_numbers": _TEAM_RED}),
        ):
            response = client.get(url) if method == "GET" else client.post(url, json=body)
            assert_declared_error(openapi, response, method, path, code="epa_source_not_loaded")


@pytest.mark.parametrize("method, path, url, body, code", [
    ("GET", MATCH, MATCH.format(match_key="9997zzznomatch_qm1"), None, "match_not_found"),
    ("GET", MATCH, MATCH.format(match_key=_MATCH_UNPLAYED), None, None),  # 200 or insufficient_features
    ("POST", ADHOC, ADHOC, {**ALLIANCES, "event_key": _S_EVENT_UNKNOWN}, "event_not_found"),
    ("POST", ADHOC, ADHOC, {**ALLIANCES, "red_team_numbers": [_TEAM_UNKNOWN, *_TEAM_RED[1:]]}, "team_not_found"),
    ("POST", ADHOC, ADHOC, {**ALLIANCES, "red_team_numbers": _TEAM_EMPTY, "blue_team_numbers": _TEAM_EMPTY},
     "insufficient_features"),
    ("POST", ADHOC, ADHOC, {**ALLIANCES, "red_team_numbers": _TEAM_RED[:2]}, "validation_error"),
    ("GET", RANKING, RANKING.format(event_key=_S_EVENT_UNKNOWN), None, "event_not_found"),
    ("POST", SYNERGY, SYNERGY, {"event_key": _S_EVENT_UNKNOWN, "team_numbers": _TEAM_RED}, "event_not_found"),
    ("POST", SYNERGY, SYNERGY, {"event_key": _S_EVENT, "team_numbers": [_TEAM_UNKNOWN, *_TEAM_RED[1:]]},
     "team_not_found"),
    ("POST", SYNERGY, SYNERGY, {"event_key": _S_EVENT, "team_numbers": _TEAM_RED[:1]}, "validation_error"),
    ("GET", FORECAST, FORECAST.format(event_key=_S_EVENT_UNKNOWN), None, "event_not_found"),
    ("GET", FORECAST, FORECAST.format(event_key=_S_EVENT) + "?as_of=bad", None, "invalid_as_of"),
])
def test_every_refusal_is_declared(client, method, path, url, body, code):
    response = client.get(url) if method == "GET" else client.post(url, json=body)
    if code is None:  # the unplayed match: either a served prediction or the declared insufficient_features
        if response.status_code != 200:
            assert_declared_error(_openapi(client), response, method, path, code="insufficient_features")
        return
    assert_declared_error(_openapi(client), response, method, path, code=code)
