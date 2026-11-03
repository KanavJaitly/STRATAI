"""Team workspaces end to end, through the real API on an isolated stratai_test_<suffix> database.

Covers registration and ownership verification, the first administrator, invitations, sign-in for every role,
role and permission changes, suspension and removal, password change and recovery, sign-out and session expiry,
refused administrative calls, cross-team isolation, privilege escalation, team scouting, and the existing routes
under both access policies. Synthetic sentinel data only (season 9988, teams 9988xx, workspaces 9988x): nothing
here is evidence about any real team.
"""

from __future__ import annotations

import email as email_parser
from datetime import datetime, timezone
from email import policy as email_policy
from pathlib import Path
from typing import Iterator

import psycopg
import pytest
from fastapi.testclient import TestClient

from api import create_app
from data.config import Settings
from database.connection import Database, DatabaseConfig
from scripts import workspace_operator
from tests.test_live_epa import _isolated_db_name
from workspaces import passwords
from workspaces.sessions import COOKIE_NAME

pytestmark = pytest.mark.skipif(_isolated_db_name() is None, reason="needs an isolated stratai_* database copy")

SEASON, EVENT = 9988, "9988zzzscout"
TEAMS = [998801, 998802, 998803, 998804, 998805, 998806]
MATCHES = {f"{EVENT}_qm{n}": (TEAMS[:3], TEAMS[3:]) if n % 2 else (TEAMS[3:], TEAMS[:3]) for n in (1, 2, 3)}
TEAM_A, TEAM_B, TEAM_C = 99881, 99882, 99883
SETUP, PASSWORD = "setup passphrase 1", "member passphrase 1"
DOMAIN = "@workspaces.test.invalid"
CSRF = {"X-StratAI-CSRF": "1"}


def _db() -> Database:
    return Database(DatabaseConfig(Settings().database_url))


def _clean_workspaces(db: Database) -> None:
    with db.cursor() as c:
        c.execute("DELETE FROM workspaces WHERE team_number = ANY(%s)", ([TEAM_A, TEAM_B, TEAM_C],))
        c.execute("DELETE FROM users WHERE email LIKE %s", (f"%{DOMAIN}",))
        c.execute("DELETE FROM auth_attempts")


@pytest.fixture(scope="module")
def canonical() -> Iterator[None]:
    db = _db()

    def drop() -> None:
        _clean_workspaces(db)
        with db.cursor() as c:
            c.execute("DELETE FROM match_teams WHERE match_key LIKE %s", (f"{EVENT}%",))
            c.execute("DELETE FROM matches WHERE event_key = %s", (EVENT,))
            c.execute("DELETE FROM events WHERE event_key = %s", (EVENT,))
            c.execute("DELETE FROM teams WHERE team_number = ANY(%s)", (TEAMS,))

    drop()
    with db.cursor() as c:
        c.execute("INSERT INTO events (event_key, season, name, end_date) VALUES (%s, %s, 'Sentinel', %s)",
                  (EVENT, SEASON, datetime(2026, 3, 2).date()))
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
def _environment(monkeypatch, canonical) -> Iterator[None]:
    monkeypatch.setattr(passwords, "LOG2_N", 10)
    monkeypatch.setattr(passwords, "PARALLELISM", 1)
    monkeypatch.setenv("ENV", "development")
    for name in ("ACCESS_POLICY", "PUBLIC_APP_URL", "DEV_OUTBOX_DIR", "SMTP_HOST", "SMTP_FROM"):
        monkeypatch.delenv(name, raising=False)
    _clean_workspaces(_db())
    yield
    _clean_workspaces(_db())


def make_app(monkeypatch=None, **env: str):
    if monkeypatch is not None:
        for key, value in env.items():
            monkeypatch.setenv(key, value)
    return create_app(Settings())


def browser(app) -> TestClient:
    """One person's browser: its own cookie jar."""
    return TestClient(app, headers=CSRF)


def email(name: str) -> str:
    return f"{name}{DOMAIN}"


def register(c: TestClient, number: int = TEAM_A, name: str = "Sentinel Robotics") -> dict:
    response = c.post("/auth/teams/register", json={"team_number": number, "team_name": name,
                                                    "setup_password": SETUP})
    assert response.status_code == 201, response.text
    return response.json()


