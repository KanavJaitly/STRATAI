"""Run one unattended Phase 4 attempt with Claude Code and classify how it ended.

Authentication is CLAUDE_CODE_OAUTH_TOKEN only (decision D1). ANTHROPIC_API_KEY
is stripped from the child environment -- if it were present the CLI would bill
the API instead of the subscription -- along with every GitHub credential:
Claude commits locally and never pushes; a separate job validates and
publishes its work.

Claude's own report is untrusted input. It can only ever lower the verdict:
a timeout is budget_exhausted and a usage-limit message is usage_exhausted no
matter what the report claims, and a missing or malformed report is
claude_failed.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path
from string import Template
from typing import Any, Callable

from automation.execution_state import (
    OUTCOME_AWAITING_SIGNOFF,
    OUTCOME_BUDGET_EXHAUSTED,
    OUTCOME_CLAUDE_FAILED,
    OUTCOME_ESCALATED,
    OUTCOME_PROGRESS,
    OUTCOME_USAGE_EXHAUSTED,
)

# Outcomes Claude itself may report; everything else is decided by this runner.
CLAIMABLE_OUTCOMES = frozenset({OUTCOME_PROGRESS, OUTCOME_AWAITING_SIGNOFF, OUTCOME_ESCALATED})
USAGE_EXHAUSTION_MARKERS = (
    "usage limit", "limit reached", "rate_limit_error", "credit balance", "out of credits", "quota exceeded",
)
STRIPPED_ENV = ("ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN", "GITHUB_TOKEN", "GH_TOKEN", "ACTIONS_RUNTIME_TOKEN",
                "ACTIONS_ID_TOKEN_REQUEST_TOKEN", "ACTIONS_ID_TOKEN_REQUEST_URL")
ALLOWED_TOOLS = "Read Edit Write Glob Grep Bash TodoWrite Agent"


def render_prompt(template_path: Path, values: dict[str, str]) -> str:
    return Template(template_path.read_text(encoding="utf-8")).substitute(values)


def child_environment(base: dict[str, str]) -> dict[str, str]:
    env = {key: value for key, value in base.items() if key not in STRIPPED_ENV}
    if not env.get("CLAUDE_CODE_OAUTH_TOKEN"):
        raise RuntimeError("CLAUDE_CODE_OAUTH_TOKEN is not set; refusing to run (decision D1)")
    return env


def _cli_reported_error(output: str) -> bool:
    """`--output-format json` ends with one result object carrying is_error."""
    for line in reversed(output.strip().splitlines()):
        try:
            result = json.loads(line)
        except ValueError:
            continue
        return isinstance(result, dict) and bool(result.get("is_error"))
    return False


def classify(
    *, returncode: int | None, timed_out: bool, output: str, report_path: Path,
) -> dict[str, Any]:
    if timed_out:
        return {"outcome": OUTCOME_BUDGET_EXHAUSTED, "stop_reason": "attempt time budget reached; work up to the last commit is kept"}
    # Only an errored run is scanned for limit wording: a successful run may
    # legitimately mention "usage limit" in its own text.
    if returncode != 0 or _cli_reported_error(output):
        if any(marker in output.lower() for marker in USAGE_EXHAUSTION_MARKERS):
            return {"outcome": OUTCOME_USAGE_EXHAUSTED, "stop_reason": "Claude reported a usage or rate limit"}
        return {"outcome": OUTCOME_CLAUDE_FAILED, "stop_reason": f"claude exited with status {returncode} or reported an error"}
    try:
        report = json.loads(report_path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        return {"outcome": OUTCOME_CLAUDE_FAILED, "stop_reason": f"no valid attempt report: {type(exc).__name__}"}
    if not isinstance(report, dict) or report.get("outcome") not in CLAIMABLE_OUTCOMES:
        return {"outcome": OUTCOME_CLAUDE_FAILED, "stop_reason": "attempt report has no recognised outcome"}
    stop_reason = report.get("stop_reason")
    milestones = report.get("milestones")
    return {
        "outcome": report["outcome"],
        "stop_reason": str(stop_reason)[:2000] if stop_reason else "(no reason given)",
        "claimed_milestones": {str(k): str(v) for k, v in milestones.items()} if isinstance(milestones, dict) else {},
    }


def run(
    *, prompt: str, minutes: float, report_path: Path, env: dict[str, str], workdir: Path | None = None,
    runner: Callable[..., subprocess.CompletedProcess] = subprocess.run,
) -> dict[str, Any]:
    command = ["claude", "-p", prompt, "--output-format", "json",
               "--permission-mode", "dontAsk", "--allowedTools", ALLOWED_TOOLS]
    try:
        completed = runner(command, env=env, cwd=workdir, capture_output=True, text=True, timeout=minutes * 60)
    except subprocess.TimeoutExpired as exc:
        output = f"{exc.stdout or ''}{exc.stderr or ''}"
        return classify(returncode=None, timed_out=True, output=str(output), report_path=report_path)
    return classify(returncode=completed.returncode, timed_out=False,
                    output=f"{completed.stdout}{completed.stderr}", report_path=report_path)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--template", type=Path, required=True)
    parser.add_argument("--minutes", type=float, required=True, help="Hard wall-clock limit for Claude.")
    parser.add_argument("--report", type=Path, required=True, help="Where Claude is told to write its report.")
    parser.add_argument("--outcome-out", type=Path, required=True)
    parser.add_argument("--attempt-id", required=True)
    parser.add_argument("--base-sha", required=True)
    parser.add_argument("--workdir", type=Path, required=True,
                        help="Checkout Claude works in -- separate from the trusted harness checkout running this.")
    args = parser.parse_args(argv)

    prompt = render_prompt(args.template, {
        "attempt_id": args.attempt_id, "base_sha": args.base_sha,
        "report_path": str(args.report), "minutes": f"{args.minutes:.0f}",
    })
    outcome = run(prompt=prompt, minutes=args.minutes, report_path=args.report,
                  env=child_environment(dict(os.environ)), workdir=args.workdir)
    args.outcome_out.write_text(json.dumps(outcome, indent=2), encoding="utf-8")
    print(f"attempt {args.attempt_id}: {outcome['outcome']} — {outcome['stop_reason']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
