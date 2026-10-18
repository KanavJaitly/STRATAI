"""P7-M5: the match strategy endpoints -- HTTP parity between the AI and coach paths, labels, refusals, the coach
writes and the model pin.

Real Postgres sentinel rows (namespace 9966), only on an isolated stratai_* database copy, with the reference
Statbotics EPA source and a synthetic P6-M10 model (tests/phase6_fixtures FIXTURE_BETA / FIXTURE_SIGMA): no result
here is evidence about any real team or about the model of record.
"""

from __future__ import annotations

import json
from datetime import date, datetime, timedelta, timezone
from typing import Generator

import pytest
from fastapi.testclient import TestClient
from starlette.requests import Request  # module level: FastAPI resolves dependency annotations from module globals

from api import create_app
from api.dependencies import get_database, get_epa_source, get_strategy_model
from data.config import Settings
from database.connection import Database, DatabaseConfig
from ml.strategy.outcome import (
    MODEL_TYPE,
    MODEL_VERSION,
    REASON_GATE_FAILED,
    REASON_OBSERVATION,
    REASON_PLAYOFF,
    REASON_STRATEGY,
    SERVED_BASELINE_STATUS,
    ComponentOutcomeModel,
)
from ml.strategy.display import DIFFERS, INDISTINGUISHABLE
from tests.phase6_fixtures import FIXTURE_BETA, FIXTURE_SIGMA
from tests.phase7_support import assert_declared_error
from tests.test_live_epa import _isolated_db_name

pytestmark = pytest.mark.skipif(_isolated_db_name() is None, reason="needs an isolated stratai_* database copy")

_SEASON = 9966
_FILL, _PRIOR, _EVENT = "9966zzzfill", "9966zzzprior", "9966zzzevent"
_RED, _BLUE = [996601, 996602, 996603], [996604, 996605, 996606]
_NO_EPA = 996607
_TEAMS = [*_RED, *_BLUE, _NO_EPA]
_T = datetime(2026, 3, 1, 10, tzinfo=timezone.utc)
QM1, SF, UNSCHEDULED, SHORT, NOLEVEL, MISSING = (f"{_EVENT}_qm1", f"{_EVENT}_sf1m1", f"{_EVENT}_qm2",
                                                  f"{_EVENT}_qm3", f"{_EVENT}_qm4", f"{_EVENT}_qm5")
TOKEN = "test-write-token"
MATCH = "/strategy/matches/{match_key}/{action}"
HYPO = "/strategy/hypothetical/{action}"


@pytest.fixture(autouse=True)
def _reference_epa_source(monkeypatch):
    monkeypatch.setenv("EPA_SOURCE", "statbotics")


def _cleanup(db: Database) -> None:
    with db.cursor() as c:
        c.execute("DELETE FROM raw_source_payloads WHERE source = 'coach_input' AND payload_json->>'event_key' LIKE "
                  "'9966zzz%%'")
        c.execute("DELETE FROM match_teams WHERE match_key LIKE '9966zzz%%'")
        c.execute("DELETE FROM matches WHERE event_key LIKE '9966zzz%%'")
        c.execute("DELETE FROM team_event_stats WHERE event_key LIKE '9966zzz%%'")
        c.execute("DELETE FROM teams WHERE team_number = ANY(%s)", (_TEAMS,))
        c.execute("DELETE FROM events WHERE event_key LIKE '9966zzz%%'")


def _match(c, key, event, level, when, red, blue, scores=(None, None)) -> None:
    number = int(key.rsplit("m", 1)[1])
    c.execute("INSERT INTO matches (match_key, event_key, season, competition_level, set_number, match_number, "
              "scheduled_time, score_red, score_blue) VALUES (%s, %s, %s, %s, 1, %s, %s, %s, %s)",
              (key, event, _SEASON, level, number, when, *scores))
    for color, teams in (("red", red), ("blue", blue)):
        for team in teams:
            c.execute("INSERT INTO match_teams (match_key, team_number, alliance_color) VALUES (%s, %s, %s)",
                      (key, team, color))


