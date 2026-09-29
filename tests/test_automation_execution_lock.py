"""Tests for automation.execution_lock against an in-memory GitHub with the
same atomicity rules the real ref API has: create fails if the ref exists, and
a non-force update succeeds only as a fast-forward from the current value."""

from __future__ import annotations

import itertools

import httpx

from automation import execution_lock as lock


class FakeGitHub:
    def __init__(self) -> None:
        self.refs: dict[str, str] = {}
        self.commits: dict[str, dict] = {"base": {"message": "base", "tree": "t0", "parents": []}}
        self.runs: dict[str, str] = {}
        self._ids = itertools.count(1)
        self.before_create = None  # hook to interleave a competing writer

    def commit_tree(self, sha):
        return self.commits[sha]["tree"]

    def commit_message(self, sha):
        return self.commits[sha]["message"]

    def create_commit(self, message, tree, parents):
        sha = f"c{next(self._ids)}"
        self.commits[sha] = {"message": message, "tree": tree, "parents": parents}
        return sha

    def get_ref(self, branch):
        return self.refs.get(branch)

    def create_ref(self, branch, sha):
        if self.before_create:
            hook, self.before_create = self.before_create, None
            hook()
        if branch in self.refs:
            return False
        self.refs[branch] = sha
        return True

    def _descends(self, sha, ancestor):
        stack = [sha]
        while stack:
            current = stack.pop()
            if current == ancestor:
                return True
            stack.extend(self.commits[current]["parents"])
        return False

    def fast_forward_ref(self, branch, sha):
        current = self.refs.get(branch)
        if current is None or not self._descends(sha, current):
            return False
        self.refs[branch] = sha
        return True

    def delete_ref(self, branch):
        self.refs.pop(branch, None)

    def run_status(self, run_id):
        return self.runs.get(run_id)


def owner(run_id: str, kind: str = "attempt") -> lock.LockOwner:
    return lock.LockOwner(run_id=run_id, kind=kind, acquired_at="2026-10-01T00:00:00+00:00")


def test_first_run_acquires():
    github = FakeGitHub()
    result = lock.acquire(github, owner("100"), "base")
    assert result.acquired
    assert lock.parse_owner(github.commit_message(github.refs[lock.LOCK_BRANCH])).run_id == "100"


def test_simultaneous_triggers_cannot_both_hold_the_lock():
    github = FakeGitHub()
    # Run 200 creates the ref in the instant between run 100 building its commit and creating the ref.
    github.before_create = lambda: lock.acquire(github, owner("200"), "base")
    github.runs["200"] = "in_progress"
    first = lock.acquire(github, owner("100"), "base")
    assert not first.acquired
    assert first.holder.run_id == "200"


def test_an_active_run_keeps_its_lock():
    github = FakeGitHub()
    lock.acquire(github, owner("100"), "base")
    for status in lock.ACTIVE_RUN_STATUSES:
        github.runs["100"] = status
        assert not lock.acquire(github, owner("101"), "base").acquired


def test_a_crashed_run_does_not_lock_the_system_forever():
    github = FakeGitHub()
    lock.acquire(github, owner("100"), "base")
    github.runs["100"] = "completed"  # runner died; publish never released the lock
    result = lock.acquire(github, owner("101"), "base")
    assert result.acquired and result.reclaimed_from.run_id == "100"


def test_a_deleted_run_counts_as_stale():
    github = FakeGitHub()
    lock.acquire(github, owner("100"), "base")
    assert lock.acquire(github, owner("101"), "base").acquired  # run 100 unknown to the API


def test_only_one_of_two_reclaimers_wins():
    github = FakeGitHub()
    lock.acquire(github, owner("100"), "base")
    github.runs["100"] = "completed"
    stale = github.refs[lock.LOCK_BRANCH]
    # Simulate reclaimer 102 winning the race after 101 read the stale holder.
    winner = github.create_commit(lock._message(owner("102")), "t0", [stale])
    original = github.fast_forward_ref

    def racing_fast_forward(branch, sha):
        github.fast_forward_ref = original
        assert original(branch, winner)
        return original(branch, sha)

    github.fast_forward_ref = racing_fast_forward
    result = lock.acquire(github, owner("101"), "base")
    assert not result.acquired
    assert lock.parse_owner(github.commit_message(github.refs[lock.LOCK_BRANCH])).run_id == "102"


def test_an_unreadable_lock_is_never_reclaimed_automatically():
    github = FakeGitHub()
    github.refs[lock.LOCK_BRANCH] = github.create_commit("hand-made", "t0", ["base"])
    result = lock.acquire(github, owner("101"), "base")
    assert not result.acquired and "unreadable" in result.reason


def test_rerun_of_the_same_run_is_idempotent():
    github = FakeGitHub()
    lock.acquire(github, owner("100"), "base")
    assert lock.acquire(github, owner("100"), "base").acquired


def test_release_only_removes_this_runs_lock():
    github = FakeGitHub()
    lock.acquire(github, owner("100"), "base")
    assert not lock.release(github, owner("999"))
    assert lock.LOCK_BRANCH in github.refs
    assert lock.release(github, owner("100"))
    assert lock.LOCK_BRANCH not in github.refs
    assert not lock.release(github, owner("100"))


def test_rest_adapter_maps_422_to_contention():
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append((request.method, request.url.path))
        if request.method == "POST" and request.url.path.endswith("/git/refs"):
            return httpx.Response(422, json={"message": "Reference already exists"})
        if request.method == "PATCH":
            return httpx.Response(422, json={"message": "Update is not a fast forward"})
        if request.method == "GET" and "/git/ref/" in request.url.path:
            return httpx.Response(404)
        return httpx.Response(200, json={})

    api = lock.GitHubRestRefs("o/r", "t", client=httpx.Client(transport=httpx.MockTransport(handler)))
    assert api.create_ref(lock.LOCK_BRANCH, "sha") is False
    assert api.fast_forward_ref(lock.LOCK_BRANCH, "sha") is False
    assert api.get_ref(lock.LOCK_BRANCH) is None
    assert ("POST", "/repos/o/r/git/refs") in calls
    patch = [path for method, path in calls if method == "PATCH"][0]
    assert patch == f"/repos/o/r/git/refs/heads/{lock.LOCK_BRANCH}"