def first_admin(c: TestClient, number: int = TEAM_A, who: str = "ada") -> dict:
    response = c.post("/auth/teams/initial-admin", json={
        "team_number": number, "setup_password": SETUP, "full_name": who.title(), "email": email(who),
        "password": PASSWORD})
    assert response.status_code == 201, response.text
    return response.json()


def verify(number: int = TEAM_A) -> None:
    assert workspace_operator.main(["verify", "--team", str(number), "--operator", "Test Operator",
                                    "--note", "checked against the team's official contact"]) == 0


def workspace(app, number: int = TEAM_A, admin: str = "ada") -> TestClient:
    """A verified workspace with its first administrator signed in."""
    c = browser(app)
    register(c, number)
    first_admin(c, number, admin)
    verify(number)
    return c


def invite(admin: TestClient, who: str, role: str) -> str:
    response = admin.post("/workspace/invitations", json={"email": email(who), "full_name": who.title(),
                                                          "role": role})
    assert response.status_code == 201, response.text
    link = response.json()["invitation_link"]
    assert link.startswith("/auth/invite#token=")
    return link.split("#token=", 1)[1]


def join(app, admin: TestClient, who: str, role: str) -> TestClient:
    c = browser(app)
    response = c.post("/auth/invitations/accept", json={"token": invite(admin, who, role), "password": PASSWORD})
    assert response.status_code == 201, response.text
    return c


def login(c: TestClient, who: str, number: int = TEAM_A, password: str = PASSWORD):
    return c.post("/auth/login", json={"team_number": number, "email": email(who), "password": password})


def member_id(admin: TestClient, who: str) -> int:
    members = admin.get("/workspace/members").json()["members"]
    return next(m["membership_id"] for m in members if m["email"] == email(who))


def code(response) -> str:
    return response.json()["error"]["code"]


# --- registration, ownership verification, the first administrator --------------------------------------------


def test_registering_a_team_creates_a_pending_workspace_and_refuses_a_duplicate(monkeypatch):
    app = make_app()
    c = browser(app)
    body = register(c)
    assert body["verification_status"] == "pending_verification" and body["known_frc_team"] is False
    again = c.post("/auth/teams/register", json={"team_number": TEAM_A, "team_name": "Impostors",
                                                 "setup_password": SETUP})
    assert again.status_code == 409 and code(again) == "team_already_registered"
    bad = c.post("/auth/teams/register", json={"team_number": 0, "team_name": "x", "setup_password": SETUP})
    assert bad.status_code == 422
    weak = c.post("/auth/teams/register", json={"team_number": TEAM_B, "team_name": "x", "setup_password": "weak"})
    assert weak.status_code == 422 and code(weak) == "invalid_input"


def test_the_first_administrator_needs_the_setup_password_which_then_retires():
    app = make_app()
    c = browser(app)
    register(c)
    wrong = c.post("/auth/teams/initial-admin", json={"team_number": TEAM_A, "setup_password": "not the setup one",
                                                      "full_name": "Eve", "email": email("eve"),
                                                      "password": PASSWORD})
    assert wrong.status_code == 401 and code(wrong) == "invalid_setup_credentials"
    session = first_admin(c)
    assert session["authenticated"] and session["role"] == "admin"
    assert session["workspace"]["verification_status"] == "pending_verification"
    assert "team_management" in session["permissions"]
    assert COOKIE_NAME in c.cookies
    second = browser(app).post("/auth/teams/initial-admin", json={
        "team_number": TEAM_A, "setup_password": SETUP, "full_name": "Eve", "email": email("eve"),
        "password": PASSWORD})
    assert second.status_code == 401 and code(second) == "invalid_setup_credentials"


