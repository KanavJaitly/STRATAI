"""automation.publish reads paths as git stores them, not as git displays them;
records a manifest per published branch; and never reports progress for a
partial publication. Real git, like tests/test_automation_publish.py, whose
fixtures this module reuses."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from automation import publish
from tests.test_automation_publish import bundle, git, milestone, remote_branches, repos, run  # noqa: F401


def commit_paths(repo: Path, branch: str, start: str, files: dict[str, str], *, remove: tuple[str, ...] = ()) -> str:
    """Commit exact path names through git's index, so names Windows cannot create
    on disk (quotes, backslashes, tabs) are still real git paths under test."""
    git(repo, "checkout", "-q", "-B", branch, start)
    for path in remove:
        git(repo, "rm", "-q", "--cached", "--", path)
    for path, text in files.items():
        blob = subprocess.run(["git", "-C", str(repo), "hash-object", "-w", "--stdin"], input=text.encode(),
                              capture_output=True, check=True).stdout.decode().strip()
        subprocess.run(["git", "-C", str(repo), "-c", "core.protectNTFS=false", "update-index", "--add",
                        "--cacheinfo", f"100644,{blob},{path}"], check=True, capture_output=True)
    git(repo, "commit", "-q", "-m", branch)
    return git(repo, "rev-parse", "HEAD")


def show_blob(repo: Path, commit: str, path: str) -> str:
    listing = subprocess.run(["git", "-C", str(repo), "ls-tree", "-z", commit, "--", path],
                             capture_output=True, check=True).stdout.decode("utf-8")
    return listing.split("\t", 1)[0].split()[2]


PROTECTED_UNUSUAL = [
    "automation/é.py",                  # the reproduced bypass; git displays "automation/\303\251.py"
    "automation/with space.py",
    'automation/quo"te.py',
    "automation/back\\slash.py",
    "automation/tab\there.py",
    ".github/workflows/ünïcode.yml",
    "prompts/MASTER BUILD copy.md",
    "tests/test_automation_é.py",
    "docs/P4Milestones.md",
]


def test_git_really_displays_the_bypass_path_quoted(repos):
    """Guards the premise: without the fix, this is what the check used to see."""
    sha = commit_paths(repos["attempt"], "probe", repos["base"], {"automation/é.py": "x\n"})
    shown = git(repos["attempt"], "diff", "--name-only", repos["base"], sha)
    assert shown == '"automation/\\303\\251.py"'
    assert publish.changed_paths(publish._git(repos["attempt"], publish._run), repos["base"], sha) == ["automation/é.py"]


@pytest.mark.parametrize("path", PROTECTED_UNUSUAL)
def test_protected_paths_cannot_hide_behind_git_quoting(repos, path):
    commit_paths(repos["attempt"], "automation/phase4-m04", repos["base"], {path: "weakened\n"})
    result = run(repos, bundle(repos["attempt"], repos["tmp"], "automation/phase4-m04"))
    assert not result.ok
    # The violation lists offending paths with repr(), so match the exact path that way.
    assert any("protected" in v and repr(path) in v for v in result.violations), result.violations
    assert remote_branches(repos["origin"]) == {"main"}


def test_renaming_a_protected_file_away_is_caught(repos):
    commit_paths(repos["attempt"], "automation/phase4-m04", repos["base"], {"elsewhere/gate.py": "x\n"},
                 remove=("automation/gate.py",))
    result = run(repos, bundle(repos["attempt"], repos["tmp"], "automation/phase4-m04"))
    assert not result.ok
    assert any("automation/gate.py" in v for v in result.violations)


@pytest.mark.parametrize("path", ["ml/é file.py", 'ml/quo"te.py', "ml/back\\slash.py", "ml/tab\there.py"])
def test_unusual_unprotected_paths_still_publish(repos, path):
    """The policy is unchanged: only PROTECTED_PATHS prefixes are refused."""
    commit_paths(repos["attempt"], "automation/phase4-m04", repos["base"],
                 {path: "fine\n", ".agent/phase4/M04_ACCEPTANCE.md": "accepted\n"})
    result = run(repos, bundle(repos["attempt"], repos["tmp"], "automation/phase4-m04"))
    assert result.ok and result.violations == []
    assert path in result.manifests["automation/phase4-m04"]


def test_protected_path_policy_is_exactly_the_documented_prefixes():
    assert publish.PROTECTED_PATHS == (
        ".github/", "automation/", "prompts/", "docs/P4Milestones.md", "tests/test_automation_",
    )


def test_manifest_records_every_change_against_main_with_its_blob(repos):
    sha = commit_paths(repos["attempt"], "automation/phase4-m04", repos["base"],
                       {".agent/phase4/M04_ACCEPTANCE.md": "a\n", "ml/new.py": "n\n"}, remove=("ml/model.py",))
    result = run(repos, bundle(repos["attempt"], repos["tmp"], "automation/phase4-m04"))
    assert result.manifests["automation/phase4-m04"] == {
        ".agent/phase4/M04_ACCEPTANCE.md": show_blob(repos["attempt"], sha, ".agent/phase4/M04_ACCEPTANCE.md"),
        "ml/new.py": show_blob(repos["attempt"], sha, "ml/new.py"),
        "ml/model.py": None,                                          # a deletion
    }


def test_a_stacked_branch_manifest_is_cumulative_against_main(repos):
    m04 = commit_paths(repos["attempt"], "automation/phase4-m04", repos["base"], {"ml/a.py": "a\n"})
    commit_paths(repos["attempt"], "automation/phase4-m05", m04, {"ml/b.py": "b\n"})
    result = run(repos, bundle(repos["attempt"], repos["tmp"], "automation/phase4-m04", "automation/phase4-m05"))
    assert set(result.manifests["automation/phase4-m05"]) == {"ml/a.py", "ml/b.py"}


def test_a_failed_push_publishes_no_progress(repos):
    milestone(repos["attempt"], "automation/phase4-m04", repos["base"], {".agent/phase4/M04_ACCEPTANCE.md": "a\n"})
    human = repos["tmp"] / "human-edit"
    subprocess.run(["git", "clone", "--quiet", str(repos["origin"]), str(human)], check=True, capture_output=True)
    milestone(human, "automation/phase4-m04", repos["base"], {"ml/model.py": "human\n"})
    git(human, "push", "-q", "origin", "automation/phase4-m04")
    result = run(repos, bundle(repos["attempt"], repos["tmp"], "automation/phase4-m04"))
    assert not result.ok and result.push_failures
    assert result.new_acceptance_files == []


def test_main_always_writes_a_result(repos, tmp_path, monkeypatch):
    out = tmp_path / "publish.json"
    common = ["--repo", str(repos["publisher"]), "--base-sha", repos["base"], "--repository", "o/r", "--out", str(out)]

    assert publish.main(["--bundle", str(tmp_path / "absent.bundle"), *common]) == 0
    written = json.loads(out.read_text(encoding="utf-8"))
    assert written["ok"] is True and written["bundle_present"] is False and written["error"] is None

    def boom(*args, **kwargs):
        raise RuntimeError("bundle verify failed: not a bundle")

    monkeypatch.setattr(publish, "validate_and_publish", boom)
    (tmp_path / "junk.bundle").write_text("junk", encoding="utf-8")
    assert publish.main(["--bundle", str(tmp_path / "junk.bundle"), *common]) == 1
    written = json.loads(out.read_text(encoding="utf-8"))
    assert written["ok"] is False and "bundle verify failed" in written["error"]
