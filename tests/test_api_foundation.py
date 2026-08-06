"""Phase 3 Milestone 12: the API foundation.

The milestone's success criteria are that the app boots under uvicorn, the
health check returns 200, and an invalid route and a forced error both return
documented structured responses with no leaked internals. These tests pin all
four, plus the two properties the design depends on that would otherwise erode
silently:

  * **One error shape, no mix.** Every error path -- 404, 405, 422, a raised
    HTTPException, a 503 from readiness, and an uncaught exception -- is
    asserted against the same envelope by the same helper. FastAPI's defaults
    return {"detail": ...}; a single unhandled path reverting to that shape
    would be invisible without this.
  * **CORS headers survive a 500.** That only holds because CORSMiddleware is
    outermost and RequestLoggingMiddleware catches the exception inside it. Swap
    the two add_middleware calls in api/app.py and this suite fails.

The forced-error endpoints are registered on locally built apps *inside this
module*. The shipped application has no /_test_boom route, and
test_only_health_endpoints_are_exposed pins that.

Note on TestClient: the 500 tests use raise_server_exceptions=False, which makes
the client return the response an ordinary HTTP caller would receive rather than
re-raising the server-side exception into the test.
"""

from __future__ import annotations

from contextlib import contextmanager
from typing import Any, Generator, Iterator

import psycopg
import pytest
import uvicorn
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from api import create_app
from api.dependencies import get_database
from api.errors import INTERNAL_ERROR_MESSAGE, SERVICE_UNAVAILABLE_MESSAGE
from api.request_id import REQUEST_ID_HEADER
from data.config import Settings
from database.connection import Database, DatabaseConfig


ALLOWED_ORIGIN = "http://localhost:5173"
DISALLOWED_ORIGIN = "http://evil.example"

# Strings that must never appear in any response body. The first three are what
# a leaking 500 would expose; the last two are what a leaking readiness failure
# would expose.
LEAK_MARKERS = (
    "Traceback",
    "KeyError",
    "missing_column",
    "/home/",
    ".py",
    "password authentication failed",
    "db-primary",
)

# The message a stubbed database failure raises. Deliberately shaped like a real
# psycopg connection error, host and credentials included, so the no-leak
# assertions are testing against something that would actually matter.
DATABASE_FAILURE_MESSAGE = (
    'connection to server at "db-primary" (10.0.0.5), port 5432 failed: '
    'FATAL: password authentication failed for user "stratai"'
)


# ===========================================================================
# Fixtures and stubs. No database or network required by anything above the
# requires_db section at the bottom of this file.
# ===========================================================================


@pytest.fixture
def settings(monkeypatch) -> Settings:
    """Settings built from a controlled environment, per the house pattern."""
    monkeypatch.setenv("DATABASE_URL", "postgresql://user:pass@localhost:5432/testdb")
    monkeypatch.setenv("TBA_API_KEY", "test-key")
    monkeypatch.setenv("ENV", "development")
    monkeypatch.delenv("CORS_ORIGINS", raising=False)
    monkeypatch.delenv("API_PREFIX", raising=False)
    return Settings()


class StubCursor:
    """Minimal psycopg-cursor stand-in for the readiness check."""

    def __init__(self, failure: Exception | None) -> None:
        self._failure = failure
        self.executed: list[str] = []

    def execute(self, statement: str, params: Any = None) -> None:
        if self._failure is not None:
            raise self._failure
        self.executed.append(statement)

    def fetchone(self) -> tuple[int, ...]:
        return (1,)


class StubDatabase:
    """Database stand-in that records use and can be made to fail.

    Lets the readiness endpoint be tested in both directions with no PostgreSQL
    anywhere, and lets the liveness test prove /health performs no I/O.
    """

    def __init__(self, failure: Exception | None = None) -> None:
        self._failure = failure
        self.cursor_calls = 0
        self.last_cursor: StubCursor | None = None

    @contextmanager
    def cursor(self) -> Iterator[StubCursor]:
        self.cursor_calls += 1
        cursor = StubCursor(self._failure)
        self.last_cursor = cursor
        yield cursor


@contextmanager
def build_client(
    settings: Settings,
    *,
    database: StubDatabase | None = None,
    raise_server_exceptions: bool = True,
) -> Generator[tuple[TestClient, FastAPI], None, None]:
    """Build the real application with an optional stubbed database."""
    app = create_app(settings)
    if database is not None:
        app.dependency_overrides[get_database] = lambda: database
    with TestClient(app, raise_server_exceptions=raise_server_exceptions) as client:
        yield client, app


