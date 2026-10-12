"""Game Manual Manager, season-ruleset entry, readiness and the historical explorer (2026-10-11).

Isolated database only (the test-database guard). Synthetic seasons 2099 (manuals) and 9984 (rulesets), cleaned before
and after. **SYNTHETIC fixtures:** the PDFs are generated test documents, never game manuals; the rulesets are test
fixtures, never approved rules. The explorer tests read the real 2023-2026 rows already in the isolated copy, and
never write them.
"""

from __future__ import annotations

import copy
import hashlib
import json
import re
from pathlib import Path
from typing import Generator

import pytest
from fastapi.testclient import TestClient

from api import create_app
from api.dependencies import get_database
from api.routes.human_inputs import WRITE_TOKEN_HEADER
from data import human_inputs as hi
from data import manual_processing as mp
from data.config import Settings
from database.connection import Database, DatabaseConfig
from tests.pdf_fixtures import make_pdf, manual_pages
from tests.phase6_bracket_fixtures import ruleset as synthetic_ruleset
from tests.test_live_epa import _isolated_db_name

pytestmark = pytest.mark.skipif(_isolated_db_name() is None, reason="needs an isolated stratai_* database copy")

SEASON, RULESET_SEASON = 2099, 9984
TOKEN = "synthetic-test-token"
ACTOR = "Test Person"


def _cleanup(db: Database) -> None:
    with db.cursor() as c:
        c.execute("DELETE FROM game_manuals WHERE season IN (%s, %s, %s)", (SEASON, SEASON - 1, RULESET_SEASON))
        c.execute("DELETE FROM season_rulesets WHERE season = %s", (RULESET_SEASON,))


@pytest.fixture
def database() -> Generator[Database, None, None]:
    from database.migrate import run_migrations

    settings = Settings()
    run_migrations(settings)
    db = Database(DatabaseConfig(settings.database_url))
    _cleanup(db)
    try:
        yield db
    finally:
        _cleanup(db)


@pytest.fixture
def store(tmp_path) -> Path:
    return tmp_path / "store"


@pytest.fixture
def client(database, store, tmp_path) -> Generator[TestClient, None, None]:
    app = create_app(Settings(human_inputs_write_token=TOKEN, artifact_store_dir=str(store),
                              ruleset_approval_record_dir=str(tmp_path / "records")))
    app.dependency_overrides[get_database] = lambda: database
    with TestClient(app) as test_client:
        yield test_client


def _w() -> dict:
    return {WRITE_TOKEN_HEADER: TOKEN}


def _upload(database, store, pages, season=SEASON) -> dict:
    row, _ = hi.store_manual(database, store, season=season, game_name="SYNTHETICA", filename="m.pdf",
                             content=make_pdf(pages), uploaded_by=ACTOR)
    return row


def _process(database, store, manual_id) -> dict:
    claimed = mp.start(database, store, manual_id, requested_by=ACTOR)
    return mp.run(database, store, manual_id, requested_by=ACTOR) if claimed["claimed"] else claimed


# --- the processing pipeline ---------------------------------------------------------------------------------------


def test_a_manual_is_processed_into_deterministic_write_once_artifacts(database, store):
    manual = _upload(database, store, manual_pages(SEASON))
    state = _process(database, store, manual["id"])
    assert state["status"] == "succeeded" and state["report"]["identity"]["decision"] == "identified"
    assert state["report"]["page_count"] == 6 and state["report"]["authoritative"] is False
    directory = mp.ledger_dir(store, manual["content_sha256"])
    extraction = (directory / "extraction.json").read_bytes()
    data = json.loads(extraction)
    assert {s["rule"] for s in data["suggestions"]} >= {"auto_seconds", "teleop_minutes", "alliance_count", "point_value",
                                                        "playoff_format"}
    assert all(s["status"] == "machine_extracted_unverified" and s["page"] >= 1 for s in data["suggestions"])
    assert [s["number"] for s in data["sections"]][:2] == ["5", "5.1"]
    again = mp.start(database, store, manual["id"], requested_by=ACTOR)  # idempotent: never redone
    assert again["claimed"] is False and again["status"] == "succeeded"
    assert (directory / "extraction.json").read_bytes() == extraction and [x["attempt"] for x in again["attempts"]] == [1]


