"""The in-app ScoutRadioz CSV upload, end to end through the API (audit 2026-11-26, workstream 8).

On an isolated stratai_test_<suffix> copy, with SYNTHETIC data only: season 9987, event 9987zzzupload, teams 9987xx,
invented scout labels, and a synthetic column mapping registered for season 9987 for the length of each test. Nothing
here is evidence about any real team, scout or season's form.
"""

from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from typing import Iterator

import pytest
from fastapi.testclient import TestClient

from api import create_app
from data.config import Settings
from data.metrics import scoutradioz_mappings
from data.metrics.scoutradioz import ScoutRadiozFieldMapping, ScoutRadiozRatingMapping
from database.connection import Database, DatabaseConfig
from tests.test_live_epa import _isolated_db_name
from workspaces import passwords

pytestmark = pytest.mark.skipif(_isolated_db_name() is None, reason="needs an isolated stratai_* database copy")

SEASON, EVENT = 9987, "9987zzzupload"
TEAMS = [998701, 998702, 998703, 998704, 998705, 998706]
MATCHES = {f"{EVENT}_qm{n}": (TEAMS[:3], TEAMS[3:]) for n in (1, 2)}
JOIN_CODE, PASSWORD = "sentinel-join-code-9987", "member pass 1"
DOMAIN = "@upload.test.invalid"
CSRF = {"X-StratAI-CSRF": "1"}
TEAM_WORKSPACE_SQL = ("INSERT INTO workspaces (team_number, team_name, verification_status, verified_at, verified_by) "
                      "VALUES (11, 'MORT', 'verified', NOW(), 'migration 0015_single_team_auth')")
SYNTHETIC_MAPPING = ScoutRadiozFieldMapping(defense_rating=ScoutRadiozRatingMapping(
    column="qDefense", source_min=1, source_max=10, excluded_values=("0",), target_min=1))
HEADER = "org_key,year,event_key,match_key,match_number,time,alliance,team_key,scouter,qDefense,superNotes"
SCOUTS = ("Synthetic Scout Alpha", "Synthetic Scout Beta")


def row(*, org="frc11", event=EVENT, match="qm1", team=TEAMS[0], scouter=SCOUTS[0], defense="7", time=None,
        notes="", extra: str | None = None) -> str:
    time = time or "3/1/2030 10:00:00 AM"
    cells = [org, str(SEASON), event, f"{event}_{match}", match[2:], time, "red", f"frc{team}" if isinstance(team, int)
             else team, scouter, defense, notes]
    return ",".join(cells) + (f",{extra}" if extra is not None else "")


GOOD_A = row()
GOOD_B = row(team=TEAMS[1], scouter=SCOUTS[1], defense="3", notes="steady")
FILE_ROWS = [
    GOOD_A,                                   # 2 accepted
    GOOD_A,                                   # 3 duplicate of row 2
    row(team=TEAMS[2], defense="0"),          # 4 excluded: "0" is "played no defense"
    row(team="bad-key"),                      # 5 rejected: team key
    row(team=TEAMS[3], scouter=""),           # 6 rejected: no scout recorded
    row(org="frc254", team=TEAMS[4]),         # 7 rejected: another team's export
    row(event="9987other", team=TEAMS[4]),    # 8 rejected: another event
    row(match="qm99", team=TEAMS[4]),         # 9 rejected: match StratAI does not have
    row(team=TEAMS[5], defense="lots"),       # 10 rejected: not a number
    GOOD_B,                                   # 11 accepted
    row(team=TEAMS[5], extra="surplus"),      # 12 rejected: more cells than columns
    row(match="qm2", time="yesterday"),       # 13 rejected: time
]


def csv_text(rows: list[str]) -> str:
    return "\r\n".join([HEADER, *rows]) + "\r\n"


def sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _db() -> Database:
    return Database(DatabaseConfig(Settings().database_url))


def _reset_accounts(db: Database) -> None:
    with db.cursor() as c:
        c.execute("DELETE FROM workspaces")
        c.execute("DELETE FROM users WHERE email LIKE %s", (f"%{DOMAIN}",))
        c.execute("DELETE FROM auth_attempts")
        c.execute(TEAM_WORKSPACE_SQL)


def _drop_scouting(db: Database) -> None:
    with db.cursor() as c:
        c.execute("DELETE FROM scouting_observations WHERE event_key = %s", (EVENT,))
        c.execute("DELETE FROM raw_source_payloads WHERE source = 'scoutradioz' AND source_object_id LIKE %s",
                  (f"{EVENT}%",))
        c.execute("DELETE FROM team_metrics WHERE event_key = %s", (EVENT,))
        c.execute("DELETE FROM pipeline_runs WHERE scope_key = %s", (EVENT,))
        c.execute("DELETE FROM source_watermarks WHERE scope_key = %s", (EVENT,))


