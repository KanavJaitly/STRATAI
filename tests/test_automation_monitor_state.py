"""Tests for automation.monitor_state -- debounce, revocation, circuit breaker."""

from __future__ import annotations

import pytest

from automation import monitor_state as ms
from automation import statbotics_health as health


def result(day: str, *, ready: bool = True, code: str | None = None) -> health.ReadinessResult:
    failure = None if ready else (code or health.FAIL_HTTP_STATUS)
    return health.ReadinessResult(
        checked_at=f"{day}T15:37:00+00:00", url=health.probe_url(), ready=ready,
        stage_a_passed=ready or failure in health.DATA_CONTRACT_FAILURES,
        stage_b_passed=ready, failed_stage=None if ready else ("B" if failure in health.DATA_CONTRACT_FAILURES else "A"),
        failure_code=failure, detail="test", http_status=200 if ready else 503, elapsed_ms=10,
        epa_total=40.0 if ready else None, matches_played=12 if ready else None,
    )


def run(*checks: health.ReadinessResult) -> tuple[dict, list[str | None]]:
    state, events = ms.initial_state(), []
    for check in checks:
        transition = ms.apply_check(state, check)
        state = transition.state
        events.append(transition.event)
    return state, events


def test_one_success_is_pending_not_confirmed():
    state, events = run(result("2026-10-01"))
    assert state["status"] == ms.RECOVERY_PENDING
    assert events == [ms.EVENT_TENTATIVE_RECOVERY]


def test_two_consecutive_days_confirm():
    state, events = run(result("2026-10-01"), result("2026-10-02"))
    assert state["status"] == ms.RECOVERY_CONFIRMED
    assert events == [ms.EVENT_TENTATIVE_RECOVERY, ms.EVENT_RECOVERY_CONFIRMED]
    assert state["recovery_confirmed_at"].startswith("2026-10-02")


def test_two_passes_on_the_same_day_do_not_confirm():
    state, events = run(result("2026-10-01"), result("2026-10-01"))
    assert state["status"] == ms.RECOVERY_PENDING
    assert events == [ms.EVENT_TENTATIVE_RECOVERY, None]


def test_a_skipped_day_restarts_the_count():
    state, events = run(result("2026-10-01"), result("2026-10-03"))
    assert state["status"] == ms.RECOVERY_PENDING
    assert state["pass_dates"] == ["2026-10-03"]
    assert ms.EVENT_RECOVERY_CONFIRMED not in events


def test_flap_never_confirms():
    state, events = run(
        result("2026-10-01"), result("2026-10-02", ready=False), result("2026-10-03"),
    )
    assert state["status"] == ms.RECOVERY_PENDING
    assert ms.EVENT_RECOVERY_CONFIRMED not in events
    assert events[1] == ms.EVENT_RECOVERY_LOST


def test_failure_after_confirmation_revokes_it():
    state, events = run(result("2026-10-01"), result("2026-10-02"), result("2026-10-03", ready=False))
    assert state["status"] == ms.WAITING
    assert state["recovery_confirmed_at"] is None and state["pass_dates"] == []
    assert events[-1] == ms.EVENT_RECOVERY_LOST


def test_confirmation_is_announced_once():
    _, events = run(result("2026-10-01"), result("2026-10-02"), result("2026-10-03"))
    assert events.count(ms.EVENT_RECOVERY_CONFIRMED) == 1
    assert events[-1] is None


def test_continued_outage_is_silent():
    state, events = run(*(result(f"2026-10-0{d}", ready=False) for d in range(1, 8)))
    assert state["status"] == ms.WAITING
    assert events == [None] * 7


def test_outage_never_trips_the_circuit_breaker():
    state, _ = run(*(result(f"2026-10-{d:02d}", ready=False, code=health.FAIL_HTTP_STATUS) for d in range(1, 21)))
    assert state["status"] == ms.WAITING
    assert state["consecutive_contract_failures"] == 0


def test_repeated_unusable_200s_trip_the_circuit_breaker():
    state, events = run(*(result(f"2026-10-0{d}", ready=False, code=health.FAIL_SCHEMA_INVALID) for d in (1, 2, 3)))
    assert state["status"] == ms.ESCALATED
    assert events == [None, None, ms.EVENT_CIRCUIT_BREAKER]
    assert "schema_invalid" in state["escalation_reason"]


def test_breaker_counts_only_consecutive_contract_failures():
    state, _ = run(
        result("2026-10-01", ready=False, code=health.FAIL_SCHEMA_INVALID),
        result("2026-10-02", ready=False, code=health.FAIL_SCHEMA_INVALID),
        result("2026-10-03", ready=False, code=health.FAIL_HTTP_STATUS),
        result("2026-10-04", ready=False, code=health.FAIL_SCHEMA_INVALID),
    )
    assert state["status"] == ms.WAITING
    assert state["consecutive_contract_failures"] == 1


def test_escalated_state_is_frozen_even_if_checks_pass():
    state, _ = run(*(result(f"2026-10-0{d}", ready=False, code=health.FAIL_EPA_MISSING) for d in (1, 2, 3)))
    for day in ("2026-10-04", "2026-10-05", "2026-10-06"):
        transition = ms.apply_check(state, result(day))
        state = transition.state
        assert transition.event is None
    assert state["status"] == ms.ESCALATED
    assert state["last_check"]["checked_at"].startswith("2026-10-06")


def test_clearing_an_escalation_returns_to_waiting_and_cannot_skip_the_debounce():
    state, _ = run(*(result(f"2026-10-0{d}", ready=False, code=health.FAIL_EPA_MISSING) for d in (1, 2, 3)))
    cleared = ms.clear_escalation(state)
    assert cleared.event == ms.EVENT_ESCALATION_CLEARED
    assert cleared.state["status"] == ms.WAITING
    assert cleared.state["pass_dates"] == [] and cleared.state["consecutive_contract_failures"] == 0

    after_one = ms.apply_check(cleared.state, result("2026-10-04"))
    assert after_one.state["status"] == ms.RECOVERY_PENDING


def test_clearing_when_not_escalated_is_a_no_op():
    state, _ = run(result("2026-10-01"), result("2026-10-02"))
    transition = ms.clear_escalation(state)
    assert transition.event is None
    assert transition.state["status"] == ms.RECOVERY_CONFIRMED


def test_apply_check_does_not_mutate_its_input():
    state = ms.initial_state()
    ms.apply_check(state, result("2026-10-01"))
    assert state == ms.initial_state()


@pytest.mark.parametrize("bad", [
    {**ms.initial_state(), "schema_version": 99},
    {**ms.initial_state(), "status": "RUNNING"},
    {},
])
def test_unknown_state_is_refused_not_guessed(bad):
    with pytest.raises(ValueError):
        ms.apply_check(bad, result("2026-10-01"))


def test_only_human_action_events_are_escalations():
    assert ms.ESCALATION_EVENTS == {ms.EVENT_RECOVERY_CONFIRMED, ms.EVENT_CIRCUIT_BREAKER}
