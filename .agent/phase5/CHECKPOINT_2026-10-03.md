# Phase 5 checkpoint — 2026-10-03 (STOPPED for human review)

- **Reason:** Kanav instructed a stop after the 2026arli debug replay, before the full recorded P5-M6 replay
  (559 matches × 2).
- **Supersedes:** the earlier "build all of Phase 5 without stopping" instruction.

## Git

- **Branch:** `phase5/build`, from origin/main `369687f`. Nothing has been pushed.
- **Checkpoint commit:** the commit that adds this file (see `git log`). The previous commit was `5b1e296`.
- **Working tree after the checkpoint:** clean except the user's own `.gitignore` modification, which is never
  staged.
- **Phase 4 evidence, D18 models and PR #29 machinery:** untouched. No Phase 4 file is modified on this branch;
  `ml/features/score_breakdown.py` is extended by a new module, not edited.
- **Local databases (not in git):**
  - `stratai` (serving): never written by any Phase 5 test or replay;
  - `stratai_test` (template copy used for every test run);
  - `stratai_p5_replay_debug` (the debug replay's final state, kept for inspection).

## Milestones

| Milestone | Status | Evidence |
|---|---|---|
| P5-M1 alliance and seed data | ACCEPTED | `M01_ACCEPTANCE.md`, `results/p5_m1_alliance_acceptance.json` |
| P5-M3 strength views | ACCEPTED | `M03_ACCEPTANCE.md`, `results/p5_m3_strength_acceptance.json` |
| P5-M4 event analysis | ACCEPTED | `M04_ACCEPTANCE.md`, `results/p5_m4_event_analysis.json` |
| P5-M5 qualification forecasts | ACCEPTED; (b) recorded as failed, so the range is served `not_validated` | `M05_ACCEPTANCE.md`, `results/p5_m5_qualification_forecast.json` |
| P5-M2 live EPA refresh | NOT ACCEPTED: open decision Q1; L1/L2 not run; L3 passed; L4 passed on a labelled rerun | `M02_ACCEPTANCE.md`, `M02_DECISION_REQUIRED.md`, `results/p5_m2_l3*`, `results/p5_m2_l4*` |
| P5-M7 meta tracking | NOT ACCEPTED: open decision Q2; (a) passed, 106,390 / 106,390 | `M07_ACCEPTANCE.md`, `M07_DECISION_REQUIRED.md`, `results/p5_m7_adapter_parity.json` |
| P5-M6 in-season loop (DM2) | IN PROGRESS: implementation committed, debug replay run, recorded replay NOT run | `debug/M06_DEBUG_2026ARLI.md` |
| P5-M8 game-rule analysis | NOT ACCEPTED: infrastructure built and tested; needs Q3 and human inputs | `M08_ACCEPTANCE.md`, `M08_DECISION_REQUIRED.md` |
| P5-M9 capability and DM1 | NOT ACCEPTED: infrastructure built and tested; DM1 needs Q3 and human inputs | `M09_ACCEPTANCE.md` |
| P5-M10 docs, contracts, done-means | IN PROGRESS: `scripts/phase5_done_means.py` committed; contract tests parked in `wip/` until docs/phase5.md is finalized | `wip/test_phase5_contract.py` |
| Mid-phase audit | DONE | `MID_PHASE_AUDIT.md` |
| Phase-level audit and PHASE_ACCEPTANCE | NOT STARTED | |

**Done-means:**
- **DM1:** NOT MET (Q3 and human inputs).
- **DM2:** NOT MET.
  - The recorded replay has not been run.
  - P5-M6's declared dependency, "P5-M2 adopted", is unmet (Q1, then L1/L2, then the P5-D3 adoption decision).

## Verification completed

- **Full suite (mid-phase), on `stratai_test`:** 1,732 passed, 3 skipped, 2 failed. Both were fixed (Phase 5
  paths scoped out of the Phase 3 docs contract; the INTERIM reliability caveat added to two endpoints); the
  affected suites then passed (106).
- **Since then (targeted):**
  - live EPA: 27;
  - meta: 9;
  - game analysis: 8;
  - watch plus follow-on: 48 (this includes the 4 new follow-on tests);
  - replay source: 2;
  - qualification forecast and event analysis suites as recorded in their ACCEPTANCE files.
- **The checkpoint full-suite run** is recorded in `PHASE_STATUS.md`.
- **Write-once records** each carry their commit and frame or snapshot hashes.
- **Leakage and determinism checks:**
  - M3 point-in-time sentinel;
  - M4/M5 pre-event and match-time features;
  - L3 outage drill;
  - L4 one `snapshot_id` per response, bit-for-bit re-serve, no change without an input;
  - M2 root equals D18 (24,022 values).
- **P5-M6 debug replay (2026arli):** see `debug/M06_DEBUG_2026ARLI.md`.
  - Ingestion reproduced the serving database's canonical rows exactly.
  - 65 / 65 re-polls were no-ops.
  - `team_metrics` equals a recompute, apart from its timestamp.
  - All reported problems are harness defects.

## Methodology and acceptance criteria

- **Unchanged.** No criterion, methodology, feature definition, dataset or threshold was changed.
- **Flagged instead of decided:** three spec gaps (Q1, Q2, Q3).
- **Operationalizations, recorded before their runs:**
  - M4: the switch snapshot is at the next match; the bootstrap follows the Phase 4 precedent.
  - M5: 80% bounds by `gate.central_interval`'s convention.
  - L4: the event and lag were pre-declared.

## Outstanding work (in order, after review)

1. **Human decisions:**
   - Q1 (P5-M2);
   - Q2 (P5-M7);
   - Q3 (P5-M8/M9);
   - whether the P5-M6 reproducibility check needs a second full replay (see the performance note in this
     report);
   - eventually, P5-M2 adoption (P5-D3).
2. **Fix the three harness defects** in `scripts/phase5_m6_replay.py`:
   - (d) compare excluding `computed_at`;
   - (b) refresh the control baseline on every served step;
   - write the full debug result to a file.
   Then rerun the 2026arli debug replay to confirm a clean (a)–(d) plus sentinel result.
3. **The recorded P5-M6 replay,** in the form approved at review.
4. **P5-M2:** L1/L2 after Q1. **P5-M7:** (b)/(c) after Q2.
5. **P5-M10:** finalize docs/phase5.md (P5-M6 section, label and code glossary), move the contract tests back
   into tests/, run `scripts/phase5_done_means.py`.
6. **The phase-level audit and `PHASE_ACCEPTANCE.md`.** DM1 stays open until the human inputs exist.

## Exact next step after review

- Apply the reviewer's decision on the replay form.
- Fix the three harness defects (verification-harness bugs only; no criterion changes) and commit.
- Rerun `--debug-event 2026arli` and confirm a clean result.
- Only then launch the recorded P5-M6 replay.

## Update — 2026-10-03, after review (Kanav)

- **New permanent rule (CLAUDE.md):** no verification run may exceed about 45 minutes; use seeded samples plus
  edge cases.
- **Harness defects:** fixed at commit baf8144.
- **The recorded six-event run is disabled** in the script until a design within the rule is approved.
- **2026arli debug rerun:** 0 problems in 30.1 min. Per-match equality, the leakage sentinel, the final
  re-request and A1/A2-rule agreement all pass. See `debug/M06_DEBUG_2026ARLI.md`.
- **Q1, Q2 and Q3:** still OPEN. Their details were reported to Kanav; nothing is decided.
- **Next step:** Kanav's decisions on Q1, Q2 and Q3, and approval of a recorded P5-M6 design within 45 minutes.

## New open decision Q4: P5-M6's frozen population vs the 45-minute rule (raised 2026-10-03)

**The conflict.** P5-M6 freezes the six-event replay (559 matches), with (a) and (d) checked "after every completed
match". Ingestion plus the production watch follow-on alone costs about 8 s per match:
- `sync_event` about 0.9 s;
- the `team_metrics` recompute about 7 s, which is production behaviour and must not be shortcut.

That is about 75 min for 559 matches before any serving check. 2026arc alone (141 matches, a larger roster) would
exceed 45 min. No sampling of serving checks can bring the frozen population under the rule. So either the
evaluation population is amended by a dated decision (a spec change), or the rule is applied per run (several
budgeted runs). Not decided.

**Options:**
1. **Per-event budgeted runs.** Each run stays ≤ 45 min, with sampled serving checks. 2026arc needs splitting by
   time window, which is still the full population.
2. **Amend P5-M6's evaluation population** (a decision row before the result) to a seeded, stratified sample of
   events or windows plus the fixed edge cases: 2026iscmp for (e), a championship division, an early-week event.
3. **Engineering speedups that leave behaviour unchanged,** then re-estimate.
