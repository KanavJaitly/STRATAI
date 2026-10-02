"""Phase 4 Milestone 12: ML prediction endpoints, end to end.

Real Postgres, real FastAPI TestClient against the real application from
create_app() -- the same integration style tests/test_metrics_api.py already
established. The two servable model types (RankingXGBModelV2 and
CalibratedWinProbModel, the D18 models of record) are fit on small synthetic
training sets and registered, with sha256 pins, into a temporary registry so the
happy-path tests exercise the real registry-load-predict pipeline end to end.
They are synthetic: no result here is evidence about model quality. This file
tests the API layer's own contract -- wiring, model identity, the M7-driven
gating of unvalidated probabilities, EPA provenance, error codes and schemas.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Generator

import psycopg
import pytest
from fastapi.testclient import TestClient

from api import create_app
from api.dependencies import get_database, get_epa_source, get_ranking_model, get_win_prob_model
from api.routes.predictions import (
    AllianceSynergyResponse,
    TeamRankingResponse,
    WinProbabilityResponse,
    display_probability,
)
from data.config import Settings
from database.connection import Database, DatabaseConfig
from ml.dataset.builder import LABEL_BLUE_WIN, LABEL_RED_WIN, TrainingRow
from ml.features.assembler import EPA_WITHHELD_NO_PRIOR_EVENT, TeamFeatures
from ml.models.calibrated_win_prob import CalibratedWinProbModel
from ml.models.ranking_xgb import FEATURE_NAMES as RANKING_FEATURE_NAMES
from ml.models.ranking_xgb import RankingXGBModel
from ml.models.ranking_xgb_v2 import FEATURE_NAMES_V2, RankingXGBModelV2
from ml.models.win_prob import FEATURE_NAMES as WIN_PROB_FEATURE_NAMES
from ml.registry import model_file_sha256, register_model
from scripts.ml_bias_audit import _synthetic_ranking_rows

# Sentinel namespace 9997 -- confirmed unused by every other requires_db
# integration suite (9985-9999 are each owned by a different test module;
# see this file's own git history / RUNNING_NOTES for the survey).
_S_EVENT = "9997zzzpredapi"
_S_SEASON = 9997
_S_EVENT_UNKNOWN = "9997zzznosuchevent"

_MATCH_PRIOR = f"{_S_EVENT}_qm1"
_MATCH_PLAYED = f"{_S_EVENT}_qm2"
_MATCH_UNPLAYED = f"{_S_EVENT}_qm3"
_MATCH_PLAYOFF = f"{_S_EVENT}_sf1m1"

# Red/blue in the one played match -- real scores, so these six teams have
# real average_score data (and are the ones used for happy-path/symmetry).
_TEAM_RED = [999701, 999702, 999703]
_TEAM_BLUE = [999704, 999705, 999706]
# Rostered only into the unplayed match -- zero real signal anywhere
# (no score, no scouting, no EPA) for the insufficient-features case.
_TEAM_EMPTY = [999707, 999708, 999709]
_TEAM_UNKNOWN = 999799  # never rostered at this event at all

_ALL_SENTINEL_TEAMS = _TEAM_RED + _TEAM_BLUE + _TEAM_EMPTY


@pytest.fixture(autouse=True)
def _statbotics_reference_epa_source(monkeypatch):
    """These tests exercise EPA selection over sentinel team_event_stats rows, i.e.
    the Statbotics reference source (ml.ratings.provider); production uses STRATAI."""
    monkeypatch.setenv("EPA_SOURCE", "statbotics")


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
            "DELETE FROM match_teams WHERE match_key IN (%s, %s, %s, %s)",
            (_MATCH_PRIOR, _MATCH_PLAYED, _MATCH_UNPLAYED, _MATCH_PLAYOFF),
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
        cursor.execute(
            "INSERT INTO matches (match_key, event_key, season, competition_level, set_number, match_number, "
            "scheduled_time, score_red, score_blue) VALUES (%s, %s, %s, 'semifinal', 1, 1, %s, NULL, NULL)",
            (_MATCH_PLAYOFF, _S_EVENT, _S_SEASON, datetime(2026, 3, 1, 14, 0, tzinfo=timezone.utc)),
        )
        for team in _TEAM_RED:
            cursor.execute(
                "INSERT INTO match_teams (match_key, team_number, alliance_color) VALUES "
                "(%s, %s, 'red'), (%s, %s, 'red'), (%s, %s, 'red')",
                (_MATCH_PRIOR, team, _MATCH_PLAYED, team, _MATCH_PLAYOFF, team),
            )
        for team in _TEAM_BLUE:
            cursor.execute(
                "INSERT INTO match_teams (match_key, team_number, alliance_color) VALUES "
                "(%s, %s, 'blue'), (%s, %s, 'blue'), (%s, %s, 'blue')",
                (_MATCH_PRIOR, team, _MATCH_PLAYED, team, _MATCH_PLAYOFF, team),
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
        average_auto_points_present=False, auto_points_matches_used=0,
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


_PROVENANCE = {"source_version": "synthetic-test", "evaluation_record": "none"}


@pytest.fixture
def registry_dir(tmp_path: Path) -> Path:
    created_at = datetime.now(timezone.utc)

    ranking_model = RankingXGBModelV2(num_boost_round=10)
    ranking_model.fit(_synthetic_ranking_rows(count=40))
    register_model(
        ranking_model, registry_dir=tmp_path, model_type="ranking_xgb_v2", model_version="2.0.0",
        version_tag="test-v1", training_dataset_hash="testhash", feature_list=list(FEATURE_NAMES_V2),
        created_at=created_at, provenance=_PROVENANCE,
    )

    win_prob_model = CalibratedWinProbModel()
    win_prob_model.fit(_synthetic_training_rows())
    register_model(
        win_prob_model, registry_dir=tmp_path, model_type="win_prob_xgb_calibrated", model_version="1.0.0",
        version_tag="test-v1", training_dataset_hash="testhash", feature_list=list(WIN_PROB_FEATURE_NAMES),
        created_at=created_at, provenance=_PROVENANCE,
    )
    return tmp_path


def _settings(registry_dir: Path, **overrides: Any) -> Settings:
    values = dict(
        ml_registry_dir=str(registry_dir),
        ml_ranking_model_version_tag="test-v1",
        ml_ranking_model_sha256=model_file_sha256(registry_dir, "ranking_xgb_v2", "test-v1"),
        ml_win_prob_model_version_tag="test-v1",
        ml_win_prob_model_sha256=model_file_sha256(registry_dir, "win_prob_xgb_calibrated", "test-v1"),
    )
    values.update(overrides)
    return Settings(**values)


@pytest.fixture
def client(database: Database, registry_dir: Path) -> Generator[TestClient, None, None]:
    app = create_app(_settings(registry_dir))
    app.dependency_overrides[get_database] = lambda: database
    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture
def client_no_models(database: Database, registry_dir: Path) -> Generator[TestClient, None, None]:
    """The real application, but with both ML model dependencies overridden
    to None -- exercises model_not_loaded without needing a second, empty
    registry directory."""
    app = create_app(_settings(registry_dir))
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
    assert body.probability_scope == "qualification"
    assert body.validation_status == "approximately_calibrated_qualification"
    assert body.red_win_probability is not None and body.unvalidated_red_win_probability is None
    assert 0.05 <= body.red_win_probability <= 0.95
    assert round(body.red_win_probability / 0.05, 9).is_integer()  # rounded, never a precise decimal
    assert body.model_type == "win_prob_xgb_calibrated"
    assert body.model_version == "1.0.0"
    assert body.model_version_tag == "test-v1"
    assert body.calibration_status == "m7_gate_failed"
    assert body.warning is None


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
    # no stated context: the model output is returned only as an explicitly unvalidated value
    assert body.probability_scope == "unspecified" and body.validation_status == "not_validated"
    assert body.red_win_probability is None and body.unvalidated_red_win_probability is not None
    assert body.warning


def test_win_probability_symmetry_through_api(client: TestClient):
    """The milestone's own named test: swapping alliances flips the
    probability, exercised through the real HTTP endpoint (not just the
    model object directly, as ml.models.win_prob's own unit tests do)."""
    forward = client.post(
        "/predictions/win-probability",
        json={"event_key": _S_EVENT, "red_team_numbers": _TEAM_RED, "blue_team_numbers": _TEAM_BLUE,
              "match_context": "qualification"},
    )
    swapped = client.post(
        "/predictions/win-probability",
        json={"event_key": _S_EVENT, "red_team_numbers": _TEAM_BLUE, "blue_team_numbers": _TEAM_RED,
              "match_context": "qualification"},
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
    assert body.model_type == "ranking_xgb_v2"
    assert body.model_version_tag == "test-v1"
    assert body.validation_status == "moderate_held_out"
    assert [entry.rank for entry in body.rankings] == list(range(1, len(body.rankings) + 1))
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
    assert body.validation_status == "not_validated_against_outcomes"


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


# ---------------------------------------------------------------------------
# D18 alignment (2026-10-02): served-model identity, M7-driven gating, EPA provenance
# ---------------------------------------------------------------------------


def test_playoff_match_probability_is_not_served_as_a_validated_statistic(client: TestClient):
    response = client.get(f"/predictions/matches/{_MATCH_PLAYOFF}/win-probability")
    assert response.status_code == 200
    body = WinProbabilityResponse.model_validate(response.json())
    assert body.competition_level == "semifinal" and body.probability_scope == "playoff"
    assert body.validation_status == "not_validated"
    assert body.red_win_probability is None
    assert body.unvalidated_red_win_probability is not None and "Not a validated probability" in body.warning


def test_adhoc_playoff_context_is_not_validated_and_qualification_context_is(client: TestClient):
    def post(context):
        return client.post("/predictions/win-probability", json={
            "event_key": _S_EVENT, "red_team_numbers": _TEAM_RED, "blue_team_numbers": _TEAM_BLUE,
            "match_context": context}).json()

    playoff, qualification = post("playoff"), post("qualification")
    assert playoff["red_win_probability"] is None and playoff["validation_status"] == "not_validated"
    assert qualification["red_win_probability"] is not None
    assert qualification["validation_status"] == "approximately_calibrated_qualification"


def test_served_model_identity_traces_to_the_registered_artifact(client: TestClient, registry_dir: Path):
    win = client.get(f"/predictions/matches/{_MATCH_PLAYED}/win-probability").json()["model"]
    assert win["model_type"] == "win_prob_xgb_calibrated"
    assert win["model_sha256"] == model_file_sha256(registry_dir, "win_prob_xgb_calibrated", "test-v1")
    assert win["training_dataset_hash"] == "testhash" and win["provenance"] == _PROVENANCE
    ranking = client.get(f"/predictions/events/{_S_EVENT}/ranking").json()["model"]
    assert ranking["model_type"] == "ranking_xgb_v2"
    assert ranking["model_sha256"] == model_file_sha256(registry_dir, "ranking_xgb_v2", "test-v1")


def test_responses_carry_epa_source_and_per_team_provenance(client: TestClient):
    body = client.get(f"/predictions/matches/{_MATCH_PLAYED}/win-probability").json()
    assert body["epa"]["epa_source"] == "statbotics"  # these sentinel tests use the reference source
    assert body["epa"]["evaluated_configuration"] is False  # only d18_statbotics_primary is the evaluated one
    assert {t["team_number"] for t in body["teams"]} == set(_TEAM_RED + _TEAM_BLUE)
    assert all(set(t) >= {"epa_value_source", "epa_source_event_key", "epa_withheld_reason"} for t in body["teams"])
    ranking = client.get(f"/predictions/events/{_S_EVENT}/ranking").json()
    assert all("epa_value_source" in entry for entry in ranking["rankings"])


def test_epa_source_not_loaded_is_a_distinct_code(database: Database, registry_dir: Path):
    app = create_app(_settings(registry_dir))
    app.dependency_overrides[get_database] = lambda: database
    app.dependency_overrides[get_epa_source] = lambda: None
    with TestClient(app) as test_client:
        for response in (test_client.get(f"/predictions/matches/{_MATCH_PLAYED}/win-probability"),
                         test_client.get(f"/predictions/events/{_S_EVENT}/ranking"),
                         test_client.post("/predictions/alliance-synergy",
                                          json={"event_key": _S_EVENT, "team_numbers": _TEAM_RED})):
            assert response.status_code == 404
            assert_error_envelope(response.json(), status=404, code="epa_source_not_loaded")


def test_superseded_m5_v1_is_never_served(database: Database, tmp_path: Path):
    """A registry holding only an M5 v1 artifact under the pinned tag serves nothing:
    the loader only ever looks up ranking_xgb_v2, so there is no fallback to v1."""
    v1 = RankingXGBModel(num_boost_round=5)
    v1.fit(_synthetic_training_rows())
    register_model(v1, registry_dir=tmp_path, model_type="ranking_xgb", model_version="1.0.0", version_tag="test-v1",
                   training_dataset_hash="testhash", feature_list=list(RANKING_FEATURE_NAMES),
                   created_at=datetime.now(timezone.utc))
    settings = Settings(ml_registry_dir=str(tmp_path), ml_ranking_model_version_tag="test-v1",
                        ml_ranking_model_sha256=model_file_sha256(tmp_path, "ranking_xgb", "test-v1"))
    app = create_app(settings)
    app.dependency_overrides[get_database] = lambda: database
    with TestClient(app) as test_client:
        response = test_client.get(f"/predictions/events/{_S_EVENT}/ranking")
    assert response.status_code == 404
    assert_error_envelope(response.json(), status=404, code="model_not_loaded")


def test_a_wrong_artifact_sha256_is_refused(database: Database, registry_dir: Path):
    app = create_app(_settings(registry_dir, ml_ranking_model_sha256="0" * 64))
    app.dependency_overrides[get_database] = lambda: database
    with TestClient(app) as test_client:
        response = test_client.get(f"/predictions/events/{_S_EVENT}/ranking")
    assert response.status_code == 404
    assert_error_envelope(response.json(), status=404, code="model_not_loaded")


@pytest.mark.parametrize(("probability", "shown"), [
    (0.5, 0.5), (0.524, 0.5), (0.526, 0.55), (0.474, 0.45), (0.476, 0.5), (0.61, 0.6), (0.99, 0.95), (0.001, 0.05), (1.0, 0.95)])
def test_display_probability_rounds_symmetrically_and_never_reads_as_certain(probability, shown):
    assert display_probability(probability) == shown
    assert display_probability(1.0 - probability) == pytest.approx(1.0 - shown, abs=1e-12)