def add_failing_route(app: FastAPI) -> None:
    """Register the forced-error routes used by the 500 and detail tests.

    Test-only. These are never part of the shipped application.
    """

    @app.get("/_test_boom")
    def boom() -> dict[str, str]:  # pragma: no cover - raises by design
        raise KeyError("missing_column")

    @app.get("/_test_db_boom")
    def db_boom() -> dict[str, str]:  # pragma: no cover - raises by design
        raise psycopg.OperationalError(DATABASE_FAILURE_MESSAGE)

    @app.get("/_test_client_error")
    def client_error() -> dict[str, str]:  # pragma: no cover - raises by design
        raise HTTPException(status_code=404, detail="Team 9999 is not registered at 2026casj.")

    @app.get("/_test_server_error")
    def server_error() -> dict[str, str]:  # pragma: no cover - raises by design
        raise HTTPException(status_code=500, detail=DATABASE_FAILURE_MESSAGE)

    @app.get("/_test_validation/{team_number}")
    def validation(team_number: int) -> dict[str, int]:  # pragma: no cover - 422s by design
        return {"team_number": team_number}


def assert_error_envelope(payload: Any, *, status: int, code: str, has_details: bool = False) -> dict:
    """Assert a body is the documented error envelope and return its error object.

    Every error-path test in this module goes through this function. That is the
    point: if any handler drifts back to FastAPI's {"detail": ...} default, the
    assertion that fails is this one, in every affected test at once.
    """
    assert isinstance(payload, dict), f"error body is not an object: {payload!r}"
    assert set(payload) == {"error"}, f"error body has unexpected top-level keys: {sorted(payload)}"

    error = payload["error"]
    expected_keys = {"code", "message", "status", "request_id"}
    if has_details:
        expected_keys.add("details")
    assert set(error) == expected_keys, f"unexpected error keys: {sorted(error)}"

    assert error["code"] == code
    assert error["status"] == status
    assert isinstance(error["message"], str) and error["message"]
    assert isinstance(error["request_id"], str) and error["request_id"]
    if has_details:
        assert isinstance(error["details"], list) and error["details"]
        for detail in error["details"]:
            assert set(detail) == {"field", "message", "type"}, f"unexpected detail keys: {sorted(detail)}"
    return error


def assert_no_internals_leaked(response_text: str) -> None:
    """Assert no traceback, exception text, path, or DB error reached the client."""
    for marker in LEAK_MARKERS:
        assert marker not in response_text, f"response leaked {marker!r}: {response_text}"


# ===========================================================================
# The app boots.
# ===========================================================================


def test_create_app_returns_a_configured_application(settings: Settings):
    app = create_app(settings)
    assert isinstance(app, FastAPI)
    assert app.state.settings is settings
    assert isinstance(app.state.database, Database)
    # Starlette's debug mode renders tracebacks into responses. It must never be
    # on, and must never be derived from settings.env.
    assert app.debug is False


def test_create_app_succeeds_without_a_reachable_database(monkeypatch):
    """Constructing Database must not connect, or /health could never report a
    live process during an outage -- the exact moment it is most needed."""
    monkeypatch.setenv("DATABASE_URL", "postgresql://nobody:nothing@127.0.0.1:1/nonexistent")
    monkeypatch.setenv("TBA_API_KEY", "test-key")
    monkeypatch.setenv("ENV", "development")
    app = create_app(Settings())
    with TestClient(app) as client:
        assert client.get("/health").status_code == 200


def test_uvicorn_can_load_the_application(settings: Settings):
    """The milestone's 'boots under uvicorn' criterion, without binding a port.

    uvicorn.Config.load() is the step uvicorn.run performs before it serves;
    if the app were unloadable this is where it would fail.
    """
    config = uvicorn.Config(create_app(settings), host=settings.api_host, port=settings.api_port)
    config.load()
    assert config.loaded_app is not None


