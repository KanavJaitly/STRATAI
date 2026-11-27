"""Team 11's accounts end to end, through the real API on an isolated stratai_test_<suffix> database.

Covers sign-up with the team join code (right, wrong, closed, rate-limited per address and across all addresses),
ADMIN_EMAILS, unique emails in any case, the 8-character password rule, sign-in, base members refused by every route
but the events list and an event's page (the API, not only the web app), Team Management, the set_role command,
password reset by emailed code (single use, 15-minute expiry, 5 wrong attempts, 3 codes per email per hour, every
session ended), sign-out and session expiry, team scouting, and the access policies.

Needs migration 0015 on the test database. Each test starts from no accounts: the cleanup deletes the team
workspace (which cascades every membership, session, log and team-scouting row) and recreates it exactly as 0015
does, because the database refuses to remove a workspace's last administrator any other way. Synthetic sentinel data
only (season 9988, teams 9988xx): nothing here is evidence about any real team.
"""

from __future__ import annotations

import email as email_parser
import re
from datetime import datetime, timezone
from email import policy as email_policy
from pathlib import Path
from typing import Iterator

import pytest
from fastapi.testclient import TestClient

from api import create_app
from data.config import Settings
from database.connection import Database, DatabaseConfig
from scripts import set_role
from tests.test_live_epa import _isolated_db_name
from workspaces import passwords
from workspaces.sessions import COOKIE_NAME

pytestmark = pytest.mark.skipif(_isolated_db_name() is None, reason="needs an isolated stratai_* database copy")

SEASON, EVENT = 9988, "9988zzzscout"
TEAMS = [998801, 998802, 998803, 998804, 998805, 998806]
MATCHES = {f"{EVENT}_qm{n}": (TEAMS[:3], TEAMS[3:]) if n % 2 else (TEAMS[3:], TEAMS[:3]) for n in (1, 2, 3)}
JOIN_CODE, PASSWORD = "sentinel-join-code-9988", "member pass 1"
ADMIN_JOIN_CODE = "sentinel-admin-code-9988"
DOMAIN = "@workspaces.test.invalid"
ADMIN_EMAILS_ENV = f"ADA{DOMAIN.upper()}"  # ada signs up as an administrator; matched in any case
CSRF = {"X-StratAI-CSRF": "1"}
TEAM_WORKSPACE_SQL = ("INSERT INTO workspaces (team_number, team_name, verification_status, verified_at, verified_by) "
                      "VALUES (11, 'MORT', 'verified', NOW(), 'migration 0015_single_team_auth')")
BASE_PERMISSIONS = ["event_analysis", "qualification_forecast", "team_info"]


def _db() -> Database:
    return Database(DatabaseConfig(Settings().database_url))


def _reset_accounts(db: Database) -> None:
    with db.cursor() as c:
        c.execute("DELETE FROM workspaces")
        c.execute("DELETE FROM users WHERE email LIKE %s", (f"%{DOMAIN}",))
        c.execute("DELETE FROM auth_attempts")
        c.execute(TEAM_WORKSPACE_SQL)


@pytest.fixture(scope="module")
def canonical() -> Iterator[None]:
    db = _db()

    def drop() -> None:
        _reset_accounts(db)
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
    monkeypatch.setenv("TEAM_JOIN_CODE", JOIN_CODE)
    monkeypatch.setenv("ADMIN_EMAILS", ADMIN_EMAILS_ENV)
    monkeypatch.delenv("TEAM_ADMIN_JOIN_CODE", raising=False)
    for name in ("ACCESS_POLICY", "PUBLIC_APP_URL", "DEV_OUTBOX_DIR", "SMTP_HOST", "SMTP_FROM",
                 "AUTH_TRUSTED_PROXY_HOPS"):
        monkeypatch.delenv(name, raising=False)
    _reset_accounts(_db())
    yield
    _reset_accounts(_db())


def make_app(monkeypatch=None, **env: str):
    if monkeypatch is not None:
        for key, value in env.items():
            monkeypatch.setenv(key, value)
    return create_app(Settings())


def browser(app, **headers: str) -> TestClient:
    """One person's browser: its own cookie jar."""
    return TestClient(app, headers={**CSRF, **headers})


def email(name: str) -> str:
    return f"{name}{DOMAIN}"


def code(response) -> str:
    return response.json()["error"]["code"]


def sign_up(c: TestClient, who: str, *, join_code: str = JOIN_CODE, password: str = PASSWORD, address: str | None = None):
    return c.post("/auth/signup", json={"full_name": who.title(), "email": address or email(who),
                                        "password": password, "join_code": join_code})


def member(app, who: str, **headers: str) -> TestClient:
    """A browser signed in as a new member (admin when who is "ada", the one ADMIN_EMAILS entry)."""
    c = browser(app, **headers)
    response = sign_up(c, who)
    assert response.status_code == 201, response.text
    return c


def workspace(app, who: str = "ada") -> TestClient:
    """The team's administrator, signed in (ada is the ADMIN_EMAILS entry). For other test modules."""
    return member(app, who)


def join(app, admin: TestClient, who: str, role: str = "base") -> TestClient:
    """A new member with role, signed in: signs up, then the administrator sets the role."""
    c = member(app, who)
    if role != "base":
        response = admin.post(f"/workspace/members/{member_id(admin, who)}/role", json={"role": role})
        assert response.status_code == 200, response.text
    return c


def login(c: TestClient, who: str, password: str = PASSWORD):
    return c.post("/auth/login", json={"email": email(who), "password": password})


def member_id(admin: TestClient, who: str) -> int:
    members = admin.get("/workspace/members").json()["members"]
    return next(m["membership_id"] for m in members if m["email"] == email(who))


# --- sign-up --------------------------------------------------------------------------------------------------


