"""Phase 3 Milestone 13: the team metrics endpoint, end to end.

Real Postgres, in tests/test_metrics_pipeline.py's integration style: a seeded
sentinel event with teams shaped to produce each case, a `database` fixture
that cleans up before and after, and the API exercised through FastAPI's
TestClient against the real application from create_app().

Two deliberate choices about what is seeded and how:

  * **Metrics are produced by the real compute_event_team_metrics, not by
    hand-inserted team_metrics rows.** A hand-built row could be given any
    shape the test found convenient, including one the pipeline would never
    produce, which would make the happy-path assertion prove the endpoint can
    serve fiction. Running the real pipeline means the object the endpoint
    returns is one the system genuinely produces.
  * **The happy path is validated against the canonical model**, not
    shape-checked -- TeamMetrics.model_validate(response.json()) must succeed
    AND the result must equal the stored object. Milestone 1's validators are
    then what the response is judged against, so a serialization that drifted
    (a flattened sub-model, a dropped confidence field, a stringified float)
    fails here rather than in a frontend.

The four 404s all assert their distinct error code through the shared envelope
helper. One status, four codes is the design (see api/routes/metrics.py): a
client branches on the code because only metrics_not_computed is worth
retrying, and a status cannot say that.
"""

from __future__ import annotations

from typing import Any, Generator

import psycopg
import pytest
from fastapi.testclient import TestClient

from api import create_app
from api.dependencies import get_database
from data.config import Settings
from data.metrics.compute import compute_event_team_metrics
from data.metrics.read import (
    STATUS_EVENT_NOT_FOUND,
    STATUS_FOUND,
    STATUS_METRICS_NOT_COMPUTED,
    STATUS_TEAM_DID_NOT_ATTEND,
    STATUS_TEAM_NOT_FOUND,
    get_team_metrics,
    look_up_team_metrics,
)
from data.metrics.schemas import TeamMetrics
from data.metrics.submission import submit_human_scout_observation
from database.connection import Database, DatabaseConfig

# Sentinel namespace, distinct from every other module's (9990-9999 are taken
# by the existing integration suites; this module owns 9989).
_S_EVENT = "9989zzzapi"
_S_EVENT_UNKNOWN = "9989zzznosuchevent"
_S_MATCH_1 = f"{_S_EVENT}_qm1"
_S_MATCH_2 = f"{_S_EVENT}_qm2"

# Two played matches, two scouting observations -> every scoring field defined,
# defense sufficient. The happy path.
_S_TEAM_FULL = 998901
# One played match only, zero observations -> average_score set, every
# variance-derived field None, both tracks insufficient_data. Thin but real.
_S_TEAM_THIN = 998902
# Rostered at the event, but its team_metrics row is deleted before the request
# -> metrics_not_computed.
_S_TEAM_UNCOMPUTED = 998903
# Exists in teams, never rostered into a match at this event -> did_not_attend.
_S_TEAM_ABSENT = 998904
# Not in the teams table at all -> team_not_found.
_S_TEAM_UNKNOWN = 998999

_ALL_SENTINEL_TEAMS = [_S_TEAM_FULL, _S_TEAM_THIN, _S_TEAM_UNCOMPUTED, _S_TEAM_ABSENT]


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
            "DELETE FROM canonical_lineage WHERE entity_type = 'team_metrics' AND entity_key LIKE %s",
            (f"%{_S_EVENT}",),
        )
        cursor.execute("DELETE FROM data_quality_issues WHERE object_id LIKE %s", (f"%{_S_EVENT}%",))
        cursor.execute("DELETE FROM team_metrics WHERE event_key = %s", (_S_EVENT,))
        cursor.execute("DELETE FROM scouting_observations WHERE event_key = %s", (_S_EVENT,))
        cursor.execute(
            "DELETE FROM raw_source_payloads WHERE source = 'human_scout' AND source_object_id LIKE %s",
            (f"{_S_EVENT}%",),
        )
        cursor.execute("DELETE FROM match_teams WHERE match_key IN (%s, %s)", (_S_MATCH_1, _S_MATCH_2))
        cursor.execute("DELETE FROM matches WHERE event_key = %s", (_S_EVENT,))
        cursor.execute("DELETE FROM teams WHERE team_number = ANY(%s::int[])", (_ALL_SENTINEL_TEAMS,))
        cursor.execute("DELETE FROM events WHERE event_key = %s", (_S_EVENT,))
        cursor.execute("DELETE FROM pipeline_runs WHERE scope_key = %s", (_S_EVENT,))