def test_module_entry_point_serves_the_configured_host_and_port(monkeypatch, settings: Settings):
    """`python -m api` must serve on the Settings-configured address."""
    import api.__main__ as entry_point

    captured: dict[str, Any] = {}

    def fake_run(app: Any, **kwargs: Any) -> None:
        captured["app"] = app
        captured.update(kwargs)

    monkeypatch.setattr(entry_point.uvicorn, "run", fake_run)
    entry_point.main()

    assert isinstance(captured["app"], FastAPI)
    assert captured["host"] == settings.api_host
    assert captured["port"] == settings.api_port


def test_exactly_the_intended_endpoints_are_exposed(settings: Settings):
    """The shipped application exposes these paths and nothing else.

    Originally Milestone 12's scope pin, asserting health and readiness were the
    only endpoints ("the metrics endpoint is Milestone 13"). Milestone 13 landed
    that endpoint, so the metrics path joins the list -- the pin doing exactly
    its job. It still guards the other direction, which has not changed: a
    test-only forced-error route (/_test_boom and friends, registered on locally
    built apps in this module) must never reach the shipped application.
    """
    app = create_app(settings)
    assert sorted(app.openapi()["paths"]) == [
        "/health",
        "/ready",
        "/teams/{team_number}/events/{event_key}/metrics",
    ]


# ===========================================================================
# Liveness and readiness.
# ===========================================================================


def test_health_returns_200_with_the_documented_shape(settings: Settings):
    with build_client(settings) as (client, _app):
        response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok", "env": "development"}


def test_health_performs_no_database_io(settings: Settings):
    """Liveness must stay usable while PostgreSQL is down, and cheap enough to
    poll aggressively -- which is why the database round-trip is on /ready."""
    database = StubDatabase(failure=AssertionError("/health must not touch the database"))
    with build_client(settings, database=database) as (client, _app):
        response = client.get("/health")

    assert response.status_code == 200
    assert database.cursor_calls == 0


