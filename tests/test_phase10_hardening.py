"""P10-M1: platform hardening (Phase 7 risks R6, R7, R10, R11, R16). Each test fails on the code before the fix.

No test here writes to a database. The statement-timeout test only runs `pg_sleep` on the isolated `stratai_test`.
"""

from __future__ import annotations

import asyncio
import hashlib
import time
from types import SimpleNamespace

import pytest
from fastapi import Request
from fastapi.testclient import TestClient

from api import create_app
from api.body_limit import CODE_PAYLOAD_TOO_LARGE, UPLOAD_MARGIN_BYTES, BodySizeLimitMiddleware
from data.config import Settings
from data.human_inputs import MAX_MANUAL_BYTES
from database.connection import DEFAULT_CONNECT_TIMEOUT_SECONDS, Database, DatabaseConfig

# --- R6: request-body size limit ------------------------------------------------------------------------------------


@pytest.fixture
def client():
    with TestClient(create_app(Settings(api_prefix="", max_request_body_bytes=64 * 1024))) as test_client:
        yield test_client


def test_a_declared_oversized_body_is_refused_with_413_in_the_envelope(client):
    response = client.post("/predictions/win-probability", content=b"{" + b" " * (65 * 1024) + b"}",
                           headers={"content-type": "application/json"})
    assert response.status_code == 413
    error = response.json()["error"]
    assert (error["code"], error["status"]) == (CODE_PAYLOAD_TOO_LARGE, 413)
    assert error["request_id"] == response.headers["x-request-id"]


def test_a_streamed_body_without_a_length_is_cut_off_once_it_passes_the_limit(client):
    def chunks():
        for _ in range(80):
            yield b" " * 1024
    response = client.post("/predictions/win-probability", content=chunks(),
                           headers={"content-type": "application/json"})
    assert response.status_code == 413 and response.json()["error"]["code"] == CODE_PAYLOAD_TOO_LARGE


def test_a_body_within_the_limit_reaches_the_route(client):
    response = client.post("/predictions/win-probability", json={"not": "a valid body"})
    assert response.status_code == 422  # the route's own validation, not the limit


def test_only_the_manual_upload_gets_the_manual_sized_limit():
    middleware = BodySizeLimitMiddleware(lambda *a: None, default_limit=1024, upload_limit=MAX_MANUAL_BYTES)
    assert middleware.limit_for("POST", "/human-inputs/game-manuals") == MAX_MANUAL_BYTES
    assert middleware.limit_for("POST", "/api/human-inputs/game-manuals/") == MAX_MANUAL_BYTES
    assert middleware.limit_for("GET", "/human-inputs/game-manuals") == 1024
    assert middleware.limit_for("POST", "/strategy/coach-observations") == 1024
    app = create_app(Settings(api_prefix=""))
    [limit] = [m for m in app.user_middleware if m.cls is BodySizeLimitMiddleware]
    assert limit.kwargs == {"default_limit": 1024 * 1024, "upload_limit": MAX_MANUAL_BYTES + UPLOAD_MARGIN_BYTES}


# --- R7: database timeouts and the EPA-source retry backoff ---------------------------------------------------------


def test_every_connection_has_a_connect_timeout_and_the_api_a_statement_timeout():
    assert DatabaseConfig("postgresql://x@h/d").connect_kwargs() == {"connect_timeout": DEFAULT_CONNECT_TIMEOUT_SECONDS}
    assert DatabaseConfig("postgresql://x@h/d", statement_timeout_ms=250).connect_kwargs() == {
        "connect_timeout": DEFAULT_CONNECT_TIMEOUT_SECONDS, "options": "-c statement_timeout=250"}
    app = create_app(Settings(api_prefix=""))
    config = app.state.database._config
    assert (config.connect_timeout, config.statement_timeout_ms) == (10, 60000)


def test_a_statement_over_the_timeout_is_cancelled(monkeypatch):
    import psycopg

    from tests.test_live_epa import _isolated_db_name

    if _isolated_db_name() is None:
        pytest.skip("needs the isolated stratai_test database")
    database = Database(DatabaseConfig(Settings().database_url, statement_timeout_ms=200))
    started = time.monotonic()
    with pytest.raises(psycopg.errors.QueryCanceled):
        with database.cursor() as cursor:
            cursor.execute("SELECT pg_sleep(5)")
    assert time.monotonic() - started < 3