def test_sign_up_with_the_join_code_creates_a_signed_in_base_member():
    app = make_app()
    c = browser(app)
    response = sign_up(c, "bo")
    assert response.status_code == 201
    body = response.json()
    assert body["authenticated"] is True and body["role"] == "base" and body["permissions"] == BASE_PERMISSIONS
    assert body["workspace"]["team_number"] == 11 and body["user"]["email"] == email("bo")
    assert COOKIE_NAME in c.cookies
    assert c.get("/auth/session").json()["role"] == "base"  # the cookie is a real session


def test_a_wrong_join_code_is_refused_clearly_and_creates_nothing():
    app = make_app()
    response = sign_up(browser(app), "bo", join_code="not-the-code")
    assert response.status_code == 403 and code(response) == "invalid_join_code"
    assert "join code is not correct" in response.json()["error"]["message"]
    with _db().cursor() as cursor:
        cursor.execute("SELECT count(*) FROM users WHERE email = %s", (email("bo"),))
        assert cursor.fetchone()[0] == 0


def test_sign_up_is_closed_without_a_configured_join_code(monkeypatch):
    monkeypatch.delenv("TEAM_JOIN_CODE")
    app = make_app()
    for attempt in ("", "anything"):
        response = sign_up(browser(app), "bo", join_code=attempt)
        assert response.status_code == 403 and code(response) == "signup_closed"
    assert TestClient(app).get("/auth/session").json()["signup_open"] is False


def test_an_email_in_admin_emails_signs_up_as_an_administrator_in_any_case():
    app = make_app()
    response = sign_up(browser(app), "ada", address=f"Ada{DOMAIN}")
    assert response.status_code == 201
    assert response.json()["role"] == "admin" and "team_management" in response.json()["permissions"]
    assert response.json()["user"]["email"] == email("ada")  # stored lowercased


def test_the_admin_join_code_signs_up_an_administrator_and_the_member_code_a_base_member(monkeypatch):
    app = make_app(monkeypatch, TEAM_ADMIN_JOIN_CODE=ADMIN_JOIN_CODE)
    admin = sign_up(browser(app), "cy", join_code=ADMIN_JOIN_CODE)
    assert admin.status_code == 201 and admin.json()["role"] == "admin"
    base = sign_up(browser(app), "di", join_code=JOIN_CODE)
    assert base.status_code == 201 and base.json()["role"] == "base"
    wrong_case = sign_up(browser(app), "ed", join_code=ADMIN_JOIN_CODE.upper())
    assert wrong_case.status_code == 403 and code(wrong_case) == "invalid_join_code"


def test_the_admin_join_code_alone_opens_sign_up_for_administrators_only(monkeypatch):
    monkeypatch.delenv("TEAM_JOIN_CODE")
    app = make_app(monkeypatch, TEAM_ADMIN_JOIN_CODE=ADMIN_JOIN_CODE)
    assert TestClient(app).get("/auth/session").json()["signup_open"] is True
    assert sign_up(browser(app), "cy", join_code=JOIN_CODE).status_code == 403
    assert sign_up(browser(app), "cy", join_code=ADMIN_JOIN_CODE).json()["role"] == "admin"


def test_an_email_is_unique_whatever_its_case():
    app = make_app()
    member(app, "bo")
    again = sign_up(browser(app), "bo", address=f"BO{DOMAIN.upper()}")
    assert again.status_code == 409 and code(again) == "email_already_registered"


def test_passwords_need_eight_characters_and_nothing_else():
    app = make_app()
    short = sign_up(browser(app), "bo", password="seven77")
    assert short.status_code == 422 and "at least 8 characters" in short.json()["error"]["message"]
    assert sign_up(browser(app), "bo", password="aaaaaaaa").status_code == 201


def test_wrong_join_codes_are_rate_limited_per_address_even_against_the_right_code(monkeypatch):
    app = make_app(monkeypatch, AUTH_TRUSTED_PROXY_HOPS="1")
    here = {"X-Forwarded-For": "203.0.113.7"}
    for _ in range(10):
        assert sign_up(browser(app, **here), "bo", join_code="guess").status_code == 403
    limited = sign_up(browser(app, **here), "bo")
    assert limited.status_code == 429 and code(limited) == "rate_limited"
    # Another address is unaffected, and correct sign-ups never count against anyone.
    assert sign_up(browser(app, **{"X-Forwarded-For": "203.0.113.8"}), "bo").status_code == 201
    for who in ("cy", "di", "ed"):
        assert sign_up(browser(app, **{"X-Forwarded-For": "203.0.113.8"}), who).status_code == 201


def test_wrong_join_codes_are_rate_limited_across_all_addresses(monkeypatch):
    app = make_app(monkeypatch, AUTH_TRUSTED_PROXY_HOPS="1")
    for n in range(50):  # 50 wrong codes, each from its own address: no per-address limit trips
        response = sign_up(browser(app, **{"X-Forwarded-For": f"198.51.100.{n}"}), "bo", join_code=f"guess{n}")
        assert response.status_code == 403, n
    fresh = sign_up(browser(app, **{"X-Forwarded-For": "192.0.2.1"}), "bo")  # a new address, the right code
    assert fresh.status_code == 429 and code(fresh) == "rate_limited"


# --- sign-in --------------------------------------------------------------------------------------------------


def test_sign_in_takes_only_email_and_password():
    app = make_app()
    member(app, "bo")
    c = browser(app)
    response = c.post("/auth/login", json={"email": f"Bo{DOMAIN}", "password": PASSWORD})
    assert response.status_code == 200 and response.json()["role"] == "base"
    with_team = c.post("/auth/login", json={"team_number": 11, "email": email("bo"), "password": PASSWORD})
    assert with_team.status_code == 422  # no team number field exists


def test_failed_sign_ins_all_read_the_same_and_are_rate_limited():
    app = make_app()
    member(app, "bo")
    for attempt in (login(browser(app), "bo", password="wrong pass"), login(browser(app), "nobody")):
        assert attempt.status_code == 401 and code(attempt) == "invalid_credentials"
    for _ in range(4):
        login(browser(app), "bo", password="wrong pass")
    limited = login(browser(app), "bo")  # even the right password, once the account is locked out
    assert limited.status_code == 429 and code(limited) == "rate_limited"


