"""Publish one workflow's change to the automation/phase4-state branch safely:
`python -m automation.state_push`.

The monitor and the heavy workflows all write to the same branch, and a heavy
job holds its checkout for hours, so its push is routinely behind. This makes
publication an optimistic-concurrency loop:

    commit only this workflow's own files
    repeat at most MAX_ATTEMPTS times:
        fetch the branch's latest tip
        rebase the commit onto it          (conflict -> abort, fail closed)
        plain push                         (rejected -> someone pushed; retry)

The workflows write disjoint files (monitor_* vs execution_*), so a rebase
keeps both sides' changes. A real conflict -- two writers changing the same
file, e.g. a human-dispatched `clear` racing a build's record -- is never
resolved by picking a side: the rebase is aborted, nothing is pushed, and the
command exits non-zero so the workflow reports the state as unpublished. There
is no force push anywhere, and never an unbounded loop.
"""

from __future__ import annotations

import argparse
import subprocess
import sys
import time
from pathlib import Path
from typing import Callable, Sequence

MAX_ATTEMPTS = 5
PUBLISHED = "published"
NOTHING = "nothing_to_publish"      # the files were staged and are unchanged
ADD_FAILED = "add_failed"           # could not stage: never read as "nothing to publish"
COMMIT_FAILED = "commit_failed"
CONFLICT = "conflict"
EXHAUSTED = "retries_exhausted"
SUCCESS_STATUSES = frozenset({PUBLISHED, NOTHING})

Runner = Callable[[Sequence[str]], subprocess.CompletedProcess]


def _run(command: Sequence[str]) -> subprocess.CompletedProcess:
    return subprocess.run(list(command), capture_output=True, text=True, encoding="utf-8", errors="surrogateescape")


def publish_state(
    state_dir: Path, *, branch: str, paths: Sequence[str], message: str,
    runner: Runner = _run, max_attempts: int = MAX_ATTEMPTS, pause: Callable[[float], None] = time.sleep,
) -> tuple[str, str]:
    """Returns (status, detail). Only status == PUBLISHED means the change is on the remote."""

    def git(*args: str) -> subprocess.CompletedProcess:
        return runner(["git", "-C", str(state_dir), "-c", "core.hooksPath=/dev/null", *args])

    added = git("add", "--", *paths)
    if added.returncode != 0:
        return ADD_FAILED, f"could not stage {list(paths)}: {added.stderr.strip()[:500]}"
    if git("diff", "--cached", "--quiet").returncode == 0:
        return NOTHING, "no state change to publish"
    commit = git("commit", "--quiet", "-m", message)
    if commit.returncode != 0:
        return COMMIT_FAILED, f"could not commit state: {commit.stderr.strip()[:500]}"

    for attempt in range(1, max_attempts + 1):
        fetched = git("fetch", "--quiet", "origin", branch)
        if fetched.returncode == 0:
            rebased = git("rebase", "--quiet", "FETCH_HEAD")
            if rebased.returncode != 0:
                git("rebase", "--abort")
                return CONFLICT, f"state change conflicts with newer remote state: {rebased.stderr.strip()[:500]}"
        # A failed fetch means the branch does not exist yet; the push creates
        # it, and is rejected if another writer created it first.
        pushed = git("push", "--quiet", "origin", f"HEAD:refs/heads/{branch}")
        if pushed.returncode == 0:
            return PUBLISHED, f"published on attempt {attempt}"
        pause(min(2 ** attempt, 20))
    return EXHAUSTED, f"remote kept advancing; gave up after {max_attempts} attempts"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--state-dir", type=Path, required=True)
    parser.add_argument("--branch", required=True)
    parser.add_argument("--message", required=True)
    parser.add_argument("paths", nargs="+")
    args = parser.parse_args(argv)
    status, detail = publish_state(args.state_dir, branch=args.branch, paths=args.paths, message=args.message)
    print(f"state {status}: {detail}")
    return 0 if status in SUCCESS_STATUSES else 1


if __name__ == "__main__":
    sys.exit(main())