def test_a_failed_epa_source_load_is_not_retried_on_every_request(monkeypatch):
    from api import dependencies

    calls: list[float] = []

    def failing_load(settings, database):
        calls.append(time.monotonic())
        return None

    monkeypatch.setattr(dependencies, "load_epa_source", failing_load)
    state = SimpleNamespace(epa_source=None, epa_source_lock=__import__("threading").Lock(), epa_source_failed_at=None,
                            settings=SimpleNamespace(epa_source_retry_seconds=30.0), database=None)
    request = SimpleNamespace(app=SimpleNamespace(state=state))
    for _ in range(5):
        assert dependencies.get_epa_source(request) is None
    assert len(calls) == 1  # one attempt, then the backoff
    state.epa_source_failed_at -= 31  # the window has passed
    assert dependencies.get_epa_source(request) is None
    assert len(calls) == 2


def test_a_successful_load_after_a_failure_clears_the_backoff(monkeypatch):
    from api import dependencies

    loaded = SimpleNamespace(log_stamp=None)
    monkeypatch.setattr(dependencies, "load_epa_source", lambda settings, database: loaded)
    state = SimpleNamespace(epa_source=None, epa_source_lock=__import__("threading").Lock(), epa_source_failed_at=0.0,
                            settings=SimpleNamespace(epa_source_retry_seconds=0.0), database=None)
    assert dependencies.get_epa_source(SimpleNamespace(app=SimpleNamespace(state=state))) is loaded
    assert state.epa_source_failed_at is None


# --- R10: the live-EPA snapshot record cache is bounded --------------------------------------------------------------


def test_the_live_epa_record_cache_keeps_only_the_most_recent_snapshots():
    from ml.ratings import live_epa

    reads: list[str] = []

    class Log:
        def entries(self):
            return []

        def records(self, snapshot_id):
            reads.append(snapshot_id)
            return {}

    instance = object.__new__(live_epa.LiveRetrieval)
    instance.log = Log()
    instance.reload()
    ids = [f"s{i}" for i in range(live_epa.MAX_CACHED_SNAPSHOTS + 5)]
    for snapshot_id in ids:
        instance._records_of(snapshot_id)
    assert len(instance._records) == live_epa.MAX_CACHED_SNAPSHOTS
    assert list(instance._records) == ids[-live_epa.MAX_CACHED_SNAPSHOTS:]
    instance._records_of(ids[-live_epa.MAX_CACHED_SNAPSHOTS])  # a hit: no re-read, and it becomes the most recent
    assert reads.count(ids[-live_epa.MAX_CACHED_SNAPSHOTS]) == 1
    assert list(instance._records)[-1] == ids[-live_epa.MAX_CACHED_SNAPSHOTS]


# --- R11: the human-input defects -----------------------------------------------------------------------------------


@pytest.mark.parametrize("filename", ["manual.pdf", 'a"b.pdf', "résumé 2026.pdf", "x\\y.pdf", "日本.pdf", ""])
def test_the_download_header_is_valid_for_any_filename(filename):
    """F1: a raw filename="..." made the download a 500 for a quote or a non-latin-1 name."""
    from urllib.parse import unquote

    from api.routes.human_inputs import content_disposition

    header = content_disposition(filename)
    header.encode("latin-1")  # Starlette encodes headers as latin-1: this raised before the fix
    ascii_part = header.split('filename="', 1)[1].split('"', 1)[0]
    assert '"' not in ascii_part and "\\" not in ascii_part
    assert unquote(header.split("filename*=UTF-8''", 1)[1]) == filename