@pytest.fixture
def database() -> Generator[Database, None, None]:
    """Seed the sentinel event and compute real metrics for it.

    Matches are inserted with plain SQL (this module asserts nothing about
    lineage, unlike test_metrics_pipeline.py), but the metrics themselves come
    from the real compute_event_team_metrics -- see the module docstring.
    """
    from database.migrate import run_migrations

    settings = Settings()
    run_migrations(settings)
    db = Database(DatabaseConfig(settings.database_url))
    _cleanup(db)
    with db.cursor() as cursor:
        cursor.execute(
            "INSERT INTO events (event_key, season, name) VALUES (%s, %s, %s)",
            (_S_EVENT, 9989, "Sentinel API Event"),
        )
        cursor.execute(
            "INSERT INTO teams (team_number, name) VALUES (%s, %s), (%s, %s), (%s, %s), (%s, %s)",
            (
                _S_TEAM_FULL, "Full Data",
                _S_TEAM_THIN, "Thin Data",
                _S_TEAM_UNCOMPUTED, "Uncomputed",
                _S_TEAM_ABSENT, "Never Attended",
            ),
        )
        for match_key, match_number, score_red, score_blue in (
            (_S_MATCH_1, 1, 50, 30),
            (_S_MATCH_2, 2, 70, 40),
        ):
            cursor.execute(
                "INSERT INTO matches (match_key, event_key, season, competition_level, match_number, "
                "score_red, score_blue) VALUES (%s, %s, 9989, 'qualification', %s, %s, %s)",
                (match_key, _S_EVENT, match_number, score_red, score_blue),
            )
        # _S_TEAM_FULL: red in both matches -> scores [50, 70].
        cursor.execute(
            "INSERT INTO match_teams (match_key, team_number, alliance_color) VALUES (%s, %s, 'red'), (%s, %s, 'red')",
            (_S_MATCH_1, _S_TEAM_FULL, _S_MATCH_2, _S_TEAM_FULL),
        )
        # _S_TEAM_THIN: blue in qm1 only -> scores [30].
        cursor.execute(
            "INSERT INTO match_teams (match_key, team_number, alliance_color) VALUES (%s, %s, 'blue')",
            (_S_MATCH_1, _S_TEAM_THIN),
        )
        # _S_TEAM_UNCOMPUTED: rostered, so it is not a did-not-attend case.
        cursor.execute(
            "INSERT INTO match_teams (match_key, team_number, alliance_color) VALUES (%s, %s, 'blue')",
            (_S_MATCH_2, _S_TEAM_UNCOMPUTED),
        )
        # _S_TEAM_ABSENT gets no match_teams row anywhere at this event.

    # Two observations for _S_TEAM_FULL, through the real submission path, so
    # its defense track is sufficient (MIN_OBSERVATIONS_FOR_SCORE = 2) and the
    # happy-path response carries real defense data rather than only nulls.
    for scout, defense_rating, match_key in (
        ("alice", 4, _S_MATCH_1),
        ("bob", 3, _S_MATCH_2),
    ):
        submit_human_scout_observation(
            {
                "match_key": match_key, "event_key": _S_EVENT, "team_number": _S_TEAM_FULL,
                "scout_identifier": scout, "defense_rating": defense_rating,
                "submitted_at": "2026-08-06T15:00:00Z",
            },
            database=db,
        )

    compute_event_team_metrics(_S_EVENT, database=db)

    # Now remove exactly one computed row, so that team is rostered-but-
    # uncomputed. Done after the pipeline rather than by withholding the team,
    # because withholding it would have made it a did-not-attend case instead
    # -- which is the very distinction this suite exists to pin.
    with db.cursor() as cursor:
        cursor.execute(
            "DELETE FROM team_metrics WHERE team_number = %s AND event_key = %s", (_S_TEAM_UNCOMPUTED, _S_EVENT)
        )

    try:
        yield db
    finally:
        _cleanup(db)