def test_the_extraction_is_reproducible_byte_for_byte(database, store, tmp_path):
    manual = _upload(database, store, manual_pages(SEASON))
    _process(database, store, manual["id"])
    first = (mp.ledger_dir(store, manual["content_sha256"]) / "extraction.json").read_bytes()
    other = tmp_path / "other-store"
    _, content = hi.manual_file(database, manual["id"])
    (other / "manual_processing").mkdir(parents=True)
    directory = mp.ledger_dir(other, manual["content_sha256"])
    assert mp._process(manual, content, directory) == "succeeded"
    assert (directory / "extraction.json").read_bytes() == first


def test_a_manual_naming_another_season_fails_closed(database, store):
    manual = _upload(database, store, manual_pages(SEASON - 1))  # the PDF says 2098; uploaded as 2099
    state = _process(database, store, manual["id"])
    assert state["status"] == "failed" and state["attempts"][-1]["error"]["code"] == "wrong_season"
    assert state["report"] is None
    with pytest.raises(mp.ManualProcessingError) as e:
        mp.resolve_identity(database, store, manual["id"], season=SEASON, resolved_by=ACTOR, note="looks right")
    assert e.value.code == "invalid_state"  # a contradiction is never resolved by acknowledgement


def test_an_unidentifiable_season_needs_a_named_persons_resolution(database, store):
    pages = ["FIRST Robotics Competition SYNTHETICA\nGame Manual (no year printed)", *manual_pages(SEASON)[1:]]
    manual = _upload(database, store, pages)
    state = _process(database, store, manual["id"])
    assert state["status"] == "needs_resolution" and state["report"] is None
    assert mp.start(database, store, manual["id"], requested_by=ACTOR)["claimed"] is False  # not retried silently
    with pytest.raises(mp.ManualProcessingError):
        mp.resolve_identity(database, store, manual["id"], season=SEASON + 1, resolved_by=ACTOR)
    resolved = mp.resolve_identity(database, store, manual["id"], season=SEASON, resolved_by=ACTOR, note="cover page")
    assert resolved["retry_allowed"] is True
    final = _process(database, store, manual["id"])
    assert final["status"] == "succeeded" and final["report"]["identity"]["decision"] == "resolved"


@pytest.mark.parametrize("content, code", [
    (b"%PDF-1.7\nthis is not a real pdf body\n%%EOF\n", "malformed_pdf"),
    (make_pdf(["", "", ""]), "unreadable_text"),
])
def test_unreadable_or_malformed_pdfs_fail_closed(database, store, content, code):
    row, _ = hi.store_manual(database, store, season=SEASON, game_name="X", filename="bad.pdf", content=content,
                             uploaded_by=ACTOR)
    state = _process(database, store, row["id"])
    assert state["status"] == "failed" and state["attempts"][-1]["error"]["code"] == code
    assert state["retry_allowed"] is True


def test_each_attempt_is_listed_once_and_numbered_in_sequence(database, store):
    """D1 (2026-10-12, browser checklist step 1.9): attempts were numbered and listed by ledger line, two per attempt."""
    manual = _upload(database, store, manual_pages(SEASON - 1))  # names another season: fails on every attempt
    _process(database, store, manual["id"])
    state = _process(database, store, manual["id"])  # the retry
    assert state["status"] == "failed"
    assert [a["attempt"] for a in state["attempts"]] == [1, 2]
    for attempt in state["attempts"]:
        assert attempt["status"] == "failed" and attempt["error"]["code"] == "wrong_season"
        assert attempt["started_at"] and attempt["finished_at"] and attempt["requested_by"] == ACTOR
    ledger = (mp.ledger_dir(store, manual["content_sha256"]) / "attempts.jsonl").read_text(encoding="utf-8").splitlines()
    assert [json.loads(line)["status"] for line in ledger] == ["running", "failed", "running", "failed"]  # append-only


