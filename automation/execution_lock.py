"""Cross-run mutual exclusion for Phase 4 builds and attempts, on GitHub refs.

Why not a database advisory lock: every run's database is an ephemeral
service container, so no two runs ever share one. Why not a lock *file*: two
runs can both read "unlocked" before either pushes. GitHub's ref API gives two
genuinely atomic primitives, and the lock uses only those:

- acquire = create refs/heads/automation/phase4-lock. Creation fails (422) if
  the ref already exists, so exactly one of two simultaneous creators wins.
- reclaim a stale lock = a non-force ref update to a new commit whose parent
  is the stale lock commit. GitHub accepts a non-force update only as a
  fast-forward from the ref's *current* value, so if another run reclaimed
  first, this update is rejected: a compare-and-swap.

The lock commit's message names its owner (workflow run id). A lock is stale
only when that run is no longer queued or running according to the Actions
API -- a definitive fact, not a heartbeat timeout guess. An unreadable lock is
never reclaimed automatically.

The workflows' `concurrency: phase4-heavy` group is a second, independent
guard; neither is relied on alone.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Protocol

import httpx

LOCK_BRANCH = "automation/phase4-lock"
LOCK_MESSAGE_PREFIX = "phase4-execution-lock"
ACTIVE_RUN_STATUSES = frozenset({"queued", "in_progress", "waiting", "requested", "pending"})


class GitHubRefs(Protocol):
    def commit_tree(self, sha: str) -> str: ...
    def commit_message(self, sha: str) -> str: ...
    def create_commit(self, message: str, tree: str, parents: list[str]) -> str: ...
    def get_ref(self, branch: str) -> str | None: ...
    def create_ref(self, branch: str, sha: str) -> bool: ...
    def fast_forward_ref(self, branch: str, sha: str) -> bool: ...
    def delete_ref(self, branch: str) -> None: ...
    def run_status(self, run_id: str) -> str | None: ...


@dataclass(frozen=True)
class LockOwner:
    run_id: str
    kind: str          # "build" or "attempt"
    acquired_at: str


@dataclass(frozen=True)
class LockResult:
    acquired: bool
    reason: str
    holder: LockOwner | None = None
    reclaimed_from: LockOwner | None = None


def _message(owner: LockOwner) -> str:
    return f"{LOCK_MESSAGE_PREFIX}\n\n" + json.dumps(
        {"run_id": owner.run_id, "kind": owner.kind, "acquired_at": owner.acquired_at}, sort_keys=True,
    )


def parse_owner(message: str) -> LockOwner | None:
    head, _, body = message.partition("\n\n")
    if head.strip() != LOCK_MESSAGE_PREFIX:
        return None
    try:
        data = json.loads(body)
        return LockOwner(run_id=str(data["run_id"]), kind=str(data["kind"]), acquired_at=str(data["acquired_at"]))
    except (ValueError, KeyError, TypeError):
        return None


def acquire(api: GitHubRefs, owner: LockOwner, base_sha: str) -> LockResult:
    tree = api.commit_tree(base_sha)
    if api.create_ref(LOCK_BRANCH, api.create_commit(_message(owner), tree, [base_sha])):
        return LockResult(True, "acquired")

    holder_sha = api.get_ref(LOCK_BRANCH)
    if holder_sha is None:
        # Released between our create and our read: one more atomic attempt, no loop.
        if api.create_ref(LOCK_BRANCH, api.create_commit(_message(owner), tree, [base_sha])):
            return LockResult(True, "acquired after a concurrent release")
        return LockResult(False, "lock changed hands during acquisition; not retrying")

    holder = parse_owner(api.commit_message(holder_sha))
    if holder is None:
        return LockResult(False, f"lock commit {holder_sha[:12]} is unreadable; a human must inspect it")
    if holder.run_id == owner.run_id:
        return LockResult(True, "already held by this run", holder=holder)

    status = api.run_status(holder.run_id)
    if status in ACTIVE_RUN_STATUSES:
        return LockResult(False, f"held by active run {holder.run_id} ({status})", holder=holder)

    stale_commit = api.create_commit(_message(owner), api.commit_tree(holder_sha), [holder_sha])
    if api.fast_forward_ref(LOCK_BRANCH, stale_commit):
        return LockResult(True, f"reclaimed stale lock of run {holder.run_id} (status {status})",
                          holder=None, reclaimed_from=holder)
    return LockResult(False, "another run reclaimed the stale lock first", holder=holder)


def release(api: GitHubRefs, owner: LockOwner) -> bool:
    """Delete the lock only if this run holds it. Returns whether it did."""
    holder_sha = api.get_ref(LOCK_BRANCH)
    if holder_sha is None:
        return False
    holder = parse_owner(api.commit_message(holder_sha))
    if holder is None or holder.run_id != owner.run_id:
        return False
    api.delete_ref(LOCK_BRANCH)
    return True


class GitHubRestRefs:
    """GitHubRefs over the REST API with the workflow's GITHUB_TOKEN."""

    def __init__(self, repository: str, token: str, *, client: httpx.Client | None = None) -> None:
        self._base = f"https://api.github.com/repos/{repository}"
        self._client = client or httpx.Client(timeout=30.0, headers={
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        })

    def _call(self, method: str, path: str, **kwargs: Any) -> httpx.Response:
        return self._client.request(method, f"{self._base}{path}", **kwargs)

    def commit_tree(self, sha: str) -> str:
        response = self._call("GET", f"/git/commits/{sha}")
        response.raise_for_status()
        return response.json()["tree"]["sha"]

    def commit_message(self, sha: str) -> str:
        response = self._call("GET", f"/git/commits/{sha}")
        response.raise_for_status()
        return response.json()["message"]

    def create_commit(self, message: str, tree: str, parents: list[str]) -> str:
        response = self._call("POST", "/git/commits", json={"message": message, "tree": tree, "parents": parents})
        response.raise_for_status()
        return response.json()["sha"]

    def get_ref(self, branch: str) -> str | None:
        response = self._call("GET", f"/git/ref/heads/{branch}")
        if response.status_code == 404:
            return None
        response.raise_for_status()
        return response.json()["object"]["sha"]

    def create_ref(self, branch: str, sha: str) -> bool:
        response = self._call("POST", "/git/refs", json={"ref": f"refs/heads/{branch}", "sha": sha})
        if response.status_code == 422:
            return False
        response.raise_for_status()
        return True

    def fast_forward_ref(self, branch: str, sha: str) -> bool:
        response = self._call("PATCH", f"/git/refs/heads/{branch}", json={"sha": sha, "force": False})
        if response.status_code == 422:
            return False
        response.raise_for_status()
        return True

    def delete_ref(self, branch: str) -> None:
        response = self._call("DELETE", f"/git/refs/heads/{branch}")
        if response.status_code not in (204, 422):
            response.raise_for_status()

    def run_status(self, run_id: str) -> str | None:
        response = self._call("GET", f"/actions/runs/{run_id}")
        if response.status_code == 404:
            return None
        response.raise_for_status()
        return response.json()["status"]
