"""Phase 5 human-input workflows: storage, versioning, workflow states, authorization, M9 output, DM1 status.

Runs only on an isolated stratai_* database copy (sentinel season 9986, profile keys `t-p5-*`).

**Synthetic test fixtures, not DM1 evidence.** Every spec, codebook, coding, map, rubric and review here exists to
exercise the software. None was entered from a manual or authored by a mentor, and none is DM1 evidence; DM1's
done-means reads only the write-once records.
"""

from __future__ import annotations

import json
from typing import Generator

import pytest
from fastapi.testclient import TestClient

from api import create_app
from api.dependencies import get_database
from api.routes.human_inputs import WRITE_TOKEN_HEADER
from data import human_inputs as hi
from data.config import Settings
from database.connection import Database, DatabaseConfig
from tests.test_game_analysis import _spec
from tests.test_live_epa import _isolated_db_name

pytestmark = pytest.mark.skipif(_isolated_db_name() is None, reason="needs an isolated stratai_* database copy")

SEASON = 9986
TOKEN = "synthetic-test-token"
PDF = b"%PDF-1.7\n% synthetic test fixture, not a game manual\n%%EOF\n"


def _cleanup(db: Database) -> None:
    with db.cursor() as c:
        c.execute("DELETE FROM human_review_artifacts WHERE season IN (%s, %s)", (SEASON, SEASON - 1))
        c.execute("DELETE FROM game_spec_versions WHERE season IN (%s, %s)", (SEASON, SEASON - 1))
        c.execute("DELETE FROM game_manuals WHERE season IN (%s, %s)", (SEASON, SEASON - 1))
        c.execute("DELETE FROM capability_profiles WHERE profile_key LIKE 't-p5-%%'")
        c.execute("DELETE FROM raw_source_payloads WHERE source = 'capability_intake' AND source_object_id LIKE "
                  "'t-p5-%%'")


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
def client(database, tmp_path) -> Generator[TestClient, None, None]:
    app = create_app(Settings(human_inputs_write_token=TOKEN, artifact_store_dir=str(tmp_path)))
    app.dependency_overrides[get_database] = lambda: database
    with TestClient(app) as test_client:
        yield test_client


def _w(**extra) -> dict:
    return {WRITE_TOKEN_HEADER: TOKEN, **extra}


def _spec_body(season: int = SEASON) -> dict:
    body = _spec(season)
    body["source"] = {"manual_title": "synthetic", "manual_version": "0"}
    return body


# --- game manuals ------------------------------------------------------------------------------


def test_upload_stores_metadata_and_is_idempotent(client, tmp_path):
    params = {"season": SEASON, "game_name": "SYNTHETIC", "filename": "manual.pdf", "uploaded_by": "tester"}
    first = client.post("/human-inputs/game-manuals", params=params, content=PDF,
                        headers=_w(**{"Content-Type": "application/pdf"}))
    assert first.status_code == 201 and first.json()["created"] is True
    manual = first.json()["manual"]
    assert manual["byte_size"] == len(PDF) and len(manual["content_sha256"]) == 64 and "storage_path" not in manual
    again = client.post("/human-inputs/game-manuals", params=params, content=PDF,
                        headers=_w(**{"Content-Type": "application/pdf"}))
    assert again.status_code == 200 and again.json()["created"] is False and again.json()["manual"]["id"] == manual["id"]
    other = client.post("/human-inputs/game-manuals", params=params, content=PDF + b"v2",
                        headers=_w(**{"Content-Type": "application/pdf"}))
    assert other.status_code == 201 and other.json()["manual"]["id"] != manual["id"]  # a new version, never a replace
    listed = client.get("/human-inputs/game-manuals", params={"season": SEASON}).json()
    assert len(listed) == 2
    download = client.get(f"/human-inputs/game-manuals/{manual['id']}/file")
    assert download.content == PDF and download.headers["X-Content-SHA256"] == manual["content_sha256"]
    workflow = client.get(f"/human-inputs/seasons/{SEASON}/workflow").json()
    assert workflow["source_uploaded"] and workflow["spec_state"] == "no_structured_spec"  # upload validates nothing


