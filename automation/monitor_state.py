"""The monitor's persistent state machine: debounce, revocation, circuit breaker.

Pure functions over a JSON-serializable state -- no I/O -- so every transition
is unit-testable. States:

    WAITING             Statbotics not (yet) shown ready.
    RECOVERY_PENDING    one ready check; not trusted yet.
    RECOVERY_CONFIRMED  ready on two consecutive UTC calendar days with no
                        failed check between. Authorizes nothing by itself: the execution
                        gates (fresh preflight, historical-data readiness,
                        lock) are separate and do not exist yet.
    ESCALATED           the circuit breaker tripped. Checks are still logged,
                        but nothing advances until a human clears it.

A failed check from PENDING or CONFIRMED drops straight back to WAITING, so a
flap (pass, fail, pass) never confirms.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from typing import Any

from automation.statbotics_health import DATA_CONTRACT_FAILURES, ReadinessResult

STATE_SCHEMA_VERSION = 1

WAITING = "WAITING"
RECOVERY_PENDING = "RECOVERY_PENDING"
RECOVERY_CONFIRMED = "RECOVERY_CONFIRMED"
ESCALATED = "ESCALATED"

REQUIRED_CONSECUTIVE_DAYS = 2
# Three consecutive HTTP-200-but-unusable responses means schema drift or a
# placeholder dataset -- a human decision, not something another day fixes.
CIRCUIT_BREAKER_THRESHOLD = 3

EVENT_MONITOR_INITIALIZED = "monitor_initialized"
EVENT_TENTATIVE_RECOVERY = "tentative_recovery"
EVENT_RECOVERY_CONFIRMED = "recovery_confirmed"
EVENT_RECOVERY_LOST = "recovery_lost"
EVENT_CIRCUIT_BREAKER = "circuit_breaker"
EVENT_ESCALATION_CLEARED = "escalation_cleared"

# Events that need a human, as opposed to routine status. The notifier
# @-mentions the owner on these so GitHub emails them.
ESCALATION_EVENTS = frozenset({EVENT_RECOVERY_CONFIRMED, EVENT_CIRCUIT_BREAKER})


def initial_state() -> dict[str, Any]:
    return {
        "schema_version": STATE_SCHEMA_VERSION,
        "status": WAITING,
        "pass_dates": [],
        "consecutive_contract_failures": 0,
        "recovery_confirmed_at": None,
        "escalation_reason": None,
        "last_check": None,
    }


@dataclass(frozen=True)
class Transition:
    state: dict[str, Any]
    event: str | None
    message: str


def validate_state(state: dict[str, Any]) -> None:
    """Refuse a state file this code does not understand rather than guess."""
    if state.get("schema_version") != STATE_SCHEMA_VERSION:
        raise ValueError(f"unsupported monitor state schema_version {state.get('schema_version')!r}")
    if state.get("status") not in (WAITING, RECOVERY_PENDING, RECOVERY_CONFIRMED, ESCALATED):
        raise ValueError(f"unknown monitor status {state.get('status')!r}")


def apply_check(state: dict[str, Any], result: ReadinessResult) -> Transition:
    """Fold one readiness result into the state and name the transition, if any."""
    validate_state(state)
    new = {**state, "pass_dates": list(state["pass_dates"]), "last_check": result.to_dict()}
    check_date = result.checked_at[:10]

    if not result.ready and result.failure_code in DATA_CONTRACT_FAILURES:
        new["consecutive_contract_failures"] = state["consecutive_contract_failures"] + 1
    else:
        new["consecutive_contract_failures"] = 0

    if state["status"] == ESCALATED:
        return Transition(new, None, "escalated; check recorded, state frozen until a human clears it")

    if not result.ready:
        was_recovering = state["status"] in (RECOVERY_PENDING, RECOVERY_CONFIRMED)
        new.update(status=WAITING, pass_dates=[], recovery_confirmed_at=None)
        if new["consecutive_contract_failures"] >= CIRCUIT_BREAKER_THRESHOLD:
            new["status"] = ESCALATED
            new["escalation_reason"] = (
                f"{new['consecutive_contract_failures']} consecutive checks returned HTTP 200 with data "
                f"StratAI cannot use (latest: {result.failure_code}: {result.detail})"
            )
            return Transition(new, EVENT_CIRCUIT_BREAKER, new["escalation_reason"])
        if was_recovering:
            return Transition(new, EVENT_RECOVERY_LOST, f"recovery revoked: {result.failure_code}: {result.detail}")
        return Transition(new, None, f"not ready: {result.failure_code}: {result.detail}")

    # A second pass on the same UTC date (e.g. a manual re-check) is not a second
    # day, and a gap day with no check at all restarts the count: GitHub can drop
    # a scheduled run, and an unobserved day is not evidence of health.
    if new["pass_dates"] and check_date != new["pass_dates"][-1]:
        if check_date != _next_day(new["pass_dates"][-1]):
            new["pass_dates"] = []
    if check_date not in new["pass_dates"]:
        new["pass_dates"].append(check_date)
    days = len(new["pass_dates"])

    if state["status"] == RECOVERY_CONFIRMED:
        return Transition(new, None, "still ready")
    if days >= REQUIRED_CONSECUTIVE_DAYS:
        new.update(status=RECOVERY_CONFIRMED, recovery_confirmed_at=result.checked_at)
        return Transition(new, EVENT_RECOVERY_CONFIRMED, f"ready on {days} distinct days: {new['pass_dates']}")
    new["status"] = RECOVERY_PENDING
    if state["status"] == RECOVERY_PENDING:
        return Transition(new, None, "ready again on the same day; still one day of evidence")
    return Transition(new, EVENT_TENTATIVE_RECOVERY, "ready once; one more day needed before it is trusted")


def _next_day(iso_date: str) -> str:
    return (date.fromisoformat(iso_date) + timedelta(days=1)).isoformat()


def clear_escalation(state: dict[str, Any]) -> Transition:
    """Human-only reset. Returns to WAITING -- never to CONFIRMED -- so it cannot skip the debounce."""
    validate_state(state)
    if state["status"] != ESCALATED:
        return Transition(dict(state), None, f"nothing to clear (status is {state['status']})")
    new = {**state, "status": WAITING, "pass_dates": [], "consecutive_contract_failures": 0,
           "recovery_confirmed_at": None, "escalation_reason": None}
    return Transition(new, EVENT_ESCALATION_CLEARED, f"escalation cleared (was: {state['escalation_reason']})")