def test_a_storage_integrity_error_names_no_server_path(tmp_path, caplog):
    """F7: the message reaches the client; the path only goes to the log."""
    from data import human_inputs as hi

    content = b"%PDF-1.7 synthetic"
    sha = hashlib.sha256(content).hexdigest()
    stored = tmp_path / "game_manuals" / "2099" / f"{sha}.pdf"
    stored.parent.mkdir(parents=True)
    stored.write_bytes(b"%PDF- different bytes")

    class Cursor:
        description = []

        def execute(self, *args):
            pass

        def fetchall(self):
            return []

    class FakeDatabase:
        def cursor(self):
            from contextlib import contextmanager

            @contextmanager
            def cm():
                yield Cursor()
            return cm()

    with pytest.raises(hi.HumanInputError) as raised:
        hi.store_manual(FakeDatabase(), tmp_path, season=2099, game_name="Synthetic", filename="m.pdf",
                        content=content, uploaded_by="P10 test")
    assert raised.value.code == "storage_integrity"
    assert str(tmp_path) not in str(raised.value) and "/" not in str(raised.value)
    assert str(stored) in caplog.text


def test_the_manual_upload_stores_off_the_event_loop(monkeypatch):
    """F2: the hashing, file write and database work ran on the event loop, blocking every other request."""
    from api.dependencies import get_database
    from api.routes import human_inputs as route

    seen: list[bool] = []

    def store(*args, **kwargs):
        try:
            asyncio.get_running_loop()
            seen.append(True)  # on the event loop
        except RuntimeError:
            seen.append(False)  # in a worker thread
        return {"id": 1, "storage_path": "x"}, True

    monkeypatch.setattr(route.hi, "store_manual", store)
    app = create_app(Settings(api_prefix=""))
    app.dependency_overrides[route.require_writer] = lambda: None
    app.dependency_overrides[get_database] = lambda: None
    with TestClient(app) as test_client:
        response = test_client.post("/human-inputs/game-manuals", content=b"%PDF-1.7",
                                    params={"season": 2099, "game_name": "g", "filename": "f.pdf", "uploaded_by": "u"},
                                    headers={"content-type": "application/pdf"})
    assert response.status_code == 201, response.text
    assert seen == [False]


# --- R16: the Phase 5 evidence hash holds on any checkout, and still catches a change --------------------------------


def test_the_evidence_hash_ignores_line_endings_but_not_content():
    from tests.test_phase5_contract import evidence_sha256

    crlf, lf = b'{\r\n "a": 1\r\n}\r\n', b'{\n "a": 1\n}\n'
    assert evidence_sha256(crlf) == evidence_sha256(lf) == hashlib.sha256(crlf).hexdigest()
    assert evidence_sha256(lf.replace(b"1", b"2")) != evidence_sha256(lf)


# --- review P10-R1 regressions --------------------------------------------------------------------------------------


async def _reads_its_own_body(request: Request):  # module level, so the annotation resolves for FastAPI
    return {"bytes": len(await request.body())}


def test_a_chunked_oversized_body_read_by_the_route_itself_is_a_413_not_a_500():
    """The manual upload reads its own body (`await request.body()`), which raised ClientDisconnect on the simulated
    disconnect: a 500. The minimal app reproduces that route shape with a small limit."""
    from fastapi import FastAPI

    from api.middleware import RequestLoggingMiddleware

    app = FastAPI()
    app.add_api_route("/human-inputs/game-manuals", _reads_its_own_body, methods=["POST"])
    app.add_middleware(BodySizeLimitMiddleware, default_limit=1024, upload_limit=4096)
    app.add_middleware(RequestLoggingMiddleware)

    def chunks():
        for _ in range(10):
            yield b"x" * 1024

    with TestClient(app) as test_client:
        refused = test_client.post("/human-inputs/game-manuals", content=chunks())
        accepted = test_client.post("/human-inputs/game-manuals", content=b"x" * 2048)
    assert refused.status_code == 413 and refused.json()["error"]["code"] == CODE_PAYLOAD_TOO_LARGE
    assert accepted.status_code == 200 and accepted.json() == {"bytes": 2048}


def _epa_state(retry: float):
    import threading

    return SimpleNamespace(epa_source=None, epa_source_lock=threading.Lock(), epa_source_failed_at=None,
                           epa_source_reload_failed_at=None, settings=SimpleNamespace(epa_source_retry_seconds=retry),
                           database=None)