@pytest.mark.parametrize(("content", "media", "status", "code"), [
    (b"not a pdf", "application/pdf", 422, "invalid_input"),
    (PDF, "text/plain", 415, "unsupported_media_type"),
])
def test_upload_input_validation(client, content, media, status, code):
    response = client.post("/human-inputs/game-manuals", content=content, headers=_w(**{"Content-Type": media}),
                           params={"season": SEASON, "game_name": "S", "filename": "x.pdf", "uploaded_by": "t"})
    assert response.status_code == status and response.json()["error"]["code"] == code


def test_writes_need_the_token_and_fail_closed(database, tmp_path):
    for token, code in ((None, "writes_disabled"), ("configured", "write_not_authorized")):
        app = create_app(Settings(human_inputs_write_token=token, artifact_store_dir=str(tmp_path)))
        app.dependency_overrides[get_database] = lambda: database
        with TestClient(app) as test_client:
            response = test_client.post(f"/human-inputs/seasons/{SEASON}/specs",
                                        json={"spec_json": {}, "created_by": "x"}, headers={WRITE_TOKEN_HEADER: "nope"})
            assert response.status_code == 403 and response.json()["error"]["code"] == code
            assert test_client.get(f"/human-inputs/seasons/{SEASON}/specs").status_code == 200  # reads stay open


# --- structured specs ----------------------------------------------------------------------------


def test_spec_versions_and_review_states(client):
    incomplete = client.post(f"/human-inputs/seasons/{SEASON}/specs", headers=_w(),
                             json={"spec_json": {"game_name": "PARTIAL"}, "created_by": "entrant"}).json()
    assert incomplete["status"] == "draft" and not incomplete["complete"] and incomplete["validation_errors"]
    assert client.get(f"/human-inputs/seasons/{SEASON}/workflow").json()["spec_state"] == "structured_spec_incomplete"
    refused = client.post(f"/human-inputs/specs/{incomplete['id']}/submit", headers=_w())
    assert refused.status_code == 409 and refused.json()["error"]["code"] == "spec_incomplete"

    complete = client.post(f"/human-inputs/seasons/{SEASON}/specs", headers=_w(),
                           json={"spec_json": _spec_body(), "created_by": "entrant",
                                 "based_on_id": incomplete["id"]}).json()
    assert complete["version"] == 2 and complete["complete"] and complete["spec_sha256"]
    assert complete["entry_started_at"] == incomplete["entry_started_at"]  # the season's clock starts once
    assert complete["spec_json"]["source"]["entered_by"] == "entrant" and complete["spec_json"]["source"]["llm_used"] is False
    client.post(f"/human-inputs/specs/{complete['id']}/submit", headers=_w())
    assert client.get(f"/human-inputs/seasons/{SEASON}/workflow").json()["spec_state"] == "awaiting_human_review"
    returned = client.post(f"/human-inputs/specs/{complete['id']}/review", headers=_w(),
                           json={"reviewer": "reviewer", "approve": False, "note": "check the endgame points"}).json()
    assert returned["status"] == "draft" and returned["review_note"]
    client.post(f"/human-inputs/specs/{complete['id']}/submit", headers=_w())
    approved = client.post(f"/human-inputs/specs/{complete['id']}/review", headers=_w(),
                           json={"reviewer": "reviewer", "approve": True}).json()
    assert approved["status"] == "approved" and approved["reviewed_by"] == "reviewer"

    third = client.post(f"/human-inputs/seasons/{SEASON}/specs", headers=_w(),
                        json={"spec_json": _spec_body(), "created_by": "entrant"}).json()
    client.post(f"/human-inputs/specs/{third['id']}/submit", headers=_w())
    client.post(f"/human-inputs/specs/{third['id']}/review", headers=_w(), json={"reviewer": "r2", "approve": True})
    versions = {v["version"]: v for v in client.get(f"/human-inputs/seasons/{SEASON}/specs").json()}
    assert versions[2]["status"] == "superseded" and versions[3]["status"] == "approved"  # nothing overwritten
    assert versions[2]["spec_json"] == complete["spec_json"]
    again = client.post(f"/human-inputs/specs/{third['id']}/review", headers=_w(), json={"reviewer": "r", "approve": True})
    assert again.status_code == 409 and again.json()["error"]["code"] == "invalid_state"


