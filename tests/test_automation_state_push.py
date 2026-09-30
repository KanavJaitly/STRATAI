"""Tests for automation.state_push -- publishing state under concurrent writers.

Real git: a bare repo plays origin's automation/phase4-state branch; separate
clones play the heavy workflow (checkout taken hours earlier) and the monitor.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from automation import state_push as sp

BRANCH = "automation/phase4-state"
IDENTITY = ["-c", "user.name=t", "-c", "user.email=t@example.invalid", "-c", "commit.gpgsign=false"]


def git(repo: Path, *args: str) -> str:
    result = subprocess.run(["git", "-C", str(repo), *IDENTITY, *args], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    return result.stdout.strip()


def write_json(repo: Path, name: str, value: dict) -> None:
    (repo / name).write_text(json.dumps(value, sort_keys=True) + "\n", encoding="utf-8")


def remote_file(origin: Path, name: str) -> dict:
    return json.loads(subprocess.run(["git", "-C", str(origin), "show", f"{BRANCH}:{name}"],
                                     capture_output=True, text=True, check=True).stdout)


def clone(origin: Path, path: Path) -> Path:
    subprocess.run(["git", "clone", "--quiet", "--branch", BRANCH, str(origin), str(path)],
                   check=True, capture_output=True)
    for key, value in (("user.name", "t"), ("user.email", "t@example.invalid"), ("commit.gpgsign", "false")):
        git(path, "config", key, value)
    return path


@pytest.fixture
def origin(tmp_path) -> Path:
    bare = tmp_path / "origin.git"
    subprocess.run(["git", "init", "--quiet", "--bare", str(bare)], check=True)
    seed = tmp_path / "seed"
    seed.mkdir()
    git(seed, "init", "--quiet", "-b", BRANCH)
    write_json(seed, "monitor_state.json", {"status": "WAITING"})
    write_json(seed, "execution_state.json", {"status": "READY", "builds": []})
    git(seed, "add", "-A")
    git(seed, "commit", "--quiet", "-m", "initial state")
    git(seed, "push", "--quiet", str(bare), f"{BRANCH}:{BRANCH}")
    return bare


def publish(repo: Path, *paths: str, **kwargs) -> tuple[str, str]:
    return sp.publish_state(repo, branch=BRANCH, paths=list(paths), message="test", pause=lambda s: None, **kwargs)


def test_stale_heavy_state_reconciles_with_newer_monitor_state(origin, tmp_path):
    heavy = clone(origin, tmp_path / "heavy")          # checked out at the start of a 4-hour build
    monitor = clone(origin, tmp_path / "monitor")

    write_json(monitor, "monitor_state.json", {"status": "RECOVERY_PENDING"})   # the daily run lands meanwhile
    assert publish(monitor, "monitor_state.json")[0] == sp.PUBLISHED

    write_json(heavy, "execution_state.json", {"status": "READY", "builds": ["b1"]})
    status, detail = publish(heavy, "execution_state.json")

    assert status == sp.PUBLISHED, detail
    assert remote_file(origin, "monitor_state.json") == {"status": "RECOVERY_PENDING"}   # the monitor's change survives
    assert remote_file(origin, "execution_state.json")["builds"] == ["b1"]            # and so does the build's
    log = subprocess.run(["git", "-C", str(origin), "log", "--format=%s", BRANCH], capture_output=True, text=True).stdout
    assert log.split("\n")[:3] == ["test", "test", "initial state"]  # linear history, nothing overwritten


def test_genuine_conflict_fails_closed_and_leaves_the_remote_untouched(origin, tmp_path):
    heavy = clone(origin, tmp_path / "heavy")
    human_clear = clone(origin, tmp_path / "clear")
    write_json(human_clear, "execution_state.json", {"status": "READY", "builds": [], "cleared": True})
    assert publish(human_clear, "execution_state.json")[0] == sp.PUBLISHED
    remote_before = git(origin, "rev-parse", BRANCH)

    write_json(heavy, "execution_state.json", {"status": "ESCALATED", "builds": ["b1"]})
    status, detail = publish(heavy, "execution_state.json")

    assert status == sp.CONFLICT and "conflicts" in detail
    assert git(origin, "rev-parse", BRANCH) == remote_before
    assert remote_file(origin, "execution_state.json")["cleared"] is True     # never silently overwritten
    assert not (heavy / ".git" / "rebase-merge").exists()                      # rebase aborted cleanly


def test_a_remote_that_keeps_advancing_exhausts_a_bounded_retry(origin, tmp_path):
    heavy = clone(origin, tmp_path / "heavy")
    rival = clone(origin, tmp_path / "rival")
    pushes = []

    def racing(command):
        if "push" in command:
            pushes.append(command)
            write_json(rival, "monitor_state.json", {"status": "WAITING", "n": len(pushes)})
            assert publish(rival, "monitor_state.json")[0] == sp.PUBLISHED   # someone always gets there first
        return sp._run(command)

    write_json(heavy, "execution_state.json", {"status": "READY", "builds": ["b1"]})
    status, _ = sp.publish_state(heavy, branch=BRANCH, paths=["execution_state.json"], message="test",
                                 runner=racing, pause=lambda s: None)
    assert status == sp.EXHAUSTED
    assert len(pushes) == sp.MAX_ATTEMPTS
    assert "b1" not in json.dumps(remote_file(origin, "execution_state.json"))


def test_a_failed_publication_is_never_reported_as_success(origin, tmp_path, monkeypatch):
    heavy = clone(origin, tmp_path / "heavy")
    other = clone(origin, tmp_path / "other")
    write_json(other, "execution_state.json", {"status": "READY", "builds": ["other"]})
    assert publish(other, "execution_state.json")[0] == sp.PUBLISHED
    write_json(heavy, "execution_state.json", {"status": "READY", "builds": ["mine"]})

    monkeypatch.setattr(sp.time, "sleep", lambda s: None)
    code = sp.main(["--state-dir", str(heavy), "--branch", BRANCH, "--message", "m", "execution_state.json"])
    assert code == 1


def test_no_force_push_is_ever_issued(origin, tmp_path):
    heavy = clone(origin, tmp_path / "heavy")
    seen = []

    def recording(command):
        seen.append(command)
        return sp._run(command)

    write_json(heavy, "execution_state.json", {"status": "READY", "builds": ["b1"]})
    sp.publish_state(heavy, branch=BRANCH, paths=["execution_state.json"], message="t", runner=recording,
                     pause=lambda s: None)
    for command in (c for c in seen if "push" in c):
        assert not any(arg.startswith("+") or arg in ("--force", "-f", "--force-with-lease") for arg in command)


def test_nothing_changed_publishes_nothing(origin, tmp_path):
    heavy = clone(origin, tmp_path / "heavy")
    assert publish(heavy, "execution_state.json")[0] == sp.NOTHING


def test_first_publication_creates_the_branch(tmp_path):
    bare = tmp_path / "empty.git"
    subprocess.run(["git", "init", "--quiet", "--bare", str(bare)], check=True)
    fresh = tmp_path / "fresh"
    fresh.mkdir()
    git(fresh, "init", "--quiet", "-b", BRANCH)
    git(fresh, "remote", "add", "origin", str(bare))
    for key, value in (("user.name", "t"), ("user.email", "t@example.invalid"), ("commit.gpgsign", "false")):
        git(fresh, "config", key, value)
    write_json(fresh, "monitor_state.json", {"status": "WAITING"})
    assert publish(fresh, "monitor_state.json")[0] == sp.PUBLISHED
    assert remote_file(bare, "monitor_state.json") == {"status": "WAITING"}
