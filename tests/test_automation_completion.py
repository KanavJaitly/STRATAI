"""Tests for automation.completion -- the shutdown condition."""

from __future__ import annotations

from automation.completion import (
    PHASE_ACCEPTANCE_FILE,
    REQUIRED_ACCEPTANCE_FILES,
    CompletionFacts,
    evaluate,
)
from automation.verify_dataset import verify

EVERYTHING = frozenset({*REQUIRED_ACCEPTANCE_FILES, PHASE_ACCEPTANCE_FILE, "PHASE_STATUS.md"})


def facts(files=EVERYTHING, issue="CLOSED", prs=frozenset()) -> CompletionFacts:
    return CompletionFacts(files_on_main=frozenset(files), tracking_issue_state=issue, open_pr_head_branches=frozenset(prs))


def test_genuine_completion():
    verdict = evaluate(facts())
    assert verdict.complete and verdict.missing == []


def test_every_milestone_from_m03_to_m13_is_required_including_m11():
    assert REQUIRED_ACCEPTANCE_FILES[0] == "M03_ACCEPTANCE.md"
    assert REQUIRED_ACCEPTANCE_FILES[-1] == "M13_ACCEPTANCE.md"
    assert "M11_ACCEPTANCE.md" in REQUIRED_ACCEPTANCE_FILES  # decision D4: M11 is not skippable
    for name in REQUIRED_ACCEPTANCE_FILES:
        assert not evaluate(facts(EVERYTHING - {name})).complete


def test_milestones_without_phase_acceptance_are_not_complete():
    verdict = evaluate(facts(EVERYTHING - {PHASE_ACCEPTANCE_FILE}))
    assert not verdict.complete and PHASE_ACCEPTANCE_FILE in verdict.missing


def test_open_tracking_issue_blocks_shutdown():
    assert not evaluate(facts(issue="OPEN")).complete


def test_unmerged_automation_pr_blocks_shutdown():
    verdict = evaluate(facts(prs={"automation/phase4-m13"}))
    assert not verdict.complete
    assert evaluate(facts(prs={"someone/else"})).complete  # unrelated PRs don't matter


def test_partial_artifact_set_is_not_complete():
    assert not evaluate(facts(frozenset({"M03_ACCEPTANCE.md", "M04_ACCEPTANCE.md"}))).complete


# --- restored-dataset verification --------------------------------------------


def test_restored_dataset_must_match_what_was_gated():
    assert verify("COMPLETE", "abc", "abc") == []
    assert verify("PARTIAL", "abc", "abc")
    assert verify("COMPLETE", "abd", "abc")
    assert verify("COMPLETE", "abc", "")  # no recorded fingerprint: refuse, don't trust