@pytest.fixture
def database() -> Generator[Database, None, None]:
    from database.migrate import run_migrations

    settings = Settings()
    run_migrations(settings)
    db = Database(DatabaseConfig(settings.database_url))
    _cleanup(db)
    with db.cursor() as c:
        c.execute("INSERT INTO events (event_key, season, name, end_date) VALUES (%s, %s, 'Fill', %s), "
                  "(%s, %s, 'Prior', %s), (%s, %s, 'Event', %s)",
                  (_FILL, _SEASON, date(2026, 1, 20), _PRIOR, _SEASON, date(2026, 2, 20), _EVENT, _SEASON,
                   date(2026, 3, 2)))
        c.execute("INSERT INTO teams (team_number, name) VALUES " + ", ".join(["(%s, %s)"] * len(_TEAMS)),
                  [v for t in _TEAMS for v in (t, f"Team {t}")])
        # 110 completed filler matches, so the causal season scale is defined (>= 200 alliance scores).
        start = datetime(2026, 1, 10, tzinfo=timezone.utc)
        c.executemany("INSERT INTO matches (match_key, event_key, season, competition_level, match_number, "
                      "scheduled_time, score_red, score_blue) VALUES (%s, %s, %s, 'qualification', %s, %s, %s, %s)",
                      [(f"{_FILL}_qm{i}", _FILL, _SEASON, i, start + timedelta(minutes=10 * i),
                        40 + (i * 7) % 50, 30 + (i * 11) % 45) for i in range(1, 111)])
        _match(c, f"{_PRIOR}_qm1", _PRIOR, "qualification", datetime(2026, 2, 19, 10, tzinfo=timezone.utc), _RED,
               _BLUE, (60, 50))
        for i, team in enumerate([*_RED, *_BLUE]):
            c.execute("INSERT INTO team_event_stats (team_number, event_key, season, epa_total, epa_auto, epa_teleop, "
                      "epa_endgame, matches_played) VALUES (%s, %s, %s, %s, %s, %s, %s, 1)",
                      (team, _PRIOR, _SEASON, 30 + 3 * i, 5 + i, 20 + 2 * i, 5.0, ))
        _match(c, QM1, _EVENT, "qualification", _T, _RED, _BLUE)
        _match(c, SF, _EVENT, "semifinal", _T + timedelta(hours=5), _RED, _BLUE)
        _match(c, UNSCHEDULED, _EVENT, "qualification", None, _RED, _BLUE)
        _match(c, SHORT, _EVENT, "qualification", _T + timedelta(hours=1), _RED[:2], _BLUE)
        _match(c, NOLEVEL, _EVENT, None, _T + timedelta(hours=2), _RED, _BLUE)
        _match(c, MISSING, _EVENT, "qualification", _T + timedelta(hours=3), [_NO_EPA, *_RED[1:]], _BLUE)
    try:
        yield db
    finally:
        _cleanup(db)


def _model() -> ComponentOutcomeModel:
    """A synthetic P6-M10 model carrying the served status of the model of record (not_validated, gate failed)."""
    return ComponentOutcomeModel(FIXTURE_BETA, FIXTURE_SIGMA, fit_info={}, spec_sha256="0" * 64,
                                 artifact_sha256="a" * 64).with_status(version_tag="test",
                                                                       baseline_status=SERVED_BASELINE_STATUS)


@pytest.fixture
def app(database):
    application = create_app(Settings(human_inputs_write_token=TOKEN))
    application.dependency_overrides[get_database] = lambda: database
    application.dependency_overrides[get_strategy_model] = _model
    return application


@pytest.fixture
def client(app) -> Generator[TestClient, None, None]:
    with TestClient(app) as test_client:
        yield test_client


def _strategy(teams, role_for=None) -> dict:
    robots = []
    for team in teams:
        if role_for and team == role_for[0]:
            robots.append({"team_number": team, "role": "defense", "components": ["auto", "endgame"],
                           "defense_target": role_for[1]})
        else:
            robots.append({"team_number": team})
    return {"robots": robots}


def _post(client, url, body, **params):
    return client.post(url, json=body, params=params or None)


# --- labels and the single path ---------------------------------------------------------------------------------------


def test_the_baseline_is_served_not_validated_with_the_gate_reason(client):
    body = _post(client, MATCH.format(match_key=QM1, action="assess"), {"side": "red", "strategy": _strategy(_RED)}).json()
    odds = body["assessment"]["odds"]
    assert odds["display"] is not None and odds["validation"]["status"] == "not_validated"
    assert odds["validation"]["reasons"] == [REASON_GATE_FAILED]
    assert datetime.fromisoformat(body["context"]["as_of"]) == _T  # the match's own scheduled time (same instant)
    assert body["context"]["match_context"] == "qualification"
    assert body["model"] == {"model_type": MODEL_TYPE, "model_version": MODEL_VERSION, "model_version_tag": "test",
                             "model_sha256": "a" * 64, "spec_sha256": "0" * 64}