def test_an_existing_ledger_keeps_its_history_and_numbers_the_next_attempt_after_the_highest(database, store):
    """A ledger written before the D1 fix (manual #123's shape: attempts #1 and #3) is never rewritten."""
    manual = _upload(database, store, manual_pages(SEASON - 1))
    directory = mp.ledger_dir(store, manual["content_sha256"])
    directory.mkdir(parents=True)
    old = [{"attempt": 1, "status": "running", "started_at": "2026-10-12T21:46:44+00:00", "requested_by": ACTOR},
           {"attempt": 1, "status": "failed", "finished_at": "2026-10-12T21:46:45+00:00",
            "error": {"code": "wrong_season", "message": "m"}},
           {"attempt": 3, "status": "running", "started_at": "2026-10-12T21:49:27+00:00", "requested_by": ACTOR},
           {"attempt": 3, "status": "failed", "finished_at": "2026-10-12T21:49:28+00:00",
            "error": {"code": "wrong_season", "message": "m"}}]
    history = "".join(json.dumps(line, sort_keys=True) + "\n" for line in old)
    (directory / "attempts.jsonl").write_text(history, encoding="utf-8")
    assert [a["attempt"] for a in mp.status(store, manual)["attempts"]] == [1, 3]
    state = _process(database, store, manual["id"])
    assert [a["attempt"] for a in state["attempts"]] == [1, 3, 4]
    assert (directory / "attempts.jsonl").read_text(encoding="utf-8").startswith(history)


def test_a_tampered_stored_file_fails_on_hash_and_a_restored_one_succeeds_on_retry(database, store):
    manual = _upload(database, store, manual_pages(SEASON))
    path = Path(manual["storage_path"])
    original = path.read_bytes()
    path.write_bytes(original + b"\n% tampered")
    failed = _process(database, store, manual["id"])  # recorded as a failed attempt, never a crash
    assert failed["status"] == "failed" and failed["attempts"][-1]["error"]["code"] == "hash_mismatch"
    assert not (mp.ledger_dir(store, manual["content_sha256"]) / "lock").exists()
    assert mp.status(store, mp.manual_meta(database, manual["id"]))["retry_allowed"] is True
    path.write_bytes(original)
    assert _process(database, store, manual["id"])["status"] == "succeeded"


def test_a_run_in_progress_is_never_duplicated_and_a_stale_lock_is_recoverable(database, store):
    manual = _upload(database, store, manual_pages(SEASON))
    first = mp.start(database, store, manual["id"], requested_by=ACTOR)
    assert first["claimed"] is True
    second = mp.start(database, store, manual["id"], requested_by="Someone Else")
    assert second["claimed"] is False and second["status"] == "running"
    lock = mp.ledger_dir(store, manual["content_sha256"]) / "lock"
    lock.write_text(json.dumps({"started_at": "2020-01-01T00:00:00+00:00", "requested_by": ACTOR}), encoding="utf-8")
    assert mp.status(store, manual)["status"] == "not_started"
    assert mp.start(database, store, manual["id"], requested_by=ACTOR)["claimed"] is True


def test_artifacts_are_write_once(tmp_path):
    path = tmp_path / "a.json"
    mp._write_once(path, b"one")
    mp._write_once(path, b"one")  # identical bytes: fine
    with pytest.raises(mp.ManualProcessingError) as e:
        mp._write_once(path, b"two")
    assert e.value.code == "storage_integrity" and path.read_bytes() == b"one"


# --- the API: processing ---------------------------------------------------------------------------------------------


def test_processing_over_http_is_gated_and_reports_progress(client, database, store):
    manual = _upload(database, store, manual_pages(SEASON))
    refused = client.post(f"/human-inputs/game-manuals/{manual['id']}/processing", json={"requested_by": ACTOR})
    assert refused.status_code == 403
    started = client.post(f"/human-inputs/game-manuals/{manual['id']}/processing", json={"requested_by": ACTOR},
                          headers=_w())
    assert started.status_code == 202 and started.json()["status"] == "running"
    status = client.get(f"/human-inputs/game-manuals/{manual['id']}/processing").json()  # background task has run
    assert status["status"] == "succeeded"
    extraction = client.get(f"/human-inputs/game-manuals/{manual['id']}/extraction").json()
    assert "text" not in extraction["pages"][0] and extraction["suggestions"]
    page = client.get(f"/human-inputs/game-manuals/{manual['id']}/pages", params={"first": 3, "last": 3}).json()
    assert "15 seconds" in page[0]["text"]
    too_many = client.get(f"/human-inputs/game-manuals/{manual['id']}/pages", params={"first": 1, "last": 30})
    assert too_many.status_code == 422
    duplicate = client.post(f"/human-inputs/game-manuals/{manual['id']}/processing", json={"requested_by": ACTOR},
                            headers=_w())
    assert duplicate.json()["claimed"] is False and [x["attempt"] for x in duplicate.json()["attempts"]] == [1]