def test_a_burst_queued_behind_one_failing_load_does_not_retry_it_one_by_one(monkeypatch):
    import threading

    from api import dependencies

    calls: list[float] = []
    start = threading.Barrier(10)

    def slow_failing_load(settings, database):
        calls.append(time.monotonic())
        time.sleep(0.2)  # the others queue on the lock meanwhile
        return None

    monkeypatch.setattr(dependencies, "load_epa_source", slow_failing_load)
    request = SimpleNamespace(app=SimpleNamespace(state=_epa_state(30.0)))

    def one():
        start.wait()
        dependencies.get_epa_source(request)

    threads = [threading.Thread(target=one) for _ in range(10)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=30)
    assert len(calls) == 1


def test_a_failed_reload_after_a_live_refresh_backs_off_and_keeps_serving_the_loaded_source(monkeypatch):
    from api import dependencies

    loaded = SimpleNamespace(log_stamp="old")
    calls: list[int] = []
    monkeypatch.setattr(dependencies, "live_log_stamp", lambda settings: "new")
    monkeypatch.setattr(dependencies, "load_epa_source", lambda settings, database: calls.append(1))
    state = _epa_state(30.0)
    state.epa_source = loaded
    request = SimpleNamespace(app=SimpleNamespace(state=state))
    for _ in range(5):
        assert dependencies.get_epa_source(request) is loaded
    assert len(calls) == 1


def test_the_live_epa_record_cache_is_safe_under_concurrent_lookups():
    import sys
    import threading

    from ml.ratings import live_epa

    class Log:
        def entries(self):
            return []

        def records(self, snapshot_id):
            return {("x", snapshot_id): snapshot_id}

    instance = object.__new__(live_epa.LiveRetrieval)
    instance.log = Log()
    instance.reload()
    errors: list[str] = []
    ids = [f"s{i}" for i in range(live_epa.MAX_CACHED_SNAPSHOTS + 4)]

    def hammer(seed: int) -> None:
        for i in range(3000):
            snapshot_id = ids[(i * 7 + seed) % len(ids)]
            try:
                assert instance._records_of(snapshot_id) == {("x", snapshot_id): snapshot_id}
            except Exception as exc:
                errors.append(type(exc).__name__)
                return

    previous = sys.getswitchinterval()
    sys.setswitchinterval(1e-6)  # force frequent thread switches (the reviewer reproduced 1,921 KeyErrors this way)
    try:
        threads = [threading.Thread(target=hammer, args=(seed,)) for seed in range(6)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=120)
    finally:
        sys.setswitchinterval(previous)
    assert errors == []
    assert len(instance._records) <= live_epa.MAX_CACHED_SNAPSHOTS


def test_the_statement_timeout_is_appended_to_options_already_in_the_url():
    config = DatabaseConfig("postgresql://u@h/d?options=-c%20search_path%3Dfoo", statement_timeout_ms=5)
    assert config.connect_kwargs()["options"] == "-c search_path=foo -c statement_timeout=5"


# --- P10-Q9: the 413 is declared where it is served ---------------------------------------------------------------


def test_the_413_is_declared_on_exactly_the_operations_that_take_a_body_and_matches_what_is_served(client):
    """P10-Q9 (approved 2026-10-21): every operation with a request body (and the raw-body manual upload) declares
    413 `payload_too_large`; no other operation does; and the served refusal carries that declared code."""
    openapi = client.app.openapi()
    declared, with_body = set(), set()
    for path, methods in openapi["paths"].items():
        for method, operation in methods.items():
            key = f"{method.upper()} {path}"
            if "requestBody" in operation or key == "POST /human-inputs/game-manuals":
                with_body.add(key)
            if "413" in operation["responses"]:
                declared.add(key)
                assert "`payload_too_large`" in operation["responses"]["413"]["description"], key
    assert declared == with_body and len(declared) == 20
    served = client.post("/predictions/win-probability", content=b"{" + b" " * (65 * 1024) + b"}",
                         headers={"content-type": "application/json"})
    assert served.status_code == 413 and served.json()["error"]["code"] == "payload_too_large"
    from api.errors import error_code_for_status

    assert error_code_for_status(413) == "payload_too_large"  # pinned: not derived from the Python version's phrase
