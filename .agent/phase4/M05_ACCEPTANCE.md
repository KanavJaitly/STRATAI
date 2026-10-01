# Phase 4 — Milestone 5 (v2): Team Ranking Model — Gate PASSED, pending review

2026-09-30. Decision D16, the single pre-registered run. **The gate passed; acceptance is pending Kanav's review.** M5 v1's failure stays on record (`M05_ESCALATION.md`, `results/m05_*`). EPA source: STRATAI (D15). Statbotics parity is not claimed.

## Gate (frozen spec §1.5; strictly beat both)

| Held-out 2026, midpoint snapshot | Spearman | Top-8 recall |
|---|---|---|
| **M5 v2 `RankingXGBModelV2`** | **0.6128** | **0.6550** |
| Raw-EPA baseline, same protocol | 0.5951 | 0.6472 |
| Frozen M4 raw-EPA baseline | 0.5951 | 0.6472 |

- 0.6128 > 0.5951 (same protocol) **and** > 0.5951 (frozen): **PASS**.
- Reproducible: a second, independent fit gives an identical evaluation.
- The same-protocol baseline equals the frozen number exactly. Prior-event EPA is the same at every qualification snapshot, and the ranked teams are the same, so the new decision point does not move the baseline.

## Evaluation population and timing

- **Population:** 208 events with real 2026 final qualification ranks (0 skipped) and 8,160 team-events, every one scored.
- **Decision point:** each team's ⌈n_i/2⌉-th qualification match. n_i = 3–13 (median 12). Each team has 2–10 completed matches known at its snapshot (median 5).
- **0 snapshots after qualification ended.** No playoff or post-event information is used.
- **Features known at the snapshot:**
  - D13 prior-event STRATAI EPA (available before the snapshot);
  - the team's completed matches at the event before the snapshot;
  - the causal season scale S(Y, as_of).

## Training

- Train 2024 + 2025, 34,465 rows (D7).
- Labels: 15,617 team-events (1 excluded for having fewer than 3 matches; 0 events with zero spread).
- 137,246 training and 34,311 validation samples (temporal last 20%). Early stopping selected iteration 7 (v1: 2).

## Secondary (pre-declared, not gating)

| Snapshot | M5 v2 Spearman / top-8 | Baseline |
|---|---|---|
| k = 1 (before any in-event match) | 0.5487 / 0.6130 | 0.5951 / 0.6472 |
| k = n_i (before the last qualification match) | 0.6493 / 0.6689 | 0.5951 / 0.6472 |

- **Label shuffle**, 8 seeds, midpoint Spearman: −0.26 … +0.25, mean **0.041**. That is chance level, so no leakage signal.
- **Feature gain:**
  - epa_total_norm 0.561;
  - average_score_norm 0.220;
  - epa_teleop_norm 0.059;
  - consistency_rating 0.039;
  - matches_considered 0.032;
  - the rest ≤ 0.027.

  No non-EPA feature dominates.
- **Per event (diagnostic):** the model beats the baseline in 120 of 208 events; mean difference +0.0177, SD 0.085, standard error 0.0059.

## Caveats for the review

- **The gain is modest.** It is about 3 standard errors on the paired per-event difference, a diagnostic, not part of the gate.
- **It depends on in-event information.** Before any in-event match (k = 1), the model is worse than raw EPA (0.5487 vs 0.5951). At the midpoint it uses half the team's qualification results, while the raw-EPA baseline uses only prior-event EPA by M4's definition. That is the comparison the frozen gate defines.

## No post-hoc change

- **Checked by the run itself before evaluating (`frozen_files.ok = true`):**
  - the spec blob is `318c20a7…`, identical to freeze commit d77ffe4;
  - none of the frozen methodology or acceptance files changed;
  - the dataset builder's diff is scale-fields-only.
- **One reading of the spec**, committed before the run (fbb94a2): §1.4's "temporal last 20% of samples by scheduled_time" was taken literally (samples, with v1's split-index rule).
- **Before the run:** the pre-run record (`results/m05v2_prerun_record.json`, commit fa1f54b) was committed.
- **After the run:** no code or parameter was changed.

## Evidence

- `results/m05v2_result.json` (the in-repo record; it also blocks a second run);
- `results/m05v2_prerun_record.json`.
- Frame `77ada71a…`: the same rows and exclusions as M4's frame, plus the D16 scale fields.
- Implementation: `ml/models/ranking_xgb_v2.py`, `ml/features/scale.py`, `ml/backtest/ranking_midpoint.py`; tests in `tests/test_ml_models_ranking_xgb_v2.py`.