@pytest.fixture(scope="module", autouse=True)
def canonical() -> Iterator[None]:
    db = _db()

    def drop() -> None:
        _reset_accounts(db)
        _drop_scouting(db)
        with db.cursor() as c:
            c.execute("DELETE FROM match_teams WHERE match_key LIKE %s", (f"{EVENT}%",))
            c.execute("DELETE FROM matches WHERE event_key = %s", (EVENT,))
            c.execute("DELETE FROM events WHERE event_key = %s", (EVENT,))
            c.execute("DELETE FROM teams WHERE team_number = ANY(%s)", (TEAMS,))

    drop()
    with db.cursor() as c:
        c.execute("INSERT INTO events (event_key, season, name, end_date) VALUES (%s, %s, 'Sentinel', %s)",
                  (EVENT, SEASON, datetime(2030, 3, 2).date()))
        for team in TEAMS:
            c.execute("INSERT INTO teams (team_number, name) VALUES (%s, %s)", (team, f"Team {team}"))
        for n, (key, (red, blue)) in enumerate(MATCHES.items(), start=1):
            c.execute("INSERT INTO matches (match_key, event_key, season, competition_level, match_number, "
                      "scheduled_time) VALUES (%s, %s, %s, 'qualification', %s, %s)",
                      (key, EVENT, SEASON, n, datetime(2030, 3, 1, 9 + n, tzinfo=timezone.utc)))
            for color, teams in (("red", red), ("blue", blue)):
                for team in teams:
                    c.execute("INSERT INTO match_teams (match_key, team_number, alliance_color) VALUES (%s, %s, %s)",
                              (key, team, color))
    yield
    drop()