def test_every_state_change_needs_the_csrf_header():
    app = make_app()
    bare = TestClient(app)
    for path, body in (("/auth/login", {"email": email("bo"), "password": PASSWORD}),
                       ("/auth/signup", {"full_name": "Bo", "email": email("bo"), "password": PASSWORD,
                                         "join_code": JOIN_CODE})):
        response = bare.post(path, json=body)
        assert response.status_code == 403 and code(response) == "csrf_check_failed"


def test_the_removed_multi_team_routes_are_gone():
    paths = set(make_app().openapi()["paths"])
    for gone in ("/auth/teams/register", "/auth/teams/initial-admin", "/auth/invitations/preview",
                 "/auth/invitations/accept", "/workspace/invitations", "/workspace/permissions",
                 "/workspace/members/{membership_id}/password-reset"):
        assert gone not in paths
    assert "/auth/signup" in paths


def test_the_session_reports_a_database_without_the_account_tables(monkeypatch):
    import api.routes.auth as auth_routes

    monkeypatch.setattr(auth_routes, "accounts_schema_present", lambda database: False)
    app = make_app()
    answer = TestClient(app, cookies={COOKIE_NAME: "a-stale-cookie"}).get("/auth/session")
    assert answer.status_code == 200 and answer.json()["accounts_available"] is False
    monkeypatch.undo()
    assert TestClient(app).get("/auth/session").json()["accounts_available"] is True  # the real check, 0015 applied


# --- what a base member may reach -----------------------------------------------------------------------------

# The only routes a base member may call: the events list and an event's page (plus their own session).
BASE_ROUTES = {"/events", "/events/{event_key}/teams", "/events/{event_key}/matches", "/events/{event_key}/analysis",
               "/events/{event_key}/qualification-forecast", "/workspace/team-events",
               "/explorer/seasons/{season}/events"}  # the members' event chooser (audit 2026-11-26)
PUBLIC_ROUTES = {"/health", "/ready", "/auth/session"}
PATH_VALUES = {"season": str(SEASON), "event_key": EVENT, "team_number": str(TEAMS[0]), "match_key": f"{EVENT}_qm1"}


def _concrete(path: str) -> str:
    return re.sub(r"\{(\w+)\}", lambda m: PATH_VALUES.get(m.group(1), "1"), path)


def test_a_base_member_is_refused_by_every_read_route_but_the_event_ones(monkeypatch):
    """Enumerated from the live OpenAPI schema, so a route added later is covered without editing this test."""
    app = make_app(monkeypatch, ACCESS_POLICY="members")
    base = member(app, "bo")
    query = {"season": SEASON, "event_key": EVENT}
    reads = sorted(path for path, operations in app.openapi()["paths"].items() if "get" in operations)
    refused = [path for path in reads if path not in BASE_ROUTES | PUBLIC_ROUTES]
    assert "/explorer/seasons" in refused and "/workspace" in refused and "/workspace/members" in refused
    for path in refused:
        response = base.get(_concrete(path), params=query)
        assert response.status_code == 403, (path, response.status_code, response.text[:200])
        assert code(response) == "permission_denied", path
    for path in BASE_ROUTES:
        response = base.get(_concrete(path), params=query)
        assert response.status_code not in (401, 403), (path, response.text[:200])


def test_a_base_member_is_refused_by_admin_only_writes(monkeypatch):
    app = make_app(monkeypatch, ACCESS_POLICY="members")
    admin, base = member(app, "ada"), member(app, "bo")
    ada = member_id(admin, "ada")
    for path, body in (
        (f"/workspace/members/{ada}/role", {"role": "base"}),
        (f"/workspace/members/{ada}/remove", None),
        ("/workspace/settings", {"team_name": "Hijacked"}),
        ("/workspace/scouting/reports", {"match_key": f"{EVENT}_qm1", "team_number": TEAMS[0], "defense_rating": 3}),
        ("/workspace/scouting/assignments", {"match_key": f"{EVENT}_qm1", "team_number": TEAMS[0],
                                             "membership_id": ada}),
        ("/workspace/alliance-selection/drafts", {"event_key": EVENT, "record_uid": "u", "action_id": "a"}),
        (f"/strategy/matches/{EVENT}_qm1/assess", {"side": "red", "strategy": {}}),
    ):
        response = base.post(path, json=body)
        assert response.status_code == 403, (path, response.text[:200])
    own = base.post(f"/workspace/members/{member_id(admin, 'bo')}/role", json={"role": "admin"})
    assert own.status_code == 403  # no self-promotion


def test_an_administrator_reaches_the_admin_routes(monkeypatch):
    app = make_app(monkeypatch, ACCESS_POLICY="members")
    admin = member(app, "ada")
    for path in ("/workspace", "/workspace/members", "/explorer/seasons", "/workspace/activity",
                 f"/events/{EVENT}/analysis"):
        assert admin.get(path).status_code not in (401, 403), path


def test_members_access_requires_a_session(monkeypatch):
    app = make_app(monkeypatch, ACCESS_POLICY="members")
    anonymous = TestClient(app)
    assert anonymous.get("/health").status_code == 200  # probes stay open
    for path in ("/events", f"/events/{EVENT}", "/explorer/seasons"):
        response = anonymous.get(path, params={"season": SEASON})
        assert response.status_code in (401, 404, 405), path
    events = anonymous.get("/events", params={"season": SEASON})
    assert events.status_code == 401 and code(events) == "not_authenticated"
    assert anonymous.get("/auth/session").json() == {"authenticated": False, "access_policy": "members",
                                                     "email_delivery_configured": False, "signup_open": True,
                                                     "accounts_available": True}


def test_open_access_keeps_the_existing_routes_public_in_development():
    app = make_app()
    anonymous = TestClient(app)
    events = anonymous.get("/events", params={"season": SEASON})
    assert events.status_code == 200 and EVENT in events.text


