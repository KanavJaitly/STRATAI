"""Validate an attempt's git bundle and publish it as one branch + PR per milestone.

Runs in its own job, on a fresh runner that never executed anything Claude
wrote, from a pristine checkout of main -- so nothing produced during the
attempt can alter the code doing the validation. All-or-nothing: if any rule
fails, nothing is pushed and the outcome is harness_violation.

Rules, per bundled branch:
- name is automation/phase4-mNN with NN in 03..13 (one branch per milestone);
- its tip descends from the attempt's base commit (no rewritten history);
- it changes nothing in PROTECTED_PATHS (the harness, the rules, and the
  acceptance criteria are not something an attempt may edit);
- the push is a plain, non-force push, so a branch a human has since changed
  is rejected rather than overwritten.

PR creation can be disabled for GITHUB_TOKEN by a repository setting; then the
branches are still pushed and the notification carries compare links instead.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Callable, Sequence

BRANCH_PATTERN = re.compile(r"^automation/phase4-m(0[3-9]|1[0-3])$")
# The harness, the rules it enforces (MASTER_BUILD.md, the unattended prompt)
# and the acceptance criteria themselves (P4Milestones.md): an attempt that
# could edit these could lower its own bar.
PROTECTED_PATHS = (".github/", "automation/", "prompts/", "docs/P4Milestones.md", "tests/test_automation_")
ACCEPTANCE_PATTERN = re.compile(r"^\.agent/phase4/M\d\d_ACCEPTANCE\.md$")
IMPORT_NAMESPACE = "refs/phase4-import/"

Runner = Callable[[Sequence[str]], subprocess.CompletedProcess]


@dataclass
class PublishResult:
    ok: bool
    violations: list[str] = field(default_factory=list)
    published: dict[str, str] = field(default_factory=dict)
    new_acceptance_files: list[str] = field(default_factory=list)
    pull_requests: dict[str, str] = field(default_factory=dict)
    compare_links: dict[str, str] = field(default_factory=dict)
    push_failures: dict[str, str] = field(default_factory=dict)

    def to_dict(self) -> dict:
        return asdict(self)


def _git(repo: Path, runner: Runner) -> Callable[..., subprocess.CompletedProcess]:
    def git(*args: str, check: bool = True) -> subprocess.CompletedProcess:
        result = runner(["git", "-C", str(repo), "-c", "core.hooksPath=/dev/null", *args])
        if check and result.returncode != 0:
            raise RuntimeError(f"git {' '.join(args)} failed: {result.stderr.strip()}")
        return result
    return git


def _run(command: Sequence[str]) -> subprocess.CompletedProcess:
    return subprocess.run(list(command), capture_output=True, text=True)


def bundle_branches(repo: Path, bundle: Path, runner: Runner = _run) -> dict[str, str]:
    git = _git(repo, runner)
    git("bundle", "verify", str(bundle))
    heads = git("bundle", "list-heads", str(bundle)).stdout.split()
    return {ref: sha for sha, ref in zip(heads[0::2], heads[1::2])}


def validate_and_publish(
    repo: Path, bundle: Path, *, base_sha: str, repository: str,
    runner: Runner = _run, gh: Runner = _run,
) -> PublishResult:
    git = _git(repo, runner)
    result = PublishResult(ok=False)
    refs = bundle_branches(repo, bundle, runner)

    branches: dict[str, str] = {}
    for ref, sha in refs.items():
        name = ref.removeprefix("refs/heads/")
        if not ref.startswith("refs/heads/") or not BRANCH_PATTERN.match(name):
            result.violations.append(f"disallowed ref in bundle: {ref}")
            continue
        branches[name] = sha
    if result.violations:
        return result  # all-or-nothing: one bad ref rejects the attempt
    if not branches:
        result.ok = True  # nothing committed this attempt; not a violation
        return result

    git("fetch", "--quiet", str(bundle), *[f"refs/heads/{b}:{IMPORT_NAMESPACE}{b}" for b in branches])
    main_files = set(git("ls-tree", "-r", "--name-only", base_sha, "--", ".agent/phase4/").stdout.split())
    for name, sha in sorted(branches.items()):
        if git("merge-base", "--is-ancestor", base_sha, sha, check=False).returncode != 0:
            result.violations.append(f"{name} does not descend from the attempt base {base_sha[:12]}")
            continue
        changed = git("diff", "--name-only", base_sha, sha).stdout.split()
        touched = sorted(path for path in changed if path.startswith(PROTECTED_PATHS))
        if touched:
            result.violations.append(f"{name} modifies protected harness paths: {touched}")
        branch_files = set(git("ls-tree", "-r", "--name-only", sha, "--", ".agent/phase4/").stdout.split())
        result.new_acceptance_files.extend(
            path for path in sorted(branch_files - main_files) if ACCEPTANCE_PATTERN.match(path)
        )
    if result.violations:
        result.new_acceptance_files = []
        return result

    result.new_acceptance_files = sorted(set(result.new_acceptance_files))
    previous = "main"
    for name, sha in sorted(branches.items()):
        push = git("push", "--quiet", "origin", f"{sha}:refs/heads/{name}", check=False)
        if push.returncode != 0:
            result.push_failures[name] = push.stderr.strip()[:500]
            continue
        result.published[name] = sha
        pr_base = previous if previous == "main" or git(
            "merge-base", "--is-ancestor", branches[previous], sha, check=False).returncode == 0 else "main"
        result.pull_requests[name] = _ensure_pull_request(gh, repository, name, pr_base)
        if not result.pull_requests[name].startswith("https://"):
            result.compare_links[name] = f"https://github.com/{repository}/compare/{pr_base}...{name}?expand=1"
        previous = name
    result.ok = not result.push_failures
    return result


def _ensure_pull_request(gh: Runner, repository: str, branch: str, base: str) -> str:
    existing = gh(["gh", "pr", "list", "--repo", repository, "--head", branch, "--state", "open",
                   "--json", "url", "--jq", ".[0].url"])
    if existing.returncode == 0 and existing.stdout.strip():
        return existing.stdout.strip()
    milestone = branch.rsplit("-", 1)[-1].upper()
    body = (f"Automated Phase 4 attempt output for {milestone}. Review the milestone's own acceptance "
            f"artifact and real-data numbers before merging; merging is the human acceptance step.\n\n"
            f"Stacked on `{base}`.\n\n🤖 Generated with [Claude Code](https://claude.com/claude-code)")
    created = gh(["gh", "pr", "create", "--repo", repository, "--head", branch, "--base", base,
                  "--title", f"Phase 4 {milestone} (automated attempt)", "--body", body])
    if created.returncode == 0:
        return created.stdout.strip().splitlines()[-1]
    return f"not created: {created.stderr.strip()[:300]}"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--repo", type=Path, required=True)
    parser.add_argument("--bundle", type=Path, required=True)
    parser.add_argument("--base-sha", required=True)
    parser.add_argument("--repository", required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args(argv)
    result = validate_and_publish(args.repo, args.bundle, base_sha=args.base_sha, repository=args.repository)
    args.out.write_text(json.dumps(result.to_dict(), indent=2), encoding="utf-8")
    print(json.dumps(result.to_dict(), indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