def test_an_unverified_workspace_cannot_invite_or_scout_until_the_operator_verifies_it():
    app = make_app()
    c = browser(app)
    register(c)
    first_admin(c)
    refused = c.post("/workspace/invitations", json={"email": email("sam"), "full_name": "Sam", "role": "scouter"})
    assert refused.status_code == 403 and code(refused) == "workspace_not_verified"
    report = c.post("/workspace/scouting/reports", json={"match_key": f"{EVENT}_qm1", "team_number": TEAMS[0],
                                                         "defense_rating": 3})
    assert report.status_code == 403 and code(report) == "workspace_not_verified"
    # The admin can still configure the pending workspace.
    assert c.get("/workspace/permissions").status_code == 200
    verify()
    assert c.get("/auth/session").json()["workspace"]["verification_status"] == "verified"
    assert c.post("/workspace/invitations", json={"email": email("sam"), "full_name": "Sam",
                                                  "role": "scouter"}).status_code == 201


def test_rejecting_a_squatted_registration_ends_its_sessions_and_frees_the_number():
    app = make_app()
    squatter = browser(app)
    register(squatter, TEAM_C, "Not Really Them")
    first_admin(squatter, TEAM_C, "mallory")
    assert workspace_operator.main(["reject", "--team", str(TEAM_C), "--operator", "Test Operator",
                                    "--note", "the real team never registered"]) == 0
    assert squatter.get("/workspace").status_code == 401
    assert login(browser(app), "mallory", TEAM_C).status_code == 401
    register(browser(app), TEAM_C, "The Real Team")  # the number is free again


# --- invitations and sign-in ---------------------------------------------------------------------------------


def test_invited_members_create_their_own_accounts_and_each_role_gets_its_dashboard():
    app = make_app()
    admin = workspace(app)
    strategy = join(app, admin, "sol", "strategy")
    scouter = join(app, admin, "sky", "scouter")
    second_admin = join(app, admin, "ben", "admin")
    roles = {who: c.get("/auth/session").json() for who, c in
             (("sol", strategy), ("sky", scouter), ("ben", second_admin))}
    assert roles["sol"]["role"] == "strategy" and "match_predictions" in roles["sol"]["permissions"]
    assert "team_management" not in roles["sol"]["permissions"]
    assert roles["sky"]["role"] == "scouter" and "scouting_submit" in roles["sky"]["permissions"]
    assert "match_predictions" not in roles["sky"]["permissions"]
    assert roles["ben"]["role"] == "admin" and "team_management" in roles["ben"]["permissions"]
    # Each signs in again on a fresh browser with their own password; the role is found automatically.
    for who, role in (("ada", "admin"), ("sol", "strategy"), ("sky", "scouter"), ("ben", "admin")):
        response = login(browser(app), who)
        assert response.status_code == 200 and response.json()["role"] == role, who


def test_an_invitation_works_once_and_expires():
    app = make_app()
    admin = workspace(app)
    token = invite(admin, "sky", "scouter")
    preview = browser(app).post("/auth/invitations/preview", json={"token": token})
    assert preview.status_code == 200 and preview.json()["role"] == "scouter"
    assert preview.json()["team_number"] == TEAM_A and preview.json()["existing_account"] is False
    assert browser(app).post("/auth/invitations/accept", json={"token": token, "password": PASSWORD}).status_code == 201
    reused = browser(app).post("/auth/invitations/accept", json={"token": token, "password": PASSWORD})
    assert reused.status_code == 410 and code(reused) == "invitation_invalid"
    late = invite(admin, "lee", "scouter")
    with _db().cursor() as c:
        c.execute("UPDATE invitations SET expires_at = NOW() - interval '1 minute' WHERE email = %s", (email("lee"),))
    expired = browser(app).post("/auth/invitations/accept", json={"token": late, "password": PASSWORD})
    assert expired.status_code == 410 and code(expired) == "invitation_expired"
    # Resending replaces the link: the new one works.
    invitation_id = admin.get("/workspace/members").json()["invitations"][0]["invitation_id"]
    fresh = admin.post(f"/workspace/invitations/{invitation_id}/resend").json()["invitation_link"].split("#token=")[1]
    assert browser(app).post("/auth/invitations/accept", json={"token": fresh, "password": PASSWORD}).status_code == 201


