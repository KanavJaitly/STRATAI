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

Paths are read as git stores them, never as git displays them: NUL-separated
output with core.quotePath off (the quoted display form of a non-ASCII path,
"automation/\303\251.py", would not start with "automation/"), --no-renames
(a rename out of a protected directory must show the deletion too), and UTF-8
decoding with surrogateescape.

Each published branch also carries a manifest -- every path it changes
relative to its merge-base with main, and that path's blob (None if deleted) --
so a later preflight can recognise the work on main after a squash or rebase
merge rewrote the commits (see execution_state.preflight).

PR creation can be disabled for GITHUB_TOKEN by a repository setting; then the
branches are still pushed and the notification carries compare links instead.

main() always writes its result file: a missing bundle is "nothing to
publish", and an exception is recorded as {"ok": false, "error": ...}. The
recorder treats a missing file as an infrastructure failure.
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
    manifests: dict[str, dict[str, str | None]] = field(default_factory=dict)
    bundle_present: bool = True
    error: str | None = None

    def to_dict(self) -> dict:
        return asdict(self)


def _git(repo: Path, runner: Runner) -> Callable[..., subprocess.CompletedProcess]:
    def git(*args: str, check: bool = True) -> subprocess.CompletedProcess:
        result = runner(["git", "-C", str(repo), "-c", "core.hooksPath=/dev/null", "-c", "core.quotePath=false",
                         *args])
        if check and result.returncode != 0:
            raise RuntimeError(f"git {' '.join(args)} failed: {result.stderr.strip()}")
        return result
    return git


def _run(command: Sequence[str]) -> subprocess.CompletedProcess:
    # UTF-8, not the locale codepage: git emits path bytes verbatim.
    return subprocess.run(list(command), capture_output=True, text=True, encoding="utf-8", errors="surrogateescape")


def _nul_split(output: str) -> list[str]:
    return [path for path in output.split("\0") if path]


def changed_paths(git: Callable[..., subprocess.CompletedProcess], old: str, new: str) -> list[str]:
    return _nul_split(git("diff", "-z", "--name-only", "--no-renames", old, new).stdout)


def tree_blobs(git: Callable[..., subprocess.CompletedProcess], commit: str, *paths: str) -> dict[str, str]:
    """{path: blob sha} for every file under paths (the whole tree if none) at commit."""
    blobs = {}
    for entry in _nul_split(git("ls-tree", "-r", "-z", commit, "--", *paths).stdout):
        meta, _, path = entry.partition("\t")
        blobs[path] = meta.split()[2]
    return blobs


def bundle_branches(repo: Path, bundle: Path, runner: Runner = _run) -> dict[str, str]:
    git = _git(repo, runner)
    git("bundle", "verify", str(bundle))
    heads = git("bundle", "list-heads", str(bundle)).stdout.split()
    return {ref: sha for sha, ref in zip(heads[0::2], heads[1::2])}


def validate_and_publish(
    repo: Path, bundle: Path, *, base_sha: str, repository: str,
    runner: Runner = _run, gh: Runner = _run, main_ref: str = "origin/main",
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
    main_files = set(tree_blobs(git, base_sha, ".agent/phase4/"))
    acceptance_by_branch: dict[str, list[str]] = {}
    for name, sha in sorted(branches.items()):
        if git("merge-base", "--is-ancestor", base_sha, sha, check=False).returncode != 0:
            result.violations.append(f"{name} does not descend from the attempt base {base_sha[:12]}")
            continue
        touched = sorted(path for path in changed_paths(git, base_sha, sha) if path.startswith(PROTECTED_PATHS))
        if touched:
            result.violations.append(f"{name} modifies protected harness paths: {touched}")
        branch_files = set(tree_blobs(git, sha, ".agent/phase4/"))
        acceptance_by_branch[name] = [p for p in sorted(branch_files - main_files) if ACCEPTANCE_PATTERN.match(p)]
        merge_base = git("merge-base", main_ref, sha).stdout.strip()
        blobs = tree_blobs(git, sha)
        result.manifests[name] = {path: blobs.get(path) for path in changed_paths(git, merge_base, sha)}
    if result.violations:
        result.manifests = {}
        return result

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
    # Only artifacts that actually reached the remote count, and none at all if
    # any push failed: a partial publication is not progress.
    if not result.push_failures:
        result.new_acceptance_files = sorted({p for b in result.published for p in acceptance_by_branch[b]})
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
    if not args.bundle.exists():
        result = PublishResult(ok=True, bundle_present=False)  # the attempt committed nothing
    else:
        try:
            result = validate_and_publish(args.repo, args.bundle, base_sha=args.base_sha, repository=args.repository)
        except Exception as exc:  # recorded, not swallowed: the recorder makes this infrastructure_failed
            result = PublishResult(ok=False, error=f"{type(exc).__name__}: {exc}"[:2000])
    args.out.write_text(json.dumps(result.to_dict(), indent=2), encoding="utf-8")
    print(json.dumps(result.to_dict(), indent=2))
    return 0 if result.ok else 1


if __name__ == "__main__":
    sys.exit(main())
