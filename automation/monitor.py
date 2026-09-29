"""Daily Statbotics monitor entry point: `python -m automation.monitor`.

Reads the persisted state, runs one readiness check (or a human-only
command), appends one line to the audit log, writes the new state, and --
only when the state machine names a transition -- writes a Markdown
notification for the workflow to post on the Phase 4 tracking issue.

It never launches Phase 4. RECOVERY_CONFIRMED is reported to a human.

Exit status: 0 whenever the monitor did its job, including "Statbotics is
down" (that is the expected answer, not a failure). Non-zero only when the
monitor itself cannot operate -- e.g. an unreadable state file -- so GitHub's
own failed-run email reaches a human.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from automation.monitor_state import (
    ESCALATION_EVENTS,
    EVENT_MONITOR_INITIALIZED,
    EVENT_RECOVERY_CONFIRMED,
    Transition,
    apply_check,
    clear_escalation,
    initial_state,
    validate_state,
)
from automation.statbotics_health import ReadinessResult, check_statbotics_readiness

STATE_FILE = "monitor_state.json"
LOG_FILE = "monitor_log.jsonl"

MODE_CHECK = "check"
MODE_STATUS = "status"
MODE_CLEAR_ESCALATION = "clear-escalation"

_EVENT_TITLES = {
    EVENT_MONITOR_INITIALIZED: "Statbotics monitor started",
    "tentative_recovery": "Statbotics answered correctly once (not yet trusted)",
    EVENT_RECOVERY_CONFIRMED: "Statbotics readiness confirmed on two consecutive days — human action required",
    "recovery_lost": "Statbotics recovery revoked",
    "circuit_breaker": "Statbotics monitor circuit breaker tripped — human action required",
    "escalation_cleared": "Statbotics monitor escalation cleared",
}

_RECOVERY_CONFIRMED_NEXT_STEPS = """\
**This does not start Phase 4.** Unattended execution is not implemented; see
`docs/phase4_automation.md` for the decisions it is waiting on.

What this does and does not prove:
- Proven: the exact endpoint the pipeline calls returned real EPA for a known
  record, accepted by the production parse path, on two consecutive days.
- Not proven: historical coverage. `team_event_stats` has never been populated;
  M4–M7 need a full Statbotics season sync (`python -m data.orchestrator --season YEAR`)
  and a coverage check before any real-data acceptance work can begin.
"""


def load_state(state_dir: Path) -> tuple[dict[str, Any], bool]:
    path = state_dir / STATE_FILE
    if not path.exists():
        return initial_state(), True
    state = json.loads(path.read_text(encoding="utf-8"))
    validate_state(state)
    return state, False


def save_state(state_dir: Path, state: dict[str, Any]) -> None:
    state_dir.mkdir(parents=True, exist_ok=True)
    path = state_dir / STATE_FILE
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(state, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    tmp.replace(path)


def append_log(state_dir: Path, entry: dict[str, Any]) -> None:
    state_dir.mkdir(parents=True, exist_ok=True)
    with (state_dir / LOG_FILE).open("a", encoding="utf-8") as log:
        log.write(json.dumps(entry, sort_keys=True) + "\n")


def render_notification(
    event: str, message: str, state: dict[str, Any], *, owner: str | None, run_url: str | None,
) -> str:
    lines = [f"### {_EVENT_TITLES.get(event, event)}", ""]
    if event in ESCALATION_EVENTS and owner:
        lines += [f"@{owner}", ""]
    lines += [message, "", f"- Monitor status: `{state['status']}`"]
    check = state.get("last_check")
    if check:
        lines.append(f"- Last check: {check['checked_at']} — `{check['url']}`")
        if check["ready"]:
            lines.append(f"- EPA total {check['epa_total']}, matches played {check['matches_played']}")
        else:
            lines.append(f"- Stage {check['failed_stage']} failed: `{check['failure_code']}` ({check['detail']})")
    if run_url:
        lines.append(f"- Run: {run_url}")
    if event == EVENT_RECOVERY_CONFIRMED:
        lines += ["", _RECOVERY_CONFIRMED_NEXT_STEPS]
    lines += ["", "<sub>Automated by `.github/workflows/statbotics-monitor.yml`. "
              "Audit log: `monitor_log.jsonl` on the `automation/phase4-state` branch.</sub>"]
    return "\n".join(lines) + "\n"


def run(
    state_dir: Path,
    mode: str,
    *,
    checker: Callable[[], ReadinessResult] = check_statbotics_readiness,
    notify_out: Path | None = None,
    owner: str | None = None,
    run_url: str | None = None,
    now: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
) -> Transition:
    state, fresh = load_state(state_dir)

    if mode == MODE_STATUS:
        return Transition(state, None, f"status {state['status']}; last check: {state.get('last_check')}")

    before = state["status"]
    if mode == MODE_CHECK:
        transition = apply_check(state, checker())
    elif mode == MODE_CLEAR_ESCALATION:
        transition = clear_escalation(state)
    else:
        raise ValueError(f"unknown mode {mode!r}")

    event, message = transition.event, transition.message
    if fresh and event is None:
        event, message = EVENT_MONITOR_INITIALIZED, f"First check recorded. {message}"

    append_log(state_dir, {
        "recorded_at": now().isoformat(), "mode": mode, "status_before": before,
        "status_after": transition.state["status"], "event": event, "message": message,
        "check": transition.state.get("last_check") if mode == MODE_CHECK else None,
    })
    save_state(state_dir, transition.state)

    if event is not None and notify_out is not None:
        notify_out.write_text(
            render_notification(event, message, transition.state, owner=owner, run_url=run_url),
            encoding="utf-8",
        )
    return Transition(transition.state, event, message)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--state-dir", type=Path, required=True)
    parser.add_argument("--mode", choices=[MODE_CHECK, MODE_STATUS, MODE_CLEAR_ESCALATION], default=MODE_CHECK)
    parser.add_argument("--notify-out", type=Path, default=None,
                        help="Where to write a Markdown notification, only if a transition occurred.")
    parser.add_argument("--owner", default=None, help="GitHub handle to @-mention on escalations.")
    parser.add_argument("--run-url", default=None)
    args = parser.parse_args(argv)

    transition = run(
        args.state_dir, args.mode, notify_out=args.notify_out, owner=args.owner, run_url=args.run_url,
    )
    summary = f"Statbotics monitor [{args.mode}]: {transition.state['status']} — {transition.message}"
    if transition.event:
        summary += f" (event: {transition.event})"
    print(summary)
    step_summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if step_summary:
        with open(step_summary, "a", encoding="utf-8") as handle:
            handle.write(summary + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
