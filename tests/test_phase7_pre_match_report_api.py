"""P7-M7: pre-match report data -- traceability to the engines, explicit absences, and no look-ahead.

Real Postgres sentinel rows (namespace 9977), only on an isolated stratai_* database copy, with the reference
Statbotics EPA source, a synthetic P6-M10 model (tests/phase6_fixtures) and a stub M6/M7 model: no result here is
evidence about any real team or model.
"""

from __future__ import annotations

import ast
import inspect
from datetime import date, datetime, timedelta, timezone
from typing import Generator

import pytest
from fastapi.testclient import TestClient

from api import create_app
from api.dependencies import get_database, get_epa_source, get_strategy_model, get_win_prob_model
from data.config import Settings
from database.connection import Database, DatabaseConfig
from ml.strategy.outcome import SERVED_BASELINE_STATUS, ComponentOutcomeModel
from ml.views.pre_match_report import NOT_PRODUCED
from tests.phase6_fixtures import FIXTURE_BETA, FIXTURE_SIGMA
from tests.phase7_support import assert_declared_error, stub_served_model
from tests.test_live_epa import _isolated_db_name

pytestmark = pytest.mark.skipif(_isolated_db_name() is None, reason="needs an isolated stratai_* database copy")

_SEASON = 9977
_FILL, _PRIOR, _EVENT = "9977zzzfill", "9977zzzprior", "9977zzzevent"
_RED, _BLUE = [997701, 997702, 997703], [997704, 997705, 997706]
_TEAMS = [*_RED, *_BLUE]
_BARE = list(range(997711, 997717))  # six teams with no history at all (one test)
TOKEN = "test-write-token"
_T = datetime(2026, 3, 1, 10, tzinfo=timezone.utc)
QM1, QM2, SHORT, NOLEVEL, UNSCHEDULED, FUTURE, SF = (f"{_EVENT}_qm1", f"{_EVENT}_qm2", f"{_EVENT}_qm3",
                                                     f"{_EVENT}_qm4", f"{_EVENT}_qm5", f"{_EVENT}_qm6",
                                                     f"{_EVENT}_sf1m1")
REPORT = "/matches/{match_key}/pre-match-report"


@pytest.fixture(autouse=True)
def _reference_epa_source(monkeypatch):
    monkeypatch.setenv("EPA_SOURCE", "statbotics")


def _cleanup(db: Database) -> None:
    with db.cursor() as c:
        c.execute("DELETE FROM raw_source_payloads WHERE source = 'coach_input' AND payload_json->>'event_key' LIKE "
                  "'9977zzz%%'")
        c.execute("DELETE FROM scouting_observations WHERE event_key LIKE '9977zzz%%'")
        c.execute("DELETE FROM team_metrics WHERE event_key LIKE '9977zzz%%'")
        c.execute("DELETE FROM match_teams WHERE match_key LIKE '9977zzz%%'")
        c.execute("DELETE FROM matches WHERE event_key LIKE '9977zzz%%'")
        c.execute("DELETE FROM team_event_stats WHERE event_key LIKE '9977zzz%%'")
        c.execute("DELETE FROM teams WHERE team_number = ANY(%s)", (_TEAMS + _BARE,))
        c.execute("DELETE FROM events WHERE event_key LIKE '9977zzz%%'")


def _match(c, key, level, when, red, blue, scores=(None, None), event=_EVENT) -> None:
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
        start = datetime(2026, 1, 10, tzinfo=timezone.utc)  # filler: the causal season scale needs >= 200 scores
        c.executemany("INSERT INTO matches (match_key, event_key, season, competition_level, match_number, "
                      "scheduled_time, score_red, score_blue) VALUES (%s, %s, %s, 'qualification', %s, %s, %s, %s)",
                      [(f"{_FILL}_qm{i}", _FILL, _SEASON, i, start + timedelta(minutes=10 * i),
                        40 + (i * 7) % 50, 30 + (i * 11) % 45) for i in range(1, 111)])
        _match(c, f"{_PRIOR}_qm1", "qualification", datetime(2026, 2, 19, 10, tzinfo=timezone.utc), _RED, _BLUE,
               (60, 50), event=_PRIOR)
        for i, team in enumerate(_TEAMS):
            c.execute("INSERT INTO team_event_stats (team_number, event_key, season, epa_total, epa_auto, epa_teleop, "
                      "epa_endgame, matches_played) VALUES (%s, %s, %s, %s, %s, %s, %s, 1)",
                      (team, _PRIOR, _SEASON, 30 + 3 * i, 5 + i, 20 + 2 * i, 5.0))
        _match(c, QM1, "qualification", _T, _RED, _BLUE)
        _match(c, SHORT, "qualification", _T + timedelta(hours=1), _RED[:2], _BLUE)
        _match(c, NOLEVEL, None, _T + timedelta(hours=2), _RED, _BLUE)
        _match(c, UNSCHEDULED, "qualification", None, _RED, _BLUE)
        _match(c, FUTURE, "qualification", datetime.now(timezone.utc) + timedelta(days=2), _RED, _BLUE)
        _match(c, SF, "semifinal", _T + timedelta(hours=5), _RED, _BLUE)
    try:
        yield db
    finally:
        _cleanup(db)