@pytest.fixture
def client(database: Database) -> Generator[TestClient, None, None]:
    """The real application, with its Database dependency pointed at the fixture."""
    app = create_app(Settings())
    app.dependency_overrides[get_database] = lambda: database
    with TestClient(app) as test_client:
        yield test_client


def metrics_url(team_number: int, event_key: str) -> str:
    return f"/teams/{team_number}/events/{event_key}/metrics"


def assert_error_envelope(payload: Any, *, status: int, code: str) -> dict:
    """Assert a body is M12's documented error envelope and return its error object.

    Deliberately a local copy of tests/test_api_foundation.py's helper rather
    than an import from it: importing a helper out of another test module
    couples two suites together, and this one needs to fail loudly if a
    metrics 404 ever drifts to FastAPI's {"detail": ...} default regardless of
    what happens to that file.
    """
    assert isinstance(payload, dict), f"error body is not an object: {payload!r}"
    assert set(payload) == {"error"}, f"error body has unexpected top-level keys: {sorted(payload)}"

    error = payload["error"]
    assert set(error) == {"code", "message", "status", "request_id"}, f"unexpected keys: {sorted(error)}"
    assert error["code"] == code
    assert error["status"] == status
    assert isinstance(error["message"], str) and error["message"]
    assert isinstance(error["request_id"], str) and error["request_id"]
    return error


# ---------------------------------------------------------------------------
# Happy path: the canonical model, validated as such.
# ---------------------------------------------------------------------------


def test_returns_the_complete_metrics_object(client: TestClient, database: Database):
    response = client.get(metrics_url(_S_TEAM_FULL, _S_EVENT))

    assert response.status_code == 200
    # The load-bearing assertion: the response validates against Milestone 1's
    # canonical model, and equals what is actually stored.
    served = TeamMetrics.model_validate(response.json())
    stored = get_team_metrics(database, _S_TEAM_FULL, _S_EVENT)
    assert stored is not None
    assert served == stored


def test_the_response_carries_every_definition_of_done_field(client: TestClient):
    """Phase 3's Definition of Done is a *complete* metrics object, so the
    response is checked field by field, not just for validity."""
    body = client.get(metrics_url(_S_TEAM_FULL, _S_EVENT)).json()

    assert set(body) == {"team_number", "event_key", "season", "computed_at", "scoring", "defense_feeding"}
    assert body["team_number"] == _S_TEAM_FULL
    assert body["event_key"] == _S_EVENT
    assert body["season"] == 9989

    # Nested, not flattened -- the two profiles are independent computations
    # with independent confidence signals, and the served shape says so.
    assert set(body["scoring"]) == {
        "matches_scheduled", "matches_used", "average_score", "score_stddev",
        "consistency_rating", "reliability_score",
        "good_day_count", "average_day_count", "bad_day_count",
    }
    assert set(body["defense_feeding"]) == {
        "defense_score", "defense_observation_count", "defense_agreement", "defense_insufficient_data",
        "feeding_score", "feeding_observation_count", "feeding_agreement", "feeding_insufficient_data",
        "contributing_sources",
    }


def test_the_served_scoring_values_are_the_hand_computed_ones(client: TestClient):
    """Pins that the endpoint serves the stored numbers, not something rounded,
    re-derived, or type-mangled on the way out."""
    scoring = client.get(metrics_url(_S_TEAM_FULL, _S_EVENT)).json()["scoring"]

    # Scores [50, 70] over two scheduled, both played.
    assert scoring["matches_scheduled"] == 2
    assert scoring["matches_used"] == 2
    assert scoring["average_score"] == 60.0
    assert scoring["score_stddev"] == 10.0
    assert scoring["reliability_score"] == 100.0
    assert isinstance(scoring["average_score"], float)