# --- Team Management and the command line --------------------------------------------------------------------


def test_an_administrator_changes_roles_and_the_change_applies_on_the_next_request(monkeypatch):
    app = make_app(monkeypatch, ACCESS_POLICY="members")
    admin, base = member(app, "ada"), member(app, "bo")
    assert base.get("/explorer/seasons").status_code == 403
    bo = member_id(admin, "bo")
    assert admin.post(f"/workspace/members/{bo}/role", json={"role": "admin"}).json()["role"] == "admin"
    assert base.get("/explorer/seasons").status_code == 200  # no new sign-in needed
    assert admin.post(f"/workspace/members/{bo}/role", json={"role": "coach"}).status_code == 422  # unknown role


def test_the_last_active_administrator_is_protected():
    app = make_app()
    admin = member(app, "ada")
    member(app, "bo")
    last = admin.post(f"/workspace/members/{member_id(admin, 'ada')}/role", json={"role": "base"})
    assert last.status_code == 409 and code(last) == "last_active_admin"


def test_removal_ends_access_at_once_and_keeps_the_email_taken():
    app = make_app()
    admin, base = member(app, "ada"), member(app, "bo")
    assert admin.post(f"/workspace/members/{member_id(admin, 'bo')}/remove").status_code == 200
    assert base.get("/auth/session").json()["authenticated"] is False
    refused = login(browser(app), "bo")
    assert refused.status_code == 403 and code(refused) == "account_inactive"
    assert email("bo") not in [m["email"] for m in admin.get("/workspace/members").json()["members"]]
    again = sign_up(browser(app), "bo")
    assert again.status_code == 409 and code(again) == "email_already_registered"


def test_set_role_promotes_reactivates_and_refuses_what_it_should(capsys):
    app = make_app()
    admin = member(app, "ada")
    member(app, "bo")
    assert set_role.main([f"BO{DOMAIN.upper()}", "admin"], database=_db()) == 0
    assert login(browser(app), "bo").json()["role"] == "admin"
    assert set_role.main([email("bo"), "base"], database=_db()) == 0
    admin.post(f"/workspace/members/{member_id(admin, 'bo')}/remove")
    assert login(browser(app), "bo").status_code == 403
    assert set_role.main([email("bo"), "base"], database=_db()) == 0  # restores a removed member
    assert login(browser(app), "bo").json()["role"] == "base"
    assert set_role.main([email("nobody"), "admin"], database=_db()) == 1
    assert "member_not_found" in capsys.readouterr().err
    assert set_role.main([email("ada"), "base"], database=_db()) == 1  # the last active administrator
    assert "last_active_admin" in capsys.readouterr().err
    with pytest.raises(SystemExit):
        set_role.main([email("bo"), "scouter"], database=_db())  # only admin or base
    actions = [e["action"] for e in admin.get("/workspace/activity").json()["entries"]]
    assert actions.count("role_changed") >= 2 and "member_reactivated" in actions


# --- passwords -----------------------------------------------------------------------------------------------


def test_password_change_needs_the_current_password_and_ends_other_sessions():
    app = make_app()
    first = member(app, "bo")
    second = browser(app)
    login(second, "bo")
    wrong = first.post("/auth/password/change", json={"current_password": "nope", "new_password": "new pass 1"})
    assert wrong.status_code == 403 and code(wrong) == "current_password_incorrect"
    assert first.post("/auth/password/change", json={"current_password": PASSWORD,
                                                     "new_password": "new pass 1"}).status_code == 200
    assert first.get("/auth/session").json()["authenticated"] is True
    assert second.get("/auth/session").json()["authenticated"] is False


def _reset_app(monkeypatch, tmp_path: Path):
    outbox = tmp_path / "outbox"
    return make_app(monkeypatch, DEV_OUTBOX_DIR=str(outbox)), outbox


def _codes(outbox: Path) -> list[str]:
    """Every code emailed so far, oldest first."""
    found = []
    # By write time: the outbox file names carry the time only to the second, then a random suffix.
    messages = sorted(outbox.glob("*.eml"), key=lambda path: path.stat().st_mtime_ns) if outbox.exists() else []
    for message in messages:
        body = email_parser.message_from_bytes(message.read_bytes(), policy=email_policy.default).get_content()
        found.append(re.search(r"Your code is: (\d{6})", body).group(1))
    return found


def _reset(c: TestClient, who: str, reset_code: str, new_password: str = "reset pass 1"):
    return c.post("/auth/password/reset", json={"email": email(who), "code": reset_code,
                                                "new_password": new_password})


def test_a_reset_code_is_emailed_ends_every_session_and_signs_in(monkeypatch, tmp_path):
    app, outbox = _reset_app(monkeypatch, tmp_path)
    other_session = member(app, "bo")
    asked = browser(app).post("/auth/password/forgot", json={"email": f"BO{DOMAIN.upper()}"})
    assert asked.status_code == 202 and asked.json() == {"accepted": True, "email_delivery_configured": True}
    (reset_code,) = _codes(outbox)
    c = browser(app)
    response = _reset(c, "bo", reset_code)
    assert response.status_code == 200 and response.json()["authenticated"] is True
    assert c.get("/auth/session").json()["user"]["email"] == email("bo")  # signed in by the reset
    assert other_session.get("/auth/session").json()["authenticated"] is False  # every earlier session ended
    assert login(browser(app), "bo", password="reset pass 1").status_code == 200
    with _db().cursor() as cursor:  # only a salted hash is stored, never the code
        cursor.execute("SELECT code_hash, code_salt FROM password_reset_codes")
        for stored_hash, salt in cursor.fetchall():
            assert reset_code not in (stored_hash, salt)


def test_a_reset_code_works_once(monkeypatch, tmp_path):
    app, outbox = _reset_app(monkeypatch, tmp_path)
    member(app, "bo")
    browser(app).post("/auth/password/forgot", json={"email": email("bo")})
    (reset_code,) = _codes(outbox)
    assert _reset(browser(app), "bo", reset_code).status_code == 200
    again = _reset(browser(app), "bo", reset_code, "another pass")
    assert again.status_code == 410 and code(again) == "reset_code_invalid"


