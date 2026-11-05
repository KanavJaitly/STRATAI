"""Phase 11: the live draft record end to end, through the real API on an isolated stratai_test_<suffix> database.

Covers every route as admin, strategy and scouter and as another team (permissions and isolation), CSRF, the rule
refusals and overrides, undo and correction, idempotent retries, close and reopen, serialized concurrent appends,
the append-only log, and the recommendations (withheld, fallback, never an unavailable team).

Synthetic sentinel data only (season 9977, teams 99771-99786, event 9977zzzdraft): nothing here is evidence about any
real team.
"""

from __future__ import annotations

import threading
from datetime import datetime, timezone
from typing import Iterator

import psycopg
import pytest
from fastapi.testclient import TestClient

from api.dependencies import get_epa_source
from data.config import Settings
from database.connection import Database, DatabaseConfig
from tests.test_live_epa import _isolated_db_name
from tests.test_workspaces_api import CSRF, browser, code, join, make_app, workspace
from workspaces import draft_recommendations, passwords

pytestmark = pytest.mark.skipif(_isolated_db_name() is None, reason="needs an isolated stratai_* database copy")

SEASON, EVENT, OTHER_EVENT = 9977, "9977zzzdraft", "9977zzzother"
TEAMS = list(range(99771, 99787))  # 16 teams
TEAM_A, TEAM_B, TEAM_OUT = 99771, 99772, 99799  # A and B attend; OUT does not
RULES = {"n_alliances": 4, "picks_per_alliance": 2, "declined_team_may_be_picked_later": False,
         "declined_team_may_become_captain": True, "captain_may_accept_higher_alliance": True, "backup_robots": True}
BASE = "/workspace/alliance-selection/drafts"
DOMAIN_TEAMS = [TEAM_A, TEAM_B, TEAM_OUT]


def _db() -> Database:
    return Database(DatabaseConfig(Settings().database_url))


def _clean(db: Database) -> None:
    with db.cursor() as c:
        c.execute("DELETE FROM workspaces WHERE team_number = ANY(%s)", (DOMAIN_TEAMS,))
        c.execute("DELETE FROM users u WHERE u.email LIKE %s AND NOT EXISTS "
                  "(SELECT 1 FROM team_memberships m WHERE m.user_id = u.id)", ("%@workspaces.test.invalid",))
        c.execute("DELETE FROM auth_attempts")


@pytest.fixture(scope="module")
def canonical() -> Iterator[None]:
    db = _db()

    def drop() -> None:
        _clean(db)
        with db.cursor() as c:
            for event in (EVENT, OTHER_EVENT):
                c.execute("DELETE FROM match_teams WHERE match_key LIKE %s", (f"{event}%",))
                c.execute("DELETE FROM matches WHERE event_key = %s", (event,))
                c.execute("DELETE FROM events WHERE event_key = %s", (event,))
            c.execute("DELETE FROM teams WHERE team_number = ANY(%s)", (TEAMS + [TEAM_OUT],))

    drop()
    with db.cursor() as c:
        for event in (EVENT, OTHER_EVENT):
            c.execute("INSERT INTO events (event_key, season, name, end_date) VALUES (%s, %s, 'Sentinel', %s)",
                      (event, SEASON, datetime(2026, 3, 2).date()))
        for team in TEAMS + [TEAM_OUT]:
            c.execute("INSERT INTO teams (team_number, name) VALUES (%s, %s)", (team, f"Team {team}"))
        for n in range(1, 9):  # every team plays; quals scheduled in the past and scored
            key = f"{EVENT}_qm{n}"
            c.execute("INSERT INTO matches (match_key, event_key, season, competition_level, match_number, "
                      "scheduled_time, score_red, score_blue) VALUES (%s, %s, %s, 'qualification', %s, %s, 10, 5)",
                      (key, EVENT, SEASON, n, datetime(2026, 3, 1, 9 + n, tzinfo=timezone.utc)))
            six = [TEAMS[(n * 6 + i) % 16] for i in range(6)]
            for i, team in enumerate(six):
                c.execute("INSERT INTO match_teams (match_key, team_number, alliance_color) VALUES (%s, %s, %s)",
                          (key, team, "red" if i < 3 else "blue"))
    yield
    drop()