def _strategy_model() -> ComponentOutcomeModel:
    return ComponentOutcomeModel(FIXTURE_BETA, FIXTURE_SIGMA, fit_info={}, spec_sha256="0" * 64,
                                 artifact_sha256="a" * 64).with_status(version_tag="test",
                                                                       baseline_status=SERVED_BASELINE_STATUS)


def _win_prob_model():
    return stub_served_model(predict_win_prob=lambda row: 0.62, model_type="win_prob_xgb_calibrated")


@pytest.fixture
def app(database):
    application = create_app(Settings(human_inputs_write_token=TOKEN))
    application.dependency_overrides[get_database] = lambda: database
    application.dependency_overrides[get_strategy_model] = _strategy_model
    application.dependency_overrides[get_win_prob_model] = _win_prob_model
    return application


@pytest.fixture
def client(app) -> Generator[TestClient, None, None]:
    with TestClient(app) as test_client:
        yield test_client


def _report(client, match_key=QM1, **params) -> dict:
    response = client.get(REPORT.format(match_key=match_key), params=params)
    assert response.status_code == 200, response.text
    return response.json()


# --- traceability ---------------------------------------------------------------------------------------------------


def test_a_past_match_is_reported_at_its_scheduled_time_with_every_part(client):
    body = _report(client)
    assert datetime.fromisoformat(body["as_of"]) == _T and body["as_of_source"] == "scheduled_time"
    assert body["red_team_numbers"] == _RED and body["blue_team_numbers"] == _BLUE
    assert [t["team_number"] for t in body["teams"]] == _TEAMS
    assert [t["alliance"] for t in body["teams"]] == ["red"] * 3 + ["blue"] * 3
    assert all(datetime.fromisoformat(t["strength"]["as_of"]) == _T for t in body["teams"])
    epa = body["teams"][0]["strength"]["epa"]
    assert {"auto", "teleop", "endgame"} <= set(epa) and epa["auto"]["value"] is not None  # EPA components
    assert [s["alliance"] for s in body["synergy"]] == ["red", "blue"]
    assert all(s["validation"]["status"] == "not_validated_against_outcomes" for s in body["synergy"])
    assert body["win_probability"]["value"]["validated_value"] == 0.6  # the display rule applied to 0.62
    assert [s["side"] for s in body["strategy"]["sides"]] == ["red", "blue"]
    assert body["strategy"]["absent_reason"] is None and body["strategy"]["model"]["model_sha256"] == "a" * 64


def test_the_win_probability_is_the_predictions_routes_value(client):
    report = _report(client)["win_probability"]["value"]
    route = client.get(f"/predictions/matches/{QM1}/win-probability").json()["win_probability"]
    assert report == route


def test_each_side_is_the_strategy_routes_recommendation(client):
    report = _report(client)["strategy"]
    for side in report["sides"]:
        route = client.post(f"/strategy/matches/{QM1}/recommend", json={"side": side["side"]}).json()
        assert side["recommended"] == route["recommended"] and side["baseline"] == route["baseline"]
        assert side["vs_baseline_label"] == route["vs_baseline_label"]
        assert side["unavailable_reasons"] == route["unavailable_reasons"]
        assert report["context"] == route["context"]


def test_the_strength_views_are_the_strength_routes_views(client):
    body = _report(client)
    for team in body["teams"]:
        route = client.get(f"/teams/{team['team_number']}/events/{_EVENT}/strength",
                           params={"as_of": _T.isoformat()}).json()
        ours, theirs = dict(team["strength"]), dict(route["strength"])
        assert datetime.fromisoformat(ours.pop("as_of")) == datetime.fromisoformat(theirs.pop("as_of"))  # one instant
        assert ours == theirs