# --- capability profiles and the M9 output ----------------------------------------------------------


def _profile(budget: float = 8000, manufacturing: int = 3) -> dict:
    return {"budget_usd": budget, "manufacturing": manufacturing, "programming": 2, "mentoring": 1,
            "notes": "synthetic"}


def test_profile_lifecycle(client, database):
    created = client.post("/human-inputs/capability-profiles", headers=_w(),
                          json={"profile_key": "t-p5-a", "payload": _profile(), "created_by": "coach"})
    assert created.status_code == 201 and created.json()["version"] == 1 and created.json()["raw_payload_id"]
    duplicate_key = client.post("/human-inputs/capability-profiles", headers=_w(),
                                json={"profile_key": "t-p5-a", "payload": _profile(), "created_by": "coach"})
    assert duplicate_key.status_code == 409
    edited = client.put("/human-inputs/capability-profiles/t-p5-a", headers=_w(),
                        json={"payload": _profile(budget=1000), "created_by": "coach"}).json()
    assert edited["version"] == 2 and edited["payload"]["budget_usd"] == 1000
    history = client.get("/human-inputs/capability-profiles/t-p5-a/history").json()
    assert [h["status"] for h in history] == ["superseded", "active"]
    copy = client.post("/human-inputs/capability-profiles/t-p5-a/duplicate", headers=_w(),
                       json={"new_key": "t-p5-b", "created_by": "coach"}).json()
    assert copy["profile_key"] == "t-p5-b" and copy["payload"]["budget_usd"] == 1000
    client.post("/human-inputs/capability-profiles/t-p5-b/archive", headers=_w(), json={"archived_by": "coach"})
    keys = {p["profile_key"] for p in client.get("/human-inputs/capability-profiles").json()}
    assert "t-p5-a" in keys and "t-p5-b" not in keys
    archived_edit = client.put("/human-inputs/capability-profiles/t-p5-b", headers=_w(),
                               json={"payload": _profile(), "created_by": "coach"})
    assert archived_edit.status_code == 409
    bad = client.post("/human-inputs/capability-profiles", headers=_w(),
                      json={"profile_key": "t-p5-c", "payload": {"budget_usd": -5, "manufacturing": 9},
                            "created_by": "coach"})
    assert bad.status_code == 422 and bad.json()["error"]["code"] == "invalid_input"
    with database.cursor() as c:  # raw first: the invalid form was still landed
        c.execute("SELECT count(*) FROM raw_source_payloads WHERE source = 'capability_intake' AND "
                  "source_object_id = 't-p5-c'")
        assert c.fetchone()[0] == 1


def _rubric_payload() -> dict:
    return {"version": "synthetic", "archetypes": [
        {"archetype": "simple", "tier": 1, "priority": 2, "min_budget_usd": 0, "min_levels": {},
         "achievable_features": ["drive"]},
        {"archetype": "shooter", "tier": 2, "priority": 1, "min_budget_usd": 5000,
         "min_levels": {"manufacturing": 2}, "achievable_features": ["shoot"]}]}