def test_one_person_can_join_a_second_team_only_by_proving_their_existing_password():
    app = make_app()
    admin_a, admin_b = workspace(app, TEAM_A, "ada"), workspace(app, TEAM_B, "bob")
    join(app, admin_a, "sky", "scouter")
    token = invite(admin_b, "sky", "strategy")
    assert browser(app).post("/auth/invitations/preview", json={"token": token}).json()["existing_account"] is True
    wrong = browser(app).post("/auth/invitations/accept", json={"token": token, "password": "another passphrase"})
    assert wrong.status_code == 401 and code(wrong) == "existing_account_password_mismatch"
    assert browser(app).post("/auth/invitations/accept", json={"token": token, "password": PASSWORD}).status_code == 201
    assert login(browser(app), "sky", TEAM_A).json()["role"] == "scouter"
    assert login(browser(app), "sky", TEAM_B).json()["role"] == "strategy"


def test_failed_sign_ins_all_read_the_same_and_are_rate_limited():
    app = make_app()
    workspace(app)
    for attempt in (login(browser(app), "ada", password="wrong passphrase"),
                    login(browser(app), "nobody"),
                    login(browser(app), "ada", TEAM_B)):
        assert attempt.status_code == 401 and code(attempt) == "invalid_credentials"
    for _ in range(4):
        login(browser(app), "ada", password="wrong passphrase")
    limited = login(browser(app), "ada")  # even the right password, once the account is locked out
    assert limited.status_code == 429 and code(limited) == "rate_limited"


def test_every_state_change_needs_the_csrf_header():
    app = make_app()
    bare = TestClient(app)
    response = bare.post("/auth/login", json={"team_number": TEAM_A, "email": email("ada"), "password": PASSWORD})
    assert response.status_code == 403 and code(response) == "csrf_check_failed"


# --- authorization: admin routes, escalation, cross-team isolation ---------------------------------------------


def test_non_administrators_and_strangers_cannot_reach_administrative_routes():
    app = make_app()
    admin = workspace(app)
    strategy, scouter = join(app, admin, "sol", "strategy"), join(app, admin, "sky", "scouter")
    target = member_id(admin, "sky")
    for c, expected in ((browser(app), 401), (scouter, 403), (strategy, 403)):
        assert c.get("/workspace/members").status_code == expected
        assert c.get("/workspace/activity").status_code == expected
        assert c.get("/workspace/permissions").status_code == expected
        assert c.post(f"/workspace/members/{target}/role", json={"role": "admin"}).status_code == expected
        assert c.post("/workspace/invitations", json={"email": email("x"), "full_name": "X",
                                                      "role": "admin"}).status_code == expected
    assert scouter.get("/auth/session").json()["role"] == "scouter"  # nothing changed


def test_members_cannot_escalate_and_administrative_permissions_are_never_grantable():
    app = make_app()
    admin = workspace(app)
    scouter = join(app, admin, "sky", "scouter")
    own = scouter.post(f"/workspace/members/{member_id(admin, 'sky')}/role", json={"role": "admin"})
    assert own.status_code == 403
    assert scouter.post("/workspace/permissions", json={"role": "scouter",
                                                        "grants": {"match_predictions": True}}).status_code == 403
    reserved = admin.post("/workspace/permissions", json={"role": "scouter", "grants": {"team_management": True}})
    assert reserved.status_code == 403 and code(reserved) == "permission_not_grantable"
    with pytest.raises(psycopg.errors.CheckViolation), _db().cursor() as c:
        c.execute("INSERT INTO workspace_role_permissions (workspace_id, role, permission, granted) "
                  "SELECT id, 'scouter', 'team_management', TRUE FROM workspaces WHERE team_number = %s", (TEAM_A,))
    with pytest.raises(psycopg.errors.CheckViolation), _db().cursor() as c:
        c.execute("INSERT INTO workspace_role_permissions (workspace_id, role, permission, granted) "
                  "SELECT id, 'admin', 'team_info', FALSE FROM workspaces WHERE team_number = %s", (TEAM_A,))