def test_every_team_carries_the_interim_caveat_and_explicit_scouting_absence(client):
    for team in _report(client)["teams"]:
        assert team["validation"]["status"] == "descriptive"
        assert team["validation"]["reasons"][0].startswith("reliability_score_interim")
        for part in ("defense", "feeding"):
            score = team["strength"][part]["score"]
            assert score["value"] is None and score["absent_reason"].startswith("insufficient_data")


def test_every_unproduced_item_is_an_explicit_absence(client):
    items = _report(client)["not_produced"]
    assert set(items) == set(NOT_PRODUCED)
    assert all(v == {"value": None, "reason": "not_produced_by_any_engine", "semantics": NOT_PRODUCED[k]}
               for k, v in items.items())


# --- the moment -----------------------------------------------------------------------------------------------------


def test_an_earlier_as_of_is_the_moment(client):
    earlier = _T - timedelta(days=1)
    body = _report(client, as_of=earlier.isoformat())
    assert datetime.fromisoformat(body["as_of"]) == earlier and body["as_of_source"] == "requested"
    assert all(datetime.fromisoformat(t["strength"]["as_of"]) == earlier for t in body["teams"])
    assert datetime.fromisoformat(body["strategy"]["context"]["as_of"]) == earlier


def test_a_later_as_of_never_moves_past_the_match(client):
    body = _report(client, as_of=(_T + timedelta(days=30)).isoformat())
    assert datetime.fromisoformat(body["as_of"]) == _T and body["as_of_source"] == "scheduled_time"


def test_a_match_still_ahead_is_reported_now(client):
    body = _report(client, FUTURE)
    assert body["as_of_source"] == "now"
    assert datetime.fromisoformat(body["as_of"].replace("Z", "+00:00")) <= datetime.now(timezone.utc)


def test_later_matches_change_no_field(client, database):
    """No look-ahead (P7-Q12): results, a scored replay of the match itself and a later EPA row at this event,
    all landed after the report's moment, change nothing."""
    before = _report(client)
    with database.cursor() as c:
        c.execute("UPDATE matches SET score_red = 99, score_blue = 1 WHERE match_key = %s", (QM1,))
        _match(c, QM2, "qualification", _T + timedelta(minutes=30), _RED, _BLUE, (120, 10))
        for team in _TEAMS:
            c.execute("INSERT INTO team_event_stats (team_number, event_key, season, epa_total, epa_auto, epa_teleop, "
                      "epa_endgame, matches_played) VALUES (%s, %s, %s, 500, 100, 300, 100, 2)",
                      (team, _EVENT, _SEASON))
    after = _report(client)
    assert after == before


# --- absences -------------------------------------------------------------------------------------------------------


@pytest.mark.parametrize("missing", [get_strategy_model, get_win_prob_model])
def test_a_missing_model_drops_only_its_own_part(client, app, missing):
    app.dependency_overrides[missing] = lambda: None
    body = _report(client)
    win, strategy = body["win_probability"], body["strategy"]
    if missing is get_win_prob_model:
        assert win["value"] is None and win["absent_code"] == "model_not_loaded" and win["absent_reason"]
        assert len(strategy["sides"]) == 2 and strategy["absent_code"] is None
    else:
        assert strategy["sides"] == [] and strategy["absent_code"] == "model_not_loaded" and strategy["model"] is None
        assert win["value"] is not None and win["absent_code"] is None
    assert len(body["teams"]) == 6 and body["synergy"][0]["score"] is not None


def test_an_incomplete_alliance_drops_its_synergy_and_the_strategy(client):
    body = _report(client, SHORT)
    red, blue = body["synergy"]
    assert red["score"] is None and red["absent_code"] == "alliance_incomplete" and red["absent_reason"]
    assert blue["score"] is not None and blue["absent_code"] is None and blue["absent_reason"] is None
    assert body["strategy"]["absent_code"] == "alliance_incomplete"


def test_a_match_without_a_level_is_unspecified_and_has_no_strategy(client):
    body = _report(client, NOLEVEL)
    assert body["win_probability"]["probability_scope"] == "unspecified"
    assert body["win_probability"]["value"]["validated_value"] is None
    assert body["strategy"]["absent_code"] == "match_context_unknown"
    assert "no competition level" in body["strategy"]["absent_reason"]


def test_a_playoff_match_is_unvalidated_and_the_engine_gives_no_strategy_probability(client):
    body = _report(client, SF)
    assert body["win_probability"]["value"]["unvalidated_reason"] == "playoff_scope"
    assert all(s["recommended"] is None and "playoff_model_unavailable" in s["unavailable_reasons"]
               for s in body["strategy"]["sides"])


