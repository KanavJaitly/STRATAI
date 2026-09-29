"""Workflow entry points for Phase 4 data builds and attempts: `python -m automation.ops`.

Each subcommand gathers facts (git, GitHub API, Statbotics), hands them to the
pure decision functions in execution_state / execution_lock / completion, and
persists the result on the state branch. Decisions live in those modules; this
one only does I/O.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Sequence

from automation import execution_state as es
from automation.completion import CompletionFacts, evaluate
from automation.execution_lock import GitHubRestRefs, LockOwner, acquire, release
from automation.monitor import load_state as load_monitor_state
from automation.statbotics_health import check_statbotics_readiness

EXECUTION_STATE_FILE = "execution_state.json"
EXECUTION_LOG_FILE = "execution_log.jsonl"
TRACKING_ISSUE_ENV = "TRACKING_ISSUE"

Runner = Callable[[Sequence[str]], subprocess.CompletedProcess]


def _run(command: Sequence[str]) -> subprocess.CompletedProcess:
    return subprocess.run(list(command), capture_output=True, text=True)


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def load_execution_state(state_dir: Path) -> dict[str, Any]:
    path = state_dir / EXECUTION_STATE_FILE
    if not path.exists():
        return es.initial_state()
    state = json.loads(path.read_text(encoding="utf-8"))
    es.validate_state(state)
    return state


def save_execution_state(state_dir: Path, state: dict[str, Any], entry: dict[str, Any]) -> None:
    state_dir.mkdir(parents=True, exist_ok=True)
    tmp = state_dir / f"{EXECUTION_STATE_FILE}.tmp"
    tmp.write_text(json.dumps(state, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    tmp.replace(state_dir / EXECUTION_STATE_FILE)
    with (state_dir / EXECUTION_LOG_FILE).open("a", encoding="utf-8") as log:
        log.write(json.dumps(entry, sort_keys=True, default=str) + "\n")


def write_output(**values: Any) -> None:
    path = os.environ.get("GITHUB_OUTPUT")
    if path:
        with open(path, "a", encoding="utf-8") as handle:
            for key, value in values.items():
                handle.write(f"{key}={str(value).lower() if isinstance(value, bool) else value}\n")


def notify(path: Path | None, title: str, body: str, *, mention: str | None) -> None:
    if path is None:
        return
    lines = [f"### {title}", ""]
    if mention:
        lines += [f"@{mention}", ""]
    lines += [body, "", "<sub>Automated by the Phase 4 execution workflows "
              "(docs/phase4_automation.md). Audit log: `execution_log.jsonl` on "
              "`automation/phase4-state`.</sub>"]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _flag(name: str) -> bool:
    return os.environ.get(name, "").strip().lower() == "true"


# --- facts ---------------------------------------------------------------


def is_ancestor(repo: Path, ancestor: str, descendant: str, runner: Runner = _run) -> bool:
    return runner(["git", "-C", str(repo), "merge-base", "--is-ancestor", ancestor, descendant]).returncode == 0


def dump_available(repository: str, dump: dict[str, Any], runner: Runner = _run) -> bool:
    listed = runner(["gh", "api", f"repos/{repository}/actions/runs/{dump['run_id']}/artifacts",
                     "--jq", ".artifacts[] | [.name, .expired] | @tsv"])
    if listed.returncode != 0:
        return False
    for line in listed.stdout.splitlines():
        name, _, expired = line.partition("\t")
        if name == dump["artifact_name"] and expired.strip() == "false":
            return True
    return False


def completion_facts(repo: Path, repository: str, issue: str, runner: Runner = _run) -> CompletionFacts:
    listed = runner(["git", "-C", str(repo), "ls-tree", "--name-only", "origin/main", ".agent/phase4/"])
    issue_state = runner(["gh", "issue", "view", issue, "--repo", repository, "--json", "state", "--jq", ".state"])
    prs = runner(["gh", "pr", "list", "--repo", repository, "--state", "open", "--json", "headRefName",
                  "--jq", ".[].headRefName", "--limit", "200"])
    if listed.returncode != 0 or issue_state.returncode != 0 or prs.returncode != 0:
        raise RuntimeError("could not read completion facts from git/GitHub")
    return CompletionFacts(
        files_on_main=frozenset(Path(line).name for line in listed.stdout.split()),
        tracking_issue_state=issue_state.stdout.strip(),
        open_pr_head_branches=frozenset(prs.stdout.split()),
    )


def billed_minutes_from_jobs(jobs: list[dict[str, Any]], now: datetime) -> int:
    seconds = []
    for job in jobs:
        if not job.get("started_at"):
            continue
        started = datetime.fromisoformat(job["started_at"].replace("Z", "+00:00"))
        finished = datetime.fromisoformat(job["completed_at"].replace("Z", "+00:00")) if job.get("completed_at") else now
        seconds.append(max(0.0, (finished - started).total_seconds()))
    return es.billed_minutes(seconds)


def run_billed_minutes(repository: str, run_id: str, runner: Runner = _run) -> int:
    listed = runner(["gh", "api", f"repos/{repository}/actions/runs/{run_id}/jobs", "--jq", ".jobs"])
    if listed.returncode != 0:
        # Unknown usage must never read as zero: charge the documented worst case.
        return es.ATTEMPT_WORST_CASE_MINUTES
    return billed_minutes_from_jobs(json.loads(listed.stdout or "[]"), _utc_now())


# --- subcommands -----------------------------------------------------------


def cmd_preflight(args: argparse.Namespace) -> int:
    state = load_execution_state(args.state_dir)
    monitor_status = None
    if (args.state_dir / "monitor_state.json").exists():
        monitor_status = load_monitor_state(args.state_dir)[0]["status"]
    probe = check_statbotics_readiness()
    repo, repository = Path(args.repo), os.environ["GITHUB_REPOSITORY"]

    main_sha = _run(["git", "-C", str(repo), "rev-parse", "origin/main"]).stdout.strip() or None
    facts = es.PreflightFacts(
        kind=args.kind, month=_utc_now().strftime("%Y-%m"),
        monitor_status=monitor_status, probe_ready=probe.ready,
        probe_detail=f"{probe.failure_code}: {probe.detail}", execution_state=state,
        monthly_cap=int(os.environ.get("PHASE4_MONTHLY_MINUTE_CAP") or es.DEFAULT_MONTHLY_MINUTE_CAP),
        secrets_present={name: _flag(f"HAS_{name}") for name in args.require_secret},
        forbidden_secrets_present=[name for name in ("ANTHROPIC_API_KEY",) if _flag(f"HAS_{name}")],
        main_sha=main_sha,
    )
    try:
        facts.phase4_complete = evaluate(completion_facts(repo, repository, os.environ[TRACKING_ISSUE_ENV])).complete
    except RuntimeError as exc:
        facts.unreadable_facts.append(f"whether Phase 4 is already complete ({exc})")
    if main_sha is None:
        facts.unreadable_facts.append("the origin/main commit")
    if args.kind == "attempt":
        if state["data_build"] and state["data_build"].get("dump"):
            facts.dump_available = dump_available(repository, state["data_build"]["dump"])
        published = state["last_published"]
        if published and main_sha:
            _run(["git", "-C", str(repo), "fetch", "--quiet", "origin", published["sha"]])
            facts.main_contains_published = is_ancestor(repo, published["sha"], main_sha)
            facts.published_contains_main = is_ancestor(repo, main_sha, published["sha"])

    decision = es.preflight(facts)
    args.out.write_text(json.dumps({
        "allowed": decision.allowed, "reasons": decision.reasons, "base_sha": decision.base_sha,
        "probe": probe.to_dict(), "monitor_status": monitor_status,
    }, indent=2), encoding="utf-8")
    write_output(allowed=decision.allowed, base_sha=decision.base_sha or "")
    print("preflight " + ("PASSED" if decision.allowed else "REFUSED"))
    for reason in decision.reasons:
        print(f"  - {reason}")
    return 0


def _lock_api() -> GitHubRestRefs:
    return GitHubRestRefs(os.environ["GITHUB_REPOSITORY"], os.environ["GH_TOKEN"])


def cmd_lock(args: argparse.Namespace) -> int:
    owner = LockOwner(run_id=args.run_id, kind=args.kind, acquired_at=_utc_now().isoformat())
    if args.action == "acquire":
        result = acquire(_lock_api(), owner, args.base_sha)
        write_output(acquired=result.acquired)
        print(f"lock: {'ACQUIRED' if result.acquired else 'NOT ACQUIRED'} — {result.reason}")
        return 0
    released = release(_lock_api(), owner)
    print("lock: released" if released else "lock: not held by this run; left untouched")
    return 0


def cmd_record_build(args: argparse.Namespace) -> int:
    state = load_execution_state(args.state_dir)
    report = json.loads(args.report.read_text(encoding="utf-8")) if args.report.exists() else None
    dump = json.loads(args.dump_meta.read_text(encoding="utf-8")) if args.dump_meta and args.dump_meta.exists() else None
    readiness = (report or {}).get("readiness", {})
    build = {
        "run_id": args.run_id, "finished_at": _utc_now().isoformat(),
        "billed_minutes": run_billed_minutes(os.environ["GITHUB_REPOSITORY"], args.run_id),
        "readiness_status": readiness.get("status", "UNKNOWN"),
        "readiness_reasons": readiness.get("reasons", ["build produced no report"]),
        "valid_source_rows": readiness.get("valid_source_rows", 0),
        "required_source_rows": readiness.get("required_source_rows", 0),
        "fingerprint": readiness.get("team_event_stats_fingerprint"),
        "stop_reason": ((report or {}).get("build") or {}).get("stop_reason") or ("no report" if report is None else "finished"),
        "dump": dump,
    }
    transition = es.record_build(state, build, month=_utc_now().strftime("%Y-%m"))
    save_execution_state(args.state_dir, transition.state, {"event": transition.event, "build": build})
    body = "\n".join([transition.message, "", *[f"- {r}" for r in build["readiness_reasons"]],
                      f"- Billed minutes this run: {build['billed_minutes']}", f"- Run: {args.run_url}"])
    if transition.event == es.EVENT_DATA_READY:
        body += ("\n\nThis authorizes a human to dispatch `phase4-execute.yml`; it does not start Phase 4.")
    notify(args.notify_out, f"Phase 4 data build: {build['readiness_status']}", body,
           mention=args.owner if transition.event in es.HUMAN_EVENTS else None)
    print(transition.message)
    return 0


def cmd_record_attempt(args: argparse.Namespace) -> int:
    state = load_execution_state(args.state_dir)
    outcome = json.loads(args.outcome.read_text(encoding="utf-8")) if args.outcome.exists() else {
        "outcome": es.OUTCOME_INFRASTRUCTURE_FAILED,
        "stop_reason": "the execute job produced no outcome (runner lost, restore or setup failed)"}
    published = json.loads(args.publish.read_text(encoding="utf-8")) if args.publish.exists() else None
    if published and published["violations"]:
        outcome = {"outcome": es.OUTCOME_HARNESS_VIOLATION, "stop_reason": "; ".join(published["violations"])}
    elif published and published["push_failures"]:
        outcome = {"outcome": es.OUTCOME_INFRASTRUCTURE_FAILED,
                   "stop_reason": f"push failed for {sorted(published['push_failures'])}; possible divergence from human changes"}
    attempt = {
        "attempt_id": args.run_id, "run_id": args.run_id, "base_sha": args.base_sha,
        "outcome": outcome["outcome"], "stop_reason": outcome["stop_reason"],
        "claimed_milestones": outcome.get("claimed_milestones", {}),
        "billed_minutes": run_billed_minutes(os.environ["GITHUB_REPOSITORY"], args.run_id),
        "published": (published or {}).get("published", {}),
        "new_acceptance_files": (published or {}).get("new_acceptance_files", []),
        "finished_at": _utc_now().isoformat(),
    }
    transition = es.record_attempt(state, attempt, month=_utc_now().strftime("%Y-%m"))
    save_execution_state(args.state_dir, transition.state, {"event": transition.event, "attempt": attempt})

    lines = [transition.message, "", f"- Outcome: `{attempt['outcome']}`",
             f"- New acceptance artifacts (awaiting your PR review): {attempt['new_acceptance_files'] or 'none'}",
             f"- Billed minutes this attempt: {attempt['billed_minutes']}", f"- Run: {args.run_url}"]
    for branch, link in sorted(((published or {}).get("pull_requests") or {}).items()):
        lines.append(f"- {branch}: {link}")
    for branch, link in sorted(((published or {}).get("compare_links") or {}).items()):
        lines.append(f"- Open a PR for {branch}: {link}")
    notify(args.notify_out, f"Phase 4 attempt: {attempt['outcome']}", "\n".join(lines),
           mention=args.owner if transition.event in es.HUMAN_EVENTS else None)
    print(transition.message)
    return 0


def cmd_clear(args: argparse.Namespace) -> int:
    transition = es.clear(load_execution_state(args.state_dir), note=args.note)
    save_execution_state(args.state_dir, transition.state, {"event": transition.event, "note": args.note})
    notify(args.notify_out, "Phase 4 execution state cleared", transition.message, mention=None)
    print(transition.message)
    return 0


def cmd_completion(args: argparse.Namespace) -> int:
    # Unreadable facts mean "not complete": shutdown must never fire on a guess,
    # and a GitHub API hiccup must not cost the monitor its daily check.
    try:
        verdict = evaluate(completion_facts(Path(args.repo), os.environ["GITHUB_REPOSITORY"],
                                            os.environ[TRACKING_ISSUE_ENV]))
    except RuntimeError as exc:
        write_output(complete=False)
        print(f"phase 4 completion unknown ({exc}); treating as not complete")
        return 0
    write_output(complete=verdict.complete)
    if verdict.complete:
        notify(args.notify_out, "Phase 4 complete — automation disabled",
               "origin/main holds every Phase 4 acceptance artifact and PHASE_ACCEPTANCE.md, the tracking issue "
               "is closed, and no automation PR is open. The monitor, data-build and execute workflows are being "
               "disabled (not deleted); their history and the state branch remain for audit.",
               mention=args.owner)
    print("phase 4 complete" if verdict.complete else f"phase 4 not complete: {verdict.missing}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    def common(p: argparse.ArgumentParser, *, state: bool = True) -> None:
        if state:
            p.add_argument("--state-dir", type=Path, required=True)
        p.add_argument("--notify-out", type=Path, default=None)
        p.add_argument("--owner", default=None)
        p.add_argument("--run-url", default=None)

    p = sub.add_parser("preflight")
    common(p)
    p.add_argument("--kind", choices=["build", "attempt"], required=True)
    p.add_argument("--repo", default=".")
    p.add_argument("--require-secret", action="append", default=[])
    p.add_argument("--out", type=Path, required=True)
    p.set_defaults(func=cmd_preflight)

    p = sub.add_parser("lock")
    p.add_argument("action", choices=["acquire", "release"])
    p.add_argument("--kind", choices=["build", "attempt"], required=True)
    p.add_argument("--run-id", required=True)
    p.add_argument("--base-sha", default="")
    p.set_defaults(func=cmd_lock)

    p = sub.add_parser("record-build")
    common(p)
    p.add_argument("--run-id", required=True)
    p.add_argument("--report", type=Path, required=True)
    p.add_argument("--dump-meta", type=Path, default=None)
    p.set_defaults(func=cmd_record_build)

    p = sub.add_parser("record-attempt")
    common(p)
    p.add_argument("--run-id", required=True)
    p.add_argument("--base-sha", required=True)
    p.add_argument("--outcome", type=Path, required=True)
    p.add_argument("--publish", type=Path, required=True)
    p.set_defaults(func=cmd_record_attempt)

    p = sub.add_parser("clear")
    common(p)
    p.add_argument("--note", required=True)
    p.set_defaults(func=cmd_clear)

    p = sub.add_parser("completion")
    common(p, state=False)
    p.add_argument("--repo", default=".")
    p.set_defaults(func=cmd_completion)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