def test_a_non_baseline_strategy_adds_its_unmeasured_reasons(client):
    body = _post(client, MATCH.format(match_key=QM1, action="assess"),
                 {"side": "red", "strategy": _strategy(_RED, role_for=(_RED[0], _BLUE[0]))}).json()
    reasons = body["assessment"]["odds"]["validation"]["reasons"]
    assert REASON_STRATEGY in reasons and "defense_effect_insufficient_data" in reasons


def test_the_ai_and_coach_paths_give_identical_odds_for_the_identical_strategy(client):
    """P6-DM2 over HTTP: the recommended strategy, assessed as a coach would submit it, gets the same display,
    status and reasons; compared with itself it is indistinguishable."""
    rec = _post(client, MATCH.format(match_key=QM1, action="recommend"), {"side": "blue"}).json()
    ai = rec["recommended"]
    coach = _post(client, MATCH.format(match_key=QM1, action="assess"),
                  {"side": "blue", "strategy": ai["strategy"]}).json()["assessment"]
    assert coach["odds"] == ai["odds"] and coach["strategy"] == ai["strategy"]
    same = _post(client, MATCH.format(match_key=QM1, action="compare"),
                 {"side": "blue", "first": ai["strategy"], "second": ai["strategy"]}).json()
    assert same["label"] == INDISTINGUISHABLE and same["first"]["odds"] == same["second"]["odds"] == ai["odds"]
    assert rec["candidates_evaluated"] == 21_952 and "not an unbiased probability" in rec["selection_note"]
    assert rec["baseline"]["odds"]["validation"]["reasons"] == [REASON_GATE_FAILED]
    assert rec["vs_baseline_label"] in (INDISTINGUISHABLE, DIFFERS)


def test_a_playoff_match_returns_no_odds_with_the_engines_reason(client):
    body = _post(client, MATCH.format(match_key=SF, action="assess"), {"side": "red", "strategy": _strategy(_RED)})
    assert body.status_code == 200
    odds = body.json()["assessment"]["odds"]
    assert odds["display"] is None and odds["validation"]["reasons"] == [REASON_PLAYOFF]
    rec = _post(client, MATCH.format(match_key=SF, action="recommend"), {"side": "red"}).json()
    assert rec["recommended"] is None and rec["unavailable_reasons"] == [REASON_PLAYOFF]


def test_missing_inputs_return_insufficient_data_not_an_error(client):
    strategy = _strategy([_NO_EPA, *_RED[1:]])
    odds = _post(client, MATCH.format(match_key=MISSING, action="assess"),
                 {"side": "red", "strategy": strategy}).json()["assessment"]["odds"]
    assert odds["display"] is None and odds["validation"]["status"] == "insufficient_data"
    assert any(r.startswith(f"missing_input:{_NO_EPA}:") for r in odds["validation"]["reasons"])


def test_no_raw_probability_is_ever_served(client, app):
    forbidden = ("p_ours", "p_red", "p_blue", "mean_difference", "sigma", "component_means",
                 "expected_component_means_normalized", "difference", "p_win_event", "p_reach_finals",
                 "margin_over_next")

    def keys(value):
        if isinstance(value, dict):
            for k, v in value.items():
                yield k
                yield from keys(v)
        elif isinstance(value, list):
            for v in value:
                yield from keys(v)

    schema = json.dumps({k: v for k, v in app.openapi()["components"]["schemas"].items()})
    assert not [name for name in forbidden if f'"{name}"' in schema]
    for action, body in (("assess", {"side": "red", "strategy": _strategy(_RED)}), ("recommend", {"side": "red"}),
                         ("compare", {"side": "red", "first": _strategy(_RED), "second": _strategy(_RED)})):
        served = set(keys(_post(client, MATCH.format(match_key=QM1, action=action), body).json()))
        assert not served & set(forbidden), (action, served & set(forbidden))


# --- HTTP parity, with defects planted in the HTTP layer (P7-M5 acceptance (1)) -------------------------------------------


