# `.agent/` — StratAI Autonomous Engineering Execution State

This directory is the authoritative, persistent record of Phase Execution Mode
runs, per `prompts/MASTER_BUILD.md`. It is **tracked in Git**, deliberately:
it exists to be durable engineering memory that survives across sessions and
across contributors (Kanav, Sven), not local scratch state.

## What lives here

```
.agent/
    phaseX/
        PHASE_PLAN.md        # created when "Execute Phase X" begins
        PHASE_STATUS.md      # kept current throughout the phase
        M01_ACCEPTANCE.md    # written when milestone 01 is accepted
        M02_ACCEPTANCE.md
        ...
        MID_PHASE_AUDIT.md   # written at the phase's approximate midpoint
        PHASE_ACCEPTANCE.md  # written when the whole phase is accepted
```

`X` is the real phase number (e.g. `.agent/phase4/`). A `phaseX/` directory
and its contents are created only when that phase is actually executed under
Phase Execution Mode — this repository does not backfill `.agent/` artifacts
for phases or milestones completed before Phase Execution Mode was adopted
(2026-09-24). Phase 2, Phase 3, and Phase 4 Milestones 1–2 remain recorded
only in `RUNNING_NOTES.md`, exactly as they always were.

## What this is not

- **Not `.claude/`.** `.claude/` holds Claude Code's own tooling, session, and
  worktree infrastructure — it is not StratAI engineering state and has
  caused real confusion once already (see `RUNNING_NOTES.md`'s 2026-09-21
  entry on the orphaned `.claude/worktrees/agent-a20c54804d9905347/` folder).
  Only `.agent/phaseX/` is authoritative execution state for this project.
- **Not a replacement for `RUNNING_NOTES.md`.** `RUNNING_NOTES.md` remains the
  human-readable engineering history, decision log, and known-issues tracker.
  `.agent/phaseX/` is the machine-checkable answer to "did this milestone/
  phase pass its acceptance gate" — `RUNNING_NOTES.md` narrates what happened
  and why; it does not decide acceptance.
- **Not a replacement for the milestone specifications** (`docs/P*Milestones.md`,
  `docs/ROADMAP.md`). Those documents say what must be built. `.agent/`
  records whether what was built was verified and accepted.

## Format

Per `prompts/MASTER_BUILD.md`'s "Persistent Phase State": keep these files
concise — bullet points, checklists, or YAML/JSON-style status blocks, not
prose essays. The `MXX_ACCEPTANCE.md` field list is fixed (see
`prompts/MASTER_BUILD.md`'s "Milestone Acceptance Artifact" section).
