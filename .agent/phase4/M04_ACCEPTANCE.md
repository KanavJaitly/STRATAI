# Phase 4 — Milestone 4 Acceptance: Locked Naive Baselines

Accepted 2026-09-30. EPA source: STRATAI (decision D15). No Statbotics parity is claimed.

## Criteria

| Criterion (docs/P4Milestones.md M4) | Evidence | Result |
|---|---|---|
| Both baselines first-class models | `ml/models/baselines.py` (unchanged since 2026-09-25) | PASS |
| Run through M3, held-out numbers frozen | `.agent/phase4/results/m04_result.json`; RUNNING_NOTES 2026-09-30 | PASS |
| Dated baseline logged in RUNNING_NOTES.md | session-log row 2026-09-30 | PASS |
| Baseline symmetry (p -> 1-p exactly) | `tests/test_ml_models_baselines.py` | PASS |
| Reproducibility (same data -> identical metrics) | real data: two runs identical (`reproducible: true`); unit test | PASS |
| Win-prob monotonic in EPA difference | `tests/test_ml_models_baselines.py` | PASS |

## Frozen numbers (held-out 2026, D7: train 2024+2025)

- Frame `54e9d54b5ebe6b11b616f4e72cb402ad0a50cbfc89940632deda23ec5b7dc7bc`: 52,469 rows; excluded 726 dq_affected, 25 unplayed (M2 rules).
- Win prob — `EpaWinProbBaseline` on EPA-complete rows (19,780 train / 15,061 test; 14,685 / 2,943 EPA-incomplete excluded; 34 ties excluded from scoring):
  accuracy **0.7622**, log-loss **0.6734**, Brier **0.1785**, ROC-AUC **0.8421**, ECE **0.1194**.
- Ranking — `RawEpaRankingBaseline` vs real 2026 final ranks (208 events scored, 5 skipped):
  Spearman **0.5951**, top-8 recall **0.6472**.

## Inputs and provenance

- EPA: STRATAI chain `chain_e77d9444c57a7b50` (2024 `6be8896b…`, 2025 `4d9de7a4…`, 2026 `8fa397b2…`); integration verification all PASS (`results/stratai_epa_integration_verification.json`).
- Runner: `scripts/run_phase4_stratai.py m04` — runs exactly `scripts/run_m4_baseline_backtest.py`'s procedure (imports its `_split_epa_complete`) on the cached frame; read-only DB session.

## Observations (not defects)

- The win-prob baseline is overconfident on 2026 (log-loss high relative to Brier; ECE 0.12): its single logistic scale is fit on 2024–25 EPA differences, and 2026 scores run on a much larger scale (week-1 score sd 93.8 vs 20.4 / 36.8). Frozen as-is.
- 43% of training rows lack a complete EPA set, mostly early 2024 (no STRATAI season before 2024, so a team's first 2024 event has no prior EPA). Counted and reported, never imputed.

## Regression

- `tests/test_ml_models_baselines.py`, `tests/test_scripts_run_m4_baseline_backtest.py`, `tests/test_ml_backtest_harness.py`: 50 passed.