def _parity_problems(client, match_key=QM1, side="red") -> list[str]:
    """The AI path (recommend) against the coach path (assess, compare) for the identical strategy, over HTTP:
    every displayed odds, status and reason must match exactly."""
    rec = _post(client, MATCH.format(match_key=match_key, action="recommend"), {"side": side}).json()
    problems = []
    for candidate in [rec["recommended"], rec["baseline"], *rec["alternatives"]]:
        coach = _post(client, MATCH.format(match_key=match_key, action="assess"),
                      {"side": side, "strategy": candidate["strategy"]}).json()["assessment"]
        if coach["odds"] != candidate["odds"]:
            problems.append(f"assess differs from recommend: {coach['odds']} vs {candidate['odds']}")
        compared = _post(client, MATCH.format(match_key=match_key, action="compare"),
                         {"side": side, "first": candidate["strategy"], "second": candidate["strategy"]}).json()
        if compared["first"]["odds"] != candidate["odds"] or compared["label"] != INDISTINGUISHABLE:
            problems.append(f"compare differs from recommend: {compared['first']['odds']} vs {candidate['odds']}")
    return problems


def test_http_parity_holds_for_the_recommendation_its_alternatives_and_the_baseline(client):
    assert _parity_problems(client) == [] and _parity_problems(client, side="blue") == []


def _planted_response_defect(app, path_suffix: str, mutate) -> None:
    """A defect in the HTTP layer: a middleware that rewrites the odds of one route's responses only."""
    from starlette.middleware.base import BaseHTTPMiddleware
    from starlette.responses import Response

    async def defect(request, call_next):
        response = await call_next(request)
        if not request.url.path.endswith(path_suffix):
            return response
        body = json.loads(b"".join([chunk async for chunk in response.body_iterator]))
        mutate(body)
        return Response(json.dumps(body), status_code=response.status_code, media_type="application/json")

    app.add_middleware(BaseHTTPMiddleware, dispatch=defect)


@pytest.mark.parametrize("mutate", [
    lambda odds: odds.update(display=">95%"),                                     # re-rounds / clips
    lambda odds: odds["validation"].update(status="validated"),                   # relabels
    lambda odds: odds["validation"].update(reasons=[]),                           # drops a reason
])
@pytest.mark.parametrize("route, path_mutate", [
    ("/assess", lambda mutate: lambda b: mutate(b["assessment"]["odds"])),
    ("/compare", lambda mutate: lambda b: mutate(b["first"]["odds"])),
])
def test_the_parity_check_catches_a_route_that_presents_one_path_differently(database, mutate, route, path_mutate):
    app = create_app(Settings())
    app.dependency_overrides[get_database] = lambda: database
    app.dependency_overrides[get_strategy_model] = _model
    _planted_response_defect(app, route, path_mutate(mutate))
    with TestClient(app) as client:
        assert _parity_problems(client)


def test_the_parity_check_catches_a_route_that_swaps_the_model_for_one_path(database):
    """A dependency override that serves a different model to the recommend route only."""
    other = ComponentOutcomeModel({"auto": 0.1, "teleop": 3.0, "endgame": 0.1}, FIXTURE_SIGMA, fit_info={},
                                  spec_sha256="1" * 64, artifact_sha256="b" * 64).with_status(
        version_tag="other", baseline_status=SERVED_BASELINE_STATUS)

    def swapped(request: Request):
        return other if request.url.path.endswith("/recommend") else _model()

    app = create_app(Settings())
    app.dependency_overrides[get_database] = lambda: database
    app.dependency_overrides[get_strategy_model] = swapped
    with TestClient(app) as client:
        assert _parity_problems(client)


def test_recommend_end_to_end_is_within_the_pre_registered_budget(client):
    """P7-Q11 / R19: the 10-second budget, end to end over HTTP (context building from the database, the EPA
    provider, the observation load and the 21,952-candidate search), measured on this machine."""
    import time

    start = time.perf_counter()
    response = _post(client, MATCH.format(match_key=QM1, action="recommend"), {"side": "red"})
    elapsed = time.perf_counter() - start
    assert response.status_code == 200 and response.json()["candidates_evaluated"] == 21_952
    print(f"\nP7-M5 recommend end to end (local, synthetic model, 0 observations): {elapsed:.2f} s")
    assert elapsed < 10.0, elapsed


# --- coach observations reach both paths identically --------------------------------------------------------------------