@pytest.fixture(autouse=True)
def _environment(monkeypatch, canonical) -> Iterator[None]:
    monkeypatch.setattr(passwords, "LOG2_N", 10)
    monkeypatch.setattr(passwords, "PARALLELISM", 1)
    monkeypatch.setenv("ENV", "development")
    for name in ("ACCESS_POLICY", "PUBLIC_APP_URL", "DEV_OUTBOX_DIR", "SMTP_HOST", "SMTP_FROM"):
        monkeypatch.delenv(name, raising=False)
    draft_recommendations.clear_cache()
    _clean(_db())
    yield
    _clean(_db())


@pytest.fixture
def team():
    """A verified workspace for team A at the event: its administrator, a strategy member and a scouter."""
    app = make_app()
    admin = workspace(app, TEAM_A, "ada")
    strategy = join(app, admin, "sam", "strategy")
    scouter = join(app, admin, "sue", "scouter")
    return app, admin, strategy, scouter


def start(c: TestClient, **extra):
    return c.post(BASE, json={"event_key": EVENT, "manual_rules": RULES, **extra})


def act(c: TestClient, record: int, type_: str, team: int, seed: int | None = None, **extra):
    return c.post(f"{BASE}/{record}/actions", json={"type": type_, "seed": seed, "team_number": team, **extra})


def test_starting_needs_the_events_rules_when_no_ruleset_covers_it(team):
    _, admin, _, _ = team
    refused = admin.post(BASE, json={"event_key": EVENT})
    assert refused.status_code == 422 and code(refused) == "rules_required"
    started = start(admin)
    assert started.status_code == 201, started.text
    body = started.json()
    assert body["setup"]["rules"]["source"] == "manual_entry"
    assert any(m.startswith("ruleset_unavailable") for m in body["setup"]["missing"])
    assert any(m.startswith("rankings_unavailable") for m in body["setup"]["missing"])
    assert body["setup"]["provenance"]["manual_rules_entered_by"] == "Ada"
    assert set(body["setup"]["pool"]) == set(TEAMS)
    again = start(admin)
    assert again.status_code == 409 and code(again) == "draft_exists"


def test_a_team_not_at_the_event_cannot_start_one():
    app = make_app()
    outsider = workspace(app, TEAM_OUT, "otto")
    refused = start(outsider)
    assert refused.status_code == 403 and code(refused) == "team_not_at_event"


def test_recording_follows_the_rules_and_an_override_is_kept(team):
    _, admin, _, _ = team
    record = start(admin).json()["record_id"]
    assert act(admin, record, "captain", TEAM_A, 1).status_code == 200  # no ranks: the captain is unchecked
    wrong = act(admin, record, "pick", TEAMS[5], 2)
    assert wrong.status_code == 409 and code(wrong) == "wrong_turn"
    assert act(admin, record, "decline", TEAMS[5], 1).status_code == 200
    declined = act(admin, record, "pick", TEAMS[5], 1)
    assert declined.status_code == 409 and code(declined) == "team_declined"
    overridden = act(admin, record, "pick", TEAMS[5], 1, override_reason="event-specific rule")
    assert overridden.status_code == 200
    body = overridden.json()
    assert body["effective"][-1]["status"] == "overridden"
    assert body["history"][-1]["override_reason"] == "event-specific rule"
    assert TEAMS[5] not in {t["team_number"] for t in body["available"]}
    assert {"team_number": TEAMS[5], "reason": "picked", "rank": None, "seed": 1} in body["unavailable"]


def test_undo_and_correction_keep_the_history_and_match_the_corrected_sequence(team):
    _, admin, _, _ = team
    record = start(admin).json()["record_id"]
    act(admin, record, "captain", TEAM_A, 1)
    mistake = act(admin, record, "pick", TEAMS[7], 1).json()["effective"][-1]["action_id"]
    undone = admin.post(f"{BASE}/{record}/undo", json={"target_action_id": mistake})
    assert undone.status_code == 200 and undone.json()["alliances"][0]["picks"] == []
    act(admin, record, "pick", TEAMS[8], 1)
    target = admin.get(f"{BASE}/{record}").json()["effective"][-1]["action_id"]
    fixed = admin.post(f"{BASE}/{record}/corrections", json={
        "target_action_id": target, "replacement": {"type": "pick", "seed": 1, "team_number": TEAMS[9]}})
    assert fixed.status_code == 200, fixed.text
    body = fixed.json()
    assert body["alliances"][0]["picks"] == [TEAMS[9]]
    assert [h["in_effect"] for h in body["history"]].count(False) == 2  # the undone pick and the corrected one
    stale_undo = admin.post(f"{BASE}/{record}/undo", json={"target_action_id": mistake})
    assert stale_undo.status_code == 409 and code(stale_undo) == "not_last_action"