def test_one_team_cannot_see_or_change_another_teams_members_or_scouting():
    app = make_app()
    admin_a, admin_b = workspace(app, TEAM_A, "ada"), workspace(app, TEAM_B, "bob")
    scout_a = join(app, admin_a, "sky", "scouter")
    a_member = member_id(admin_a, "sky")
    assert scout_a.post("/workspace/scouting/reports", json={"match_key": f"{EVENT}_qm1", "team_number": TEAMS[0],
                                                             "defense_rating": 4}).status_code == 201
    assignment = admin_a.post("/workspace/scouting/assignments", json={
        "match_key": f"{EVENT}_qm2", "team_number": TEAMS[0], "membership_id": a_member}).json()["assignment_id"]
    b_members = admin_b.get("/workspace/members").json()["members"]
    assert [m["email"] for m in b_members] == [email("bob")]
    for path, body in ((f"/workspace/members/{a_member}/role", {"role": "admin"}),
                       (f"/workspace/members/{a_member}/status", {"status": "suspended"}),
                       (f"/workspace/members/{a_member}/remove", None),
                       (f"/workspace/members/{a_member}/password-reset", None),
                       (f"/workspace/scouting/assignments/{assignment}/cancel", None)):
        response = admin_b.post(path, json=body) if body else admin_b.post(path)
        assert response.status_code == 404, path
    assert admin_b.get("/workspace/scouting/reports", params={"mine": "false"}).json() == []
    assert admin_b.get("/workspace/scouting/summary", params={"event_key": EVENT}).json()["teams"] == []
    assert admin_b.post("/workspace/scouting/assignments", json={
        "match_key": f"{EVENT}_qm2", "team_number": TEAMS[0], "membership_id": a_member}).status_code == 404
    assert len(admin_a.get("/workspace/scouting/reports", params={"mine": "false"}).json()) == 1
    assert "sky" not in str(admin_b.get("/workspace/activity").json())


# --- roles, permissions, suspension, removal ------------------------------------------------------------------


def test_permission_changes_apply_on_the_members_next_request(monkeypatch):
    app = make_app(monkeypatch, ACCESS_POLICY="members")
    admin = workspace(app)
    scouter = join(app, admin, "sky", "scouter")
    route = f"/predictions/matches/{EVENT}_qm1/win-probability"
    assert scouter.get(route).status_code == 403
    changed = admin.post("/workspace/permissions", json={"role": "scouter", "grants": {"match_predictions": True}})
    assert changed.status_code == 200 and changed.json()["changed"] == {"match_predictions": {"from": False,
                                                                                               "to": True}}
    assert scouter.get(route).status_code not in (401, 403)  # past the gate (the model may not be loaded)
    matrix = admin.get("/workspace/permissions").json()["permissions"]
    row = next(r for r in matrix if r["permission"] == "match_predictions")
    assert row["roles"]["scouter"]["granted"] is True and row["roles"]["admin"]["editable"] is False


def test_role_changes_and_the_last_active_administrator_is_protected():
    app = make_app()
    admin = workspace(app)
    join(app, admin, "sol", "strategy")
    ada, sol = member_id(admin, "ada"), member_id(admin, "sol")
    last = admin.post(f"/workspace/members/{ada}/role", json={"role": "scouter"})
    assert last.status_code == 409 and code(last) == "last_active_admin"
    assert admin.post(f"/workspace/members/{sol}/role", json={"role": "admin"}).json()["role"] == "admin"
    # With a second administrator, the first may step down; then the second is the last one.
    assert admin.post(f"/workspace/members/{ada}/role", json={"role": "strategy"}).status_code == 200
    with pytest.raises(psycopg.errors.CheckViolation), _db().cursor() as c:  # the database guard, independently
        c.execute("UPDATE team_memberships SET status = 'suspended' WHERE id = %s", (sol,))


def test_suspension_ends_sessions_at_once_and_reactivation_restores_sign_in():
    app = make_app()
    admin = workspace(app)
    scouter = join(app, admin, "sky", "scouter")
    sky = member_id(admin, "sky")
    assert admin.post(f"/workspace/members/{sky}/status", json={"status": "suspended"}).status_code == 200
    assert scouter.get("/workspace").status_code == 401
    refused = login(browser(app), "sky")
    assert refused.status_code == 403 and code(refused) == "account_inactive"
    assert admin.post(f"/workspace/members/{sky}/status", json={"status": "active"}).status_code == 200
    assert login(browser(app), "sky").status_code == 200
    self_suspend = admin.post(f"/workspace/members/{member_id(admin, 'ada')}/status", json={"status": "suspended"})
    assert self_suspend.status_code == 403 and code(self_suspend) == "cannot_target_self"


