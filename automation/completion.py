"""The one definition of "Phase 4 is genuinely complete", used for shutdown.

Evaluated only against origin/main (the authoritative state) and GitHub:
every milestone acceptance artifact M03-M13 plus PHASE_ACCEPTANCE.md exist on
main, the tracking issue is closed, and no automation milestone PR is still
open. M01/M02 were accepted before Phase Execution Mode existed and are recorded
only in RUNNING_NOTES.md (.agent/README.md), so they have no artifact to check.

Deliberately not signals of completion: tests passing, code existing, an
unmerged branch, a partial artifact set, Statbotics being up, or Claude exiting.
"""

from __future__ import annotations

from dataclasses import dataclass

REQUIRED_ACCEPTANCE_FILES = tuple(f"M{number:02d}_ACCEPTANCE.md" for number in range(3, 14))
PHASE_ACCEPTANCE_FILE = "PHASE_ACCEPTANCE.md"
AUTOMATION_BRANCH_PREFIX = "automation/phase4-m"


@dataclass(frozen=True)
class CompletionFacts:
    files_on_main: frozenset[str]           # basenames under .agent/phase4/ on origin/main
    tracking_issue_state: str               # "OPEN" / "CLOSED" as reported by GitHub
    open_pr_head_branches: frozenset[str]


@dataclass(frozen=True)
class CompletionVerdict:
    complete: bool
    missing: list[str]


def evaluate(facts: CompletionFacts) -> CompletionVerdict:
    missing = [name for name in (*REQUIRED_ACCEPTANCE_FILES, PHASE_ACCEPTANCE_FILE) if name not in facts.files_on_main]
    if facts.tracking_issue_state.upper() != "CLOSED":
        missing.append(f"tracking issue is {facts.tracking_issue_state}, not CLOSED")
    open_automation = sorted(b for b in facts.open_pr_head_branches if b.startswith(AUTOMATION_BRANCH_PREFIX))
    if open_automation:
        missing.append(f"open automation PRs: {open_automation}")
    return CompletionVerdict(complete=not missing, missing=missing)
