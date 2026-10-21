"""Tests for automation.execution_state -- builds, attempts, breakers, preflight."""

from __future__ import annotations

import pytest

from automation import execution_state as es
from automation.monitor_state import RECOVERY_CONFIRMED, RECOVERY_PENDING

MONTH = "2026-10"


def build(status: str = "COMPLETE", valid: int = 19761, *, dump: bool = True, run_id: str = "b1") -> dict:
    return {
        "run_id": run_id, "finished_at": "2026-10-02T00:00:00+00:00", "billed_minutes": 200,
        "readiness_status": status, "valid_source_rows": valid, "required_source_rows": 19761,
        "stop_reason": "finished", "fingerprint": "abc",
        "dump": {"artifact_name": f"phase4-db-{run_id}", "run_id": run_id, "sha256": "f" * 64, "size_bytes": 1} if dump else None,
    }


def attempt(outcome: str = es.OUTCOME_PROGRESS, *, new: list[str] | None = None, published: dict | None = None) -> dict:
    return {
        "attempt_id": "a1", "run_id": "a1", "base_sha": "base", "outcome": outcome, "stop_reason": "test",
        "billed_minutes": 290, "published": published or {}, "new_acceptance_files": new or [],
        "finished_at": "2026-10-03T00:00:00+00:00",
    }


def ready_state() -> dict:
    return es.record_build(es.initial_state(), build(), month=MONTH).state


def facts(state: dict, **overrides) -> es.PreflightFacts:
    values = dict(
        kind="attempt", month=MONTH, monitor_status=RECOVERY_CONFIRMED, probe_ready=True, probe_detail="ok",
        execution_state=state, secrets_present={"CLAUDE_CODE_OAUTH_TOKEN": True}, dump_available=True,
        main_sha="main-sha",
    )
    values.update(overrides)
    return es.PreflightFacts(**values)


# --- builds -----------------------------------------------------------------


def test_complete_build_records_the_dump_and_asks_a_human():
    transition = es.record_build(es.initial_state(), build(), month=MONTH)
    assert transition.event == es.EVENT_DATA_READY
    assert transition.event in es.HUMAN_EVENTS
    assert transition.state["data_build"]["dump"]["artifact_name"] == "phase4-db-b1"
    assert transition.state["data_build"]["fingerprint"] == "abc"
    assert transition.state["ledger"] == {MONTH: 200}


def test_partial_builds_that_make_progress_never_trip_the_breaker():
    state = es.initial_state()
    for valid in (5000, 10000, 15000, 19000):
        state = es.record_build(state, build("PARTIAL", valid), month=MONTH).state
    assert state["status"] == es.READY


def test_three_builds_without_progress_trip_the_breaker():
    state = es.record_build(es.initial_state(), build("PARTIAL", 5000), month=MONTH).state
    events = []
    for _ in range(3):
        transition = es.record_build(state, build("PARTIAL", 5000), month=MONTH)
        state, events = transition.state, [*events, transition.event]
    assert state["status"] == es.ESCALATED
    assert events[-1] == es.EVENT_CIRCUIT_BREAKER


# --- attempts ---------------------------------------------------------------


def test_progress_resets_the_attempt_breaker_and_records_the_stack_top():
    state = es.record_attempt(ready_state(), attempt(published={"automation/phase4-m04": "s4", "automation/phase4-m05": "s5"},
                                                     new=[".agent/phase4/M04_ACCEPTANCE.md"]), month=MONTH).state
    assert state["status"] == es.READY
    assert state["last_published"] == {"branch": "automation/phase4-m05", "sha": "s5", "manifest": None}
    assert state["consecutive_no_progress_attempts"] == 0


@pytest.mark.parametrize("outcome", [es.OUTCOME_ESCALATED, es.OUTCOME_USAGE_EXHAUSTED, es.OUTCOME_HARNESS_VIOLATION])
def test_hard_stops_escalate_immediately(outcome):
    transition = es.record_attempt(ready_state(), attempt(outcome), month=MONTH)
    assert transition.state["status"] == es.ESCALATED
    assert transition.event == es.EVENT_ESCALATED


def test_usage_exhaustion_says_it_will_not_bill():
    transition = es.record_attempt(ready_state(), attempt(es.OUTCOME_USAGE_EXHAUSTED), month=MONTH)
    assert "never bill" in transition.state["escalation_reason"]


M13_PUBLISHED = {"automation/phase4-m13": "s13"}


def test_m13_signoff_waits_for_a_human():
    transition = es.record_attempt(ready_state(), attempt(es.OUTCOME_AWAITING_SIGNOFF, published=M13_PUBLISHED),
                                   month=MONTH)
    assert transition.state["status"] == es.AWAITING_HUMAN
    assert transition.event in es.HUMAN_EVENTS