def test_a_reset_code_expires_after_fifteen_minutes(monkeypatch, tmp_path):
    app, outbox = _reset_app(monkeypatch, tmp_path)
    member(app, "bo")
    browser(app).post("/auth/password/forgot", json={"email": email("bo")})
    (reset_code,) = _codes(outbox)
    with _db().cursor() as cursor:
        cursor.execute("SELECT expires_at - created_at FROM password_reset_codes")
        assert cursor.fetchone()[0].total_seconds() == 15 * 60
        cursor.execute("UPDATE password_reset_codes SET expires_at = NOW() - interval '1 second'")
    expired = _reset(browser(app), "bo", reset_code)
    assert expired.status_code == 410 and code(expired) == "reset_code_invalid"
    assert login(browser(app), "bo").status_code == 200  # the password is unchanged


def test_a_reset_code_dies_after_five_wrong_attempts(monkeypatch, tmp_path):
    app, outbox = _reset_app(monkeypatch, tmp_path)
    member(app, "bo")
    browser(app).post("/auth/password/forgot", json={"email": email("bo")})
    (reset_code,) = _codes(outbox)
    wrong = f"{(int(reset_code) + 1) % 1_000_000:06d}"
    for attempt in range(5):
        response = _reset(browser(app), "bo", wrong)
        assert response.status_code == 410, attempt
    with _db().cursor() as cursor:
        cursor.execute("SELECT failed_attempts FROM password_reset_codes")
        assert cursor.fetchone()[0] == 5
    dead = _reset(browser(app), "bo", reset_code)  # the right code, too late
    assert dead.status_code == 410 and code(dead) == "reset_code_invalid"
    assert login(browser(app), "bo").status_code == 200


def test_asking_again_retires_the_old_code_and_is_limited_to_three_per_email_per_hour(monkeypatch, tmp_path):
    app, outbox = _reset_app(monkeypatch, tmp_path)
    member(app, "bo")
    for _ in range(3):
        assert browser(app).post("/auth/password/forgot", json={"email": email("bo")}).status_code == 202
    fourth = browser(app).post("/auth/password/forgot", json={"email": f"Bo{DOMAIN}"})  # any case is one email
    assert fourth.status_code == 429 and code(fourth) == "rate_limited"
    first, _, latest = _codes(outbox)
    if first != latest:  # 1 in a million they coincide
        assert _reset(browser(app), "bo", first).status_code == 410  # retired by the later request
    assert _reset(browser(app), "bo", latest).status_code == 200


def test_forgot_password_never_reveals_whether_an_account_exists(monkeypatch, tmp_path):
    plain = make_app()
    member(plain, "bo")
    answer = browser(plain).post("/auth/password/forgot", json={"email": email("bo")})
    assert answer.json() == {"accepted": True, "email_delivery_configured": False}
    app, outbox = _reset_app(monkeypatch, tmp_path)
    unknown = browser(app).post("/auth/password/forgot", json={"email": email("nobody")})
    known = browser(app).post("/auth/password/forgot", json={"email": email("bo")})
    assert unknown.status_code == known.status_code == 202 and unknown.json() == known.json()
    assert len(_codes(outbox)) == 1  # only the real account was emailed


# --- sessions, scouting, activity ----------------------------------------------------------------------------


def test_sign_out_and_session_expiry_end_access():
    app = make_app()
    admin = member(app, "ada")
    assert admin.post("/auth/logout").json() == {"authenticated": False}
    assert admin.get("/workspace").status_code == 401
    for column, value in (("expires_at", "NOW() - interval '1 minute'"),
                          ("last_seen_at", "NOW() - interval '100 hours'")):
        c = browser(app)
        login(c, "ada")
        assert c.get("/workspace").status_code == 200
        with _db().cursor() as cursor:
            cursor.execute(f"UPDATE auth_sessions SET {column} = {value} WHERE revoked_at IS NULL")
        assert c.get("/workspace").status_code == 401, column


def test_administrators_keep_team_scouting_and_base_members_cannot_use_it():
    app = make_app()
    admin, base = member(app, "ada"), member(app, "bo")
    ada = member_id(admin, "ada")
    created = admin.post("/workspace/scouting/assignments", json={"match_key": f"{EVENT}_qm1",
                                                                  "team_number": TEAMS[0], "membership_id": ada})
    assert created.status_code == 201
    done = admin.post("/workspace/scouting/reports", json={"match_key": f"{EVENT}_qm1", "team_number": TEAMS[0],
                                                           "defense_rating": 4, "assignment_id":
                                                               created.json()["assignment_id"]})
    assert done.status_code == 201
    summary = admin.get("/workspace/scouting/summary", params={"event_key": EVENT}).json()
    assert summary["teams"][0]["team_number"] == TEAMS[0]
    for path in ("/workspace/scouting/assignments", "/workspace/scouting/reports", "/workspace/scouting/scouts"):
        assert base.get(path).status_code == 403, path
    with _db().cursor() as cursor:  # team scouting never reaches the shared scouting tables
        cursor.execute("SELECT count(*) FROM scouting_observations WHERE event_key = %s", (EVENT,))
        assert cursor.fetchone()[0] == 0