def _observe(client, observed_at, team=_RED[0]):
    return client.post("/strategy/coach-observations", headers={"X-StratAI-Write-Token": TOKEN},
                       json={"event_key": _EVENT, "team_number": team, "kind": "robot_unavailable",
                             "observed_at": observed_at.isoformat(), "observer": "coach"})


def test_a_back_dated_observation_never_changes_a_past_evaluation(client):
    """P7-D3: observed_at is caller-asserted. An observation stored now but dated before a past match's scheduled
    time must not change that match's pre-match evaluation."""
    before = _post(client, MATCH.format(match_key=QM1, action="assess"), {"side": "red", "strategy": _strategy(_RED)})
    assert _observe(client, _T - timedelta(hours=1)).status_code == 201
    after = _post(client, MATCH.format(match_key=QM1, action="assess"), {"side": "red", "strategy": _strategy(_RED)})
    assert after.json()["context"]["coach_observations_applied"] == 0
    assert after.json()["assessment"] == before.json()["assessment"]


def test_an_observation_stored_before_as_of_reaches_every_path_identically(client):
    """For a hypothetical evaluated now, an observation stored and observed before now is in the one context the
    recommender, assess and compare all see."""
    assert _observe(client, datetime.now(timezone.utc) - timedelta(hours=1)).status_code == 201
    body = _hypothetical(match_context="qualification", side="red")
    rec = _post(client, HYPO.format(action="recommend"), body).json()
    assessed = _post(client, HYPO.format(action="assess"), {**body, "strategy": rec["recommended"]["strategy"]}).json()
    compared = _post(client, HYPO.format(action="compare"),
                     {**body, "first": rec["recommended"]["strategy"], "second": rec["baseline"]["strategy"]}).json()
    assert rec["context"]["coach_observations_applied"] == assessed["context"]["coach_observations_applied"] == 1
    assert compared["context"]["coach_observations_applied"] == 1
    assert REASON_OBSERVATION in assessed["assessment"]["odds"]["validation"]["reasons"]
    assert assessed["assessment"]["odds"] == rec["recommended"]["odds"] == compared["first"]["odds"]
    assert compared["second"]["odds"] == rec["baseline"]["odds"]


# --- hypothetical alliances (P7-Q9) -------------------------------------------------------------------------------------


def _hypothetical(**extra):
    return {"event_key": _EVENT, "red_team_numbers": _RED, "blue_team_numbers": _BLUE, **extra}


@pytest.mark.parametrize("red, blue", [
    ([_RED[0], _RED[0], _RED[1]], _BLUE),                    # a team twice on one side
    (_RED, [_RED[2], *_BLUE[:2]]),                           # a team on both sides
    (_RED, _RED),                                            # an alliance playing itself
])
@pytest.mark.parametrize("action", ["assess", "recommend", "compare"])
def test_a_hypothetical_needs_six_distinct_teams(client, app, red, blue, action):
    body = {**_hypothetical(match_context="qualification", side="red"), "red_team_numbers": red,
            "blue_team_numbers": blue, "strategy": _strategy(_RED), "first": _strategy(_RED),
            "second": _strategy(_RED)}
    response = _post(client, HYPO.format(action=action), body)
    assert_declared_error(app.openapi(), response, "POST", HYPO.format(action=action), code="validation_error")


def test_every_strategy_response_carries_the_epa_source_envelope(client):
    """P7-D3: like every EPA-backed route, the strategy odds say which EPA source their features came from."""
    for action, body in (("assess", {"side": "red", "strategy": _strategy(_RED)}), ("recommend", {"side": "red"}),
                         ("compare", {"side": "red", "first": _strategy(_RED), "second": _strategy(_RED)})):
        epa = _post(client, MATCH.format(match_key=QM1, action=action), body).json()["epa"]
        assert epa["epa_source"] == "statbotics" and epa["evaluated_configuration"] is False


def test_a_hypothetical_alliance_requires_an_explicit_match_context(client, app):
    response = _post(client, HYPO.format(action="assess"), _hypothetical(side="red", strategy=_strategy(_RED)))
    assert_declared_error(app.openapi(), response, "POST", HYPO.format(action="assess"), code="validation_error")


def test_a_hypothetical_playoff_context_returns_no_odds(client):
    body = _post(client, HYPO.format(action="assess"),
                 _hypothetical(side="red", strategy=_strategy(_RED), match_context="playoff"),
                 as_of=_T.isoformat()).json()
    assert body["assessment"]["odds"]["validation"]["reasons"] == [REASON_PLAYOFF]