def test_removal_ends_access_keeps_history_and_allows_a_later_reinvitation():
    app = make_app()
    admin = workspace(app)
    scouter = join(app, admin, "sky", "scouter")
    sky = member_id(admin, "sky")
    assert admin.post(f"/workspace/members/{sky}/remove").status_code == 200
    assert scouter.get("/workspace").status_code == 401
    assert login(browser(app), "sky").status_code == 403
    assert email("sky") not in [m["email"] for m in admin.get("/workspace/members").json()["members"]]
    back = browser(app).post("/auth/invitations/accept", json={"token": invite(admin, "sky", "strategy"),
                                                               "password": PASSWORD})
    assert back.status_code == 201 and back.json()["role"] == "strategy"


def test_an_administrator_can_rename_a_member_and_change_team_settings():
    app = make_app()
    admin = workspace(app)
    join(app, admin, "sky", "scouter")
    assert admin.post(f"/workspace/members/{member_id(admin, 'sky')}/profile",
                      json={"name": "Sky Walker"}).json()["name"] == "Sky Walker"
    updated = admin.post("/workspace/settings", json={"team_name": "Sentinel Robotics 2",
                                                      "default_event_key": EVENT,
                                                      "scouting_instructions": "Watch the defense."})
    assert updated.status_code == 200 and updated.json()["default_event_key"] == EVENT
    bad = admin.post("/workspace/settings", json={"default_event_key": "0000nowhere"})
    assert bad.status_code == 422
    assert admin.get("/auth/session").json()["workspace"]["team_name"] == "Sentinel Robotics 2"


# --- passwords, sign-out, session expiry -----------------------------------------------------------------------


def test_password_change_needs_the_current_password_and_ends_other_sessions():
    app = make_app()
    admin = workspace(app)
    other = browser(app)
    assert login(other, "ada").status_code == 200
    wrong = admin.post("/auth/password/change", json={"current_password": "not it at all",
                                                      "new_password": "a brand new passphrase"})
    assert wrong.status_code == 403 and code(wrong) == "current_password_incorrect"
    ok = admin.post("/auth/password/change", json={"current_password": PASSWORD,
                                                   "new_password": "a brand new passphrase"})
    assert ok.status_code == 200
    assert admin.get("/workspace").status_code == 200  # this session survives
    assert other.get("/workspace").status_code == 401  # the other one ended
    assert login(browser(app), "ada", password="a brand new passphrase").status_code == 200


def test_an_administrator_issued_reset_link_works_once_and_ends_the_members_sessions():
    app = make_app()
    admin = workspace(app)
    scouter = join(app, admin, "sky", "scouter")
    issued = admin.post(f"/workspace/members/{member_id(admin, 'sky')}/password-reset").json()
    assert issued["emailed"] is False and issued["reset_link"].startswith("/auth/reset#token=")
    token = issued["reset_link"].split("#token=")[1]
    assert browser(app).post("/auth/password/reset", json={"token": token,
                                                           "new_password": "reset passphrase 9"}).status_code == 200
    assert scouter.get("/workspace").status_code == 401
    reused = browser(app).post("/auth/password/reset", json={"token": token, "new_password": "reset passphrase 10"})
    assert reused.status_code == 410 and code(reused) == "reset_link_invalid"
    assert login(browser(app), "sky", password="reset passphrase 9").status_code == 200
    actions = [e["action"] for e in admin.get("/workspace/activity").json()["entries"]]
    assert "password_reset_issued" in actions and "password_reset_completed" in actions


def test_self_service_recovery_emails_a_link_only_when_email_is_configured(monkeypatch, tmp_path: Path):
    plain = make_app()
    workspace(plain)
    answer = browser(plain).post("/auth/password/forgot", json={"team_number": TEAM_A, "email": email("ada")})
    assert answer.status_code == 202 and answer.json() == {"accepted": True, "email_delivery_configured": False}
    outbox = tmp_path / "outbox"
    app = make_app(monkeypatch, PUBLIC_APP_URL="http://localhost:5173", DEV_OUTBOX_DIR=str(outbox))
    unknown = browser(app).post("/auth/password/forgot", json={"team_number": TEAM_A, "email": email("nobody")})
    assert unknown.json() == {"accepted": True, "email_delivery_configured": True}  # the same answer
    assert not outbox.exists()
    browser(app).post("/auth/password/forgot", json={"team_number": TEAM_A, "email": email("ada")})
    (message,) = list(outbox.glob("*.eml"))
    body = email_parser.message_from_bytes(message.read_bytes(), policy=email_policy.default).get_content()
    link = next(line for line in body.splitlines() if "#token=" in line)
    assert link.startswith("http://localhost:5173/auth/reset#token=")
    assert browser(app).post("/auth/password/reset", json={"token": link.split("#token=")[1],
                                                           "new_password": "emailed passphrase 1"}).status_code == 200
    assert login(browser(app), "ada", password="emailed passphrase 1").status_code == 200


