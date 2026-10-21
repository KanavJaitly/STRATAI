"""Tests for automation.publish with real git repositories in tmp_path.

A bare repo plays origin; an "attempt" clone plays the Claude runner (commits
locally, then bundles); a separate pristine "publisher" clone validates the
bundle and pushes. Only `gh` is faked.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from automation import publish

IDENTITY = ["-c", "user.name=test", "-c", "user.email=test@example.invalid", "-c", "commit.gpgsign=false"]


def git(repo: Path, *args: str) -> str:
    result = subprocess.run(["git", "-C", str(repo), *IDENTITY, *args], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    return result.stdout.strip()


def write(repo: Path, path: str, text: str = "x\n") -> None:
    target = repo / path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(text, encoding="utf-8")


class FakeGh:
    def __init__(self, *, can_create: bool = True) -> None:
        self.can_create = can_create
        self.calls: list[list[str]] = []

    def __call__(self, command):
        self.calls.append(list(command))
        if command[1:3] == ["pr", "list"]:
            return subprocess.CompletedProcess(command, 0, "", "")
        if command[1:3] == ["pr", "create"] and self.can_create:
            head = command[command.index("--head") + 1]
            return subprocess.CompletedProcess(command, 0, f"https://github.com/o/r/pull/{head[-2:]}\n", "")
        return subprocess.CompletedProcess(command, 1, "", "GitHub Actions is not permitted to create pull requests")


@pytest.fixture
def repos(tmp_path):
    origin = tmp_path / "origin.git"
    subprocess.run(["git", "init", "--quiet", "--bare", "-b", "main", str(origin)], check=True)
    seed = tmp_path / "seed"
    subprocess.run(["git", "clone", "--quiet", str(origin), str(seed)], check=True, capture_output=True)
    git(seed, "checkout", "-q", "-b", "main")
    for path in (".agent/phase4/PHASE_STATUS.md", ".agent/phase4/M03_ACCEPTANCE.md", "automation/gate.py",
                 "docs/P4Milestones.md", "ml/model.py"):
        write(seed, path)
    git(seed, "add", "-A")
    git(seed, "commit", "-q", "-m", "base")
    git(seed, "push", "-q", "origin", "main")
    base = git(seed, "rev-parse", "HEAD")

    attempt = tmp_path / "attempt"
    subprocess.run(["git", "clone", "--quiet", str(origin), str(attempt)], check=True, capture_output=True)
    publisher = tmp_path / "publisher"
    subprocess.run(["git", "clone", "--quiet", str(origin), str(publisher)], check=True, capture_output=True)
    return {"origin": origin, "attempt": attempt, "publisher": publisher, "base": base, "tmp": tmp_path}


def milestone(repo: Path, branch: str, start: str, files: dict[str, str]) -> str:
    git(repo, "checkout", "-q", "-B", branch, start)
    for path, text in files.items():
        write(repo, path, text)
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", branch)
    return git(repo, "rev-parse", "HEAD")


def bundle(repo: Path, tmp: Path, *refs: str) -> Path:
    path = tmp / "attempt.bundle"
    git(repo, "bundle", "create", str(path), *refs)
    return path


def remote_branches(origin: Path) -> set[str]:
    out = subprocess.run(["git", "-C", str(origin), "for-each-ref", "--format=%(refname:short)", "refs/heads"],
                         capture_output=True, text=True).stdout
    return set(out.split())


def run(repos, path: Path, gh=None) -> publish.PublishResult:
    return publish.validate_and_publish(repos["publisher"], path, base_sha=repos["base"], repository="o/r",
                                        gh=gh or FakeGh())


def test_stacked_milestones_publish_as_one_pr_each(repos):
    m04 = milestone(repos["attempt"], "automation/phase4-m04", repos["base"],
                    {".agent/phase4/M04_ACCEPTANCE.md": "accepted\n", "ml/model.py": "v2\n"})
    milestone(repos["attempt"], "automation/phase4-m05", m04, {".agent/phase4/M05_ACCEPTANCE.md": "accepted\n"})
    gh = FakeGh()
    result = run(repos, bundle(repos["attempt"], repos["tmp"], "automation/phase4-m04", "automation/phase4-m05"), gh)

    assert result.ok and result.violations == []
    assert set(result.published) == {"automation/phase4-m04", "automation/phase4-m05"}
    assert result.new_acceptance_files == [".agent/phase4/M04_ACCEPTANCE.md", ".agent/phase4/M05_ACCEPTANCE.md"]
    assert {"automation/phase4-m04", "automation/phase4-m05"} <= remote_branches(repos["origin"])
    creates = [c for c in gh.calls if c[1:3] == ["pr", "create"]]
    assert [c[c.index("--base") + 1] for c in creates] == ["main", "automation/phase4-m04"]


def test_pr_creation_disabled_falls_back_to_compare_links(repos):
    milestone(repos["attempt"], "automation/phase4-m04", repos["base"], {".agent/phase4/M04_ACCEPTANCE.md": "a\n"})
    result = run(repos, bundle(repos["attempt"], repos["tmp"], "automation/phase4-m04"), FakeGh(can_create=False))
    assert result.ok and "automation/phase4-m04" in result.published
    assert result.compare_links["automation/phase4-m04"].endswith("compare/main...automation/phase4-m04?expand=1")


@pytest.mark.parametrize("path", ["automation/gate.py", "docs/P4Milestones.md", ".github/workflows/x.yml",
                                  "prompts/MASTER_BUILD.md", "tests/test_automation_gate.py"])
def test_touching_the_harness_or_criteria_rejects_the_whole_attempt(repos, path):
    good = milestone(repos["attempt"], "automation/phase4-m04", repos["base"], {".agent/phase4/M04_ACCEPTANCE.md": "a\n"})
    milestone(repos["attempt"], "automation/phase4-m05", good, {path: "weakened\n"})
    result = run(repos, bundle(repos["attempt"], repos["tmp"], "automation/phase4-m04", "automation/phase4-m05"))
    assert not result.ok
    assert any("protected" in v for v in result.violations)
    assert result.published == {} and result.new_acceptance_files == []
    assert remote_branches(repos["origin"]) == {"main"}  # nothing pushed, not even the good branch


@pytest.mark.parametrize("branch", ["main", "automation/phase4-m99", "automation/phase4-lock", "feature/x"])
def test_disallowed_branch_names_reject_the_attempt(repos, branch):
    milestone(repos["attempt"], branch, repos["base"], {"ml/model.py": "v2\n"})
    result = run(repos, bundle(repos["attempt"], repos["tmp"], branch))
    assert not result.ok and result.violations
    assert remote_branches(repos["origin"]) == {"main"}


def test_rewritten_history_is_rejected(repos):
    git(repos["attempt"], "checkout", "-q", "--orphan", "automation/phase4-m04")
    write(repos["attempt"], ".agent/phase4/M04_ACCEPTANCE.md", "forged\n")
    git(repos["attempt"], "add", "-A")
    git(repos["attempt"], "commit", "-q", "-m", "unrelated root")
    result = run(repos, bundle(repos["attempt"], repos["tmp"], "automation/phase4-m04"))
    assert not result.ok
    assert any("does not descend" in v for v in result.violations)


def test_human_changes_on_a_published_branch_are_never_overwritten(repos):
    milestone(repos["attempt"], "automation/phase4-m04", repos["base"], {".agent/phase4/M04_ACCEPTANCE.md": "a\n"})
    human = repos["tmp"] / "human"
    subprocess.run(["git", "clone", "--quiet", str(repos["origin"]), str(human)], check=True, capture_output=True)
    milestone(human, "automation/phase4-m04", repos["base"], {"ml/model.py": "human fix\n"})
    git(human, "push", "-q", "origin", "automation/phase4-m04")

    result = run(repos, bundle(repos["attempt"], repos["tmp"], "automation/phase4-m04"))
    assert not result.ok and "automation/phase4-m04" in result.push_failures
    human_tip = git(human, "rev-parse", "HEAD")
    assert git(repos["origin"], "rev-parse", "automation/phase4-m04") == human_tip


def test_an_attempt_that_committed_nothing_publishes_nothing(repos):
    milestone(repos["attempt"], "scratch", repos["base"], {"ml/model.py": "v2\n"})
    path = repos["tmp"] / "empty.bundle"
    git(repos["attempt"], "bundle", "create", str(path), "scratch")
    result = run(repos, path)
    assert not result.ok  # a non-milestone ref is a violation, not silently ignored