def test_a_retry_with_the_same_action_id_is_idempotent_and_a_reused_id_is_refused(team):
    _, admin, _, _ = team
    record = start(admin).json()["record_id"]
    action_id = "6f1c2a3b-0000-4000-8000-000000000001"
    first = act(admin, record, "captain", TEAM_A, 1, action_id=action_id)
    retry = act(admin, record, "captain", TEAM_A, 1, action_id=action_id)
    assert first.status_code == retry.status_code == 200
    assert retry.json()["record_seq"] == first.json()["record_seq"]
    reused = act(admin, record, "decline", TEAMS[3], 1, action_id=action_id)
    assert reused.status_code == 409 and code(reused) == "action_id_conflict"


def test_close_makes_it_read_only_until_reopened(team):
    _, admin, _, _ = team
    record = start(admin).json()["record_id"]
    assert admin.post(f"{BASE}/{record}/close", json={}).json()["status"] == "closed"
    refused = act(admin, record, "captain", TEAM_A, 1)
    assert refused.status_code == 409 and code(refused) == "record_closed"
    assert admin.post(f"{BASE}/{record}/reopen", json={}).json()["status"] == "open"
    again = admin.post(f"{BASE}/{record}/reopen", json={})
    assert again.status_code == 409 and code(again) == "record_open"


def test_permissions_are_enforced_on_every_route_as_each_role(team):
    _, admin, strategy, scouter = team
    record = start(admin).json()["record_id"]
    writes = [("post", f"{BASE}/{record}/actions", {"type": "captain", "seed": 1, "team_number": TEAM_A}),
              ("post", f"{BASE}/{record}/undo", {}), ("post", f"{BASE}/{record}/close", {}),
              ("post", f"{BASE}/{record}/reopen", {}), ("post", f"{BASE}/{record}/setup", {"manual_rules": RULES}),
              ("post", f"{BASE}/{record}/corrections", {"target_action_id": "x", "replacement": None}),
              ("post", BASE, {"event_key": EVENT, "manual_rules": RULES})]
    reads = [f"{BASE}", f"{BASE}/{record}", f"{BASE}/{record}/recommendations"]
    for path in reads:
        assert strategy.get(path).status_code == 200, path  # alliance_selection by default (P11-Q4)
        denied = scouter.get(path)
        assert denied.status_code == 403 and code(denied) == "permission_denied", path
    for method, path, body in writes:
        for member in (strategy, scouter):  # alliance_selection_record is off by default (P11-Q2)
            denied = getattr(member, method)(path, json=body)
            assert denied.status_code == 403 and code(denied) == "permission_denied", (path, member)
    assert browser(make_app()).get(f"{BASE}/{record}").status_code == 401


def test_an_administrator_can_delegate_recording_to_the_strategy_role(team):
    _, admin, strategy, _ = team
    record = start(admin).json()["record_id"]
    granted = admin.post("/workspace/permissions", json={"role": "strategy",
                                                         "grants": {"alliance_selection_record": True}})
    assert granted.status_code == 200, granted.text
    assert act(strategy, record, "captain", TEAM_A, 1).status_code == 200
    activity = admin.get("/workspace/activity").json()
    actions = [entry["action"] for entry in activity["entries"]]
    assert "draft_started" in actions and "draft_action_recorded" in actions


def test_another_team_cannot_read_or_change_the_record(team):
    app, admin, _, _ = team
    record = start(admin).json()["record_id"]
    rival = workspace(app, TEAM_B, "bob")
    for response in (rival.get(f"{BASE}/{record}"), rival.get(f"{BASE}/{record}/recommendations"),
                     act(rival, record, "captain", TEAM_B, 1), rival.post(f"{BASE}/{record}/close", json={})):
        assert response.status_code == 404 and code(response) == "draft_not_found"
    assert rival.get(BASE).json() == []


def test_every_write_needs_the_csrf_header(team):
    app, admin, _, _ = team
    record = start(admin).json()["record_id"]
    bare = TestClient(app, cookies=admin.cookies)
    refused = bare.post(f"{BASE}/{record}/actions", json={"type": "captain", "seed": 1, "team_number": TEAM_A})
    assert refused.status_code == 403 and code(refused) == "csrf_check_failed"
    assert CSRF  # the team fixture's clients carry it