def test_a_hypothetical_qualification_matches_the_scheduled_match_at_the_same_moment(client):
    """The same six teams, the same moment, the same model: the same odds, whichever route builds the context."""
    match = _post(client, MATCH.format(match_key=QM1, action="assess"), {"side": "red", "strategy": _strategy(_RED)})
    hypo = _post(client, HYPO.format(action="assess"),
                 _hypothetical(side="red", strategy=_strategy(_RED), match_context="qualification"),
                 as_of=_T.isoformat())
    assert hypo.json()["assessment"]["odds"] == match.json()["assessment"]["odds"]


# --- refusals ------------------------------------------------------------------------------------------------------------


@pytest.mark.parametrize("match_key, code", [
    ("9966zzznosuch_qm1", "match_not_found"), (UNSCHEDULED, "match_not_scheduled"),
    (SHORT, "alliance_incomplete"), (NOLEVEL, "match_context_unknown"),
])
def test_match_context_refusals_are_declared(client, app, match_key, code):
    url = MATCH.format(match_key=match_key, action="assess")
    response = _post(client, url, {"side": "red", "strategy": _strategy(_RED)})
    assert_declared_error(app.openapi(), response, "POST", MATCH.format(match_key="{match_key}", action="assess"),
                          code=code)


def test_a_strategy_for_the_wrong_alliance_is_an_invalid_strategy(client, app):
    response = _post(client, MATCH.format(match_key=QM1, action="assess"), {"side": "red", "strategy": _strategy(_BLUE)})
    assert_declared_error(app.openapi(), response, "POST", MATCH.format(match_key="{match_key}", action="assess"),
                          code="invalid_strategy")


def test_a_malformed_strategy_is_a_validation_error(client, app):
    bad = {"robots": [{"team_number": _RED[0], "role": "defense"}, {"team_number": _RED[1]}, {"team_number": _RED[2]}]}
    response = _post(client, MATCH.format(match_key=QM1, action="assess"), {"side": "red", "strategy": bad})
    assert_declared_error(app.openapi(), response, "POST", MATCH.format(match_key="{match_key}", action="assess"),
                          code="validation_error")


@pytest.mark.parametrize("params, body, code", [
    ({"as_of": "2026-03-01"}, {}, "invalid_as_of"),
    ({"as_of": (datetime.now(timezone.utc) + timedelta(days=2)).isoformat()}, {}, "invalid_as_of"),
    ({}, {"event_key": "9966zzznosuch"}, "event_not_found"),
    ({}, {"red_team_numbers": [999999, *_RED[1:]]}, "team_not_found"),
])
def test_hypothetical_refusals_are_declared(client, app, params, body, code):
    request = {**_hypothetical(side="red", strategy=_strategy(_RED), match_context="qualification"), **body}
    response = client.post(HYPO.format(action="assess"), json=request, params=params or None)
    assert_declared_error(app.openapi(), response, "POST", HYPO.format(action="assess"), code=code)


def test_model_not_loaded_and_epa_source_not_loaded_are_declared(app):
    url, path = MATCH.format(match_key=QM1, action="assess"), MATCH.format(match_key="{match_key}", action="assess")
    app.dependency_overrides[get_strategy_model] = lambda: None
    with TestClient(app) as client:
        assert_declared_error(app.openapi(), _post(client, url, {"side": "red", "strategy": _strategy(_RED)}),
                              "POST", path, code="model_not_loaded")
    app.dependency_overrides[get_strategy_model] = _model
    app.dependency_overrides[get_epa_source] = lambda: None
    with TestClient(app) as client:
        assert_declared_error(app.openapi(), _post(client, url, {"side": "red", "strategy": _strategy(_RED)}),
                              "POST", path, code="epa_source_not_loaded")