def test_sign_out_and_session_expiry_end_access():
    app = make_app()
    admin = workspace(app)
    assert admin.post("/auth/logout").json() == {"authenticated": False}
    assert admin.get("/workspace").status_code == 401
    assert admin.get("/auth/session").json()["authenticated"] is False
    for column, value in (("expires_at", "NOW() - interval '1 minute'"),
                          ("last_seen_at", "NOW() - interval '100 hours'")):
        c = browser(app)
        login(c, "ada")
        assert c.get("/workspace").status_code == 200
        with _db().cursor() as cursor:
            cursor.execute(f"UPDATE auth_sessions SET {column} = {value} WHERE revoked_at IS NULL")
        assert c.get("/workspace").status_code == 401, column


# --- team scouting ------------------------------------------------------------------------------------------------


def test_assignments_reports_and_the_teams_own_summary():
    app = make_app()
    admin = workspace(app)
    strategy, scouter = join(app, admin, "sol", "strategy"), join(app, admin, "sky", "scouter")
    sky = member_id(admin, "sky")
    scouts = strategy.get("/workspace/scouting/scouts")
    assert scouts.status_code == 200 and {s["name"] for s in scouts.json()} == {"Ada", "Sol", "Sky"}
    assert all(set(s) == {"membership_id", "name", "role"} for s in scouts.json())  # no emails or account details
    assert scouter.get("/workspace/scouting/scouts").status_code == 403
    created = strategy.post("/workspace/scouting/assignments", json={"match_key": f"{EVENT}_qm1",
                                                                     "team_number": TEAMS[0], "membership_id": sky})
    assert created.status_code == 201
    assignment = created.json()["assignment_id"]
    assert scouter.post("/workspace/scouting/assignments", json={
        "match_key": f"{EVENT}_qm1", "team_number": TEAMS[1], "membership_id": sky}).status_code == 403
    mine = scouter.get("/workspace/scouting/assignments").json()
    assert [a["assignment_id"] for a in mine] == [assignment] and mine[0]["alliance_color"] == "red"
    invalid = scouter.post("/workspace/scouting/reports", json={"match_key": f"{EVENT}_qm1", "team_number": TEAMS[0],
                                                                "defense_rating": 7})
    assert invalid.status_code == 422
    neither = scouter.post("/workspace/scouting/reports", json={"match_key": f"{EVENT}_qm1",
                                                                "team_number": TEAMS[0]})
    assert neither.status_code == 422
    absent = scouter.post("/workspace/scouting/reports", json={"match_key": f"{EVENT}_qm1", "team_number": 998899,
                                                               "defense_rating": 2})
    assert absent.status_code == 422
    done = scouter.post("/workspace/scouting/reports", json={"match_key": f"{EVENT}_qm1", "team_number": TEAMS[0],
                                                             "defense_rating": 4, "feeding_rating": 2,
                                                             "assignment_id": assignment})
    assert done.status_code == 201
    assert scouter.get("/workspace/scouting/assignments").json() == []  # completed, so no longer open
    assert scouter.post("/workspace/scouting/reports", json={"match_key": f"{EVENT}_qm2", "team_number": TEAMS[0],
                                                             "defense_rating": 2}).status_code == 201
    # The scouter sees their own reports, not the team's summary; strategy sees both.
    assert len(scouter.get("/workspace/scouting/reports").json()) == 2
    assert scouter.get("/workspace/scouting/summary", params={"event_key": EVENT}).status_code == 403
    summary = strategy.get("/workspace/scouting/summary", params={"event_key": EVENT}).json()
    (team,) = summary["teams"]
    assert team["team_number"] == TEAMS[0] and team["reports"] == 2
    assert team["profile"]["defense_score"] == 3.0 and team["profile"]["defense_insufficient_data"] is False
    assert team["profile"]["feeding_insufficient_data"] is True  # one feeding rating is below the minimum
    other = join(app, admin, "lee", "scouter")
    stolen = other.post("/workspace/scouting/reports", json={"match_key": f"{EVENT}_qm1", "team_number": TEAMS[0],
                                                             "defense_rating": 1, "assignment_id": assignment})
    assert stolen.status_code == 403 and code(stolen) == "not_your_assignment"