def test_extraction_of_an_unprocessed_manual_is_not_found(client, database, store):
    manual = _upload(database, store, manual_pages(SEASON))
    assert client.get(f"/human-inputs/game-manuals/{manual['id']}/extraction").status_code == 404
    assert client.get("/human-inputs/game-manuals/999999/processing").status_code == 404


# --- the API: season rulesets (P6-M1 control, unchanged) -----------------------------------------------------------


def _checklist(**over) -> dict:
    return {**{f"R{i}": True for i in range(1, 15)}, **over}


def _save_submit(client, ruleset_json) -> dict:
    saved = client.post("/human-inputs/rulesets", json={"ruleset_json": ruleset_json, "created_by": ACTOR}, headers=_w())
    assert saved.status_code == 201, saved.text
    assert client.post(f"/human-inputs/rulesets/{saved.json()['id']}/submit", headers=_w()).status_code == 200
    return saved.json()


def test_the_worksheet_is_a_marked_reviewable_proposal_never_saved(client, database):
    before = len(client.get("/human-inputs/rulesets", params={"season": RULESET_SEASON}).json())
    sheet = client.get(f"/human-inputs/seasons/{RULESET_SEASON}/ruleset-worksheet").json()
    assert sheet["saved"] is False and sheet["schema_errors"] == [] and sheet["template_from_season"] < RULESET_SEASON
    proposal = sheet["proposal"]
    assert proposal["season"] == RULESET_SEASON and proposal["selection_variants"] == [] and proposal["event_exclusions"] == []
    assert "UNVERIFIED (carried from" in proposal["tie_rule"]
    assert len(client.get("/human-inputs/rulesets", params={"season": RULESET_SEASON}).json()) == before


def _processed_ruleset_season_manual(database, store) -> dict:
    """A processed manual for RULESET_SEASON, whose year no title page can name, so a named person resolves it."""
    manual = _upload(database, store, manual_pages(RULESET_SEASON), season=RULESET_SEASON)
    assert _process(database, store, manual["id"])["status"] == "needs_resolution"
    mp.resolve_identity(database, store, manual["id"], season=RULESET_SEASON, resolved_by=ACTOR, note="SYNTHETIC")
    assert _process(database, store, manual["id"])["status"] == "succeeded"
    return manual


def test_the_worksheet_uses_the_latest_processed_manual_not_a_later_failed_upload(client, database, store):
    """D2 (2026-10-12, browser checklist step 2.2): the worksheet took the most recent upload even when it had failed."""
    good = _processed_ruleset_season_manual(database, store)
    failed = _upload(database, store, manual_pages(2026), season=RULESET_SEASON)  # later, and names another season
    assert _process(database, store, failed["id"])["status"] == "failed"
    sheet = client.get(f"/human-inputs/seasons/{RULESET_SEASON}/ruleset-worksheet").json()
    assert sheet["manual"] == {"id": good["id"], "sha256": good["content_sha256"], "processed": True}
    assert sheet["proposal"]["manual"] == {"title": "Game Manual", "version": "1.0"}
    assert any(item["suggestions"] for item in sheet["verify"])


def test_with_no_processed_manual_the_worksheet_takes_no_identity_from_an_upload(client, database, store):
    failed = _upload(database, store, manual_pages(2026), season=RULESET_SEASON)
    assert _process(database, store, failed["id"])["status"] == "failed"
    sheet = client.get(f"/human-inputs/seasons/{RULESET_SEASON}/ruleset-worksheet").json()
    assert sheet["manual"] == {"id": failed["id"], "sha256": failed["content_sha256"], "processed": False}
    assert "UNVERIFIED (carried from" in sheet["proposal"]["manual"]["title"]  # never the failed upload's filename
    assert not any(item["suggestions"] for item in sheet["verify"])


def test_a_worksheet_draft_with_markers_can_never_be_approved(client, tmp_path):
    proposal = client.get(f"/human-inputs/seasons/{RULESET_SEASON}/ruleset-worksheet").json()["proposal"]
    row = _save_submit(client, proposal)
    response = client.post(f"/human-inputs/rulesets/{row['id']}/review", headers=_w(), json={
        "reviewer": ACTOR, "approve": True, "reviewer_qualification": "SYNTHETIC qualification",
        "checklist": _checklist(), "verified_sha256": row["ruleset_sha256"]})
    assert response.status_code == 409 and response.json()["error"]["code"] == "unverified_content"
    assert not list((tmp_path / "records").glob("*")) if (tmp_path / "records").exists() else True


