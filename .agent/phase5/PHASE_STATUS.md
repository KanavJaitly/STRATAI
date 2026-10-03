phase: 5
branch: phase5/build (from origin/main 369687f)
current_milestone: P5-M6 (STOPPED at checkpoint for human review)
status: CHECKPOINT_STOPPED (see CHECKPOINT_2026-10-03.md)
stage: P5-M6 debug replay done; recorded replay NOT run
accepted: [P5-M1, P5-M3, P5-M4, P5-M5]
blocked:
  - P5-M8/P5-M9 (DM1): open decision Q3 + human inputs (M08_DECISION_REQUIRED.md)
  - P5-M6 (DM2): recorded replay pending review; dependency 'P5-M2 adopted' unmet
  - P5-M7: open decision Q2 (M07_DECISION_REQUIRED.md); (a) passed, (b)/(c) wait
  - P5-M2: open decision Q1 (M02_DECISION_REQUIRED.md), then L1/L2, then adoption (P5-D3)
human_decisions_required:
  - P5-M8/M9 Q3: similarity/archetype/expected-range/dominant-component rules, kappa gate, coding reconciliation
  - P5-M6: form of the recorded replay's reproducibility check (second full replay vs cheaper equivalent)
  - P5-M7 Q2: detector test statistic and unit (M07_DECISION_REQUIRED.md)
  - P5-M2 Q1: A1/A2 skip vs literal state (M02_DECISION_REQUIRED.md)
  - P5-M2 adoption decision (P5-D3)
  - P5-M8 human double-coding of the curated reference (kappa)
  - P5-M9 human-authored feasibility rubric; mentor review
  - DM1 2026 game spec entered from the manual by a person (no hindsight)
known_risks: see PHASE_PLAN.md
last_verified: mid-phase full suite 1,732 passed / 2 failed then fixed; checkpoint suite: see below
last_checkpoint: CHECKPOINT_2026-10-03.md