@pytest.mark.parametrize("match_key, params, code", [
    ("9977zzzevent_qm99", {}, "match_not_found"),
    (UNSCHEDULED, {}, "match_not_scheduled"),
    (QM1, {"as_of": (datetime.now(timezone.utc) + timedelta(days=1)).isoformat()}, "invalid_as_of"),
    (QM1, {"as_of": "yesterday"}, "invalid_as_of"),
])
def test_refusals_are_declared(client, app, match_key, params, code):
    response = client.get(REPORT.format(match_key=match_key), params=params)
    assert_declared_error(app.openapi(), response, "GET", REPORT, code=code)


def test_without_an_epa_source_the_report_refuses(client, app):
    app.dependency_overrides[get_epa_source] = lambda: None
    response = client.get(REPORT.format(match_key=QM1))
    assert_declared_error(app.openapi(), response, "GET", REPORT, code="epa_source_not_loaded")


# --- no generated text, no snapshot ---------------------------------------------------------------------------------


def test_the_report_modules_call_no_llm_and_never_read_the_metrics_snapshot():
    import api.routes.pre_match_report as route
    import ml.views.pre_match_report as view

    for module in (route, view):
        tree = ast.parse(inspect.getsource(module))
        imported = {n.module or "" for n in ast.walk(tree) if isinstance(n, ast.ImportFrom)} | {
            a.name for n in ast.walk(tree) if isinstance(n, ast.Import) for a in n.names}
        assert not any(name.split(".")[0] in {"anthropic", "openai", "httpx", "requests"} for name in imported)
        assert "data.metrics.read" not in imported and "look_up_team_metrics" not in inspect.getsource(module)


# --- review additions (P7-M7 bug hunt) ---------------------------------------------------------------------------------


def _observe(client, observed_at, team=_RED[0]):
    return client.post("/strategy/coach-observations", headers={"X-StratAI-Write-Token": TOKEN},
                       json={"event_key": _EVENT, "team_number": team, "kind": "robot_unavailable",
                             "observed_at": observed_at.isoformat(), "observer": "coach"})


def _scout(c, match_key, team, submitted_at, defense=4, scout="scout-a") -> None:
    c.execute("INSERT INTO scouting_observations (match_key, event_key, team_number, scout_identifier, "
              "defense_rating, feeding_rating, source, submitted_at) "
              "SELECT %s, event_key, %s, %s, %s, NULL, 'human_scout', %s FROM matches WHERE match_key = %s",
              (match_key, team, scout, defense, submitted_at, match_key))


def _insert_team_metrics(database, team: int) -> None:
    """A stored team_metrics snapshot row with values no point-in-time computation could give."""
    from data.metrics.schemas import DefenseFeedingProfile, ScoringProfile, TeamMetrics
    from tests.test_metrics_schema import _insert_metrics

    _insert_metrics(database, TeamMetrics(
        team_number=team, event_key=_EVENT, season=_SEASON, computed_at=datetime.now(timezone.utc),
        scoring=ScoringProfile(matches_scheduled=12, matches_used=10, average_score=999.0, score_stddev=1.0,
                               consistency_rating=99.0, reliability_score=99.0, good_day_count=10,
                               average_day_count=0, bad_day_count=0),
        defense_feeding=DefenseFeedingProfile(
            defense_score=5.0, defense_observation_count=9, defense_agreement=1.0, defense_insufficient_data=False,
            feeding_score=None, feeding_observation_count=0, feeding_agreement=None, feeding_insufficient_data=True,
            contributing_sources=["human_scout"])))


def test_nothing_landed_after_an_earlier_moment_changes_the_report(client, database):
    """No look-ahead at an earlier as_of. After the moment: a scored match between the moment and the match, a
    prior event that ends after the moment (with its own EPA), scouting observations submitted later, a coach
    observation stored later (back-dated), and a stored team_metrics snapshot row. None changes the report at the
    moment; the same data does change a report taken at the match (so the data is not inert)."""
    moment = _T - timedelta(hours=2)
    early = f"{_EVENT}_qm9"  # an event match before the moment, so later scouting of it is a real candidate
    with database.cursor() as c:
        _match(c, early, "qualification", moment - timedelta(hours=1), _RED, _BLUE, (55, 45))
    before = _report(client, as_of=moment.isoformat())
    at_match_before = _report(client)
    late, now = "9977zzzlate", datetime.now(timezone.utc)
    with database.cursor() as c:
        _match(c, f"{_EVENT}_qm8", "qualification", _T - timedelta(hours=1), _RED, _BLUE, (150, 5))
        c.execute("INSERT INTO events (event_key, season, name, end_date) VALUES (%s, %s, 'Late', %s)",
                  (late, _SEASON, _T.date()))
        _match(c, f"{late}_qm1", "qualification", moment + timedelta(minutes=30), _RED, _BLUE, (70, 60), event=late)
        for team in _TEAMS:
            c.execute("INSERT INTO team_event_stats (team_number, event_key, season, epa_total, epa_auto, epa_teleop, "
                      "epa_endgame, matches_played) VALUES (%s, %s, %s, 400, 80, 240, 80, 1)", (team, late, _SEASON))
        for scout in ("scout-a", "scout-b", "scout-c"):
            _scout(c, early, _RED[0], now, scout=scout)  # a match before the moment, submitted after it
    assert _observe(client, moment - timedelta(hours=1)).status_code == 201  # back-dated, stored now
    _insert_team_metrics(database, _RED[0])
    assert _report(client, as_of=moment.isoformat()) == before
    assert _report(client) != at_match_before