def test_a_resubmitted_scouting_report_is_stored_once_and_a_correction_supersedes_it():
    """Audit 2026-11-26: a retried or double-tapped submit used to add a second row, counted twice in the summary."""
    app = make_app()
    admin = member(app, "ada")
    body = {"match_key": f"{EVENT}_qm1", "team_number": TEAMS[0], "defense_rating": 4, "notes": "held the lane"}
    first = admin.post("/workspace/scouting/reports", json=body)
    again = admin.post("/workspace/scouting/reports", json=body)
    assert first.status_code == 201 and again.status_code == 201
    assert again.json()["report_id"] == first.json()["report_id"]
    team = admin.get("/workspace/scouting/summary", params={"event_key": EVENT}).json()["teams"][0]
    assert team["reports"] == 1
    corrected = admin.post("/workspace/scouting/reports", json={**body, "defense_rating": 2})
    assert corrected.json()["report_id"] != first.json()["report_id"]
    team = admin.get("/workspace/scouting/summary", params={"event_key": EVENT}).json()["teams"][0]
    assert team["reports"] == 1  # the scout's latest report for this match and team, not both
    assert len(admin.get("/workspace/scouting/reports", params={"mine": "true"}).json()) == 2  # both kept in history


def test_the_activity_log_records_sign_ups_and_administrative_actions():
    app = make_app()
    admin = member(app, "ada")
    member(app, "bo")
    bo = member_id(admin, "bo")
    admin.post(f"/workspace/members/{bo}/role", json={"role": "admin"})
    admin.post(f"/workspace/members/{bo}/remove")
    entries = admin.get("/workspace/activity").json()["entries"]
    actions = [e["action"] for e in entries]
    assert actions.count("account_created") == 2
    assert {"role_changed", "member_removed"} <= set(actions)
    created = [e for e in entries if e["action"] == "account_created"]
    assert {e["details"]["role"] for e in created} == {"admin", "base"}
    analytics = admin.get("/workspace/analytics").json()
    assert set(analytics["members_by_role"]) == {"admin", "base", "strategy", "drive", "scout"} and "pending_invitations" not in analytics


def test_forgot_password_does_the_same_work_for_any_account_and_sends_after_answering(monkeypatch, tmp_path):
    """The response path never looks the account up: it checks the format and the limits, answers, and leaves the
    lookup and the email to a background task, so its timing cannot reveal whether the account exists."""
    import workspaces.accounts as accounts_module

    app, _ = _reset_app(monkeypatch, tmp_path)
    member(app, "bo")
    scheduled: list[str] = []
    monkeypatch.setattr(accounts_module, "send_reset_code", lambda database, settings, to: scheduled.append(to))
    answers = [browser(app).post("/auth/password/forgot", json={"email": email(who)}) for who in ("bo", "nobody")]
    assert [a.status_code for a in answers] == [202, 202] and answers[0].json() == answers[1].json()
    assert scheduled == [email("bo"), email("nobody")]  # the same work for an existing and a missing account
    with _db().cursor() as cursor:
        cursor.execute("SELECT count(*) FROM password_reset_codes")
        assert cursor.fetchone()[0] == 0  # nothing account-specific happened in the request


def test_a_failed_reset_email_never_reaches_the_caller(monkeypatch, tmp_path):
    import workspaces.mailer as mailer_module

    app, _ = _reset_app(monkeypatch, tmp_path)
    member(app, "bo")

    def broken(*args, **kwargs):
        raise RuntimeError("smtp down")

    monkeypatch.setattr(mailer_module, "send", broken)
    answer = browser(app).post("/auth/password/forgot", json={"email": email("bo")})
    assert answer.status_code == 202 and answer.json()["accepted"] is True


# --- roles beyond admin and base (migration 0016) -------------------------------------------------------------

def test_each_new_role_reaches_its_own_pages_and_nothing_more(monkeypatch):
    app = make_app(monkeypatch, ACCESS_POLICY="members")
    admin = member(app, "ada")
    strategy, drive, scout = join(app, admin, "sol", "strategy"), join(app, admin, "dee", "drive"), join(app, admin, "sky", "scout")
    labels = {m["email"]: m["role_label"] for m in admin.get("/workspace/members").json()["members"]}
    assert labels[email("sol")] == "Strategy team" and labels[email("dee")] == "Drive team" and labels[email("sky")] == "Scout"
    reach = {  # path -> which of (strategy, drive, scout) may read it
        f"/events/{EVENT}/analysis": (True, True, True),
        f"/predictions/matches/{EVENT}_qm1/win-probability": (True, True, False),
        f"/teams/{TEAMS[0]}/events/{EVENT}/strength": (True, True, False),
        f"/events/{EVENT}/alliance-selection/candidates": (True, False, False),
        "/workspace/scouting/assignments": (False, False, True),
        "/workspace/members": (False, False, False),
        "/workspace/settings": (False, False, False),
        "/explorer/seasons": (False, False, False),
    }
    for path, allowed in reach.items():
        for who, ok in zip((strategy, drive, scout), allowed):
            status = who.get(path).status_code
            assert (status not in (401, 403)) == ok, (path, ok, status)
    assert strategy.get("/workspace/alliance-selection/drafts", params={"event_key": EVENT}).status_code == 200
    # the drive team reads the engine's plan for a scheduled match, and nothing else of the strategy tools
    plan = f"/strategy/matches/{EVENT}_qm1/recommend"
    assert drive.post(plan, json={"side": "red"}).status_code not in (401, 403)
    assert scout.post(plan, json={"side": "red"}).status_code == 403
    for path, body in ((f"/strategy/matches/{EVENT}_qm1/assess", {"side": "red", "strategy": {}}),
                       (f"/strategy/matches/{EVENT}_qm1/compare", {"side": "red", "first": {}, "second": {}}),
                       ("/strategy/hypothetical/recommend", {"side": "red"})):
        assert drive.post(path, json=body).status_code == 403, path
        assert strategy.post(path, json=body).status_code != 403, path
    for who in (strategy, drive, scout):  # nobody but an administrator manages members
        assert who.post(f"/workspace/members/{member_id(admin, 'sky')}/role", json={"role": "admin"}).status_code == 403


def test_the_role_change_to_a_new_role_is_logged_and_counted(monkeypatch):
    app = make_app(monkeypatch, ACCESS_POLICY="members")
    admin = member(app, "ada")
    join(app, admin, "sol", "strategy")
    analytics = admin.get("/workspace/analytics").json()
    assert set(analytics["members_by_role"]) == {"admin", "base", "strategy", "drive", "scout"}
    assert analytics["members_by_role"]["strategy"]["active"] == 1