def test_recommendation_is_the_deterministic_m9_output(client):
    client.post("/human-inputs/capability-profiles", headers=_w(),
                json={"profile_key": "t-p5-r", "payload": _profile(), "created_by": "coach"})
    missing = client.get("/human-inputs/capability-profiles/t-p5-r/recommendation", params={"season": SEASON})
    assert missing.status_code == 409 and missing.json()["error"]["code"] == "prerequisite_missing"
    rubric = client.post(f"/human-inputs/seasons/{SEASON}/artifacts", headers=_w(),
                         json={"kind": "rubric", "author": "mentor-author", "payload": _rubric_payload()}).json()
    client.post(f"/human-inputs/artifacts/{rubric['id']}/establish", headers=_w(), json={"established_by": "lead"})
    first = client.get("/human-inputs/capability-profiles/t-p5-r/recommendation", params={"season": SEASON}).json()
    second = client.get("/human-inputs/capability-profiles/t-p5-r/recommendation", params={"season": SEASON}).json()
    assert first == second and first["label"] == "heuristic_not_validated_against_outcomes"
    assert first["realistic_ceiling_tier"] == 2 and first["recommended_archetype"] is None  # no M8 candidates yet
    assert first["candidates_note"].startswith("no candidate archetypes yet")
    assert any(e["requirements_met"] for e in first["explanation"])


# --- DM1 artifacts and status ----------------------------------------------------------------------


def _codebook() -> dict:
    return {"version": "synthetic", "functions": {"shooter": "scoring", "climber": "endgame"}}


def _coding(fn: str) -> dict:
    return {"labels": {str(r): [fn] for r in range(1, 78)}}


def test_dm1_artifact_workflow_and_status_never_marks_dm1_met(client):
    early = client.post(f"/human-inputs/seasons/{SEASON}/artifacts", headers=_w(),
                        json={"kind": "coding", "author": "coder-a", "payload": _coding("shooter")})
    assert early.status_code == 409 and early.json()["error"]["code"] == "prerequisite_missing"
    book = client.post(f"/human-inputs/seasons/{SEASON}/artifacts", headers=_w(),
                       json={"kind": "codebook", "author": "author", "payload": _codebook()}).json()
    assert book["status"] == "submitted"
    client.post(f"/human-inputs/artifacts/{book['id']}/establish", headers=_w(), json={"established_by": "lead"})
    consensus_early = client.post(f"/human-inputs/seasons/{SEASON}/artifacts", headers=_w(),
                                  json={"kind": "consensus_coding", "author": "meeting", "payload": _coding("shooter")})
    assert consensus_early.status_code == 409  # a consensus follows two independent codings
    partial = client.post(f"/human-inputs/seasons/{SEASON}/artifacts", headers=_w(),
                          json={"kind": "coding", "author": "coder-a", "payload": {"labels": {"1": ["shooter"]}}})
    assert partial.status_code == 422  # every reference row must be coded
    for coder in ("coder-a", "coder-b"):
        response = client.post(f"/human-inputs/seasons/{SEASON}/artifacts", headers=_w(),
                               json={"kind": "coding", "author": coder, "payload": _coding("shooter")})
        assert response.status_code == 201
    coding_cannot_be_established = client.post(f"/human-inputs/artifacts/{response.json()['id']}/establish",
                                               headers=_w(), json={"established_by": "lead"})
    assert coding_cannot_be_established.status_code == 409
    kappa = client.get(f"/human-inputs/seasons/{SEASON}/kappa").json()
    assert kappa["state"] == "computed" and kappa["coders"] == ["coder-a", "coder-b"]
    status = client.get(f"/human-inputs/seasons/{SEASON}/dm1-status").json()
    items = {i["artifact"]: i for i in status["items"]}
    assert items["codebook"]["state"] == "established" and items["consensus_coding"]["state"] == "missing"
    assert items["rubric"]["state"] == "missing" and items["mentor_review"]["state"] == "missing"
    assert status["inputs_ready"] is False and status["done_means"]["met"] is False


def test_export_refuses_until_every_input_is_established(database, tmp_path):
    with pytest.raises(hi.HumanInputError) as caught:
        hi.export_dm1_inputs(database, SEASON, tmp_path / "out")
    assert caught.value.code == "prerequisite_missing"


def test_existing_endpoints_are_unchanged(client):
    assert client.get("/health").status_code == 200
    paths = client.get("/openapi.json").json()["paths"]
    assert "/teams/{team_number}/events/{event_key}/strength" in paths and "/predictions/win-probability" in paths
    assert json.loads(json.dumps(paths["/human-inputs/write-access"]))
