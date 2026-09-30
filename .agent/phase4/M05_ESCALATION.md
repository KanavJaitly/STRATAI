# Phase 4 — Milestone 5 Escalation: Ranking Model Misses Its Gate

2026-09-30. Not an acceptance record. Execution stopped here under D9.

## Result (held-out 2026, D7 split, STRATAI EPA)

| | Spearman (D5 primary) | Top-8 recall (secondary) |
|---|---|---|
| Frozen M4 raw-EPA baseline | **0.5951** | 0.6472 |
| M5 `RankingXGBModel` (unchanged, defaults, seed 42) | **0.3903** | 0.5132 |

- Gate D5 (strictly beat the baseline's Spearman): **FAIL**.
- 208 events scored, 5 skipped (no usable final ranks). Re-run identical (`reproducible: true`).
- Evidence: `results/m05_result.json`, `results/m05_failure_diagnostics.json`, script `results/m05_diagnostics.py`.

## Checked: is it an implementation defect? (D9 permits fixing only those)

No defect found:

- **Leakage.** One label-shuffle run gave Spearman 0.249, so it was repeated over 8 seeds: −0.28 … +0.27, mean **0.023**. It collapses to chance on average. The single value was one random split direction on `epa_total` applied to every event.
- **Wiring.** The same fold, final ranks and harness as the baseline; the provider-served EPA equals the chained artifacts exactly (integration verification).
- **Mechanism.** Early stopping on M5's own temporal validation slice (the last 20% of training rows: 2025 from 2025-03-23) selects iteration **2**. Validation RMSE bottoms at 48.74 (round 3) and then rises while training RMSE falls.
  - The raw game-point target changes scale by season: mean |margin| is 24.6 (2024), 38.0 (2025) and **116.9 (2026)**.
  - EPA is also in game points: median 16.5 / 22.1 / 36.4, and **9.8%** of 2026 EPA values exceed the training maximum (119.5). Trees cannot extrapolate past it.
- **Not caused by D15.** Statbotics EPA is in the same game-point units and would face the same cross-season scale shift.

## Why this needs Kanav

Every way forward changes something D9 freezes: the target, the features, the model objective or the M5 methodology. For example:

- per-season normalization of the target and/or features, using only information available at prediction time (e.g. week-1 statistics, or the previous season);
- a pairwise, within-event ranking objective;
- or accept that M5 does not beat raw EPA, which keeps the phase's ranking done-means unmet.

None of these was tried.

## Not run (stopped by D9)

- M06, M07 and M11 were not run on real data. M13 was not started.

## Found ahead, for the same decision session (M7)

`ml/calibration/calibrator.check_calibration_band(target=0.60)` scores the bin **[0.6, 0.7)** against 58–62%. A perfectly calibrated synthetic model (200,000 draws) has an empirical rate of **0.6547** there and fails. As implemented, the band check cannot pass for a well-calibrated model. D6's ECE < 0.05 is the stated threshold; the band's intended definition (for example a bin centred on 0.60) needs Kanav's decision. Also noted: neither calibrator is constrained to preserve M6's exact red/blue symmetry.