# --- the team's events and its current event -------------------------------------------------------------------

def _dated_events(today):
    """Three sentinel events relative to today: one finished, one on now, one ahead."""
    from datetime import timedelta
    rows = {"9988zzzpast": (today - timedelta(days=30), today - timedelta(days=28)),
            "9988zzznow": (today - timedelta(days=1), today + timedelta(days=1)),
            "9988zzznext": (today + timedelta(days=20), today + timedelta(days=22))}
    with _db().cursor() as c:
        for key, (start, end) in rows.items():
            c.execute("INSERT INTO events (event_key, season, name, start_date, end_date) VALUES (%s, %s, %s, %s, %s) "
                      "ON CONFLICT (event_key) DO UPDATE SET start_date = EXCLUDED.start_date, end_date = EXCLUDED.end_date",
                      (key, SEASON, key, start, end))
    return list(rows)


def _drop_dated_events(keys):
    with _db().cursor() as c:
        c.execute("DELETE FROM events WHERE event_key = ANY(%s)", (keys,))


def test_the_current_event_follows_the_calendar_and_a_pin_overrides_it(monkeypatch):
    from workspaces.management import _today
    keys = _dated_events(_today())
    try:
        app = make_app(monkeypatch, ACCESS_POLICY="members")
        admin, base = member(app, "ada"), member(app, "bo")
        saved = admin.post("/workspace/settings", json={"team_event_keys": ["9988zzznext", "9988zzzpast", "9988zzznow"]})
        assert saved.status_code == 200, saved.text
        body = saved.json()
        assert body["team_event_keys"] == ["9988zzzpast", "9988zzznow", "9988zzznext"]  # by date
        assert body["current_event_key"] == "9988zzznow" and body["current_reason"] == "happening"
        assert body["default_event_key"] == "9988zzznow"  # what the dashboards open on
        assert [e["status"] for e in body["team_events"]] == ["past", "happening", "upcoming"]
        # every member reads the team's events (not only administrators)
        seen = base.get("/workspace/team-events").json()
        assert seen["current_event_key"] == "9988zzznow" and len(seen["team_events"]) == 3
        # without an event on now, the next one; without a next one, the most recent
        admin.post("/workspace/settings", json={"team_event_keys": ["9988zzzpast", "9988zzznext"]})
        assert base.get("/workspace/team-events").json()["current_reason"] == "next"
        admin.post("/workspace/settings", json={"team_event_keys": ["9988zzzpast"]})
        assert base.get("/workspace/team-events").json()["current_event_key"] == "9988zzzpast"
        # a pin wins, joins the list, and unpinning goes back to automatic
        pinned = admin.post("/workspace/settings", json={"pinned_event_key": EVENT}).json()
        assert pinned["current_event_key"] == EVENT and pinned["current_reason"] == "pinned" and EVENT in pinned["team_event_keys"]
        unpinned = admin.post("/workspace/settings", json={"pinned_event_key": None}).json()
        assert unpinned["current_reason"] == "most_recent" and unpinned["pinned_event_key"] is None
        # the overview the dashboards read carries the computed current event
        assert admin.get("/workspace").json()["settings"]["default_event_key"] == "9988zzzpast"
    finally:
        _drop_dated_events(keys)


def test_team_events_are_checked_and_only_administrators_change_them(monkeypatch):
    app = make_app(monkeypatch, ACCESS_POLICY="members")
    admin, base = member(app, "ada"), member(app, "bo")
    unknown = admin.post("/workspace/settings", json={"team_event_keys": [EVENT, "1999nosuchevent"]})
    assert unknown.status_code == 422 and code(unknown) == "invalid_input"
    deduped = admin.post("/workspace/settings", json={"team_event_keys": [EVENT, EVENT]}).json()
    assert deduped["team_event_keys"] == [EVENT]
    assert base.post("/workspace/settings", json={"team_event_keys": []}).status_code == 403
    legacy = admin.post("/workspace/settings", json={"default_event_key": EVENT}).json()  # an older client's pin
    assert legacy["pinned_event_key"] == EVENT
    log = admin.get("/workspace/activity").json()["entries"]
    assert any("team_event_keys" in (e["details"] or {}) for e in log if e["action"] == "settings_changed")


# --- the trusted proxy chain (audit 2026-11-26, workstream 5) -------------------------------------------------------
# The hosted chain is browser -> Vercel (rewrite) -> Render (load balancer) -> the app: Vercel's X-Forwarded-For entry
# is the browser, Render appends Vercel's egress address, so AUTH_TRUSTED_PROXY_HOPS=2 and the rate limits key on the
# entry two from the right. Whatever a client puts left of that is ignored.

VERCEL_EGRESS = "76.76.21.21"  # documentation stand-in for Vercel's outbound address; any address works here


def via_proxies(client_address: str, *, forged: str | None = None) -> dict[str, str]:
    """The X-Forwarded-For the app receives for a browser at client_address behind both proxies; `forged` is what a
    hostile client put in its own header first."""
    chain = [forged] if forged else []
    return {"X-Forwarded-For": ", ".join([*chain, client_address, VERCEL_EGRESS])}


def _request(headers: dict[str, str], peer: str = "10.0.0.9"):
    from starlette.requests import Request

    return Request({"type": "http", "method": "GET", "path": "/", "query_string": b"", "client": (peer, 5000),
                    "headers": [(k.lower().encode(), v.encode()) for k, v in headers.items()]})