def test_the_served_defense_data_comes_from_scouting_observations(client: TestClient):
    """Two observations (4 and 3) -> a real, sufficient defense score; feeding
    was never scouted, so it stays insufficient in the same response."""
    defense_feeding = client.get(metrics_url(_S_TEAM_FULL, _S_EVENT)).json()["defense_feeding"]

    assert defense_feeding["defense_insufficient_data"] is False
    assert defense_feeding["defense_score"] == 3.5  # median of [3, 4]
    assert defense_feeding["defense_observation_count"] == 2
    assert defense_feeding["contributing_sources"] == ["human_scout"]

    assert defense_feeding["feeding_insufficient_data"] is True
    assert defense_feeding["feeding_score"] is None
    assert defense_feeding["feeding_observation_count"] == 0


def test_a_second_request_returns_an_identical_object(client: TestClient):
    """The read path has no side effects: nothing is computed, cached, or
    mutated by serving it, so two requests agree exactly -- including
    computed_at, which would move if the endpoint were recomputing."""
    first = client.get(metrics_url(_S_TEAM_FULL, _S_EVENT)).json()
    second = client.get(metrics_url(_S_TEAM_FULL, _S_EVENT)).json()
    assert first == second


def test_the_request_path_never_recomputes(client: TestClient, database: Database):
    """No pipeline run is recorded by a read.

    compute_event_team_metrics records a pipeline_runs row every time it runs,
    so the run count is a direct, external witness that the request path did
    not trigger a computation -- stronger than asserting the response looks
    unchanged.
    """
    def run_count() -> int:
        with database.cursor() as cursor:
            cursor.execute("SELECT COUNT(*) FROM pipeline_runs WHERE scope_key = %s", (_S_EVENT,))
            return cursor.fetchone()[0]

    before = run_count()
    for team in (_S_TEAM_FULL, _S_TEAM_THIN, _S_TEAM_UNCOMPUTED, _S_TEAM_ABSENT):
        client.get(metrics_url(team, _S_EVENT))
    assert run_count() == before


# ---------------------------------------------------------------------------
# Thin data: reported honestly, at 200, never as an error.
# ---------------------------------------------------------------------------


def test_a_thin_data_team_returns_the_full_object_not_an_error(client: TestClient):
    """One played match, zero observations. Low confidence is a fact about the
    team, reported in the object -- not a failure, and never filled in."""
    response = client.get(metrics_url(_S_TEAM_THIN, _S_EVENT))

    assert response.status_code == 200
    served = TeamMetrics.model_validate(response.json())

    # average_score survives a single match; everything variance-derived does not.
    assert served.scoring.matches_used == 1
    assert served.scoring.average_score == 30.0
    assert served.scoring.score_stddev is None
    assert served.scoring.consistency_rating is None
    assert served.scoring.reliability_score is None
    assert served.scoring.good_day_count is None
    assert served.scoring.average_day_count is None
    assert served.scoring.bad_day_count is None

    # Never scouted: insufficient on both tracks, with no score invented for
    # either, and no source claimed as having produced one.
    assert served.defense_feeding.defense_insufficient_data is True
    assert served.defense_feeding.defense_score is None
    assert served.defense_feeding.defense_agreement is None
    assert served.defense_feeding.feeding_insufficient_data is True
    assert served.defense_feeding.feeding_score is None
    assert served.defense_feeding.contributing_sources == []


def test_a_thin_data_team_reports_none_rather_than_a_zero(client: TestClient):
    """The distinction the whole metrics layer is built on: an unmeasured value
    is null, never a 0 standing in for 'unknown'. 0 is a real rating."""
    body = client.get(metrics_url(_S_TEAM_THIN, _S_EVENT)).json()

    assert body["scoring"]["score_stddev"] is None
    assert body["scoring"]["consistency_rating"] is None
    assert body["defense_feeding"]["defense_score"] is None
    assert body["defense_feeding"]["feeding_score"] is None


# ---------------------------------------------------------------------------
# The four 404s: one status, four distinct codes.
# ---------------------------------------------------------------------------


