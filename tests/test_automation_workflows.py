"""Static cost, security and budget guards over the Phase 4 execution workflows.

Parsed as text (no YAML dependency): each check targets a line shape the
workflows are written in, and fails loudly if that shape stops matching.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from automation import execution_state as es

WORKFLOWS = Path(__file__).resolve().parents[1] / ".github" / "workflows"
BUILD = (WORKFLOWS / "phase4-data-build.yml").read_text(encoding="utf-8")
EXECUTE = (WORKFLOWS / "phase4-execute.yml").read_text(encoding="utf-8")
MONITOR = (WORKFLOWS / "statbotics-monitor.yml").read_text(encoding="utf-8")


def job_blocks(text: str) -> dict[str, str]:
    body = text.split("\njobs:\n", 1)[1]
    parts = re.split(r"^  ([a-z_-]+):\n", body, flags=re.MULTILINE)
    return dict(zip(parts[1::2], parts[2::2]))


def job_timeout(block: str) -> int:
    return int(re.search(r"^    timeout-minutes: (\d+)$", block, flags=re.MULTILINE).group(1))


def triggers(text: str) -> str:
    return text.split("\non:", 1)[1].split("\npermissions:", 1)[0]


@pytest.mark.parametrize("text", [BUILD, EXECUTE], ids=["build", "execute"])
def test_heavy_workflows_only_run_when_a_human_dispatches_them(text):
    trigger_block = triggers(text)
    assert "workflow_dispatch" in trigger_block
    for forbidden in ("schedule", "push", "pull_request", "workflow_run", "repository_dispatch", "issue_comment"):
        assert forbidden not in trigger_block


def test_monitor_never_dispatches_heavy_work():
    assert "gh workflow run" not in MONITOR and "phase4-execute.yml\n" not in MONITOR.replace("disable phase4-execute.yml", "")


@pytest.mark.parametrize("text", [BUILD, EXECUTE], ids=["build", "execute"])
def test_heavy_workflows_share_one_serializing_concurrency_group(text):
    assert "group: phase4-heavy" in text and "cancel-in-progress: false" in text


def test_attempt_job_timeouts_sum_to_the_budgeted_worst_case():
    jobs = job_blocks(EXECUTE)
    assert set(jobs) == {"preflight", "execute", "publish"}
    total = sum(job_timeout(block) for block in jobs.values())
    assert total == es.ATTEMPT_WORST_CASE_MINUTES <= es.MAX_ATTEMPT_MINUTES == 300  # decision D2


def test_execution_job_is_under_five_hours():
    assert job_timeout(job_blocks(EXECUTE)["execute"]) <= 300


def test_claude_step_and_runner_leave_time_to_bundle():
    execute = job_blocks(EXECUTE)["execute"]
    step_timeout = int(re.search(r"Run Claude.*?\n\s+timeout-minutes: (\d+)", execute, flags=re.DOTALL).group(1))
    runner_minutes = int(re.search(r"--minutes (\d+)", execute).group(1))
    assert runner_minutes < step_timeout < job_timeout(execute)


def test_build_job_timeout_matches_the_budgeted_worst_case():
    jobs = job_blocks(BUILD)
    assert list(jobs) == ["build"]
    assert job_timeout(jobs["build"]) == es.BUILD_WORST_CASE_MINUTES
    deadline = int(re.search(r"--deadline-minutes (\d+)", BUILD).group(1))
    assert deadline < es.BUILD_WORST_CASE_MINUTES


@pytest.mark.parametrize("text", [BUILD, EXECUTE, MONITOR], ids=["build", "execute", "monitor"])
def test_every_action_is_pinned_to_a_commit(text):
    for ref in re.findall(r"uses:\s*(\S+)", text):
        assert re.fullmatch(r"[\w.-]+/[\w.-]+@[0-9a-f]{40}", ref), ref


@pytest.mark.parametrize("text", [BUILD, EXECUTE, MONITOR], ids=["build", "execute", "monitor"])
def test_only_1x_linux_runners(text):
    assert set(re.findall(r"runs-on:\s*(\S+)", text)) == {"ubuntu-latest"}


def test_workflow_level_permissions_are_empty_and_granted_per_job():
    for text in (BUILD, EXECUTE):
        assert "\npermissions: {}\n" in text


def test_claude_runs_with_read_only_repository_access_and_no_push_credentials():
    execute = job_blocks(EXECUTE)["execute"]
    grants = re.search(r"permissions:\n((?:\s{6}\S.*\n)+)", execute).group(1)
    assert "write" not in grants
    assert "persist-credentials: false" in execute
    assert "GH_TOKEN" not in execute and "GITHUB_TOKEN" not in execute


def test_secret_exposure_is_minimal():
    # The only secret *values* ever placed in an environment.
    assert re.findall(r":\s*\$\{\{ secrets\.(\w+) \}\}", BUILD) == ["TBA_API_KEY"]
    assert re.findall(r":\s*\$\{\{ secrets\.(\w+) \}\}", EXECUTE) == ["CLAUDE_CODE_OAUTH_TOKEN"]
    assert "secrets." not in MONITOR
    # ANTHROPIC_API_KEY is only ever tested for presence, so preflight can refuse (D1/D11).
    for text in (BUILD, EXECUTE):
        assert re.findall(r"secrets\.ANTHROPIC_API_KEY(.{6})", text) == [" != ''"]


def test_claude_cli_is_pinned_and_never_skips_permissions():
    assert re.search(r'CLAUDE_CODE_VERSION: "\d+\.\d+\.\d+"', EXECUTE)
    assert "@anthropic-ai/claude-code@${CLAUDE_CODE_VERSION}" in EXECUTE
    assert "dangerously" not in EXECUTE


def test_ingestion_is_disabled_during_an_attempt():
    execute = job_blocks(EXECUTE)["execute"]
    assert "TBA_API_KEY: unavailable-during-unattended-execution" in execute
    assert "data.orchestrator" not in execute and "data_build" not in execute


def test_publishing_happens_on_a_separate_runner_after_validation():
    publish = job_blocks(EXECUTE)["publish"]
    assert "needs: [preflight, execute]" in publish
    assert "python -m automation.publish" in publish
    for text in (BUILD, EXECUTE, MONITOR):
        for push in re.findall(r"git push[^\n]*", text):
            assert not re.search(r"--force|\s-f\b|\+refs|\"\+", push), push


def test_dataset_is_integrity_checked_before_use():
    assert "sha256sum --check --strict" in job_blocks(EXECUTE)["execute"]
    assert "automation.verify_dataset --expected-fingerprint" in EXECUTE
    assert "sha256sum --check --strict" in BUILD


def test_dump_storage_is_bounded():
    assert "262144000" in BUILD  # 250 MB ceiling
    assert all(int(days) <= 30 for days in re.findall(r"retention-days: (\d+)", BUILD + EXECUTE))


def test_lock_and_state_are_always_released_and_persisted():
    publish = job_blocks(EXECUTE)["publish"]
    for step in ("Record attempt", "Persist state", "Release lock"):
        assert re.search(rf"- name: {step}\n(\s+id: \w+\n)?\s+if: always\(\)", publish), step
    for step in ("Record build", "Persist state", "Release lock"):
        assert re.search(rf"- name: {step}\n(\s+#[^\n]*\n)?(\s+id: \w+\n)?\s+if: always\(\) && "
                         rf"steps.lock.outputs.acquired == 'true'", BUILD), step
    # The build persists every completed record -- and never a crashed one (that
    # case raises the "state NOT published" alarm instead).
    assert re.search(r"- name: Persist state\n(\s+#[^\n]*\n)?\s+id: persist\n\s+if: always\(\) && "
                     r"steps.lock.outputs.acquired == 'true' && steps.record.outcome == 'success'\n", BUILD)


def test_no_job_context_where_github_rejects_it():
    # GitHub rejects `job.*` in a job-level env block ("Unrecognized named-value:
    # 'job'"); these workflows don't need the context at all.
    for text in (BUILD, EXECUTE):
        assert "${{ job." not in text


def test_dump_and_restore_use_the_service_image_over_localhost():
    services = set(re.findall(r"^\s+image: (\S+)$", BUILD + EXECUTE, flags=re.MULTILINE))
    assert services == {"postgres:18"}
    tool_lines = re.findall(r"^.*\bpg_(?:dump|restore)\b.*$", BUILD + EXECUTE, flags=re.MULTILINE)
    commands = [line for line in tool_lines if "docker run" in line]
    assert len(commands) == 3  # build: restore + dump; execute: restore
    for line in commands:
        assert "docker run --rm" in line and "--network host postgres:18" in line
        assert '--dbname "$DATABASE_URL"' in line
    assert "docker exec" not in BUILD + EXECUTE
    for text in (BUILD, EXECUTE):
        assert "@localhost:5432/" in re.search(r"DATABASE_URL: (\S+)", text).group(1)


# --- D/E: trusted code only, no re-runs; A: reconciled state publication --------

GUARD_STEP = "- name: Refuse untrusted refs and re-runs"


def steps_of(block: str) -> list[str]:
    body = "\n" + block.split("\n    steps:\n", 1)[1]
    return re.split(r"\n      - ", body)[1:]


@pytest.mark.parametrize("text", [BUILD, EXECUTE], ids=["build", "execute"])
def test_every_heavy_job_refuses_untrusted_refs_and_reruns_before_anything_else(text):
    for name, block in job_blocks(text).items():
        first = steps_of(block)[0]
        assert first.startswith(GUARD_STEP.removeprefix("- ")), name
        assert '"$GITHUB_REF" != "refs/heads/main"' in first and "exit 1" in first, name
        assert '"$GITHUB_RUN_ATTEMPT" != "1"' in first and "fresh run" in first, name
        assert "uses:" not in first, name


def test_monitor_refuses_untrusted_refs_first():
    first = steps_of(job_blocks(MONITOR)["monitor"])[0]
    assert first.startswith("name: Refuse untrusted refs") and '"$GITHUB_REF" != "refs/heads/main"' in first


@pytest.mark.parametrize("text", [BUILD, EXECUTE, MONITOR], ids=["build", "execute", "monitor"])
def test_harness_checkouts_pin_the_dispatched_main_commit(text):
    for step in re.findall(r"uses: actions/checkout@\S+.*?(?=\n      - |\Z)", text, flags=re.DOTALL):
        if "path: work" in step:
            assert "ref: ${{ needs.preflight.outputs.base_sha }}" in step  # Claude's workspace only
            assert "persist-credentials: false" in step
        else:
            assert "ref: ${{ github.sha }}" in step, step


def test_execute_runs_harness_code_only_from_the_trusted_checkout():
    execute = job_blocks(EXECUTE)["execute"]
    for step in steps_of(execute):
        if "python -m automation." in step:
            assert "working-directory: trusted" in step, step
    assert '--workdir "$GITHUB_WORKSPACE/work"' in execute
    assert "-r trusted/requirements.txt" in execute
    bundle = next(s for s in steps_of(execute) if s.startswith("name: Bundle milestone branches"))
    assert "working-directory: work" in bundle


@pytest.mark.parametrize("text", [BUILD, EXECUTE, MONITOR], ids=["build", "execute", "monitor"])
def test_state_is_only_published_through_the_reconciling_helper(text):
    assert "python -m automation.state_push" in text
    assert 'HEAD:refs/heads/${STATE_BRANCH}' not in text  # no raw, unreconciled state push remains


@pytest.mark.parametrize("text, job", [(BUILD, "build"), (EXECUTE, "publish")], ids=["build", "execute"])
def test_results_are_announced_only_after_state_is_published(text, job):
    notify = next(s for s in steps_of(job_blocks(text)[job]) if s.startswith("name: Notify tracking issue"))
    assert "PERSISTED: ${{ steps.persist.outcome }}" in notify
    success_branch = notify.split("\n          if ", 1)[1].split("; then", 1)[0]
    assert '[ "$PERSISTED" = "success" ]' in success_branch
    if job == "build":  # the build also requires its record step to have completed
        assert "RECORDED: ${{ steps.record.outcome }}" in notify
        assert '[ "$RECORDED" = "success" ] && [ "$PERSISTED" = "success" ]' in success_branch
    assert "state NOT published" in notify and notify.rstrip().endswith("fi")
    assert "exit 1" in notify


def test_no_always_step_runs_after_a_refused_dispatch_or_rerun():
    """A refused re-run must not post alarms, write state or touch the lock."""
    for name, block in job_blocks(EXECUTE).items():
        for condition in re.findall(r"^        if: (always\(\).*)$", block, flags=re.MULTILINE):
            assert "steps.guard.outcome == 'success'" in condition, (name, condition)
        assert "id: guard" in steps_of(block)[0], name
    for condition in re.findall(r"^        if: (always\(\).*)$", BUILD, flags=re.MULTILINE):
        assert "steps.lock.outputs.acquired == 'true'" in condition, condition  # a re-run never acquires the lock