@pytest.fixture(autouse=True)
def _environment(monkeypatch) -> Iterator[None]:
    monkeypatch.setattr(passwords, "LOG2_N", 10)
    monkeypatch.setattr(passwords, "PARALLELISM", 1)
    monkeypatch.setenv("ENV", "development")
    monkeypatch.setenv("TEAM_JOIN_CODE", JOIN_CODE)
    monkeypatch.setenv("ADMIN_EMAILS", f"ada{DOMAIN}")
    monkeypatch.setenv("ACCESS_POLICY", "members")
    for name in ("TEAM_ADMIN_JOIN_CODE", "AUTH_TRUSTED_PROXY_HOPS", "DEV_OUTBOX_DIR"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setitem(scoutradioz_mappings.APPROVED_FIELD_MAPPINGS, SEASON, SYNTHETIC_MAPPING)
    _reset_accounts(_db())
    _drop_scouting(_db())
    yield
    _drop_scouting(_db())
    _reset_accounts(_db())


@pytest.fixture
def app():
    return create_app(Settings())


def member(app, who: str) -> TestClient:
    c = TestClient(app, headers=CSRF)
    response = c.post("/auth/signup", json={"full_name": who.title(), "email": f"{who}{DOMAIN}",
                                            "password": PASSWORD, "join_code": JOIN_CODE})
    assert response.status_code == 201, response.text
    return c


def preview(c: TestClient, text: str):
    return c.post("/workspace/scouting/imports/preview", json={"filename": "export.csv", "content": text})


def confirm(c: TestClient, text: str, digest: str | None = None, **extra):
    return c.post("/workspace/scouting/imports", json={"filename": "export.csv", "content": text,
                                                       "file_sha256": digest or sha(text), "confirm": True, **extra})


def stored() -> dict[tuple[str, int], int | None]:
    with _db().cursor() as c:
        c.execute("SELECT match_key, team_number, defense_rating FROM scouting_observations WHERE event_key = %s",
                  (EVENT,))
        return {(m, t): d for m, t, d in c.fetchall()}


# --- the preview ---------------------------------------------------------------------------------------------------


def test_the_preview_gives_every_row_one_status_and_writes_nothing(app):
    text = csv_text(FILE_ROWS)
    response = preview(member(app, "ada"), text)
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["event_key"] == EVENT and body["season"] == SEASON and body["file_sha256"] == sha(text)
    assert body["counts"] == {"rows": 12, "accepted": 2, "rejected": 8, "excluded": 1, "duplicate": 1,
                              "already_imported": 0, "conflict": 0}
    status = {r["row"]: r["status"] for r in body["rows"]}
    assert status == {2: "accepted", 3: "duplicate", 4: "excluded", 5: "rejected", 6: "rejected", 7: "rejected",
                      8: "rejected", 9: "rejected", 10: "rejected", 11: "accepted", 12: "rejected", 13: "rejected"}
    reasons = {r["row"]: r["reason"] for r in body["rows"]}
    assert "another ScoutRadioz organization" in reasons[7] and "Another event" in reasons[8]
    assert "qm99" in reasons[9] and "more cells" in reasons[12] and "row 2" in reasons[3]
    accepted = next(r for r in body["rows"] if r["row"] == 2)
    assert accepted["team_number"] == TEAMS[0] and accepted["defense_rating"] == 4  # (7-1)/9*4+1 = 3.67
    assert body["mapping"]["defense_rating"]["column"] == "qDefense"
    for scout in SCOUTS:  # no scout's name in anything returned
        assert scout not in response.text
    assert stored() == {}


@pytest.mark.parametrize(("content", "code"), [
    ("", "empty_file"),
    (HEADER + "\r\n", "empty_file"),
    ("name,score\r\nx,1\r\n", "invalid_header"),
    ("org_key,org_key,event_key\r\n", "invalid_header"),
    ("PK\x00\x03binary", "not_a_csv"),
])
def test_files_that_are_not_a_scoutradioz_export_are_refused_as_a_whole(app, content, code):
    response = preview(member(app, "ada"), content)
    assert response.status_code == 422 and response.json()["error"]["code"] == code


def test_a_season_without_an_approved_mapping_is_refused_not_guessed(app, monkeypatch):
    monkeypatch.delitem(scoutradioz_mappings.APPROVED_FIELD_MAPPINGS, SEASON)
    response = preview(member(app, "ada"), csv_text([GOOD_A]))
    assert response.status_code == 422 and response.json()["error"]["code"] == "mapping_not_configured"


def test_the_2026_mapping_is_the_recorded_one():
    mapping = scoutradioz_mappings.approved_mapping(2026)
    assert mapping is not None and mapping.feeding_rating is None
    assert (mapping.defense_rating.column, mapping.defense_rating.source_min, mapping.defense_rating.source_max,
            mapping.defense_rating.excluded_values, mapping.defense_rating.target_min) == \
        ("qDefenseQuality", 1, 10, ("0",), 1)
    assert scoutradioz_mappings.approved_mapping(2025) is None and scoutradioz_mappings.approved_mapping(None) is None


# --- who may upload ------------------------------------------------------------------------------------------------


def test_only_administrators_may_preview_or_import(app):
    text = csv_text([GOOD_A])
    member(app, "ada")
    base = member(app, "bo")
    for response in (preview(base, text), confirm(base, text)):
        assert response.status_code == 403 and response.json()["error"]["code"] == "permission_denied"
    anonymous = TestClient(app, headers=CSRF)
    assert preview(anonymous, text).status_code == 401
    no_csrf = member(app, "ada2")
    no_csrf.headers.pop("X-StratAI-CSRF")
    assert preview(no_csrf, text).status_code == 403
    assert stored() == {}


# --- the import ----------------------------------------------------------------------------------------------------


def test_the_import_needs_the_previewed_file_and_an_explicit_confirmation(app):
    admin = member(app, "ada")
    text = csv_text(FILE_ROWS)
    changed = confirm(admin, text, digest=sha(text + "x"))
    assert changed.status_code == 409 and changed.json()["error"]["code"] == "file_changed"
    unconfirmed = admin.post("/workspace/scouting/imports", json={"content": text, "file_sha256": sha(text),
                                                                  "confirm": False})
    assert unconfirmed.status_code == 422
    assert stored() == {}


def test_only_accepted_rows_are_imported_and_a_retry_changes_nothing(app):
    admin = member(app, "ada")
    text = csv_text(FILE_ROWS)
    first = confirm(admin, text)
    assert first.status_code == 200, first.text
    body = first.json()
    assert body["import"]["landed"] == 2 and body["import"]["loaded"] == 2 and body["import"]["not_loaded"] == []
    assert body["import"]["metrics_recomputed"] is True
    assert stored() == {(f"{EVENT}_qm1", TEAMS[0]): 4, (f"{EVENT}_qm1", TEAMS[1]): 2}
    for scout in SCOUTS:
        assert scout not in first.text
    log = admin.get("/workspace/activity").json()["entries"]
    entry = next(e for e in log if e["action"] == "scouting_csv_imported")
    assert entry["details"]["loaded"] == 2 and entry["details"]["file_sha256"] == sha(text)

    again = confirm(admin, text)  # a retried or double-clicked confirmation
    assert again.status_code == 200
    assert again.json()["counts"]["accepted"] == 0 and again.json()["counts"]["already_imported"] == 2
    assert again.json()["import"] == {"run_id": None, "landed": 0, "loaded": 0, "not_loaded": [],
                                      "metrics_recomputed": False}
    assert stored() == {(f"{EVENT}_qm1", TEAMS[0]): 4, (f"{EVENT}_qm1", TEAMS[1]): 2}


def test_an_upload_never_overwrites_a_stored_observation(app):
    admin = member(app, "ada")
    assert confirm(admin, csv_text([GOOD_A])).status_code == 200
    edited = csv_text([row(defense="10"), GOOD_B])  # the same scout, match and team, now rated differently
    body = preview(admin, edited).json()
    assert [r["status"] for r in body["rows"]] == ["conflict", "accepted"]
    assert "never overwrites" in body["rows"][0]["reason"]
    assert confirm(admin, edited).json()["import"]["loaded"] == 1
    assert stored() == {(f"{EVENT}_qm1", TEAMS[0]): 4, (f"{EVENT}_qm1", TEAMS[1]): 2}  # row A unchanged