def test_health_reports_the_configured_environment(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgresql://user:pass@localhost:5432/testdb")
    monkeypatch.setenv("TBA_API_KEY", "test-key")
    monkeypatch.setenv("ENV", "staging")
    with build_client(Settings()) as (client, _app):
        assert client.get("/health").json()["env"] == "staging"


def test_ready_returns_200_when_the_database_answers(settings: Settings):
    database = StubDatabase()
    with build_client(settings, database=database) as (client, _app):
        response = client.get("/ready")

    assert response.status_code == 200
    assert response.json() == {"status": "ready", "checks": {"database": "ok"}}
    assert database.cursor_calls == 1
    assert database.last_cursor is not None
    assert database.last_cursor.executed == ["SELECT 1"]


def test_ready_returns_503_in_the_error_envelope_when_the_database_is_unreachable(settings: Settings):
    database = StubDatabase(failure=psycopg.OperationalError(DATABASE_FAILURE_MESSAGE))
    with build_client(settings, database=database) as (client, _app):
        response = client.get("/ready")

    assert response.status_code == 503
    error = assert_error_envelope(response.json(), status=503, code="service_unavailable")
    assert error["message"] == SERVICE_UNAVAILABLE_MESSAGE
    # The psycopg message carries host, port, database and username. None of it
    # may reach the client.
    assert_no_internals_leaked(response.text)


def test_ready_logs_the_database_failure_it_refuses_to_return(settings: Settings, caplog):
    """The detail withheld from the client has to exist somewhere, or the
    operator is worse off than before."""
    database = StubDatabase(failure=psycopg.OperationalError(DATABASE_FAILURE_MESSAGE))
    with caplog.at_level("ERROR"):
        with build_client(settings, database=database) as (client, _app):
            client.get("/ready")

    assert "db-primary" in caplog.text
    assert "Readiness check failed" in caplog.text


# ===========================================================================
# The error envelope, across every path that can produce one.
# ===========================================================================


def test_unknown_route_returns_the_structured_404(settings: Settings):
    with build_client(settings) as (client, _app):
        response = client.get("/no/such/route")

    assert response.status_code == 404
    error = assert_error_envelope(response.json(), status=404, code="not_found")
    assert error["message"] == "The requested resource was not found."
    # FastAPI's default would be {"detail": "Not Found"}.
    assert "detail" not in response.json()
    assert_no_internals_leaked(response.text)


def test_wrong_method_returns_the_structured_405_and_keeps_the_allow_header(settings: Settings):
    with build_client(settings) as (client, _app):
        response = client.post("/health")

    assert response.status_code == 405
    assert_error_envelope(response.json(), status=405, code="method_not_allowed")
    # The protocol requires Allow on a 405; rendering our own body must not drop it.
    assert "allow" in {name.lower() for name in response.headers}


def test_validation_failure_returns_the_structured_422_with_sanitized_details(settings: Settings):
    with build_client(settings) as (client, app):
        add_failing_route(app)
        response = client.get("/_test_validation/not-a-number")

    assert response.status_code == 422
    error = assert_error_envelope(response.json(), status=422, code="validation_error", has_details=True)
    detail = error["details"][0]
    assert detail["field"] == "path.team_number"
    assert detail["type"] == "int_parsing"
    # pydantic's raw error also carries "input" (the caller's payload) and "ctx"
    # (arbitrary objects, including exception reprs from custom validators).
    # Only the three allow-listed keys are copied out.
    assert set(detail) == {"field", "message", "type"}


def test_deliberate_client_error_passes_its_detail_through(settings: Settings):
    """A developer-authored message below 500 is intentional and useful."""
    with build_client(settings) as (client, app):
        add_failing_route(app)
        response = client.get("/_test_client_error")

    assert response.status_code == 404
    error = assert_error_envelope(response.json(), status=404, code="not_found")
    assert error["message"] == "Team 9999 is not registered at 2026casj."


def test_deliberate_server_error_suppresses_its_detail(settings: Settings):
    """An HTTPException raised at 500 carries an operator's note, not a client's."""
    with build_client(settings) as (client, app):
        add_failing_route(app)
        response = client.get("/_test_server_error")

    assert response.status_code == 500
    error = assert_error_envelope(response.json(), status=500, code="internal_error")
    assert error["message"] == INTERNAL_ERROR_MESSAGE
    assert_no_internals_leaked(response.text)


def test_uncaught_exception_returns_the_structured_500_with_nothing_leaked(settings: Settings):
    """The milestone's forced-error criterion.

    raise_server_exceptions=False so the client sees what a real HTTP caller
    would receive instead of the exception being re-raised into the test.
    """
    with build_client(settings, raise_server_exceptions=False) as (client, app):
        add_failing_route(app)
        response = client.get("/_test_boom")

    assert response.status_code == 500
    error = assert_error_envelope(response.json(), status=500, code="internal_error")
    assert error["message"] == INTERNAL_ERROR_MESSAGE
    assert_no_internals_leaked(response.text)


def test_uncaught_database_exception_leaks_no_connection_details(settings: Settings):
    """A psycopg error escaping a future data route is the realistic leak risk:
    its text carries host, port, database name and username."""
    with build_client(settings, raise_server_exceptions=False) as (client, app):
        add_failing_route(app)
        response = client.get("/_test_db_boom")

    assert response.status_code == 500
    assert_error_envelope(response.json(), status=500, code="internal_error")
    assert_no_internals_leaked(response.text)


def test_uncaught_exception_is_logged_with_its_traceback(settings: Settings, caplog):
    """The other half of the split: withheld from the client, kept for the operator."""
    with caplog.at_level("ERROR"):
        with build_client(settings, raise_server_exceptions=False) as (client, app):
            add_failing_route(app)
            response = client.get("/_test_boom")

    request_id = response.json()["error"]["request_id"]
    assert "missing_column" in caplog.text
    assert "Traceback" in caplog.text
    # The id the client was given must be the one that finds the log line.
    assert request_id in caplog.text


def test_every_error_path_returns_the_same_envelope(settings: Settings):
    """Pins 'one shape, no mix' directly, rather than as a property of six
    separate tests that could each be updated in isolation."""
    database = StubDatabase(failure=psycopg.OperationalError(DATABASE_FAILURE_MESSAGE))
    with build_client(settings, database=database, raise_server_exceptions=False) as (client, app):
        add_failing_route(app)
        responses = [
            client.get("/no/such/route"),          # router 404
            client.post("/health"),                # router 405
            client.get("/_test_validation/xyz"),   # request validation 422
            client.get("/_test_client_error"),     # raised HTTPException, < 500
            client.get("/_test_server_error"),     # raised HTTPException, >= 500
            client.get("/_test_boom"),             # uncaught exception
            client.get("/ready"),                  # dependency failure 503
        ]

    for response in responses:
        payload = response.json()
        assert set(payload) == {"error"}, f"{response.url} returned a foreign shape: {payload}"
        error = payload["error"]
        assert {"code", "message", "status", "request_id"} <= set(error)
        assert set(error) <= {"code", "message", "status", "request_id", "details"}
        assert error["status"] == response.status_code
        # details is present only where there are field-level problems to report.
        assert ("details" in error) == (response.status_code == 422)


# ===========================================================================
# Request ids.
# ===========================================================================


def test_every_response_carries_a_request_id_header(settings: Settings):
    with build_client(settings) as (client, _app):
        response = client.get("/health")

    assert response.headers[REQUEST_ID_HEADER]


def test_a_well_formed_inbound_request_id_is_reused(settings: Settings):
    """So a trace started by a gateway or the frontend survives into our logs."""
    with build_client(settings) as (client, _app):
        response = client.get("/no/such/route", headers={REQUEST_ID_HEADER: "trace-abc123"})

    assert response.headers[REQUEST_ID_HEADER] == "trace-abc123"
    assert response.json()["error"]["request_id"] == "trace-abc123"


def test_a_malformed_inbound_request_id_is_replaced(settings: Settings):
    """The value is echoed into a header and a log line, so it is constrained
    rather than trusted: a newline would forge log lines or inject a header."""
    hostile = "abc\r\nX-Injected: yes"
    with build_client(settings) as (client, _app):
        response = client.get("/health", headers={REQUEST_ID_HEADER: hostile})

    assert response.headers[REQUEST_ID_HEADER] != hostile
    assert "X-Injected" not in response.headers
    assert response.headers[REQUEST_ID_HEADER].isalnum()


def test_request_completion_is_logged_without_bodies_or_query_strings(settings: Settings, caplog):
    """Milestone 7's submission path is gated by a per-event access code, and the
    routes that will carry it must not write it to disk on every request.

    Asserts against this application's own log records only. caplog captures
    every logger in the process, including httpx's client-side one, which does
    log the full URL -- that is the test harness talking, not StratAI.
    """
    with caplog.at_level("INFO"):
        with build_client(settings) as (client, _app):
            client.get("/health?access_code=super-secret")

    application_log = "\n".join(
        record.getMessage() for record in caplog.records if record.name.startswith("api.")
    )
    assert "GET /health -> 200" in application_log
    assert "super-secret" not in application_log


# ===========================================================================
# CORS.
# ===========================================================================


def test_preflight_from_an_allowed_origin_is_approved(settings: Settings):
    with build_client(settings) as (client, _app):
        response = client.options(
            "/health",
            headers={"Origin": ALLOWED_ORIGIN, "Access-Control-Request-Method": "GET"},
        )

    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == ALLOWED_ORIGIN
    assert "GET" in response.headers["access-control-allow-methods"]


def test_simple_request_from_an_allowed_origin_carries_cors_headers(settings: Settings):
    with build_client(settings) as (client, _app):
        response = client.get("/health", headers={"Origin": ALLOWED_ORIGIN})

    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == ALLOWED_ORIGIN
    # The frontend has to be able to read the id to report it in a bug.
    assert REQUEST_ID_HEADER.lower() in response.headers["access-control-expose-headers"].lower()


def test_an_unlisted_origin_is_not_granted_access(settings: Settings):
    with build_client(settings) as (client, _app):
        response = client.get("/health", headers={"Origin": DISALLOWED_ORIGIN})

    assert "access-control-allow-origin" not in response.headers


def test_credentials_are_not_allowed_while_there_is_no_auth(settings: Settings):
    with build_client(settings) as (client, _app):
        response = client.get("/health", headers={"Origin": ALLOWED_ORIGIN})

    assert "access-control-allow-credentials" not in response.headers


def test_cors_headers_are_present_on_a_500(settings: Settings):
    """The middleware-ordering assertion.

    This passes only because CORSMiddleware is outermost and the catch-all is
    inside it. Relying on Starlette's ServerErrorMiddleware instead would
    produce a 500 with no CORS headers, which a browser reports as an opaque
    network failure exactly when something is already broken. Swapping the two
    add_middleware calls in api/app.py fails this test.
    """
    with build_client(settings, raise_server_exceptions=False) as (client, app):
        add_failing_route(app)
        response = client.get("/_test_boom", headers={"Origin": ALLOWED_ORIGIN})

    assert response.status_code == 500
    assert response.headers["access-control-allow-origin"] == ALLOWED_ORIGIN


# ===========================================================================
# The API settings on the existing Settings object.
# ===========================================================================


def test_api_settings_have_safe_defaults(settings: Settings):
    # Loopback, not 0.0.0.0: a local run should not be exposed to the network.
    assert settings.api_host == "127.0.0.1"
    assert settings.api_port == 8000
    # Empty, so routes mount at the paths the milestone docs write them at.
    assert settings.api_prefix == ""
    assert settings.cors_origins == ["http://localhost:5173", "http://localhost:3000"]
    assert "*" not in settings.cors_origins


def test_cors_origins_parses_a_comma_separated_environment_variable(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgresql://user:pass@localhost:5432/testdb")
    monkeypatch.setenv("TBA_API_KEY", "test-key")
    monkeypatch.setenv("CORS_ORIGINS", "https://stratai.example, http://localhost:4000 ")
    assert Settings().cors_origins == ["https://stratai.example", "http://localhost:4000"]


def test_wildcard_cors_origin_is_rejected_in_production(monkeypatch):
    """Structural, not conventional: 'no allow-all in production' is enforced at
    the config boundary rather than left to reviewer memory."""
    monkeypatch.setenv("DATABASE_URL", "postgresql://user:pass@localhost:5432/testdb")
    monkeypatch.setenv("TBA_API_KEY", "test-key")
    monkeypatch.setenv("ENV", "production")
    monkeypatch.setenv("CORS_ORIGINS", "*")
    with pytest.raises(ValueError, match="production"):
        Settings()


def test_wildcard_cors_origin_is_permitted_in_development(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgresql://user:pass@localhost:5432/testdb")
    monkeypatch.setenv("TBA_API_KEY", "test-key")
    monkeypatch.setenv("ENV", "development")
    monkeypatch.setenv("CORS_ORIGINS", "*")
    assert Settings().cors_origins == ["*"]


@pytest.mark.parametrize(
    "raw, expected",
    [("", ""), ("/", ""), ("api/v1", "/api/v1"), ("/api/v1/", "/api/v1"), ("  /api  ", "/api")],
)
def test_api_prefix_is_normalized(monkeypatch, raw: str, expected: str):
    monkeypatch.setenv("DATABASE_URL", "postgresql://user:pass@localhost:5432/testdb")
    monkeypatch.setenv("TBA_API_KEY", "test-key")
    monkeypatch.setenv("API_PREFIX", raw)
    assert Settings().api_prefix == expected


def test_api_port_must_be_a_valid_port(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgresql://user:pass@localhost:5432/testdb")
    monkeypatch.setenv("TBA_API_KEY", "test-key")
    monkeypatch.setenv("API_PORT", "70000")
    with pytest.raises(ValueError):
        Settings()


# ===========================================================================
# Integration. Requires a reachable PostgreSQL.
# ===========================================================================


def _database_available() -> bool:
    try:
        with psycopg.connect(str(Settings().database_url), connect_timeout=3):
            return True
    except Exception:
        return False


requires_db = pytest.mark.skipif(
    not _database_available(), reason="Requires a reachable PostgreSQL database via DATABASE_URL",
)


@requires_db
def test_ready_reports_ready_against_a_real_database():
    """The stubbed readiness tests pin the handler's logic; this pins that
    SELECT 1 through the real Database helper actually works."""
    app = create_app(Settings())
    with TestClient(app) as client:
        response = client.get("/ready")

    assert response.status_code == 200
    assert response.json() == {"status": "ready", "checks": {"database": "ok"}}


@requires_db
def test_readiness_closes_the_connection_it_opens():
    """The readiness probe must not accumulate connections.

    database/connection.py has no pooling -- a deliberate, recorded backlog item
    -- so every probe opens a real connection. This asserts the check leaves
    nothing behind, which is what makes it safe to add before pooling exists.
    """
    settings = Settings()
    database = Database(DatabaseConfig(settings.database_url))

    def backend_connection_count() -> int:
        with database.cursor() as cursor:
            cursor.execute(
                "SELECT count(*) FROM pg_stat_activity WHERE datname = current_database()"
            )
            return cursor.fetchone()[0]

    app = create_app(settings)
    with TestClient(app) as client:
        before = backend_connection_count()
        for _ in range(5):
            assert client.get("/ready").status_code == 200
        after = backend_connection_count()

    assert after <= before, f"readiness leaked connections: {before} -> {after}"