def test_scouting_present_before_the_moment_is_passed_through(client, database):
    early = f"{_EVENT}_qm9"
    with database.cursor() as c:
        _match(c, early, "qualification", _T - timedelta(hours=3), _RED, _BLUE, (55, 45))
        for scout, rating in (("scout-a", 4), ("scout-b", 2)):
            _scout(c, early, _RED[0], _T - timedelta(hours=2), defense=rating, scout=scout)
    team = _report(client)["teams"][0]
    assert team["team_number"] == _RED[0]
    defense = team["strength"]["defense"]
    assert defense["score"]["value"] == 3.0 and defense["score"]["n"] == 2  # the median of 4 and 2
    route = client.get(f"/teams/{_RED[0]}/events/{_EVENT}/strength", params={"as_of": _T.isoformat()}).json()
    assert defense == route["strength"]["defense"]


def test_a_mixed_season_scale_drops_only_the_strategy(client, monkeypatch):
    from ml.strategy.outcome import MatchContext
    from ml.strategy.service import StrategyContext
    from tests.phase6_fixtures import team

    red = tuple(team(n, score_scale=20.0) for n in _RED)
    blue = (team(_BLUE[0], score_scale=25.0), *(team(n, score_scale=20.0) for n in _BLUE[1:]))
    found = StrategyContext(MatchContext(red, blue), QM1, _EVENT, _T, "qualification", "qualification", 0, 0)
    monkeypatch.setattr("ml.views.pre_match_report.context_for_match", lambda *a, **k: found)
    body = _report(client)
    assert body["strategy"]["absent_code"] == "mixed_season_scale" and body["strategy"]["sides"] == []
    assert body["win_probability"]["value"] is not None and len(body["teams"]) == 6


def test_six_teams_without_any_feature_give_insufficient_features_not_an_error(client, database):
    bare = f"{_EVENT}_qm7"
    with database.cursor() as c:
        c.execute("INSERT INTO teams (team_number, name) VALUES " + ", ".join(["(%s, %s)"] * len(_BARE)),
                  [v for t in _BARE for v in (t, f"Bare {t}")])
        _match(c, bare, "qualification", _T, _BARE[:3], _BARE[3:])
    body = _report(client, bare)
    assert body["win_probability"]["value"] is None
    assert body["win_probability"]["absent_code"] == "insufficient_features"
    route = client.get(f"/predictions/matches/{bare}/win-probability")
    assert route.status_code == 422 and route.json()["error"]["code"] == "insufficient_features"


@pytest.mark.parametrize("pending, code", [(False, "epa_source_incomplete"), (True, "epa_source_pending")])
def test_epa_source_refusals_are_declared(client, app, monkeypatch, pending, code):
    from ml.ratings.live_epa import EpaSourcePendingError
    from ml.ratings.statbotics_primary import SilentFallbackError

    error = (EpaSourcePendingError if pending else SilentFallbackError)(_RED[0], _EVENT, _T, _PRIOR, "synthetic")

    def refuse(*args, **kwargs):
        raise error

    monkeypatch.setattr("ml.views.pre_match_report.build_match_feature_row", refuse)
    response = client.get(REPORT.format(match_key=QM1))
    assert_declared_error(app.openapi(), response, "GET", REPORT, code=code)


def test_an_upcoming_match_is_predicted_now_never_at_its_future_time(client):
    """P7-D6: the match win-probability route uses min(now, scheduled_time), as the report does."""
    body = client.get(f"/predictions/matches/{FUTURE}/win-probability").json()
    assert datetime.fromisoformat(body["as_of"].replace("Z", "+00:00")) <= datetime.now(timezone.utc)
