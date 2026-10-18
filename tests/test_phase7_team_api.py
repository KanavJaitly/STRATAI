"""P7-M2: the team metrics and strength endpoints -- their locked contracts, declared errors, the metrics
validation block (P7-Q13) and point-in-time strength.

Real Postgres sentinel rows (namespace 9977), only on an isolated stratai_* database copy, with the reference
Statbotics EPA source. Synthetic data: no result here is evidence about any real team.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from typing import Generator

import pytest
from fastapi.testclient import TestClient

from api import create_app
from api.dependencies import get_database, get_epa_source
from data.config import Settings
from data.metrics.compute import compute_event_team_metrics
from data.metrics.read import get_team_metrics
from data.metrics.schemas import TeamMetrics
from data.metrics.submission import submit_human_scout_observation
from database.connection import Database, DatabaseConfig
from ml.views.strength import DEFINITION_PENDING, DESCRIPTIVE, INSUFFICIENT_OBSERVATIONS, NOT_VALIDATED
from ml.views.strength import RELIABILITY_INTERIM
from tests.phase7_support import assert_declared_error
from tests.test_live_epa import _isolated_db_name

_SEASON = 9977
_PRIOR, _EVENT = "9977zzzprior", "9977zzzevent"
_FULL, _THIN, _UNCOMPUTED, _ABSENT, _UNKNOWN = 997701, 997702, 997703, 997704, 997799
_OTHERS = [997705, 997706, 997707, 997708]
_TEAMS = [_FULL, _THIN, _UNCOMPUTED, _ABSENT, *_OTHERS]
_T0 = datetime(2026, 3, 1, 9, tzinfo=timezone.utc)
METRICS = "/teams/{team_number}/events/{event_key}/metrics"
STRENGTH = "/teams/{team_number}/events/{event_key}/strength"

pytestmark = pytest.mark.skipif(_isolated_db_name() is None, reason="needs an isolated stratai_* database copy")


@pytest.fixture(autouse=True)
def _reference_epa_source(monkeypatch):
    monkeypatch.setenv("EPA_SOURCE", "statbotics")


def _cleanup(db: Database) -> None:
    with db.cursor() as c:
        c.execute("DELETE FROM team_metrics WHERE event_key IN (%s, %s)", (_PRIOR, _EVENT))
        c.execute("DELETE FROM scouting_observations WHERE event_key = %s", (_EVENT,))
        c.execute("DELETE FROM raw_source_payloads WHERE source = 'human_scout' AND source_object_id LIKE %s",
                  (f"{_EVENT}%",))
        c.execute("DELETE FROM match_teams WHERE match_key LIKE '9977zzz%%'")
        c.execute("DELETE FROM matches WHERE event_key IN (%s, %s)", (_PRIOR, _EVENT))
        c.execute("DELETE FROM team_event_stats WHERE event_key IN (%s, %s)", (_PRIOR, _EVENT))
        c.execute("DELETE FROM pipeline_runs WHERE scope_key IN (%s, %s)", (_PRIOR, _EVENT))
        c.execute("DELETE FROM teams WHERE team_number = ANY(%s)", (_TEAMS,))
        c.execute("DELETE FROM events WHERE event_key IN (%s, %s)", (_PRIOR, _EVENT))


def _match(c, key, event, when, red, blue, scores) -> None:
    c.execute("INSERT INTO matches (match_key, event_key, season, competition_level, match_number, scheduled_time, "
              "score_red, score_blue) VALUES (%s, %s, %s, 'qualification', %s, %s, %s, %s)",
              (key, event, _SEASON, int(key.rsplit("qm", 1)[1]), when, *scores))
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
        c.execute("INSERT INTO events (event_key, season, name, end_date) VALUES (%s, %s, 'Prior', %s), "
                  "(%s, %s, 'Event', %s)", (_PRIOR, _SEASON, date(2026, 2, 20), _EVENT, _SEASON, date(2026, 3, 2)))
        c.execute("INSERT INTO teams (team_number, name) VALUES " + ", ".join(["(%s, %s)"] * len(_TEAMS)),
                  [v for t in _TEAMS for v in (t, f"Team {t}")])
        _match(c, "9977zzzprior_qm1", _PRIOR, datetime(2026, 2, 19, 10, tzinfo=timezone.utc),
               [_FULL, _THIN, _OTHERS[0]], [_OTHERS[1], _OTHERS[2], _OTHERS[3]], (40, 30))
        for team in (_FULL, _THIN, *_OTHERS):
            c.execute("INSERT INTO team_event_stats (team_number, event_key, season, epa_total, epa_auto, epa_teleop, "
                      "epa_endgame, matches_played) VALUES (%s, %s, %s, 20, 5, 10, 5, 1)", (team, _PRIOR, _SEASON))
        # _FULL plays qm1 (t0) and qm2 (t0+1h); _THIN plays qm1 only; _UNCOMPUTED plays qm2.
        _match(c, "9977zzzevent_qm1", _EVENT, _T0, [_FULL, _OTHERS[0], _OTHERS[1]], [_THIN, _OTHERS[2], _OTHERS[3]],
               (50, 30))
        _match(c, "9977zzzevent_qm2", _EVENT, _T0 + timedelta(hours=1), [_FULL, _OTHERS[0], _OTHERS[1]],
               [_UNCOMPUTED, _OTHERS[2], _OTHERS[3]], (70, 40))
    for scout, rating, match in (("alice", 4, "9977zzzevent_qm1"), ("bob", 3, "9977zzzevent_qm2")):
        submit_human_scout_observation({"match_key": match, "event_key": _EVENT, "team_number": _FULL,
                                        "scout_identifier": scout, "defense_rating": rating,
                                        "submitted_at": "2026-03-01T15:00:00Z"}, database=db)
    compute_event_team_metrics(_EVENT, database=db)
    with db.cursor() as c:
        c.execute("DELETE FROM team_metrics WHERE team_number = %s AND event_key = %s", (_UNCOMPUTED, _EVENT))
    try:
        yield db
    finally:
        _cleanup(db)


@pytest.fixture
def app(database):
    application = create_app(Settings())
    application.dependency_overrides[get_database] = lambda: database
    return application


@pytest.fixture
def client(app) -> Generator[TestClient, None, None]:
    with TestClient(app) as test_client:
        yield test_client


def _metrics(client, team, event=_EVENT):
    return client.get(METRICS.format(team_number=team, event_key=event))


def _strength(client, team, event=_EVENT, as_of=None):
    return client.get(STRENGTH.format(team_number=team, event_key=event), params={"as_of": as_of} if as_of else None)


# --- metrics: the validation block (P7-Q13) --------------------------------------------------------------------


def test_metrics_serve_the_stored_object_unchanged_plus_its_validation_block(client, database):
    body = _metrics(client, _FULL).json()
    stored = get_team_metrics(database, _FULL, _EVENT)
    assert TeamMetrics.model_validate({k: v for k, v in body.items() if k != "validation"}) == stored
    assert body["validation"] == {
        "scoring": {"status": DESCRIPTIVE, "reasons": [RELIABILITY_INTERIM], "evidence": None},
        "defense": {"status": DEFINITION_PENDING, "reasons": [], "evidence": None},       # 2 observations
        "feeding": {"status": NOT_VALIDATED, "reasons": [INSUFFICIENT_OBSERVATIONS], "evidence": None},
    }


def test_a_thin_team_is_labelled_insufficient_never_upgraded(client):
    response = _metrics(client, _THIN)
    assert response.status_code == 200  # thin is a 200 with its flags, never an error
    body = response.json()
    assert body["defense_feeding"]["defense_insufficient_data"] is True
    assert body["defense_feeding"]["feeding_insufficient_data"] is True
    assert body["scoring"]["score_stddev"] is None  # one match: undefined, null, never 0
    validation = body["validation"]
    assert validation["defense"] == {"status": DEFINITION_PENDING, "reasons": [INSUFFICIENT_OBSERVATIONS],
                                     "evidence": None}
    assert "validated" not in {part["status"] for part in validation.values()}


@pytest.mark.parametrize("team, event, code", [
    (_UNKNOWN, _EVENT, "team_not_found"),
    (_FULL, "9977zzznowhere", "event_not_found"),
    (_ABSENT, _EVENT, "team_did_not_attend"),
    (_UNCOMPUTED, _EVENT, "metrics_not_computed"),
])
def test_metrics_refusals_are_declared(client, app, team, event, code):
    response = _metrics(client, team, event)
    assert response.status_code == 404
    assert_declared_error(app.openapi(), response, "GET", METRICS, code=code)


@pytest.mark.parametrize("team", ["0", "abc"])
def test_metrics_validation_errors_are_declared(client, app, team):
    response = client.get(f"/teams/{team}/events/{_EVENT}/metrics")
    assert response.status_code == 422
    assert_declared_error(app.openapi(), response, "GET", METRICS, code="validation_error")


# --- strength: point in time, declared errors -------------------------------------------------------------------


def test_strength_is_point_in_time(client):
    """Before qm2 the view counts one match; after it, two. A later match never changes an earlier view."""
    before = _strength(client, _FULL, as_of=(_T0 + timedelta(minutes=30)).isoformat()).json()["strength"]
    after = _strength(client, _FULL, as_of=(_T0 + timedelta(hours=2)).isoformat()).json()["strength"]
    assert before["scoring"]["average_score"]["n"] == 1 and before["scoring"]["average_score"]["value"] == 50.0
    assert after["scoring"]["average_score"]["n"] == 2 and after["scoring"]["average_score"]["value"] == 60.0
    assert before["as_of"].startswith("2026-03-01T09:30")


def test_strength_keeps_its_labels(client):
    strength = _strength(client, _FULL, as_of=(_T0 + timedelta(hours=8)).isoformat()).json()["strength"]
    assert strength["defense"]["validation_status"] == DEFINITION_PENDING
    assert strength["feeding"]["validation_status"] == NOT_VALIDATED
    assert strength["scoring"]["validation_status"] == DESCRIPTIVE
    # Feeding has no observations: absent with its reason, never 0.
    assert strength["feeding"]["score"]["value"] is None
    assert strength["feeding"]["score"]["absent_reason"] == INSUFFICIENT_OBSERVATIONS


def test_strength_scouting_is_point_in_time(client):
    """Both observations are submitted at 15:00; a view before then sees none, a view after sees both."""
    early = _strength(client, _FULL, as_of=(_T0 + timedelta(hours=2)).isoformat()).json()["strength"]
    late = _strength(client, _FULL, as_of=(_T0 + timedelta(hours=8)).isoformat()).json()["strength"]
    assert early["defense"]["score"]["n"] == 0 and early["defense"]["score"]["value"] is None
    assert late["defense"]["score"]["n"] == 2 and late["defense"]["score"]["value"] is not None


@pytest.mark.parametrize("as_of", ["yesterday", "2026-03-01T10:00:00"])  # not ISO / no offset
def test_strength_invalid_as_of_is_declared(client, app, as_of):
    response = _strength(client, _FULL, as_of=as_of)
    assert_declared_error(app.openapi(), response, "GET", STRENGTH, code="invalid_as_of")


@pytest.mark.parametrize("team, event, code", [
    (_FULL, "9977zzznowhere", "event_not_found"),
    (_UNKNOWN, _EVENT, "team_not_found"),
])
def test_strength_not_found_is_declared(client, app, team, event, code):
    assert_declared_error(app.openapi(), _strength(client, team, event), "GET", STRENGTH, code=code)


def test_strength_without_an_epa_source_is_declared(app):
    app.dependency_overrides[get_epa_source] = lambda: None
    with TestClient(app) as client:
        assert_declared_error(app.openapi(), _strength(client, _FULL), "GET", STRENGTH, code="epa_source_not_loaded")


@pytest.mark.parametrize("pending, code", [(False, "epa_source_incomplete"), (True, "epa_source_pending")])
def test_strength_epa_source_refusals_are_declared(client, app, monkeypatch, pending, code):
    from ml.ratings.live_epa import EpaSourcePendingError
    from ml.ratings.statbotics_primary import SilentFallbackError

    error = (EpaSourcePendingError if pending else SilentFallbackError)(_FULL, _EVENT, _T0, _PRIOR, "missing_row")

    def refuse(*args, **kwargs):
        raise error

    monkeypatch.setattr("api.routes.strength.build_team_strength", refuse)
    assert_declared_error(app.openapi(), _strength(client, _FULL), "GET", STRENGTH, code=code)


def test_strength_team_zero_is_a_declared_validation_error(client, app):
    response = client.get(f"/teams/0/events/{_EVENT}/strength")
    assert_declared_error(app.openapi(), response, "GET", STRENGTH, code="validation_error")
