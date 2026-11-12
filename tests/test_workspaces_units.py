"""Team accounts: the rules that need no database -- password hashing and policy, tokens, the two-role permission
model and its agreement with the role CHECK constraint of migration 0015, the join code, ADMIN_EMAILS, reset codes,
and the access-policy default."""

from __future__ import annotations

import re
from pathlib import Path

import pytest
from pydantic import SecretStr

from data.config import Settings
from workspaces import accounts, passwords, permissions, rate_limit
from workspaces.errors import WorkspaceError
from workspaces.tokens import new_token, subject_hash, token_hash

MIGRATIONS = Path(__file__).resolve().parents[1] / "database" / "migrations"


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


@pytest.mark.parametrize("short", ["", "a", "seven77"])
def test_the_policy_refuses_passwords_shorter_than_eight_characters(short):
    with pytest.raises(WorkspaceError) as refused:
        passwords.check_password_policy(short)
    assert refused.value.code == "invalid_input"
    assert "at least 8 characters" in refused.value.message


@pytest.mark.parametrize("ok", ["eight888", "aaaaaaaa", "password", "12345678"])
def test_the_policy_has_no_rule_but_the_length(ok):
    passwords.check_password_policy(ok)  # common, repetitive or all-digit: allowed, by decision (2026-11-11)


def test_the_policy_still_bounds_the_length_so_hashing_stays_bounded():
    with pytest.raises(WorkspaceError):
        passwords.check_password_policy("x" * (passwords.MAX_PASSWORD_LENGTH + 1))


def test_tokens_are_long_random_and_stored_only_as_sha256():
    first, second = new_token(), new_token()
    assert first != second and len(first) >= 43
    assert re.fullmatch(r"[0-9a-f]{64}", token_hash(first))
    assert token_hash(first) != token_hash(second)
    assert subject_hash("login_ip", "1.2.3.4") != subject_hash("login_account", "1.2.3.4")


def test_two_roles_and_an_administrator_holds_every_permission():
    assert permissions.ROLES == ("admin", "base")
    assert permissions.effective_permissions("admin") == frozenset(permissions.ALL_PERMISSIONS)
    assert permissions.effective_permissions("strategy") == frozenset()  # an old or unknown role holds nothing


def test_a_base_member_holds_exactly_the_events_list_and_event_page_permissions():
    assert permissions.effective_permissions("base") == {"team_info", "event_analysis", "qualification_forecast"}
    # The explorer, platform inputs and the team overview are separate permissions precisely so base lacks them.
    for withheld in ("season_explorer", "platform_inputs", "team_overview", "team_management", "match_predictions",
                     "strategy_tools", "alliance_selection", "scouting_forms"):
        assert withheld not in permissions.effective_permissions("base")


def test_every_granted_permission_is_a_known_permission():
    for grants in permissions.ROLE_GRANTS.values():
        assert grants <= set(permissions.ALL_PERMISSIONS)


def test_the_role_check_constraint_lists_exactly_the_roles():
    sql = (MIGRATIONS / "0015_single_team_auth.sql").read_text(encoding="utf-8")
    match = re.search(r"team_memberships_role_check CHECK \(role IN \((.*?)\)\)", sql)
    assert match is not None
    assert tuple(re.findall(r"'([a-z_]+)'", match.group(1))) == permissions.ROLES


def _settings(**values) -> Settings:
    return Settings(tba_api_key="unused", **values)


def test_the_join_code_is_compared_exactly_and_never_matches_when_unset():
    settings = _settings(team_join_code=SecretStr("Mort-2026"))
    assert accounts.join_code_matches(settings, "Mort-2026")
    assert accounts.join_code_matches(settings, "  Mort-2026  ")  # surrounding spaces from a paste are forgiven
    for wrong in ("mort-2026", "Mort-202", "Mort-20266", "", None, 123):
        assert not accounts.join_code_matches(settings, wrong)
    assert not accounts.join_code_matches(_settings(), "anything")
    assert _settings(team_join_code="   ").team_join_code is None  # blank closes sign-up, never matches ""


def test_the_join_code_is_a_secret_that_never_prints():
    settings = _settings(team_join_code="Mort-2026")
    assert "Mort-2026" not in repr(settings) and "Mort-2026" not in str(settings.team_join_code)


def test_admin_emails_are_comma_separated_and_case_insensitive(monkeypatch):
    monkeypatch.setenv("ADMIN_EMAILS", " Ada@Example.test, ,bo@example.TEST ")
    settings = Settings()
    assert settings.admin_emails == ["ada@example.test", "bo@example.test"]
    assert accounts.role_for_email(settings, "ADA@example.test") == "admin"
    assert accounts.role_for_email(settings, "cy@example.test") == "base"


@pytest.mark.parametrize(("env", "expected"), [("development", "open"), ("staging", "members"),
                                               ("production", "members")])
def test_members_only_is_the_default_access_policy_wherever_deployed(monkeypatch, env, expected):
    monkeypatch.delenv("ACCESS_POLICY", raising=False)
    assert _settings(env=env).access_policy == expected
    assert _settings(env=env, access_policy="members").access_policy == "members"


def test_reset_codes_are_six_digits_and_stored_only_as_a_salted_hash():
    codes = {accounts.new_reset_code() for _ in range(200)}
    assert all(re.fullmatch(r"\d{6}", code) for code in codes) and len(codes) > 150
    first, second = accounts.reset_code_hash("a" * 32, "012345"), accounts.reset_code_hash("b" * 32, "012345")
    assert re.fullmatch(r"[0-9a-f]{64}", first) and first != second  # the salt changes the stored value
    assert accounts.RESET_CODE_TTL.total_seconds() == 15 * 60 and accounts.RESET_CODE_MAX_ATTEMPTS == 5


def test_the_rate_limits_named_in_the_requirements():
    assert rate_limit.LIMITS["signup_code_ip"].count_all is False  # only wrong codes count
    assert rate_limit.LIMITS["signup_code_global"].attempts == 50
    assert rate_limit.LIMITS["signup_code_global"].window.total_seconds() == 3600
    per_email = rate_limit.LIMITS["reset_request_account"]
    assert (per_email.attempts, per_email.window.total_seconds(), per_email.count_all) == (3, 3600, True)
