"""Harness fixes C, E and F.

C -- a failed publication never becomes a valid Phase 4 transition.
E -- GitHub re-runs are refused, and every run attempt's minutes are counted.
F -- resume survives a merge commit, squash or rebase merge (commits rewritten,
     branch possibly deleted) by comparing content, and fails closed otherwise.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from automation import execution_state as es
from automation import ops
from automation.completion import CompletionFacts, evaluate
from automation.monitor_state import RECOVERY_CONFIRMED
from tests.test_automation_publish import bundle, git, milestone, repos, run  # noqa: F401

MONTH = "2026-10"


def ready_state() -> dict:
    build = {"run_id": "b1", "finished_at": "t", "billed_minutes": 200, "readiness_status": "COMPLETE",
             "valid_source_rows": 1, "required_source_rows": 1, "stop_reason": "finished", "fingerprint": "f",
             "dump": {"artifact_name": "phase4-db-b1", "run_id": "b1", "sha256": "0" * 64, "size_bytes": 1}}
    return es.record_build(es.initial_state(), build, month=MONTH).state


def record(state: dict, claimed: dict | None, published: dict | None) -> dict:
    outcome, pub = ops.attempt_outcome(claimed, published)
    attempt = {"attempt_id": "a", "run_id": "a", "base_sha": "b", "outcome": outcome["outcome"],
               "stop_reason": outcome["stop_reason"], "billed_minutes": 290,
               "published": pub.get("published", {}), "manifests": pub.get("manifests", {}),
               "new_acceptance_files": pub.get("new_acceptance_files", []), "finished_at": "t"}
    return es.record_attempt(state, attempt, month=MONTH).state


CLAIM_SIGNOFF = {"outcome": es.OUTCOME_AWAITING_SIGNOFF, "stop_reason": "M13 ready for sign-off"}
CLAIM_PROGRESS = {"outcome": es.OUTCOME_PROGRESS, "stop_reason": "time"}
GOOD_PUBLICATION = {"ok": True, "bundle_present": True, "violations": [], "push_failures": {}, "error": None,
                    "published": {"automation/phase4-m04": "s4"}, "manifests": {"automation/phase4-m04": {"x": "b"}},
                    "new_acceptance_files": [".agent/phase4/M04_ACCEPTANCE.md"]}


# --- C -------------------------------------------------------------------------


def test_publish_raised_is_an_infrastructure_failure():
    failed = {**GOOD_PUBLICATION, "ok": False, "error": "RuntimeError: bundle verify failed", "published": {}}
    state = record(ready_state(), CLAIM_PROGRESS, failed)
    last = state["attempts"][-1]
    assert last["outcome"] == es.OUTCOME_INFRASTRUCTURE_FAILED and "bundle verify failed" in last["stop_reason"]
    assert last["new_acceptance_files"] == []


def test_bundle_existed_but_no_publication_result_is_an_infrastructure_failure():
    state = record(ready_state(), CLAIM_PROGRESS, None)
    assert state["attempts"][-1]["outcome"] == es.OUTCOME_INFRASTRUCTURE_FAILED
    assert "publish step did not complete" in state["attempts"][-1]["stop_reason"]


def test_a_signoff_claim_never_survives_a_failed_publication():
    for failed in (None, {**GOOD_PUBLICATION, "ok": False, "error": "boom"},
                   {**GOOD_PUBLICATION, "ok": False, "push_failures": {"automation/phase4-m13": "rejected"},
                    "published": {}}):
        state = record(ready_state(), CLAIM_SIGNOFF, failed)
        assert state["status"] == es.READY, failed
        assert state["attempts"][-1]["outcome"] == es.OUTCOME_INFRASTRUCTURE_FAILED


def test_push_failure_overrides_the_claim_and_is_not_progress():
    partial = {**GOOD_PUBLICATION, "ok": False, "push_failures": {"automation/phase4-m05": "non-fast-forward"}}
    state = record(ready_state(), CLAIM_PROGRESS, partial)
    assert state["attempts"][-1]["outcome"] == es.OUTCOME_INFRASTRUCTURE_FAILED
    assert state["attempts"][-1]["new_acceptance_files"] == []
    assert state["consecutive_no_progress_attempts"] == 1


def test_failed_publications_never_reset_the_no_progress_breaker():
    state = ready_state()
    for failed in (None, {**GOOD_PUBLICATION, "ok": False, "error": "x"},
                   {**GOOD_PUBLICATION, "ok": False, "push_failures": {"automation/phase4-m04": "r"}}):
        state = record(state, CLAIM_PROGRESS, failed)
    assert state["status"] == es.ESCALATED  # three failures in a row, none of which counted as progress


def test_a_verified_publication_keeps_the_claim_and_counts_progress():
    state = record(ready_state(), CLAIM_PROGRESS, GOOD_PUBLICATION)
    assert state["attempts"][-1]["outcome"] == es.OUTCOME_PROGRESS
    assert state["consecutive_no_progress_attempts"] == 0
    assert state["last_published"]["manifest"] == {"x": "b"}


def test_signoff_needs_the_m13_branch_published():
    state = record(ready_state(), CLAIM_SIGNOFF, GOOD_PUBLICATION)          # only m04 published
    assert state["status"] == es.READY
    assert state["attempts"][-1]["outcome"] == es.OUTCOME_CLAUDE_FAILED
    m13 = {**GOOD_PUBLICATION, "published": {"automation/phase4-m13": "s13"}, "manifests": {}}
    assert record(ready_state(), CLAIM_SIGNOFF, m13)["status"] == es.AWAITING_HUMAN


def test_nothing_committed_keeps_the_claim_without_progress():
    nothing = {"ok": True, "bundle_present": False, "violations": [], "push_failures": {}, "error": None,
               "published": {}, "new_acceptance_files": []}
    state = record(ready_state(), CLAIM_PROGRESS, nothing)
    assert state["attempts"][-1]["outcome"] == es.OUTCOME_PROGRESS
    assert state["consecutive_no_progress_attempts"] == 1


# --- E -------------------------------------------------------------------------


def facts(state: dict, **overrides) -> es.PreflightFacts:
    values = dict(kind="attempt", month=MONTH, monitor_status=RECOVERY_CONFIRMED, probe_ready=True, probe_detail="ok",
                  execution_state=state, secrets_present={"CLAUDE_CODE_OAUTH_TOKEN": True}, dump_available=True,
                  main_sha="main-sha", api_month_minutes=0)
    values.update(overrides)
    return es.PreflightFacts(**values)


@pytest.mark.parametrize("attempt", [2, 3, 10])
def test_a_rerun_is_refused(attempt):
    decision = es.preflight(facts(ready_state(), run_attempt=attempt))
    assert not decision.allowed and any("re-run" in r and "fresh run" in r for r in decision.reasons)


def test_unreadable_api_minutes_refuse():
    assert not es.preflight(facts(ready_state(), api_month_minutes=None)).allowed


def test_api_minutes_count_even_when_the_ledger_missed_them():
    state = ready_state()
    state["ledger"] = {}                       # e.g. a run whose state record was never published
    over = es.DEFAULT_MONTHLY_MINUTE_CAP - es.ATTEMPT_WORST_CASE_MINUTES - es.MONITOR_RESERVE_MINUTES + 1
    assert not es.preflight(facts(state, api_month_minutes=over)).allowed
    assert es.preflight(facts(state, api_month_minutes=over - 1)).allowed


def test_reruns_of_an_attempt_are_charged_before_the_next_attempt():
    """A 295-minute attempt followed by three refused re-run clicks (each billed
    as a 1-minute job, three jobs) is counted in full by the next preflight."""
    state = ready_state()
    api_total = 200 + 295 + 3 * 3
    decision = es.preflight(facts(state, api_month_minutes=api_total))
    used = max(state["ledger"][MONTH], api_total)
    assert decision.allowed == (used + es.ATTEMPT_WORST_CASE_MINUTES + es.MONITOR_RESERVE_MINUTES
                                <= es.DEFAULT_MONTHLY_MINUTE_CAP)


def fake_runner(responses: dict[str, tuple[int, str]]):
    calls = []

    def runner(command):
        calls.append(command)
        for needle, (code, out) in responses.items():
            if any(needle in part for part in command):
                return subprocess.CompletedProcess(command, code, out, "")
        return subprocess.CompletedProcess(command, 1, "", "unexpected")

    return runner, calls


def test_billed_minutes_include_every_run_attempt():
    jobs = "\n".join(json.dumps(j) for j in (
        {"started_at": "2026-10-01T00:00:00Z", "completed_at": "2026-10-01T04:50:00Z"},  # attempt 1
        {"started_at": "2026-10-02T00:00:00Z", "completed_at": "2026-10-02T00:00:05Z"},  # re-run, refused
    ))
    runner, calls = fake_runner({"/jobs": (0, jobs)})
    assert ops.run_billed_minutes("o/r", "77", runner) == 290 + 1
    assert "filter=all" in calls[0][3] and "--paginate" in calls[0]


def test_unknown_run_usage_charges_the_worst_case():
    runner, _ = fake_runner({})
    assert ops.run_billed_minutes("o/r", "77", runner) == es.ATTEMPT_WORST_CASE_MINUTES


def test_month_minutes_cover_both_heavy_workflows():
    runner, calls = fake_runner({
        "phase4-data-build.yml": (0, "1\n"), "phase4-execute.yml": (0, "2\n3\n"),
        "/jobs": (0, json.dumps({"started_at": "2026-10-01T00:00:00Z", "completed_at": "2026-10-01T00:10:00Z"})),
    })
    assert ops.month_minutes_from_api("o/r", MONTH, runner) == 30
    assert any("created=%3E%3D2026-10-01" in part for call in calls for part in call)


def test_month_minutes_unreadable_is_none():
    runner, _ = fake_runner({"phase4-data-build.yml": (1, "")})
    assert ops.month_minutes_from_api("o/r", MONTH, runner) is None


# --- F: content-based resume ---------------------------------------------------------


def test_manifest_presence_is_judged_by_content():
    blobs = {"a.py": "1", "b.py": "2"}
    assert es.manifest_present_on({"a.py": "1"}, blobs) is True
    assert es.manifest_present_on({"a.py": "9"}, blobs) is False          # file exists, different content
    assert es.manifest_present_on({"gone.py": None}, blobs) is True       # a deletion that landed
    assert es.manifest_present_on({"a.py": None}, blobs) is False         # a deletion that did not
    assert es.manifest_present_on({}, blobs) is None and es.manifest_present_on(None, blobs) is None


def published_state(manifest: dict | None, sha: str = "s4") -> dict:
    state = ready_state()
    state["last_published"] = {"branch": "automation/phase4-m04", "sha": sha, "manifest": manifest}
    return state


def test_squash_merged_work_resumes_from_main():
    decision = es.preflight(facts(published_state({"x": "b"}), main_contains_published=False,
                                  published_contains_main=False, published_present_on_main=True))
    assert decision.allowed and decision.base_sha == "main-sha"


@pytest.mark.parametrize("present", [False, None])
def test_diverged_and_not_on_main_fails_closed(present):
    decision = es.preflight(facts(published_state({"x": "b"}), main_contains_published=False,
                                  published_contains_main=False, published_present_on_main=present))
    assert not decision.allowed and any("diverged" in r for r in decision.reasons)


def test_clear_forgets_last_published_only_when_its_work_is_on_main():
    state = published_state({"x": "b"})
    assert es.clear(state, note="n", published_present_on_main=True).state["last_published"] is None
    for unknown in (False, None):
        assert es.clear(state, note="n", published_present_on_main=unknown).state["last_published"] is not None


def human_clone(repos, name: str) -> Path:
    path = repos["tmp"] / name
    subprocess.run(["git", "clone", "--quiet", str(repos["origin"]), str(path)], check=True, capture_output=True)
    return path


def publish_m04(repos, files: dict[str, str]) -> tuple[str, dict]:
    sha = milestone(repos["attempt"], "automation/phase4-m04", repos["base"], files)
    result = run(repos, bundle(repos["attempt"], repos["tmp"], "automation/phase4-m04"))
    assert result.ok
    return sha, {"branch": "automation/phase4-m04", "sha": sha, "manifest": result.manifests["automation/phase4-m04"]}


def fresh_view(repos, name: str) -> Path:
    """A new clone, as a later preflight/monitor sees origin -- old commits may be gone."""
    return human_clone(repos, name)


MERGES = {
    "merge-commit": ["merge", "--no-ff", "-q", "-m", "Merge PR", "origin/automation/phase4-m04"],
    "squash": ["merge", "--squash", "-q", "origin/automation/phase4-m04"],
    "rebase": ["cherry-pick", "origin/automation/phase4-m04"],
}


@pytest.mark.parametrize("method", list(MERGES))
def test_every_merge_method_is_recognised_on_main(repos, method):
    sha, published = publish_m04(repos, {".agent/phase4/M04_ACCEPTANCE.md": "accepted\n", "ml/model.py": "v2\n"})
    human = human_clone(repos, f"human-{method}")
    git(human, *MERGES[method])
    if method == "squash":
        git(human, "commit", "-q", "-m", "M04 (#30)")
    git(human, "push", "-q", "origin", "HEAD:main")
    git(human, "push", "-q", "origin", "--delete", "automation/phase4-m04")   # "delete branch" after merging

    view = fresh_view(repos, f"view-{method}")
    main_sha = git(view, "rev-parse", "origin/main")
    assert ops.published_present_on_main(view, published) is True
    contains = ops.is_ancestor(view, sha, main_sha)
    assert contains == (method == "merge-commit")          # squash/rebase rewrote (and deleted) the commit
    decision = es.preflight(facts(published_state(published["manifest"], sha), main_sha=main_sha,
                                  main_contains_published=contains, published_contains_main=False,
                                  published_present_on_main=True))
    assert decision.allowed and decision.base_sha == main_sha


def test_accepted_and_unaccepted_milestones_are_never_confused(repos):
    _, unaccepted = publish_m04(repos, {"ml/model.py": "partial work\n"})       # no acceptance artifact
    human = human_clone(repos, "human-unaccepted")
    git(human, "merge", "--squash", "-q", "origin/automation/phase4-m04")
    git(human, "commit", "-q", "-m", "partial")
    git(human, "push", "-q", "origin", "HEAD:main")
    view = fresh_view(repos, "view-unaccepted")
    assert ops.published_present_on_main(view, unaccepted) is True   # resume from main ...
    files = frozenset(Path(p).name for p in git(view, "ls-tree", "--name-only", "origin/main", ".agent/phase4/").split())
    assert "M04_ACCEPTANCE.md" not in files                          # ... but M04 is still not accepted
    assert not evaluate(CompletionFacts(files, "CLOSED", frozenset())).complete


def test_work_edited_after_a_squash_is_not_trusted(repos):
    _, published = publish_m04(repos, {".agent/phase4/M04_ACCEPTANCE.md": "accepted\n"})
    human = human_clone(repos, "human-edit")
    git(human, "merge", "--squash", "-q", "origin/automation/phase4-m04")
    git(human, "commit", "-q", "-m", "M04")
    (human / ".agent" / "phase4" / "M04_ACCEPTANCE.md").write_text("hand-edited\n", encoding="utf-8")
    git(human, "commit", "-q", "-am", "edit")
    git(human, "push", "-q", "origin", "HEAD:main")
    assert ops.published_present_on_main(fresh_view(repos, "view-edit"), published) is False


def test_a_partially_merged_stack_is_not_on_main(repos):
    m04 = milestone(repos["attempt"], "automation/phase4-m04", repos["base"], {"ml/a.py": "a\n"})
    milestone(repos["attempt"], "automation/phase4-m05", m04, {"ml/b.py": "b\n"})
    result = run(repos, bundle(repos["attempt"], repos["tmp"], "automation/phase4-m04", "automation/phase4-m05"))
    top = {"branch": "automation/phase4-m05", "sha": "x", "manifest": result.manifests["automation/phase4-m05"]}
    human = human_clone(repos, "human-partial")
    git(human, "merge", "--squash", "-q", "origin/automation/phase4-m04")
    git(human, "commit", "-q", "-m", "only M04")
    git(human, "push", "-q", "origin", "HEAD:main")
    assert ops.published_present_on_main(fresh_view(repos, "view-partial"), top) is False


def test_clear_recovers_after_a_squash_merge(repos, tmp_path):
    _, published = publish_m04(repos, {".agent/phase4/M04_ACCEPTANCE.md": "accepted\n"})
    human = human_clone(repos, "human-clear")
    git(human, "merge", "--squash", "-q", "origin/automation/phase4-m04")
    git(human, "commit", "-q", "-m", "M04")
    git(human, "push", "-q", "origin", "HEAD:main")
    view = fresh_view(repos, "view-clear")

    state = published_state(published["manifest"], published["sha"])
    state["status"] = es.ESCALATED
    state["escalation_reason"] = "diverged"
    state_dir = tmp_path / "state"
    state_dir.mkdir()
    (state_dir / ops.EXECUTION_STATE_FILE).write_text(json.dumps(state), encoding="utf-8")
    ops.cmd_clear(type("A", (), {"state_dir": state_dir, "repo": str(view), "note": "merged M04",
                                 "notify_out": None})())
    cleared = ops.load_execution_state(state_dir)
    assert cleared["status"] == es.READY and cleared["last_published"] is None
    assert "forgot automation/phase4-m04" in (state_dir / ops.EXECUTION_LOG_FILE).read_text(encoding="utf-8")