def test_concurrent_appends_are_serialized_and_the_second_is_revalidated(team):
    app, admin, _, _ = team
    record = start(admin).json()["record_id"]
    act(admin, record, "captain", TEAM_A, 1)
    other = join(app, admin, "ann", "admin")
    results: list = []

    def pick(client, team_number):
        results.append(act(client, record, "pick", team_number, 1))

    threads = [threading.Thread(target=pick, args=(admin, TEAMS[10])),
               threading.Thread(target=pick, args=(other, TEAMS[11]))]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    statuses = sorted(r.status_code for r in results)
    assert statuses == [200, 409]
    loser = next(r for r in results if r.status_code == 409)
    assert code(loser) == "wrong_turn"  # re-validated against the first pick: it is alliance 2's turn now
    seqs = [h["seq"] for h in admin.get(f"{BASE}/{record}").json()["history"]]
    assert seqs == list(range(1, len(seqs) + 1))


def test_the_log_is_append_only_in_the_database(team):
    _, admin, _, _ = team
    record = start(admin).json()["record_id"]
    with pytest.raises(psycopg.errors.CheckViolation):
        with _db().cursor() as c:
            c.execute("UPDATE draft_actions SET seq = seq WHERE record_id = %s", (record,))


def test_recommendations_are_withheld_with_the_reason_when_inputs_are_missing(team):
    app, admin, _, _ = team
    record = start(admin).json()["record_id"]
    act(admin, record, "captain", TEAM_A, 1)
    app.dependency_overrides[get_epa_source] = lambda: None
    out = admin.get(f"{BASE}/{record}/recommendations").json()
    assert out["status"] == "withheld" and out["withheld"]["code"] == "epa_source_not_loaded"
    assert out["engine_refusal"]["code"] == "not_approved"  # the engine's real refusal (no 9977 ruleset)
    assert out["record_seq"] == admin.get(f"{BASE}/{record}").json()["record_seq"]


def test_the_fallback_never_recommends_an_unavailable_team(team, monkeypatch):
    app, admin, _, _ = team
    record = start(admin).json()["record_id"]
    strength = list(reversed(TEAMS))
    monkeypatch.setattr(draft_recommendations, "event_ordering", lambda *a, **k: draft_recommendations.Ordering(
        tuple(strength), "raw_epa", "validated", {}, datetime(2026, 3, 1, tzinfo=timezone.utc), "selection_moment",
        ()))
    app.dependency_overrides[get_epa_source] = lambda: type("Epa", (), {"provider": object()})()
    act(admin, record, "captain", TEAM_A, 1)
    act(admin, record, "decline", strength[0], 1)
    out = admin.get(f"{BASE}/{record}/recommendations").json()
    assert out["status"] == "current" and out["source"] == "fallback_p11_fb1"
    assert out["validation"]["status"] == "not_validated"
    assert out["primary"]["team_number"] == strength[1] and out["primary"]["win_event"] is None
    board = admin.get(f"{BASE}/{record}").json()
    unavailable = {u["team_number"] for u in board["unavailable"]}
    listed = {out["primary"]["team_number"], *(b["team_number"] for b in out["backups"])}
    assert not listed & unavailable
    assert "Team %d declined alliance 1." % strength[0] in out["movement"]


def test_a_permission_change_on_a_database_without_0013_is_explained(team, monkeypatch):
    """set_role_permissions turns the CHECK violation a pre-0013 database raises into a clear refusal."""
    from workspaces import management

    _, admin, _, _ = team

    class Refusing:
        def __init__(self, inner):
            self.inner = inner

        def execute(self, sql, params=None):
            if sql.startswith("INSERT INTO workspace_role_permissions"):
                raise psycopg.errors.CheckViolation("workspace_role_permissions_permission_check")
            return self.inner.execute(sql, params)

        def __getattr__(self, name):
            return getattr(self.inner, name)

    real = Database.cursor
    from contextlib import contextmanager

    @contextmanager
    def cursor(self):
        with real(self) as inner:
            yield Refusing(inner)

    monkeypatch.setattr(management.Database, "cursor", cursor)
    refused = admin.post("/workspace/permissions", json={"role": "strategy",
                                                         "grants": {"alliance_selection_record": True}})
    assert refused.status_code == 409 and code(refused) == "permission_needs_migration"