def test_unknown_team_returns_team_not_found(client: TestClient):
    response = client.get(metrics_url(_S_TEAM_UNKNOWN, _S_EVENT))

    assert response.status_code == 404
    error = assert_error_envelope(response.json(), status=404, code="team_not_found")
    assert str(_S_TEAM_UNKNOWN) in error["message"]


def test_unknown_event_returns_event_not_found(client: TestClient):
    response = client.get(metrics_url(_S_TEAM_FULL, _S_EVENT_UNKNOWN))

    assert response.status_code == 404
    error = assert_error_envelope(response.json(), status=404, code="event_not_found")
    assert _S_EVENT_UNKNOWN in error["message"]


def test_a_team_that_did_not_attend_is_distinct_from_uncomputed(client: TestClient):
    """A dead end, not a wait-and-retry state: this team exists and this event
    exists, but no compute run will ever produce this row."""
    response = client.get(metrics_url(_S_TEAM_ABSENT, _S_EVENT))

    assert response.status_code == 404
    error = assert_error_envelope(response.json(), status=404, code="team_did_not_attend")
    assert "rostered" in error["message"]


def test_uncomputed_metrics_are_distinct_from_every_not_found_case(client: TestClient):
    """Rostered at the event, so the metrics are genuinely pending rather than
    impossible. This is the one 404 a client should retry."""
    response = client.get(metrics_url(_S_TEAM_UNCOMPUTED, _S_EVENT))

    assert response.status_code == 404
    error = assert_error_envelope(response.json(), status=404, code="metrics_not_computed")
    assert "not been computed" in error["message"]


def test_the_four_not_found_codes_are_all_different(client: TestClient):
    """The design in one assertion: four reasons, four codes, one status.

    If any pair ever collapsed to a shared code -- which is what would happen
    if a route reverted to a plain HTTPException, since api.errors derives the
    code from the status by default -- a client could no longer tell a
    retryable pending state from a permanent dead end.
    """
    codes = {}
    for team, event in (
        (_S_TEAM_UNKNOWN, _S_EVENT),
        (_S_TEAM_FULL, _S_EVENT_UNKNOWN),
        (_S_TEAM_ABSENT, _S_EVENT),
        (_S_TEAM_UNCOMPUTED, _S_EVENT),
    ):
        response = client.get(metrics_url(team, event))
        assert response.status_code == 404
        codes[(team, event)] = response.json()["error"]["code"]

    assert len(set(codes.values())) == 4, codes
    assert set(codes.values()) == {
        "team_not_found", "event_not_found", "team_did_not_attend", "metrics_not_computed",
    }


def test_a_not_found_response_leaks_no_internals(client: TestClient):
    """The messages name the team and event the caller already supplied, and
    nothing else -- no SQL, no table names, no paths."""
    for team, event in ((_S_TEAM_UNKNOWN, _S_EVENT), (_S_TEAM_UNCOMPUTED, _S_EVENT)):
        text = client.get(metrics_url(team, event)).text
        for marker in ("SELECT", "team_metrics", "match_teams", "psycopg", "Traceback", "/home/", ".py"):
            assert marker not in text, f"response leaked {marker!r}: {text}"


# ---------------------------------------------------------------------------
# Request validation, and the envelope on a 422.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("team_number", ["0", "-5"])
def test_a_non_positive_team_number_is_a_validation_error_not_a_404(client: TestClient, team_number: str):
    """0 is not a missing team, it is not a team number -- matching
    TeamMetrics' own gt=0 bound rather than reporting it as not found."""
    response = client.get(metrics_url(team_number, _S_EVENT))  # type: ignore[arg-type]

    assert response.status_code == 422
    payload = response.json()
    assert set(payload) == {"error"}
    assert payload["error"]["code"] == "validation_error"
    assert payload["error"]["details"]


def test_a_non_numeric_team_number_is_a_validation_error(client: TestClient):
    response = client.get(metrics_url("not-a-number", _S_EVENT))  # type: ignore[arg-type]

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "validation_error"


# ---------------------------------------------------------------------------
# The reader itself, without HTTP in the way.
# ---------------------------------------------------------------------------


