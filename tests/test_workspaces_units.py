"""Team workspaces: the rules that need no database -- password hashing and policy, tokens, the permission model,
and the agreement between the code's permission list and the workspace_role_permissions CHECK constraint (defined by
0012, redefined by 0013)."""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from workspaces import passwords, permissions
from workspaces.errors import WorkspaceError
from workspaces.tokens import new_token, subject_hash, token_hash

MIGRATIONS = Path(__file__).resolve().parents[1] / "database" / "migrations"
CHECK_PATTERN = r"workspace_role_permissions_permission_check CHECK \(permission IN \((.*?)\)\)"


@pytest.fixture(autouse=True)
def _cheap_hashing(monkeypatch):
    # The real cost (N=2^15, p=3) is deliberate in production and needless here.
    monkeypatch.setattr(passwords, "LOG2_N", 10)
    monkeypatch.setattr(passwords, "PARALLELISM", 1)


def test_a_password_verifies_only_against_its_own_hash():
    stored = passwords.hash_password("correct horse battery staple")
    assert stored.startswith("scrypt$10$8$1$")
    assert passwords.verify_password("correct horse battery staple", stored)
    assert not passwords.verify_password("correct horse battery stapler", stored)
    assert not passwords.verify_password("correct horse battery staple", None)
    assert not passwords.verify_password("x", "not-a-hash")
    assert not passwords.verify_password("x", "bcrypt$1$2$3$aa$bb")


def test_two_hashes_of_one_password_differ_by_salt():
    assert passwords.hash_password("same password here") != passwords.hash_password("same password here")


def test_a_hash_made_with_other_parameters_is_flagged_for_rehash(monkeypatch):
    old = passwords.hash_password("a long enough password")
    monkeypatch.setattr(passwords, "LOG2_N", 11)
    assert passwords.needs_rehash(old)
    assert passwords.verify_password("a long enough password", old)  # still verifies with its own parameters
    assert not passwords.needs_rehash(passwords.hash_password("a long enough password"))


@pytest.mark.parametrize("weak", ["short", "elevenchars", "password1234", "aaaaaaaaaaaaaa", "abababababab"])
def test_the_policy_refuses_short_common_or_trivial_passwords(weak):
    with pytest.raises(WorkspaceError) as refused:
        passwords.check_password_policy(weak)
    assert refused.value.code == "invalid_input"


def test_the_policy_refuses_the_email_as_password_and_overlong_passwords():
    with pytest.raises(WorkspaceError):
        passwords.check_password_policy("someone@team.example", email="someone@team.example")
    with pytest.raises(WorkspaceError):
        passwords.check_password_policy("x1" * 200)
    passwords.check_password_policy("a reasonable passphrase")


def test_tokens_are_long_random_and_stored_only_as_sha256():
    first, second = new_token(), new_token()
    assert first != second and len(first) >= 43
    assert re.fullmatch(r"[0-9a-f]{64}", token_hash(first))
    assert token_hash(first) != token_hash(second)
    assert subject_hash("login_ip", "1.2.3.4") != subject_hash("login_account", "1.2.3.4")


def test_administrators_hold_every_permission_and_others_only_configurable_ones():
    assert permissions.effective_permissions("admin", {}) == frozenset(permissions.ALL_PERMISSIONS)
    for role in permissions.CONFIGURABLE_ROLES:
        held = permissions.effective_permissions(role, {p: True for p in permissions.ALL_PERMISSIONS})
        assert not held & set(permissions.ADMIN_ONLY_PERMISSIONS), role
    assert permissions.effective_permissions("nobody", {}) == frozenset()


def test_the_default_grants_match_the_documented_role_defaults():
    strategy = permissions.effective_permissions("strategy", {})
    scouter = permissions.effective_permissions("scouter", {})
    for permission in ("match_predictions", "team_analytics", "event_analysis", "alliance_selection",
                       "qualification_forecast", "strategy_tools", "scouting_view"):
        assert permission in strategy
    assert "scouting_submit" not in strategy  # configurable for strategy, off by default
    assert {"scouting_forms", "scouting_submit", "team_info"} <= scouter
    for permission in ("match_predictions", "alliance_selection", "team_analytics", "scouting_view"):
        assert permission not in scouter  # configurable for scouters, off by default


def test_a_stored_grant_overrides_the_default_and_a_missing_one_falls_back():
    assert "match_predictions" in permissions.effective_permissions("scouter", {"match_predictions": True})
    assert "scouting_submit" not in permissions.effective_permissions("scouter", {"scouting_submit": False})
    assert "scouting_submit" in permissions.effective_permissions("scouter", {})


def test_the_migration_check_lists_exactly_the_configurable_permissions():
    # The constraint in force is the one the last migration to define it leaves (migrations apply in name order).
    defining = [path for path in sorted(MIGRATIONS.glob("*.sql"))
                if re.search(CHECK_PATTERN, path.read_text(encoding="utf-8"), re.S)]
    assert [path.name for path in defining][:1] == ["0012_team_workspaces.sql"]
    block = re.search(CHECK_PATTERN, defining[-1].read_text(encoding="utf-8"), re.S)
    assert block is not None
    in_sql = set(re.findall(r"'([a-z_]+)'", block.group(1)))
    assert in_sql == set(permissions.CONFIGURABLE_PERMISSIONS)
    assert not in_sql & set(permissions.ADMIN_ONLY_PERMISSIONS)