@pytest.mark.parametrize("override, code", [({"checklist": _checklist(R7=False)}, "review_incomplete"),
                                             ({"verified_sha256": "0" * 64}, "hash_mismatch"),
                                             ({"reviewer_qualification": ""}, "invalid_input")])
def test_an_incomplete_review_is_refused(client, override, code):
    row = _save_submit(client, synthetic_ruleset(RULESET_SEASON))
    body = {"reviewer": ACTOR, "approve": True, "reviewer_qualification": "SYNTHETIC qualification",
            "checklist": _checklist(), "verified_sha256": row["ruleset_sha256"], **override}
    response = client.post(f"/human-inputs/rulesets/{row['id']}/review", headers=_w(), json=body)
    assert response.json()["error"]["code"] == code
    assert client.get(f"/human-inputs/rulesets/{row['id']}").json()["status"] == "awaiting_review"


def test_a_complete_review_approves_and_writes_the_write_once_record(client, tmp_path):
    row = _save_submit(client, synthetic_ruleset(RULESET_SEASON))
    body = {"reviewer": ACTOR, "approve": True, "reviewer_qualification": "SYNTHETIC qualification",
            "checklist": _checklist(), "verified_sha256": row["ruleset_sha256"]}
    unauthorized = client.post(f"/human-inputs/rulesets/{row['id']}/review", json=body)
    assert unauthorized.status_code == 403
    response = client.post(f"/human-inputs/rulesets/{row['id']}/review", headers=_w(), json=body)
    assert response.status_code == 200 and response.json()["ruleset"]["status"] == "approved"
    record_path = Path(response.json()["approval_record"]["path"])
    record = json.loads(record_path.read_text(encoding="utf-8"))
    assert record["approved_ruleset_sha256"] == row["ruleset_sha256"] and record["reviewer_name"] == ACTOR
    assert record_path.parent == tmp_path / "records"


def test_an_existing_approval_record_refuses_before_approving(client, tmp_path):
    row = _save_submit(client, synthetic_ruleset(RULESET_SEASON))
    records = tmp_path / "records"
    records.mkdir(parents=True, exist_ok=True)
    (records / f"P6_M1_APPROVAL_{RULESET_SEASON}_v{row['version']}.json").write_text("{}", encoding="utf-8")
    response = client.post(f"/human-inputs/rulesets/{row['id']}/review", headers=_w(), json={
        "reviewer": ACTOR, "approve": True, "reviewer_qualification": "SYNTHETIC", "checklist": _checklist(),
        "verified_sha256": row["ruleset_sha256"]})
    assert response.status_code == 409 and response.json()["error"]["code"] == "invalid_state"
    assert client.get(f"/human-inputs/rulesets/{row['id']}").json()["status"] == "awaiting_review"


def test_the_checklist_lists_r1_to_r14(client):
    items = client.get("/human-inputs/ruleset-review-checklist").json()["items"]
    assert [i["id"] for i in items] == [f"R{i}" for i in range(1, 15)] and all(i["title"] for i in items)


# --- readiness --------------------------------------------------------------------------------------------------------


def test_readiness_for_2027_lists_every_phase6_task_and_authorizes_nothing(client, database):
    with database.cursor() as c:
        c.execute("SELECT (SELECT count(*) FROM season_rulesets), (SELECT count(*) FROM game_manuals)")
        before = c.fetchone()
    report = client.get("/human-inputs/seasons/2027/readiness").json()
    tasks = {t["id"]: t for t in report["phase6"]["tasks"]}
    assert set(tasks) == {f"R{i}" for i in range(1, 11)} | {"M1", "M2", "M3", "M4"}
    assert tasks["R8"]["status"] == "done"  # the adopted M8b pre-run record
    assert tasks["R2"]["status"] == "waiting_for_2027_data" and tasks["R5"]["status"] in ("blocked", "waiting_for_2027_data")
    assert all(t["never_by_manual_upload"] for t in tasks.values())
    assert [d["met"] for d in report["phase6"]["done_means"]] == [False, True]  # P6-DM1 not met; P6-DM2 met
    with database.cursor() as c:
        c.execute("SELECT (SELECT count(*) FROM season_rulesets), (SELECT count(*) FROM game_manuals)")
        assert c.fetchone() == before


