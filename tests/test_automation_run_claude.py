"""Tests for automation.run_claude -- auth isolation and outcome classification."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from automation import execution_state as es
from automation import run_claude as rc

TEMPLATE = Path(__file__).resolve().parents[1] / "prompts" / "PHASE4_UNATTENDED.md"


def write_report(tmp_path: Path, payload) -> Path:
    path = tmp_path / "report.json"
    path.write_text(json.dumps(payload) if not isinstance(payload, str) else payload, encoding="utf-8")
    return path


def ok_output(is_error: bool = False) -> str:
    return json.dumps({"type": "result", "is_error": is_error, "result": "done"})


def test_prompt_template_renders_every_placeholder():
    prompt = rc.render_prompt(TEMPLATE, {"attempt_id": "42", "base_sha": "abc123", "report_path": "/r.json",
                                         "minutes": "235"})
    assert "attempt 42" in prompt and "abc123" in prompt and "/r.json" in prompt and "235" in prompt
    assert "$" not in prompt.replace("$$", "")


def test_prompt_carries_the_binding_decisions_and_stop_rules():
    text = TEMPLATE.read_text(encoding="utf-8")
    for required in ("MASTER_BUILD.md", "D1", "Spearman", "ECE < 0.05", "2024 + 2025", "2026",
                     "Do not iterate", "awaiting_human_signoff", "commit locally".lower()):
        assert required.lower() in text.lower(), required


def test_child_environment_strips_billing_and_github_credentials():
    env = rc.child_environment({
        "CLAUDE_CODE_OAUTH_TOKEN": "oauth", "ANTHROPIC_API_KEY": "sk-paid", "GITHUB_TOKEN": "ghs", "GH_TOKEN": "ghs",
        "PATH": "/bin",
    })
    assert env == {"CLAUDE_CODE_OAUTH_TOKEN": "oauth", "PATH": "/bin"}


def test_missing_oauth_token_refuses_to_run():
    with pytest.raises(RuntimeError):
        rc.child_environment({"ANTHROPIC_API_KEY": "sk-paid"})


def test_valid_report_is_taken_at_its_word(tmp_path):
    report = write_report(tmp_path, {"outcome": es.OUTCOME_PROGRESS, "stop_reason": "time", "milestones": {"M04": "accepted"}})
    result = rc.classify(returncode=0, timed_out=False, output=ok_output(), report_path=report)
    assert result["outcome"] == es.OUTCOME_PROGRESS
    assert result["claimed_milestones"] == {"M04": "accepted"}


def test_timeout_is_budget_exhausted_whatever_the_report_says(tmp_path):
    report = write_report(tmp_path, {"outcome": es.OUTCOME_AWAITING_SIGNOFF, "stop_reason": "done"})
    assert rc.classify(returncode=None, timed_out=True, output="", report_path=report)["outcome"] == es.OUTCOME_BUDGET_EXHAUSTED


@pytest.mark.parametrize("message", ["Claude AI usage limit reached", "rate_limit_error", "Your credit balance is too low"])
def test_usage_exhaustion_is_detected_on_an_errored_run(tmp_path, message):
    report = write_report(tmp_path, {"outcome": es.OUTCOME_PROGRESS, "stop_reason": "x"})
    result = rc.classify(returncode=1, timed_out=False, output=message, report_path=report)
    assert result["outcome"] == es.OUTCOME_USAGE_EXHAUSTED


def test_usage_words_in_a_successful_run_are_not_misread(tmp_path):
    report = write_report(tmp_path, {"outcome": es.OUTCOME_PROGRESS, "stop_reason": "discussed the usage limit"})
    output = ok_output() + "\nI noted the usage limit in docs."
    assert rc.classify(returncode=0, timed_out=False, output=output, report_path=report)["outcome"] == es.OUTCOME_PROGRESS


def test_cli_reported_error_without_limit_wording_is_claude_failed(tmp_path):
    report = write_report(tmp_path, {"outcome": es.OUTCOME_PROGRESS, "stop_reason": "x"})
    assert rc.classify(returncode=0, timed_out=False, output=ok_output(is_error=True),
                       report_path=report)["outcome"] == es.OUTCOME_CLAUDE_FAILED


@pytest.mark.parametrize("payload", ["not json", {"outcome": "accepted_everything"}, [], {"stop_reason": "x"}])
def test_missing_or_forged_report_is_claude_failed(tmp_path, payload):
    report = write_report(tmp_path, payload)
    assert rc.classify(returncode=0, timed_out=False, output=ok_output(), report_path=report)["outcome"] == es.OUTCOME_CLAUDE_FAILED


def test_report_cannot_claim_a_runner_only_outcome(tmp_path):
    for forbidden in (es.OUTCOME_BUDGET_EXHAUSTED, es.OUTCOME_HARNESS_VIOLATION, es.OUTCOME_INFRASTRUCTURE_FAILED):
        report = write_report(tmp_path, {"outcome": forbidden, "stop_reason": "x"})
        assert rc.classify(returncode=0, timed_out=False, output=ok_output(), report_path=report)["outcome"] == es.OUTCOME_CLAUDE_FAILED


def test_run_uses_subscription_auth_flags_and_a_hard_timeout(tmp_path):
    seen = {}

    def fake_run(command, **kwargs):
        seen.update(command=command, **kwargs)
        raise subprocess.TimeoutExpired(command, kwargs["timeout"])

    result = rc.run(prompt="p", minutes=235, report_path=tmp_path / "r.json",
                    env={"CLAUDE_CODE_OAUTH_TOKEN": "o"}, runner=fake_run)
    assert result["outcome"] == es.OUTCOME_BUDGET_EXHAUSTED
    assert seen["timeout"] == 235 * 60
    assert "--dangerously-skip-permissions" not in seen["command"]
    assert seen["command"][seen["command"].index("--permission-mode") + 1] == "dontAsk"
    assert "ANTHROPIC_API_KEY" not in seen["env"]