def test_team_scouting_never_reaches_the_shared_scouting_tables():
    app = make_app()
    admin = workspace(app)
    scouter = join(app, admin, "sky", "scouter")
    scouter.post("/workspace/scouting/reports", json={"match_key": f"{EVENT}_qm1", "team_number": TEAMS[0],
                                                      "defense_rating": 5})
    with _db().cursor() as c:
        c.execute("SELECT count(*) FROM scouting_observations WHERE event_key = %s", (EVENT,))
        assert c.fetchone()[0] == 0
        c.execute("SELECT count(*) FROM raw_source_payloads WHERE source_object_id LIKE %s", (f"{EVENT}%",))
        assert c.fetchone()[0] == 0


# --- activity log and analytics ---------------------------------------------------------------------------------


def test_the_activity_log_records_every_administrative_action():
    app = make_app()
    admin = workspace(app)
    join(app, admin, "sky", "scouter")
    sky = member_id(admin, "sky")
    admin.post(f"/workspace/members/{sky}/role", json={"role": "strategy"})
    admin.post(f"/workspace/members/{sky}/status", json={"status": "suspended"})
    admin.post(f"/workspace/members/{sky}/remove")
    admin.post("/workspace/permissions", json={"role": "scouter", "grants": {"team_analytics": True}})
    admin.post("/workspace/settings", json={"team_name": "Renamed"})
    log = admin.get("/workspace/activity").json()
    actions = {entry["action"] for entry in log["entries"]}
    assert {"workspace_registered", "initial_admin_created", "workspace_verified", "member_invited",
            "invitation_accepted", "account_created", "role_changed", "member_suspended", "member_removed",
            "permissions_changed", "settings_changed"} <= actions
    change = next(e for e in log["entries"] if e["action"] == "role_changed")
    assert change["actor"] == "Ada" and change["target"] == "Sky" and change["details"] == {"from": "scouter",
                                                                                          "to": "strategy"}
    only = admin.get("/workspace/activity", params={"action": "member_removed"}).json()["entries"]
    assert [e["action"] for e in only] == ["member_removed"]
    analytics = admin.get("/workspace/analytics").json()
    assert analytics["members_by_role"]["admin"]["active"] == 1


# --- existing StratAI features under both access policies -----------------------------------------------------


def test_open_access_keeps_every_existing_route_public():
    app = make_app()
    anonymous = TestClient(app)
    assert anonymous.get("/health").status_code == 200
    events = anonymous.get("/events", params={"season": SEASON})
    assert events.status_code == 200 and EVENT in events.text
    assert anonymous.get(f"/events/{EVENT}/matches").status_code == 200


def test_members_access_requires_a_session_and_the_routes_permission(monkeypatch):
    app = make_app(monkeypatch, ACCESS_POLICY="members")
    assert TestClient(app).get("/health").status_code == 200  # probes stay open
    anonymous = TestClient(app).get("/events", params={"season": SEASON})
    assert anonymous.status_code == 401 and code(anonymous) == "not_authenticated"
    admin = workspace(app)
    scouter = join(app, admin, "sky", "scouter")
    assert scouter.get("/events", params={"season": SEASON}).status_code == 200  # team_info
    assert scouter.get(f"/events/{EVENT}/analysis").status_code == 403  # event_analysis is off for scouters
    assert admin.get(f"/events/{EVENT}/analysis").status_code not in (401, 403)
    assert TestClient(app).get("/auth/session").json() == {"authenticated": False, "access_policy": "members",
                                                           "email_delivery_configured": False}