def test_mixed_season_scales_are_a_declared_409_over_http(app, monkeypatch):
    """Through the route: a context whose six teams disagree on the scale is mixed_season_scale (409)."""
    from ml.strategy.outcome import MatchContext
    from ml.strategy.service import StrategyContext
    from tests.phase6_fixtures import team

    red = tuple(team(n, score_scale=20.0) for n in _RED)
    blue = (team(_BLUE[0], score_scale=25.0), *(team(n, score_scale=20.0) for n in _BLUE[1:]))
    found = StrategyContext(MatchContext(red, blue), QM1, _EVENT, _T, "qualification", "qualification", 0, 0)
    monkeypatch.setattr("api.routes.strategy.context_for_match", lambda *a, **k: found)
    with TestClient(app) as client:
        response = _post(client, MATCH.format(match_key=QM1, action="assess"), {"side": "red", "strategy": _strategy(_RED)})
    assert_declared_error(app.openapi(), response, "POST", MATCH.format(match_key="{match_key}", action="assess"),
                          code="mixed_season_scale")


def test_any_other_engine_value_error_is_a_500_not_a_client_error(app, monkeypatch):
    """Acceptance (4): only the typed refusals are 4xx; an unexpected ValueError inside the engine is a fault."""
    from ml.strategy.engine import StrategyEngine

    def broken(self, *args, **kwargs):
        raise ValueError("an internal fault")

    monkeypatch.setattr(StrategyEngine, "assess", broken)
    with TestClient(app, raise_server_exceptions=False) as client:
        response = _post(client, MATCH.format(match_key=QM1, action="assess"), {"side": "red", "strategy": _strategy(_RED)})
    assert response.status_code == 500 and response.json()["error"]["code"] == "internal_error"
    assert "internal fault" not in response.text


def test_mixed_season_scales_are_refused_only_where_the_engine_refuses():
    """Real features share one season scale, so this is checked on the service with synthetic features: a
    qualification context with every input present and two scales is mixed_season_scale; the same teams in a
    playoff context are the engine's own 200 answer, never a 4xx."""
    from ml.strategy.engine import StrategyEngine
    from ml.strategy.outcome import MatchContext
    from ml.strategy.representation import Strategy
    from ml.strategy.service import MixedSeasonScale, evaluate_typed
    from tests.phase6_fixtures import team

    red = (team(1, score_scale=20.0), team(2, score_scale=20.0), team(3, score_scale=20.0))
    blue = (team(4, score_scale=25.0), team(5, score_scale=20.0), team(6, score_scale=20.0))
    engine = StrategyEngine(_model())
    qualification = MatchContext(red, blue)
    with pytest.raises(MixedSeasonScale):
        evaluate_typed(qualification, lambda: engine.assess(qualification, "red", Strategy.baseline([1, 2, 3])))
    playoff = MatchContext(red, blue, comp_level="semifinal")
    result = evaluate_typed(playoff, lambda: engine.assess(playoff, "red", Strategy.baseline([1, 2, 3])))
    assert result.display_ours is None and REASON_PLAYOFF in result.evaluation.reasons


# --- coach writes (P7-Q10) ----------------------------------------------------------------------------------------------


def _raw_rows(database, object_type) -> int:
    with database.cursor() as c:
        c.execute("SELECT count(*) FROM raw_source_payloads WHERE source = 'coach_input' AND source_object_type = %s "
                  "AND payload_json->>'event_key' LIKE '9966zzz%%'", (object_type,))
        return c.fetchone()[0]


def test_a_coach_strategy_is_stored_raw_first_with_its_provenance(client, database):
    body = {"event_key": _EVENT, "match_key": QM1, "author": "coach", "strategy": _strategy(_RED)}
    response = client.post("/strategy/coach-strategies", json=body, headers={"X-StratAI-Write-Token": TOKEN})
    assert response.status_code == 201
    stored = response.json()
    assert stored["origin"] == "human_entered" and stored["author"] == "coach" and len(stored["strategy_sha256"]) == 64
    assert _raw_rows(database, "strategy") == 1


def test_a_rejected_coach_submission_stays_landed(client, app, database):
    bad = {"event_key": _EVENT, "author": "coach", "strategy": {"robots": []}}
    response = client.post("/strategy/coach-strategies", json=bad, headers={"X-StratAI-Write-Token": TOKEN})
    assert_declared_error(app.openapi(), response, "POST", "/strategy/coach-strategies", code="invalid_coach_input")
    assert _raw_rows(database, "strategy") == 1  # landed before validation, never applied


@pytest.mark.parametrize("headers, code", [({}, "write_not_authorized"),
                                           ({"X-StratAI-Write-Token": "wrong"}, "write_not_authorized")])