def test_readiness_for_a_historical_season_reports_real_coverage_without_phase6_tasks(client):
    report = client.get("/human-inputs/seasons/2026/readiness").json()
    assert report["coverage"]["has_data"] is True and "phase6" not in report
    features = {f["key"]: f for f in report["features"]}
    assert features["event_browser"]["available"] is True and features["season_ruleset"]["available"] is True
    assert features["event_analysis"]["available"] is False  # no model pinned on this test app instance


# --- the historical explorer (real isolated-copy rows, read-only) ----------------------------------------------------


@pytest.mark.parametrize("season", [2023, 2024, 2025, 2026])
def test_each_historical_season_is_browsable_and_isolated(client, season):
    events = client.get(f"/seasons/{season}/events").json()
    if not events and season == 2023:
        # 2023 is kept in its own copy, stratai_test_2023: in stratai_test its team-events would become D13 prior-event
        # candidates for 2024-2026 lookups (read_team_event_facts is not season-bounded) and change frozen D18 results.
        coverage = {s["season"]: s["coverage"] for s in client.get("/seasons").json()}[2023]
        assert coverage["has_data"] is False
        pytest.skip("2023 is not in this copy; run with DATABASE_URL on stratai_test_2023")
    assert events, f"{season} has no events in the isolated copy"
    event = next(e for e in events if e["matches_played"] > 0)
    assert event["event_key"].startswith(str(season))
    teams = client.get(f"/events/{event['event_key']}/teams").json()
    assert teams["event"]["season"] == season and teams["teams"]
    matches = client.get(f"/events/{event['event_key']}/matches").json()["matches"]
    assert matches and all(m["match_key"].startswith(event["event_key"]) for m in matches)
    team = teams["teams"][0]["team_number"]
    team_season = client.get(f"/teams/{team}/seasons/{season}").json()
    assert team_season["events"] and all(e["event_key"].startswith(str(season)) for e in team_season["events"])


def test_seasons_list_every_supported_season_with_honest_coverage(client):
    seasons = {s["season"]: s["coverage"] for s in client.get("/seasons").json()}
    assert sorted(seasons) == [2023, 2024, 2025, 2026, 2027]
    assert seasons[2027]["has_data"] is False and seasons[2023]["score_breakdown_adapter"] is False


@pytest.mark.parametrize("path, status", [("/events/notakey/teams", 422), ("/events/2026zzzz/teams", 404),
                                          ("/teams/999999/seasons/2026", 404)])
def test_explorer_refusals(client, path, status):
    assert client.get(path).status_code == status


def test_a_season_without_a_score_breakdown_adapter_is_an_explained_422_not_a_500(client):
    from ml.features.score_breakdown import UnsupportedSeasonError

    def raises() -> None:
        raise UnsupportedSeasonError(2023)

    client.app.add_api_route("/__test_unsupported_season", raises)
    response = client.get("/__test_unsupported_season")
    assert response.status_code == 422
    error = response.json()["error"]
    assert error["code"] == "season_not_supported" and "2023" in error["message"] and error["request_id"]


def test_an_available_feature_states_what_it_cannot_answer_for_a_season_without_an_adapter_or_epa():
    from data.readiness import features

    def coverage(adapter: bool, epa_rows: int) -> dict:
        return {"has_data": True, "matches_played": 10, "team_event_epa_rows": epa_rows, "team_metrics_rows": 0,
                "score_breakdown_adapter": adapter}

    inputs = {"game_spec": None, "ruleset": {"approved": None}, "manuals": []}
    serving = {"ranking_model": True, "win_prob_model": True}
    limited = {f["key"]: f for f in features(2023, coverage(False, 0), inputs, serving)}
    for key in ("team_strength", "event_analysis", "qualification_forecast", "match_win_probability"):
        assert limited[key]["available"] is True
        assert any("season_not_supported" in text for text in limited[key]["limitations"])
        assert any("epa_source_incomplete" in text for text in limited[key]["limitations"])
    complete = {f["key"]: f for f in features(2026, coverage(True, 100), inputs, serving)}
    assert all(not f["limitations"] for f in complete.values())


def test_the_explorer_routes_are_exactly_the_documented_ones():
    from api.routes.explorer import router

    docs = (Path(__file__).resolve().parent.parent / "docs" / "game_manual_manager.md").read_text(encoding="utf-8")
    documented = set(re.findall(r"^- `GET (/[^`]+)`", docs, flags=re.MULTILINE))
    assert documented == {route.path for route in router.routes}