@pytest.mark.parametrize(("hops", "header", "expected"), [
    ("2", "203.0.113.7, 76.76.21.21", "203.0.113.7"),  # the hosted chain
    ("2", "6.6.6.6, 203.0.113.7, 76.76.21.21", "203.0.113.7"),  # a forged left entry is ignored
    ("2", "1.1.1.1, 2.2.2.2, 203.0.113.7, 76.76.21.21", "203.0.113.7"),
    ("2", "76.76.21.21", "10.0.0.9"),  # fewer entries than proxies: the connecting peer
    ("2", "", "10.0.0.9"),
    ("2", "not-an-address, 76.76.21.21", "10.0.0.9"),  # a malformed entry is never a rate-limit key
    ("2", "2001:DB8::1, 76.76.21.21", "2001:db8::1"),  # IPv6, normalised so one address is one bucket
    ("1", "203.0.113.7, 76.76.21.21", "76.76.21.21"),  # one hop configured: the last entry
    ("0", "203.0.113.7, 76.76.21.21", "10.0.0.9"),  # no proxies configured: the header is never trusted
])
def test_the_rate_limit_address_counts_trusted_proxies_from_the_right(monkeypatch, hops, header, expected):
    from api.session import client_ip

    monkeypatch.setenv("AUTH_TRUSTED_PROXY_HOPS", hops)
    headers = {"X-Forwarded-For": header} if header else {}
    assert client_ip(_request(headers), Settings()) == expected


def _small_limits(monkeypatch) -> None:
    from workspaces import rate_limit

    for scope in ("login_ip", "signup_code_ip", "reset_request_ip", "reset_code_ip"):
        old = rate_limit.LIMITS[scope]
        monkeypatch.setitem(rate_limit.LIMITS, scope, rate_limit.Limit(3, old.window, old.count_all))


def test_behind_two_proxies_failed_sign_ins_are_limited_per_client_not_per_proxy(monkeypatch):
    app = make_app(monkeypatch, AUTH_TRUSTED_PROXY_HOPS="2")
    _small_limits(monkeypatch)
    member(app, "bo")
    for n in range(3):  # three different accounts, so only the per-address limit can trip; a new forgery each time
        failed = login(browser(app, **via_proxies("203.0.113.7", forged=f"198.51.100.{n}")), f"nobody{n}")
        assert failed.status_code == 401
    limited = login(browser(app, **via_proxies("203.0.113.7", forged="192.0.2.99")), "bo")
    assert limited.status_code == 429 and code(limited) == "rate_limited"  # forging the left entry does not help
    # Another browser, arriving through the very same Vercel and Render addresses, is not affected.
    assert login(browser(app, **via_proxies("203.0.113.8")), "bo").status_code == 200


def test_behind_two_proxies_wrong_join_codes_are_limited_per_client(monkeypatch):
    app = make_app(monkeypatch, AUTH_TRUSTED_PROXY_HOPS="2")
    _small_limits(monkeypatch)
    for n in range(3):
        wrong = sign_up(browser(app, **via_proxies("203.0.113.7", forged=f"198.51.100.{n}")), "bo", join_code="guess")
        assert wrong.status_code == 403
    limited = sign_up(browser(app, **via_proxies("203.0.113.7")), "bo")
    assert limited.status_code == 429 and code(limited) == "rate_limited"
    assert sign_up(browser(app, **via_proxies("203.0.113.8")), "bo").status_code == 201


def test_behind_two_proxies_reset_requests_and_codes_are_limited_per_client(monkeypatch, tmp_path):
    outbox = tmp_path / "outbox"
    app = make_app(monkeypatch, DEV_OUTBOX_DIR=str(outbox), AUTH_TRUSTED_PROXY_HOPS="2")
    _small_limits(monkeypatch)
    for who in ("bo", "cy", "di", "ed"):
        member(app, who)
    for n, who in enumerate(("bo", "cy", "di")):  # different accounts: only the per-address limit can trip
        asked = browser(app, **via_proxies("203.0.113.7", forged=f"198.51.100.{n}")).post(
            "/auth/password/forgot", json={"email": email(who)})
        assert asked.status_code == 202
    limited = browser(app, **via_proxies("203.0.113.7")).post("/auth/password/forgot", json={"email": email("ed")})
    assert limited.status_code == 429 and code(limited) == "rate_limited"
    assert browser(app, **via_proxies("203.0.113.8")).post(
        "/auth/password/forgot", json={"email": email("ed")}).status_code == 202
    # Wrong reset codes: three from one client, then that client is refused even with the right code; another is not.
    bo_code, *_, ed_code = _codes(outbox)  # by write time: bo's first, ed's (asked from the second client) last
    wrong = f"{(int(bo_code) + 1) % 1_000_000:06d}"
    for n in range(3):
        failed = _reset(browser(app, **via_proxies("203.0.113.9", forged=f"198.51.100.{n}")), "bo", wrong)
        assert failed.status_code == 410
    refused = _reset(browser(app, **via_proxies("203.0.113.9")), "ed", ed_code)
    assert refused.status_code == 429 and code(refused) == "rate_limited"
    assert _reset(browser(app, **via_proxies("203.0.113.10")), "ed", ed_code).status_code == 200


def test_the_network_check_is_for_administrators_and_reports_the_chain(monkeypatch):
    app = make_app(monkeypatch, AUTH_TRUSTED_PROXY_HOPS="2")
    assert browser(app).get("/auth/network-check").status_code == 401
    base = member(app, "bo")
    denied = base.get("/auth/network-check", headers=via_proxies("203.0.113.7"))
    assert denied.status_code == 403 and code(denied) == "permission_denied"
    admin = member(app, "ada")
    seen = admin.get("/auth/network-check", headers=via_proxies("203.0.113.7")).json()
    assert seen["trusted_proxy_hops"] == 2 and seen["forwarded_entries"] == 2 and seen["consistent"] is True
    assert seen["rate_limit_address"] == "203.0.113.7" and seen["address_source"] == "x_forwarded_for"
    forged = admin.get("/auth/network-check", headers=via_proxies("203.0.113.7", forged="6.6.6.6")).json()
    assert forged["rate_limit_address"] == "203.0.113.7" and forged["consistent"] is False
    direct = admin.get("/auth/network-check").json()  # no proxies in front: the connecting peer
    assert direct["address_source"] == "connecting_peer" and direct["consistent"] is False