def test_look_up_reports_found_with_the_metrics(database: Database):
    lookup = look_up_team_metrics(database, _S_TEAM_FULL, _S_EVENT)
    assert lookup.status == STATUS_FOUND
    assert lookup.metrics is not None
    assert lookup.metrics.team_number == _S_TEAM_FULL


@pytest.mark.parametrize(
    "team_number, event_key, expected_status",
    [
        (_S_TEAM_UNKNOWN, _S_EVENT, STATUS_TEAM_NOT_FOUND),
        (_S_TEAM_FULL, _S_EVENT_UNKNOWN, STATUS_EVENT_NOT_FOUND),
        (_S_TEAM_ABSENT, _S_EVENT, STATUS_TEAM_DID_NOT_ATTEND),
        (_S_TEAM_UNCOMPUTED, _S_EVENT, STATUS_METRICS_NOT_COMPUTED),
    ],
)
def test_look_up_diagnoses_each_missing_case(
    database: Database, team_number: int, event_key: str, expected_status: str
):
    lookup = look_up_team_metrics(database, team_number, event_key)
    assert lookup.status == expected_status
    # metrics is non-None if and only if the status is found.
    assert lookup.metrics is None


def test_an_unknown_team_and_unknown_event_together_report_the_team_first(database: Database):
    """Both are wrong; the diagnosis is deterministic rather than dependent on
    which query happened to run first."""
    lookup = look_up_team_metrics(database, _S_TEAM_UNKNOWN, _S_EVENT_UNKNOWN)
    assert lookup.status == STATUS_TEAM_NOT_FOUND


def test_the_reader_reassembles_every_stored_column(database: Database):
    """The row -> model reassembly against the raw columns, so a future
    migration that reorders or adds a column cannot quietly shift the mapping.
    """
    metrics = get_team_metrics(database, _S_TEAM_FULL, _S_EVENT)
    assert metrics is not None

    with database.cursor() as cursor:
        cursor.execute(
            """
            SELECT season, computed_at, matches_scheduled, matches_used, average_score, score_stddev,
                   consistency_rating, reliability_score, good_day_count, average_day_count, bad_day_count,
                   defense_score, defense_observation_count, defense_agreement, defense_insufficient_data,
                   feeding_score, feeding_observation_count, feeding_agreement, feeding_insufficient_data,
                   contributing_sources
            FROM team_metrics WHERE team_number = %s AND event_key = %s
            """,
            (_S_TEAM_FULL, _S_EVENT),
        )
        row = cursor.fetchone()

    scoring, defense_feeding = metrics.scoring, metrics.defense_feeding
    assert row == (
        metrics.season, metrics.computed_at,
        scoring.matches_scheduled, scoring.matches_used, scoring.average_score, scoring.score_stddev,
        scoring.consistency_rating, scoring.reliability_score,
        scoring.good_day_count, scoring.average_day_count, scoring.bad_day_count,
        defense_feeding.defense_score, defense_feeding.defense_observation_count,
        defense_feeding.defense_agreement, defense_feeding.defense_insufficient_data,
        defense_feeding.feeding_score, defense_feeding.feeding_observation_count,
        defense_feeding.feeding_agreement, defense_feeding.feeding_insufficient_data,
        defense_feeding.contributing_sources,
    )


def test_the_reader_returns_floats_not_decimals(database: Database):
    """0008 chose DOUBLE PRECISION over NUMERIC specifically so reads need no
    Decimal conversion. If a future migration changed that, TeamMetrics would
    still validate (pydantic coerces Decimal to float) and this would catch it.
    """
    metrics = get_team_metrics(database, _S_TEAM_FULL, _S_EVENT)
    assert metrics is not None
    with database.cursor() as cursor:
        cursor.execute(
            "SELECT average_score, defense_score FROM team_metrics WHERE team_number = %s AND event_key = %s",
            (_S_TEAM_FULL, _S_EVENT),
        )
        average, defense = cursor.fetchone()
    assert isinstance(average, float)
    assert isinstance(defense, float)