def test_three_attempts_without_a_new_acceptance_artifact_trip_the_breaker():
    state = ready_state()
    for outcome in (es.OUTCOME_BUDGET_EXHAUSTED, es.OUTCOME_CLAUDE_FAILED, es.OUTCOME_INFRASTRUCTURE_FAILED):
        transition = es.record_attempt(state, attempt(outcome), month=MONTH)
        state = transition.state
    assert state["status"] == es.ESCALATED and transition.event == es.EVENT_CIRCUIT_BREAKER


def test_unknown_outcome_is_refused():
    with pytest.raises(ValueError):
        es.record_attempt(ready_state(), attempt("accepted_everything"), month=MONTH)


def test_clear_is_the_only_way_back_to_ready():
    state = es.record_attempt(ready_state(), attempt(es.OUTCOME_ESCALATED), month=MONTH).state
    assert not es.preflight(facts(state)).allowed
    cleared = es.clear(state, note="reviewed").state
    assert cleared["status"] == es.READY
    assert es.preflight(facts(cleared)).allowed


def test_billed_minutes_round_each_job_up():
    assert es.billed_minutes([1, 61, 3600]) == 1 + 2 + 60


# --- preflight ---------------------------------------------------------------


def test_everything_in_place_allows_the_attempt_from_main():
    decision = es.preflight(facts(ready_state()))
    assert decision.allowed and decision.reasons == [] and decision.base_sha == "main-sha"


@pytest.mark.parametrize("overrides, fragment", [
    ({"monitor_status": RECOVERY_PENDING}, "monitor status"),
    ({"monitor_status": None}, "monitor status"),
    ({"probe_ready": False, "probe_detail": "http_status: HTTP 503"}, "fresh Statbotics readiness probe failed"),
    ({"secrets_present": {"CLAUDE_CODE_OAUTH_TOKEN": False}}, "CLAUDE_CODE_OAUTH_TOKEN is not configured"),
    ({"forbidden_secrets_present": ["ANTHROPIC_API_KEY"]}, "paid billing"),
    ({"dump_available": False}, "no longer available"),
    ({"phase4_complete": True}, "already complete"),
    ({"unreadable_facts": ["the origin/main commit"]}, "could not determine"),
])
def test_each_gate_refuses_on_its_own(overrides, fragment):
    decision = es.preflight(facts(ready_state(), **overrides))
    assert not decision.allowed and decision.base_sha is None
    assert any(fragment in reason for reason in decision.reasons), decision.reasons


def test_attempt_refused_until_historical_data_is_complete():
    state = es.record_build(es.initial_state(), build("PARTIAL", 12000), month=MONTH).state
    decision = es.preflight(facts(state))
    assert not decision.allowed
    assert any("PARTIAL" in reason for reason in decision.reasons)


def test_monthly_cap_protects_the_free_allowance():
    state = ready_state()
    state["ledger"][MONTH] = es.DEFAULT_MONTHLY_MINUTE_CAP - es.ATTEMPT_WORST_CASE_MINUTES - es.MONITOR_RESERVE_MINUTES + 1
    assert not es.preflight(facts(state)).allowed
    state["ledger"][MONTH] -= 1
    assert es.preflight(facts(state)).allowed


def test_resume_continues_an_unmerged_stack():
    state = es.record_attempt(ready_state(), attempt(published={"automation/phase4-m04": "s4"},
                                                     new=["x"]), month=MONTH).state
    decision = es.preflight(facts(state, main_contains_published=False, published_contains_main=True))
    assert decision.allowed and decision.base_sha == "s4"


def test_resume_uses_main_once_the_stack_is_merged():
    state = es.record_attempt(ready_state(), attempt(published={"automation/phase4-m04": "s4"},
                                                     new=["x"]), month=MONTH).state
    decision = es.preflight(facts(state, main_contains_published=True, published_contains_main=False))
    assert decision.base_sha == "main-sha"


def test_diverged_human_work_is_never_overwritten():
    state = es.record_attempt(ready_state(), attempt(published={"automation/phase4-m04": "s4"},
                                                     new=["x"]), month=MONTH).state
    decision = es.preflight(facts(state, main_contains_published=False, published_contains_main=False))
    assert not decision.allowed
    assert any("diverged" in reason for reason in decision.reasons)


def test_build_preflight_needs_no_prior_dump():
    decision = es.preflight(facts(es.initial_state(), kind="build", secrets_present={"TBA_API_KEY": True}))
    assert decision.allowed


def test_awaiting_signoff_blocks_further_attempts():
    state = es.record_attempt(ready_state(), attempt(es.OUTCOME_AWAITING_SIGNOFF, published=M13_PUBLISHED),
                              month=MONTH).state
    assert state["status"] == es.AWAITING_HUMAN
    assert not es.preflight(facts(state)).allowed


def test_budget_constants_honour_decision_d2():
    assert es.ATTEMPT_WORST_CASE_MINUTES <= es.MAX_ATTEMPT_MINUTES == 300
    assert es.BUILD_WORST_CASE_MINUTES <= es.MAX_ATTEMPT_MINUTES