def test_coach_writes_need_the_token_and_store_nothing_without_it(client, app, database, headers, code):
    body = {"event_key": _EVENT, "author": "coach", "strategy": _strategy(_RED)}
    response = client.post("/strategy/coach-strategies", json=body, headers=headers)
    assert_declared_error(app.openapi(), response, "POST", "/strategy/coach-strategies", code=code)
    assert _raw_rows(database, "strategy") == 0


def test_coach_writes_fail_closed_without_a_configured_token(database):
    app = create_app(Settings(human_inputs_write_token=None))
    app.dependency_overrides[get_database] = lambda: database
    with TestClient(app) as client:
        response = client.post("/strategy/coach-observations", json={"event_key": _EVENT},
                               headers={"X-StratAI-Write-Token": TOKEN})
        assert_declared_error(app.openapi(), response, "POST", "/strategy/coach-observations", code="writes_disabled")
    assert _raw_rows(database, "observation") == 0


def test_a_non_object_body_is_a_validation_error_and_is_not_stored(client, app, database):
    response = client.post("/strategy/coach-observations", json=["not", "an", "object"],
                           headers={"X-StratAI-Write-Token": TOKEN})
    assert_declared_error(app.openapi(), response, "POST", "/strategy/coach-observations", code="validation_error")
    assert _raw_rows(database, "observation") == 0


# --- the model pin (P7-M5 (a)) ------------------------------------------------------------------------------------------


def test_the_pinned_model_is_loaded_with_the_recorded_gate_status(tmp_path, database):
    """Through the registry and load_registered_strategy_model: the served baseline reason is p6_m10_gate_failed,
    never the constructor's p6_m10_evaluation_not_recorded."""
    from ml.registry import model_file_sha256, register_model
    from ml.strategy.outcome import FEATURE_LIST

    model = ComponentOutcomeModel(FIXTURE_BETA, FIXTURE_SIGMA, fit_info={}, spec_sha256="0" * 64)
    register_model(model, registry_dir=tmp_path, model_type=MODEL_TYPE, model_version=MODEL_VERSION,
                   version_tag="test-v1", training_dataset_hash="synthetic", feature_list=list(FEATURE_LIST),
                   created_at=datetime.now(timezone.utc), provenance={"synthetic": True})
    settings = Settings(ml_registry_dir=str(tmp_path), ml_strategy_model_version_tag="test-v1",
                        ml_strategy_model_sha256=model_file_sha256(tmp_path, MODEL_TYPE, "test-v1"))
    app = create_app(settings)
    app.dependency_overrides[get_database] = lambda: database
    with TestClient(app) as client:
        body = _post(client, MATCH.format(match_key=QM1, action="assess"),
                     {"side": "red", "strategy": _strategy(_RED)}).json()
    assert body["assessment"]["odds"]["validation"]["reasons"] == [REASON_GATE_FAILED]
    assert body["model"]["model_version_tag"] == "test-v1" and body["model"]["model_sha256"] == settings.ml_strategy_model_sha256
    wrong = create_app(Settings(ml_registry_dir=str(tmp_path), ml_strategy_model_version_tag="test-v1",
                                ml_strategy_model_sha256="0" * 64))
    assert wrong.state.strategy_model is None  # a wrong sha256 is refused: model_not_loaded, never a substitute
    unpinned_sha = create_app(Settings(ml_registry_dir=str(tmp_path), ml_strategy_model_version_tag="test-v1"))
    assert unpinned_sha.state.strategy_model is None  # the sha256 is part of the pin: without it, nothing loads


def test_an_upcoming_match_is_evaluated_now_never_at_its_future_time(client, database):
    """P7-D6: a scheduled match still ahead is evaluated at min(now, scheduled_time); a coach observation dated
    between now and the match (observed_at is caller-asserted) is not applied."""
    upcoming = f"{_EVENT}_qm9"
    with database.cursor() as c:
        _match(c, upcoming, _EVENT, "qualification", datetime.now(timezone.utc) + timedelta(days=2), _RED, _BLUE)
    assert _observe(client, datetime.now(timezone.utc) + timedelta(hours=1)).status_code == 201
    body = _post(client, MATCH.format(match_key=upcoming, action="assess"),
                 {"side": "red", "strategy": _strategy(_RED)}).json()
    as_of = datetime.fromisoformat(body["context"]["as_of"].replace("Z", "+00:00"))
    assert as_of <= datetime.now(timezone.utc)
    assert body["context"]["coach_observations_applied"] == 0
