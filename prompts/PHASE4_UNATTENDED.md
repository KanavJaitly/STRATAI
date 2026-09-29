# Phase 4 — unattended resumption (attempt $attempt_id)

You are resuming Phase 4 of StratAI in an unattended GitHub Actions run. No
human is watching. Work under **Phase Execution Mode** exactly as
`prompts/MASTER_BUILD.md` defines it. This file adds constraints for
unattended runs; it does not relax anything in MASTER_BUILD.md.

## Authoritative sources — read these first, in this order

1. `prompts/MASTER_BUILD.md` — the process and every gate.
2. `docs/P4Milestones.md` — what each milestone must deliver and prove.
3. `.agent/phase4/PHASE_STATUS.md` — current state, and **decisions D1–D11,
   which are binding**. Where a decision and the spec text differ, the decision wins.
4. `.agent/phase4/PHASE_PLAN.md` and every `.agent/phase4/M*_ACCEPTANCE.md`.
5. `RUNNING_NOTES.md` for history.

The repository is checked out at `$base_sha`. That is your starting point.

## Environment

- PostgreSQL at `DATABASE_URL` is a restored, readiness-gated snapshot of the
  2024–2026 seasons with Statbotics EPA. Treat it as **read-only historical
  data**. Do not sync, delete, or modify its rows.
- `TBA_API_KEY` is a deliberate placeholder. Any call that reaches The Blue
  Alliance fails, by design. Ingestion is not part of this run.
- You have no git push credentials. **Commit locally.** A separate job validates
  your branches and publishes them.
- Hard time limit: about $minutes minutes, then the process is killed.
  Uncommitted work is lost. **Commit at every stage boundary.**

## Branches: one per milestone

- Work on `automation/phase4-mNN` (for example `automation/phase4-m04`). Create
  each milestone branch from the tip of the previous milestone's branch, or from
  `$base_sha` for the first, so the branches form a stack.
- If a milestone's branch already exists at the base, continue on it.
- Never commit to `main`. Never rewrite history. No force operations.
- Do not modify `.github/`, `automation/`, `prompts/`, `docs/P4Milestones.md`,
  or `tests/test_automation_*`. The publisher rejects the **entire attempt** if
  any branch touches them.

## Order

Skip every milestone that already has an `MXX_ACCEPTANCE.md`. Never redo
accepted work. Then work in this order: **M04 → M05 → M06 → M07 → M11 → M13**,
then the Mid-Phase Audit if it has not been done. The Phase Acceptance Review
comes only after the human sign-off below.

## Binding real-data rules

- Split (D7): train on 2024 + 2025, test on held-out 2026. Strict temporal order.
- M4: run `scripts/run_m4_baseline_backtest.py` on the real data, with real final
  ranks from `data.rankings.read_final_ranks_for_season`. Freeze the numbers,
  dated, in `RUNNING_NOTES.md`.
- M5 (D5): the primary gate is held-out 2026 **Spearman** against real final event
  rank, and it must **strictly** beat the frozen raw-EPA baseline. Top-8 recall
  is a secondary diagnostic only.
- M6: exact symmetry, plus beats or matches the baseline on held-out log-loss and Brier.
- M11 (D4, D12): its code is built. The logical feature is `average_auto_points`
  (see `ml/features/score_breakdown.py`); do not re-choose it. Acceptance also
  requires the real generalization test to pass:
  `python -m scripts.run_m11_generalization`, and `tests/test_m11_generalization.py`
  with `PHASE4_REAL_DATA_TESTS=1`, which is already set in this environment. Write
  `M11_ACCEPTANCE.md` only if every one of M11's criteria is satisfied.
- M7 (D6): **ECE < 0.05**, using the existing M3 ECE with 10 equal-width bins on
  [0,1]. The 60% → 58–62% band applies where that bin has sufficient observations.
  Report every bin's count and flag under-populated bins.
- Every excluded match is counted and reported. EPA is never fabricated, imputed
  or substituted. Synthetic data is never evidence for a real-data criterion.

## Stop immediately: commit, write the report, and end the session — when

- **Any real-data acceptance criterion fails** (D9). Do not iterate the model,
  features, metric, threshold, split or methodology to pass. You may fix only an
  objectively demonstrated implementation defect, and you must document the
  evidence for it.
- **M11 or any milestone needs a choice the spec and decisions D1–D14 do not make.**
- **Anything MASTER_BUILD.md's Human Escalation Protocol reserves for a human**,
  or any situation where continuing would require guessing.
- **The Circuit Breaker Rule trips**: the same failure 3 times.
- **M13 is ready for its dated human sign-off.** Only Kanav can record that sign-off.
- **Anything would cost money**, or would need a credential you don't have.

## Report (required, including on stop)

Before ending, write a JSON file to `$report_path`:

```json
{
  "outcome": "progress_checkpointed | awaiting_human_signoff | escalated",
  "stop_reason": "one or two plain sentences",
  "milestones": {"M04": "accepted | failed | in_progress | not_started", "...": "..."}
}
```

- Use `awaiting_human_signoff` only when M13 is waiting on Kanav's sign-off.
- Use `escalated` for every other stop above.
- Use `progress_checkpointed` when you ran out of time with the remaining work
  still legitimate to continue.

"Accepted" means the milestone's `MXX_ACCEPTANCE.md` is committed on its
branch after its full Milestone Acceptance Gate passed. A human still reviews
and merges each PR. Merging is the final acceptance.
