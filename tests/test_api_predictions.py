"""Phase 4 Milestone 12: ML prediction endpoints, end to end.

Real Postgres, real FastAPI TestClient against the real application from
create_app() -- the same integration style tests/test_metrics_api.py already
established. Two real models (RankingXGBModel, WinProbXGBModel) are fit on a
small synthetic training set and registered into a temporary registry
directory so the happy-path tests exercise the real registry-load-predict
pipeline end to end, not a stand-in -- but nothing here claims these are
Milestone 5/6's real, accepted models: that acceptance still needs
Statbotics (see .agent/phase4/PHASE_STATUS.md), and no result in this file
is used as evidence toward it. This file tests the API LAYER's own
correctness (wiring, error codes, response schemas), not model quality.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Generator

import psycopg
import pytest
from fastapi.testclient import TestClient

from api import create_app
from api.dependencies import get_database, get_ranking_model, get_win_prob_model
from api.routes.predictions import (
    AllianceSynergyResponse,
    TeamRankingResponse,
    WinProbabilityResponse,
)
from data.config import Settings
from database.connection import Database, DatabaseConfig
from ml.dataset.builder import LABEL_BLUE_WIN, LABEL_RED_WIN, TrainingRow
from ml.features.assembler import EPA_WITHHELD_NO_PRIOR_EVENT, TeamFeatures
from ml.models.ranking_xgb import FEATURE_NAMES as RANKING_FEATURE_NAMES
from ml.models.ranking_xgb import RankingXGBModel
from ml.models.win_prob import FEATURE_NAMES as WIN_PROB_FEATURE_NAMES
from ml.models.win_prob import WinProbXGBModel
from ml.registry import register_model

# Sentinel namespace 9997 -- confirmed unused by every other requires_db
# integration suite (9985-9999 are each owned by a different test module;
# see this file's own git history / RUNNING_NOTES for the survey).
_S_EVENT = "9997zzzpredapi"
_S_SEASON = 9997
_S_EVENT_UNKNOWN = "9997zzznosuchevent"

_MATCH_PRIOR = f"{_S_EVENT}_qm1"
_MATCH_PLAYED = f"{_S_EVENT}_qm2"
_MATCH_UNPLAYED = f"{_S_EVENT}_qm3"

# Red/blue in the one played match -- real scores, so these six teams have
# real average_score data (and are the ones used for happy-path/symmetry).
_TEAM_RED = [999701, 999702, 999703]
_TEAM_BLUE = [999704, 999705, 999706]
# Rostered only into the unplayed match -- zero real signal anywhere
# (no score, no scouting, no EPA) for the insufficient-features case.
_TEAM_EMPTY = [999707, 999708, 999709]
_TEAM_UNKNOWN = 999799  # never rostered at this event at all

_ALL_SENTINEL_TEAMS = _TEAM_RED + _TEAM_BLUE + _TEAM_EMPTY


def _database_available() -> bool:
    try:
        with psycopg.connect(str(Settings().database_url), connect_timeout=3):
            return True
    except Exception:
        return False


requires_db = pytest.mark.skipif(
    not _database_available(), reason="Requires a reachable PostgreSQL database via DATABASE_URL",
)

pytestmark = requires_db


def _cleanup(database: Database) -> None:
    with database.cursor() as cursor:
        cursor.execute(
            "DELETE FROM match_teams WHERE match_key IN (%s, %s, %s)", (_MATCH_PRIOR, _MATCH_PLAYED, _MATCH_UNPLAYED),
        )
        cursor.execute("DELETE FROM matches WHERE event_key = %s", (_S_EVENT,))
        cursor.execute("DELETE FROM teams WHERE team_number = ANY(%s::int[])", (_ALL_SENTINEL_TEAMS,))
        cursor.execute("DELETE FROM events WHERE event_key = %s", (_S_EVENT,))


@pytest.fixture
def database() -> Generator[Database, None, None]:
    from database.migrate import run_migrations

    settings = Settings()
    run_migrations(settings)
    db = Database(DatabaseConfig(settings.database_url))
    _cleanup(db)
    with db.cursor() as cursor:
        cursor.execute(
            "INSERT INTO events (event_key, season, name) VALUES (%s, %s, %s)",
            (_S_EVENT, _S_SEASON, "Sentinel Predictions API Event"),
        )
        cursor.execute(
            "INSERT INTO teams (team_number, name) VALUES " + ", ".join(["(%s, %s)"] * len(_ALL_SENTINEL_TEAMS)),
            [value for team in _ALL_SENTINEL_TEAMS for value in (team, f"Team {team}")],
        )
        # A prior, already-played match for the same six red/blue teams --
        # point-in-time correctness (ml.features.assembler) means a match's
        # OWN outcome never counts toward its own teams' average_score, so
        # _MATCH_PLAYED's teams need real history from an EARLIER match to
        # have any real feature data as of _MATCH_PLAYED's own scheduled_time.
        cursor.execute(
            "INSERT INTO matches (match_key, event_key, season, competition_level, match_number, "
            "scheduled_time, score_red, score_blue) VALUES (%s, %s, %s, 'qualification', 1, %s, 80, 50)",
            (_MATCH_PRIOR, _S_EVENT, _S_SEASON, datetime(2026, 3, 1, 8, 0, tzinfo=timezone.utc)),
        )
        cursor.execute(
            "INSERT INTO matches (match_key, event_key, season, competition_level, match_number, "
            "scheduled_time, score_red, score_blue) VALUES (%s, %s, %s, 'qualification', 2, %s, 90, 60)",
            (_MATCH_PLAYED, _S_EVENT, _S_SEASON, datetime(2026, 3, 1, 10, 0, tzinfo=timezone.utc)),
        )
        cursor.execute(
            "INSERT INTO matches (match_key, event_key, season, competition_level, match_number, "
            "scheduled_time, score_red, score_blue) VALUES (%s, %s, %s, 'qualification', 3, %s, NULL, NULL)",
            (_MATCH_UNPLAYED, _S_EVENT, _S_SEASON, datetime(2026, 3, 1, 12, 0, tzinfo=timezone.utc)),
        )
        for team in _TEAM_RED:
            cursor.execute(
                "INSERT INTO match_teams (match_key, team_number, alliance_color) VALUES (%s, %s, 'red'), (%s, %s, 'red')",
                (_MATCH_PRIOR, team, _MATCH_PLAYED, team),
            )
        for team in _TEAM_BLUE:
            cursor.execute(
                "INSERT INTO match_teams (match_key, team_number, alliance_color) VALUES (%s, %s, 'blue'), (%s, %s, 'blue')",
                (_MATCH_PRIOR, team, _MATCH_PLAYED, team),
            )
        for team in _TEAM_EMPTY:
            cursor.execute(
                "INSERT INTO match_teams (match_key, team_number, alliance_color) VALUES (%s, %s, 'red')",
                (_MATCH_UNPLAYED, team),
            )
    try:
        yield db
    finally:
        _cleanup(db)


def _synthetic_team(team_number: int) -> TeamFeatures:
    return TeamFeatures(
        team_number=team_number,
        epa_total_present=False, epa_auto_present=False, epa_teleop_present=False, epa_endgame_present=False,
        epa_source_event_key=None, epa_withheld_reason=EPA_WITHHELD_NO_PRIOR_EVENT,
        average_score=40.0, average_score_present=True,
        score_stddev_present=False, consistency_rating_present=False, reliability_score_present=False,
        matches_considered=3, matches_used=3,
        defense_score_present=False, defense_agreement_present=False, defense_observation_count=0,
        feeding_score_present=False, feeding_agreement_present=False, feeding_observation_count=0,
    )


def _synthetic_training_rows() -> list[TrainingRow]:
    """A tiny, purely-synthetic training set -- unrelated to the real DB
    fixture above -- used only so the two models registered below are
    genuinely fit (not stubs), matching every other model test's own
    "synthetic, clearly labeled" discipline in this codebase."""
    rows = []
    base_time = datetime(2026, 1, 1, tzinfo=timezone.utc)
    for i in range(20):
        red_teams = [_synthetic_team(1000 + i * 6 + j) for j in range(3)]
        blue_teams = [_synthetic_team(1000 + i * 6 + 3 + j) for j in range(3)]
        label = LABEL_RED_WIN if i % 2 == 0 else LABEL_BLUE_WIN
        score_red, score_blue = (100, 80) if label == LABEL_RED_WIN else (80, 100)
        rows.append(TrainingRow(
            match_key=f"9997zzzsynth_qm{i + 1}", event_key="9997zzzsynth", season=9997, comp_level="qualification",
            set_number=None, match_number=i + 1, scheduled_time=base_time + timedelta(hours=i), label=label,
            score_margin=score_red - score_blue, score_red=score_red, score_blue=score_blue,
            red_teams=red_teams, blue_teams=blue_teams,
            red_surrogate_team_numbers=[], blue_surrogate_team_numbers=[], dq_status_known=True,
        ))
    return rows


@pytest.fixture
def registry_dir(tmp_path: Path) -> Path:
    rows = _synthetic_training_rows()
    created_at = datetime.now(timezone.utc)

    ranking_model = RankingXGBModel(num_boost_round=10)
    ranking_model.fit(rows)
    register_model(
        ranking_model, registry_dir=tmp_path, model_type="ranking_xgb", model_version="1.0.0",
        version_tag="test-v1", training_dataset_hash="testhash", feature_list=list(RANKING_FEATURE_NAMES),
        created_at=created_at,
    )

    win_prob_model = WinProbXGBModel(num_boost_round=10)
    win_prob_model.fit(rows)
    register_model(
        win_prob_model, registry_dir=tmp_path, model_type="win_prob_xgb", model_version="1.0.0",
        version_tag="test-v1", training_dataset_hash="testhash", feature_list=list(WIN_PROB_FEATURE_NAMES),
        created_at=created_at,
    )
    return tmp_path


@pytest.fixture
def client(database: Database, registry_dir: Path) -> Generator[TestClient, None, None]:
    settings = Settings(
        ml_registry_dir=str(registry_dir), ml_ranking_model_version_tag="test-v1",
        ml_win_prob_model_version_tag="test-v1",
    )
    app = create_app(settings)
    app.dependency_overrides[get_database] = lambda: database
    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture
def client_no_models(database: Database, registry_dir: Path) -> Generator[TestClient, None, None]:
    """The real application, but with both ML model dependencies overridden
    to None -- exercises model_not_loaded without needing a second, empty
    registry directory."""
    settings = Settings(
        ml_registry_dir=str(registry_dir), ml_ranking_model_version_tag="test-v1",
        ml_win_prob_model_version_tag="test-v1",
    )
    app = create_app(settings)
    app.dependency_overrides[get_database] = lambda: database
    app.dependency_overrides[get_ranking_model] = lambda: None
    app.dependency_overrides[get_win_prob_model] = lambda: None
    with TestClient(app) as test_client:
        yield test_client


def assert_error_envelope(payload: Any, *, status: int, code: str) -> dict:
    assert isinstance(payload, dict), f"error body is not an object: {payload!r}"
    assert set(payload) == {"error"}
    error = payload["error"]
    assert error["code"] == code
    assert error["status"] == status
    assert isinstance(error["message"], str) and error["message"]
    assert isinstance(error["request_id"], str) and error["request_id"]
    return error


# ---------------------------------------------------------------------------
# Match-based win probability
# ---------------------------------------------------------------------------


def test_match_win_probability_happy_path(client: TestClient):
    response = client.get(f"/predictions/matches/{_MATCH_PLAYED}/win-probability")
    assert response.status_code == 200
    body = WinProbabilityResponse.model_validate(response.json())
    assert body.match_key == _MATCH_PLAYED
    assert body.event_key == _S_EVENT
    assert sorted(body.red_team_numbers) == sorted(_TEAM_RED)
    assert sorted(body.blue_team_numbers) == sorted(_TEAM_BLUE)
    assert 0.0 <= body.red_win_probability <= 1.0
    assert body.model_type == "win_prob_xgb"
    assert body.model_version == "1.0.0"
    assert body.model_version_tag == "test-v1"
    assert body.calibration_status == "uncalibrated"


def test_match_win_probability_unknown_match_returns_404(client: TestClient):
    response = client.get(f"/predictions/matches/{_S_EVENT}_qm999/win-probability")
    assert response.status_code == 404
    assert_error_envelope(response.json(), status=404, code="match_not_found")


def test_match_win_probability_model_not_loaded(client_no_models: TestClient):
    response = client_no_models.get(f"/predictions/matches/{_MATCH_PLAYED}/win-probability")
    assert response.status_code == 404
    assert_error_envelope(response.json(), status=404, code="model_not_loaded")


def test_match_win_probability_unplayed_match_is_insufficient_features(client: TestClient):
    """qm2 (_MATCH_UNPLAYED) has scheduled_time set but no score, and its own
    roster (_TEAM_EMPTY) has zero real feature data anywhere."""
    response = client.get(f"/predictions/matches/{_MATCH_UNPLAYED}/win-probability")
    assert response.status_code == 422
    assert_error_envelope(response.json(), status=422, code="insufficient_features")


# ---------------------------------------------------------------------------
# Ad-hoc alliance win probability
# ---------------------------------------------------------------------------


def test_win_probability_for_alliances_happy_path(client: TestClient):
    response = client.post(
        "/predictions/win-probability",
        json={"event_key": _S_EVENT, "red_team_numbers": _TEAM_RED, "blue_team_numbers": _TEAM_BLUE},
    )
    assert response.status_code == 200
    body = WinProbabilityResponse.model_validate(response.json())
    assert body.match_key is None
    assert 0.0 <= body.red_win_probability <= 1.0


def test_win_probability_symmetry_through_api(client: TestClient):
    """The milestone's own named test: swapping alliances flips the
    probability, exercised through the real HTTP endpoint (not just the
    model object directly, as ml.models.win_prob's own unit tests do)."""
    forward = client.post(
        "/predictions/win-probability",
        json={"event_key": _S_EVENT, "red_team_numbers": _TEAM_RED, "blue_team_numbers": _TEAM_BLUE},
    )
    swapped = client.post(
        "/predictions/win-probability",
        json={"event_key": _S_EVENT, "red_team_numbers": _TEAM_BLUE, "blue_team_numbers": _TEAM_RED},
    )
    assert forward.status_code == 200 and swapped.status_code == 200
    p_forward = forward.json()["red_win_probability"]
    p_swapped = swapped.json()["red_win_probability"]
    assert p_forward == pytest.approx(1.0 - p_swapped, abs=1e-9)


def test_win_probability_for_alliances_unknown_event_returns_404(client: TestClient):
    response = client.post(
        "/predictions/win-probability",
        json={"event_key": _S_EVENT_UNKNOWN, "red_team_numbers": _TEAM_RED, "blue_team_numbers": _TEAM_BLUE},
    )
    assert response.status_code == 404
    assert_error_envelope(response.json(), status=404, code="event_not_found")


def test_win_probability_for_alliances_unknown_team_returns_404(client: TestClient):
    response = client.post(
        "/predictions/win-probability",
        json={"event_key": _S_EVENT, "red_team_numbers": [_TEAM_UNKNOWN, *_TEAM_RED[1:]], "blue_team_numbers": _TEAM_BLUE},
    )
    assert response.status_code == 404
    assert_error_envelope(response.json(), status=404, code="team_not_found")


def test_win_probability_for_alliances_insufficient_features(client: TestClient):
    response = client.post(
        "/predictions/win-probability",
        json={"event_key": _S_EVENT, "red_team_numbers": _TEAM_EMPTY, "blue_team_numbers": _TEAM_EMPTY[::-1]},
    )
    # _TEAM_EMPTY appears on both sides here deliberately -- only its own
    # complete absence of data matters for this check, not the pairing.
    assert response.status_code == 422
    assert_error_envelope(response.json(), status=422, code="insufficient_features")


def test_win_probability_for_alliances_model_not_loaded(client_no_models: TestClient):
    response = client_no_models.post(
        "/predictions/win-probability",
        json={"event_key": _S_EVENT, "red_team_numbers": _TEAM_RED, "blue_team_numbers": _TEAM_BLUE},
    )
    assert response.status_code == 404
    assert_error_envelope(response.json(), status=404, code="model_not_loaded")


def test_win_probability_for_alliances_rejects_wrong_alliance_size(client: TestClient):
    response = client.post(
        "/predictions/win-probability",
        json={"event_key": _S_EVENT, "red_team_numbers": _TEAM_RED[:2], "blue_team_numbers": _TEAM_BLUE},
    )
    assert response.status_code == 422
    assert_error_envelope(response.json(), status=422, code="validation_error")


# ---------------------------------------------------------------------------
# Team ranking for an event
# ---------------------------------------------------------------------------


def test_event_team_ranking_happy_path(client: TestClient):
    response = client.get(f"/predictions/events/{_S_EVENT}/ranking")
    assert response.status_code == 200
    body = TeamRankingResponse.model_validate(response.json())
    assert body.event_key == _S_EVENT
    assert body.model_type == "ranking_xgb"
    assert body.model_version_tag == "test-v1"
    assert {entry.team_number for entry in body.rankings} == set(_ALL_SENTINEL_TEAMS)
    ratings = [entry.predicted_rating for entry in body.rankings]
    assert ratings == sorted(ratings, reverse=True)


def test_event_team_ranking_unknown_event_returns_404(client: TestClient):
    response = client.get(f"/predictions/events/{_S_EVENT_UNKNOWN}/ranking")
    assert response.status_code == 404
    assert_error_envelope(response.json(), status=404, code="event_not_found")


def test_event_team_ranking_model_not_loaded(client_no_models: TestClient):
    response = client_no_models.get(f"/predictions/events/{_S_EVENT}/ranking")
    assert response.status_code == 404
    assert_error_envelope(response.json(), status=404, code="model_not_loaded")


# ---------------------------------------------------------------------------
# Alliance synergy
# ---------------------------------------------------------------------------


def test_alliance_synergy_happy_path(client: TestClient):
    response = client.post("/predictions/alliance-synergy", json={"event_key": _S_EVENT, "team_numbers": _TEAM_RED})
    assert response.status_code == 200
    body = AllianceSynergyResponse.model_validate(response.json())
    assert body.event_key == _S_EVENT
    assert sorted(body.team_numbers) == sorted(_TEAM_RED)
    assert 0.0 <= body.confidence <= 1.0


def test_alliance_synergy_unknown_event_returns_404(client: TestClient):
    response = client.post(
        "/predictions/alliance-synergy", json={"event_key": _S_EVENT_UNKNOWN, "team_numbers": _TEAM_RED},
    )
    assert response.status_code == 404
    assert_error_envelope(response.json(), status=404, code="event_not_found")


def test_alliance_synergy_unknown_team_returns_404(client: TestClient):
    response = client.post(
        "/predictions/alliance-synergy",
        json={"event_key": _S_EVENT, "team_numbers": [_TEAM_UNKNOWN, *_TEAM_RED[1:]]},
    )
    assert response.status_code == 404
    assert_error_envelope(response.json(), status=404, code="team_not_found")


def test_alliance_synergy_has_no_model_not_loaded_case(client_no_models: TestClient):
    """alliance_synergy is a pure function -- overriding both model
    dependencies to None must not affect this endpoint at all."""
    response = client_no_models.post(
        "/predictions/alliance-synergy", json={"event_key": _S_EVENT, "team_numbers": _TEAM_RED},
    )
    assert response.status_code == 200
