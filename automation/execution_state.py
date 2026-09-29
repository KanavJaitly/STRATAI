"""Persistent state and gate logic for Phase 4 data builds and execution attempts.

Pure functions over a JSON-serializable state (no I/O), stored as
execution_state.json on the automation/phase4-state branch next to the monitor's
state. Statuses:

    READY           a human-dispatched build or attempt may run if preflight passes
    AWAITING_HUMAN  execution reached a point only a human can pass (M13 sign-off,
                    a decision the Human Escalation Protocol reserves for a person)
    ESCALATED       a circuit breaker or hard stop fired; nothing runs until cleared

Every preflight rule refuses rather than guesses; `preflight` returns every
reason it refused, not just the first.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any

from automation.data_readiness import COMPLETE as READINESS_COMPLETE

STATE_SCHEMA_VERSION = 1

READY = "READY"
AWAITING_HUMAN = "AWAITING_HUMAN"
ESCALATED = "ESCALATED"
_STATUSES = (READY, AWAITING_HUMAN, ESCALATED)

# Decision D2: at most 300 Actions minutes per attempt. The execute workflow's
# job timeouts sum to ATTEMPT_WORST_CASE_MINUTES (enforced by a test).
MAX_ATTEMPT_MINUTES = 300
ATTEMPT_WORST_CASE_MINUTES = 295
BUILD_WORST_CASE_MINUTES = 285
# The daily monitor's own worst case: 10-minute timeout x 31 days.
MONITOR_RESERVE_MINUTES = 310
# Share of the account's free monthly Actions minutes this automation may
# plan to use (overridable by the PHASE4_MONTHLY_MINUTE_CAP variable). The
# free allowance is account-wide, so the default leaves headroom.
DEFAULT_MONTHLY_MINUTE_CAP = 1500
NO_PROGRESS_BREAKER = 3

OUTCOME_PROGRESS = "progress_checkpointed"
OUTCOME_AWAITING_SIGNOFF = "awaiting_human_signoff"
OUTCOME_ESCALATED = "escalated"
OUTCOME_USAGE_EXHAUSTED = "usage_exhausted"
OUTCOME_BUDGET_EXHAUSTED = "budget_exhausted"
OUTCOME_CLAUDE_FAILED = "claude_failed"
OUTCOME_HARNESS_VIOLATION = "harness_violation"
OUTCOME_INFRASTRUCTURE_FAILED = "infrastructure_failed"

# Outcomes that stop automation immediately, without waiting for the breaker.
_IMMEDIATE_ESCALATION = {
    OUTCOME_ESCALATED: "Phase 4 execution stopped for a human decision",
    OUTCOME_USAGE_EXHAUSTED: "Claude subscription usage exhausted (decision D1: stop, never bill)",
    OUTCOME_HARNESS_VIOLATION: "execution output violated the automation harness rules; nothing was published",
}
OUTCOMES = {
    OUTCOME_PROGRESS, OUTCOME_AWAITING_SIGNOFF, OUTCOME_BUDGET_EXHAUSTED, OUTCOME_CLAUDE_FAILED,
    OUTCOME_INFRASTRUCTURE_FAILED, *_IMMEDIATE_ESCALATION,
}

EVENT_BUILD_RECORDED = "data_build_recorded"
EVENT_DATA_READY = "data_ready"
EVENT_ATTEMPT_RECORDED = "attempt_recorded"
EVENT_AWAITING_HUMAN = "awaiting_human"
EVENT_CIRCUIT_BREAKER = "execution_circuit_breaker"
EVENT_ESCALATED = "execution_escalated"
EVENT_CLEARED = "execution_cleared"
HUMAN_EVENTS = frozenset({EVENT_DATA_READY, EVENT_AWAITING_HUMAN, EVENT_CIRCUIT_BREAKER, EVENT_ESCALATED})


def initial_state() -> dict[str, Any]:
    return {
        "schema_version": STATE_SCHEMA_VERSION,
        "status": READY,
        "escalation_reason": None,
        "data_build": None,
        "builds": [],
        "attempts": [],
        "consecutive_no_progress_builds": 0,
        "consecutive_no_progress_attempts": 0,
        "best_valid_source_rows": 0,
        "last_published": None,
        "ledger": {},
    }


def validate_state(state: dict[str, Any]) -> None:
    if state.get("schema_version") != STATE_SCHEMA_VERSION:
        raise ValueError(f"unsupported execution state schema_version {state.get('schema_version')!r}")
    if state.get("status") not in _STATUSES:
        raise ValueError(f"unknown execution status {state.get('status')!r}")


@dataclass(frozen=True)
class Transition:
    state: dict[str, Any]
    event: str | None
    message: str


def billed_minutes(job_seconds: list[float]) -> int:
    """GitHub bills each job rounded up to the whole minute."""
    return sum(max(1, math.ceil(seconds / 60)) for seconds in job_seconds)


def _copy(state: dict[str, Any]) -> dict[str, Any]:
    validate_state(state)
    return {**state, "builds": list(state["builds"]), "attempts": list(state["attempts"]),
            "ledger": dict(state["ledger"])}


def _charge(state: dict[str, Any], month: str, minutes: int) -> None:
    state["ledger"][month] = state["ledger"].get(month, 0) + minutes


def _escalate(state: dict[str, Any], reason: str) -> None:
    state["status"] = ESCALATED
    state["escalation_reason"] = reason


def record_build(state: dict[str, Any], build: dict[str, Any], *, month: str) -> Transition:
    """build: run_id, finished_at, billed_minutes, readiness_status, valid_source_rows,
    required_source_rows, stop_reason, dump (artifact_name, run_id, sha256, size_bytes) or None."""
    new = _copy(state)
    new["builds"].append(build)
    _charge(new, month, build["billed_minutes"])
    if build.get("dump"):
        new["data_build"] = {
            "run_id": build["run_id"], "finished_at": build["finished_at"],
            "readiness_status": build["readiness_status"], "dump": build["dump"],
            "valid_source_rows": build["valid_source_rows"],
            "required_source_rows": build["required_source_rows"],
            "fingerprint": build.get("fingerprint"),
        }

    progressed = build["valid_source_rows"] > state["best_valid_source_rows"]
    new["best_valid_source_rows"] = max(state["best_valid_source_rows"], build["valid_source_rows"])
    summary = (f"readiness {build['readiness_status']}: {build['valid_source_rows']}/"
               f"{build['required_source_rows']} required EPA source rows valid; stop: {build['stop_reason']}")

    if build["readiness_status"] == READINESS_COMPLETE:
        new["consecutive_no_progress_builds"] = 0
        return Transition(new, EVENT_DATA_READY, f"historical data ready — {summary}")
    new["consecutive_no_progress_builds"] = 0 if progressed else state["consecutive_no_progress_builds"] + 1
    if new["consecutive_no_progress_builds"] >= NO_PROGRESS_BREAKER:
        _escalate(new, f"{NO_PROGRESS_BREAKER} consecutive data builds made no progress — {summary}")
        return Transition(new, EVENT_CIRCUIT_BREAKER, new["escalation_reason"])
    return Transition(new, EVENT_BUILD_RECORDED, summary)


def record_attempt(state: dict[str, Any], attempt: dict[str, Any], *, month: str) -> Transition:
    """attempt: attempt_id, run_id, base_sha, outcome, stop_reason, billed_minutes,
    published ({branch: sha}), new_acceptance_files, finished_at."""
    if attempt["outcome"] not in OUTCOMES:
        raise ValueError(f"unknown attempt outcome {attempt['outcome']!r}")
    new = _copy(state)
    new["attempts"].append(attempt)
    _charge(new, month, attempt["billed_minutes"])
    if attempt["published"]:
        top = max(attempt["published"])  # milestone branches sort by number
        new["last_published"] = {"branch": top, "sha": attempt["published"][top]}

    outcome = attempt["outcome"]
    progressed = bool(attempt["new_acceptance_files"])
    new["consecutive_no_progress_attempts"] = 0 if progressed else state["consecutive_no_progress_attempts"] + 1
    detail = f"{outcome}: {attempt['stop_reason']}"

    if outcome in _IMMEDIATE_ESCALATION:
        _escalate(new, f"{_IMMEDIATE_ESCALATION[outcome]} — {attempt['stop_reason']}")
        return Transition(new, EVENT_ESCALATED, new["escalation_reason"])
    if outcome == OUTCOME_AWAITING_SIGNOFF:
        new["status"] = AWAITING_HUMAN
        new["escalation_reason"] = attempt["stop_reason"]
        return Transition(new, EVENT_AWAITING_HUMAN, detail)
    if new["consecutive_no_progress_attempts"] >= NO_PROGRESS_BREAKER:
        _escalate(new, f"{NO_PROGRESS_BREAKER} consecutive attempts produced no new acceptance artifact — {detail}")
        return Transition(new, EVENT_CIRCUIT_BREAKER, new["escalation_reason"])
    return Transition(new, EVENT_ATTEMPT_RECORDED, detail)


def clear(state: dict[str, Any], *, note: str) -> Transition:
    """Human-only. Returns to READY; it does not touch any gate below."""
    new = _copy(state)
    if state["status"] == READY:
        return Transition(new, None, "nothing to clear")
    new.update(status=READY, escalation_reason=None,
               consecutive_no_progress_builds=0, consecutive_no_progress_attempts=0)
    return Transition(new, EVENT_CLEARED, f"cleared by a human ({note}); was: {state['escalation_reason']}")


@dataclass
class PreflightFacts:
    kind: str                                   # "build" or "attempt"
    month: str
    monitor_status: str | None
    probe_ready: bool
    probe_detail: str
    execution_state: dict[str, Any]
    monthly_cap: int = DEFAULT_MONTHLY_MINUTE_CAP
    secrets_present: dict[str, bool] = field(default_factory=dict)
    forbidden_secrets_present: list[str] = field(default_factory=list)
    dump_available: bool = False
    phase4_complete: bool = False
    main_sha: str | None = None
    main_contains_published: bool | None = None
    published_contains_main: bool | None = None
    unreadable_facts: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class PreflightDecision:
    allowed: bool
    reasons: list[str]
    base_sha: str | None


def preflight(facts: PreflightFacts) -> PreflightDecision:
    """Every gate between a human's dispatch and any expensive work."""
    from automation.monitor_state import RECOVERY_CONFIRMED

    state = facts.execution_state
    validate_state(state)
    reasons: list[str] = [f"could not determine: {fact}" for fact in facts.unreadable_facts]

    if facts.phase4_complete:
        reasons.append("Phase 4 is already complete on origin/main")
    if state["status"] != READY:
        reasons.append(f"execution status is {state['status']}: {state['escalation_reason']}")
    if facts.monitor_status != RECOVERY_CONFIRMED:
        reasons.append(f"monitor status is {facts.monitor_status}, not {RECOVERY_CONFIRMED}")
    if not facts.probe_ready:
        reasons.append(f"fresh Statbotics readiness probe failed: {facts.probe_detail}")
    for name, present in sorted(facts.secrets_present.items()):
        if not present:
            reasons.append(f"required secret {name} is not configured")
    for name in facts.forbidden_secrets_present:
        reasons.append(f"secret {name} is configured; it would route usage to paid billing (decision D1/D11)")

    worst_case = ATTEMPT_WORST_CASE_MINUTES if facts.kind == "attempt" else BUILD_WORST_CASE_MINUTES
    used = state["ledger"].get(facts.month, 0)
    if used + worst_case + MONITOR_RESERVE_MINUTES > facts.monthly_cap:
        reasons.append(
            f"monthly minute cap: {used} used + {worst_case} worst case + {MONITOR_RESERVE_MINUTES} monitor "
            f"reserve exceeds {facts.monthly_cap}"
        )

    base_sha: str | None = None
    if facts.kind == "attempt":
        build = state["data_build"]
        if build is None or build["readiness_status"] != READINESS_COMPLETE:
            status = build["readiness_status"] if build else "no build recorded"
            reasons.append(f"historical data is not ready ({status}); run the data build first")
        elif not facts.dump_available:
            reasons.append("the recorded database dump artifact is no longer available (expired or deleted)")

        published = state["last_published"]
        if published is None or facts.main_contains_published:
            base_sha = facts.main_sha
        elif facts.published_contains_main:
            base_sha = published["sha"]
        else:
            reasons.append(
                f"{published['branch']} and main have diverged; a human must reconcile them "
                "(automation never rebases or overwrites human work)"
            )
        if base_sha is None and not any("diverged" in r for r in reasons):
            reasons.append("could not determine the commit to resume from")

    return PreflightDecision(allowed=not reasons, reasons=reasons, base_sha=base_sha if not reasons else None)
