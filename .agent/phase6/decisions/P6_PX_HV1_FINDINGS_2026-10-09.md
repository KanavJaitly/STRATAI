# HV-1 findings: PX historical validation (2026-10-09). Diagnostic only, not acceptance

**Record:** `results/p6_px_hv1.json`
- written once, at provenance `eed46c5`;
- spec `P6_PX_HISTORICAL_VALIDATION_SPEC_V1.md`, blob `c03347ab`, frozen at `7cf2ef7` before any metric;
- 0.2 minutes.

**Data:** the rows cache, sha `d7809c5f…`, population `52a4d7f0…`. Selection times come from read-only `stratai_test`. M6/M7 `d18` is sha-pinned. The registered `px1b-v1` was not used.

**Folds:** walk-forward and event-disjoint; every fold's assertions passed. Every model was refit per fold.

## Results (log-loss, lower is better; Δ = PX-1b − comparator, event-bootstrap 95% CI, 2,000 resamples, seed 20261010)

| Fold | Rows (train → test) | PX-1b | PX-1 raw | Seed-only | M6/M7 | Δ vs seed-only | Δ vs PX-1 raw | Δ vs M6/M7 |
|---|---|---|---|---|---|---|---|---|
| **F0** 2024 within-season | 283 → 602 (45 events) | 0.853 | 0.876 | **0.639** | in-sample, not valid | **+0.214 [+0.116, +0.319]: worse** | −0.023 [−0.035, −0.012] | — |
| **F1** 2024 → 2025 | 991 → 2,435 (186) | **0.527** | 0.531 | 0.567 | in-sample, not valid | −0.040 [−0.058, −0.020] | −0.004 [−0.015, +0.007] | — |
| **F2** 2024–25 → 2026 | 3,426 → 2,626 (193) | **0.469** | 0.644 | 0.523 | 0.560 | −0.054 [−0.070, −0.037] | −0.175 [−0.231, −0.125] | −0.091 [−0.109, −0.071] |
| **Pooled F1 + F2** | 5,061 test rows (379 events) | | | | | −0.047 [−0.059, −0.034] | −0.092 [−0.121, −0.064] | — |

**Calibration** (ECE with 10 bins; calibration slope: 1 is ideal, below 1 is overconfident):

| | F0 | F1 | F2 |
|---|---|---|---|
| PX-1b | 0.151 / 0.20 | 0.044 / 0.89 | 0.032 / 0.87 |
| PX-1 raw | 0.151 / 0.19 | 0.056 / 0.65 | 0.112 / 0.32 |
| seed-only | 0.070 / 0.67 | 0.092 / 1.24 | 0.099 / 1.27 |
| M6/M7 | — | — | 0.110 / 0.87 |

**Share of test events where PX-1b's log-loss is lower:**

| Comparator | F0 | F1 | F2 |
|---|---|---|---|
| seed-only | 0.36 | 0.69 | 0.74 |
| PX-1 raw | 0.69 | 0.44 | 0.61 |
| M6/M7 | — | — | 0.79 |

**Also recorded:** Brier differences with CIs. In F1 and F2, PX-1b is better than seed-only, and in F2 better than M6/M7 and PX-1 raw, each with the CI excluding 0. In F0 it is worse than seed-only.

## Answers (by the reading rules frozen in spec §5)

1. **Beats the baselines on each valid held-out season?** Not on every fold.
   - **2025 (F1):** better than seed-only (statistically supported). vs PX-1 raw: a point estimate only. M6/M7 is not valid (in-sample).
   - **2026 (F2):** better than M6/M7, seed-only and PX-1 raw (all statistically supported).
   - **2024 (F0, within season):** **significantly worse than seed-only.** Better than PX-1 raw.
2. **Consistent across seasons and events?** **No.**
   - vs seed-only, the sign flips: F0 worse; F1 and F2 better, with 69% and 74% of events better.
   - vs PX-1 raw, PX-1b is better on the point estimate in every fold.
3. **Better probability quality and calibration?**
   - **Yes against the PX-1 raw design.** In F1/F2 the ECE is 0.044/0.032 against 0.056/0.112, the calibration slope 0.89/0.87 against 0.65/0.32, and the |logit| test/train ratio 1.13/1.27 against 1.67/3.44. The normalization removes most of the scale-shift overconfidence that failed PX-1.
   - **Against seed-only and M6/M7, in F1/F2:** better Brier and ECE.
   - **Still somewhat overconfident** (slope < 1), and very poorly calibrated in F0 (slope 0.20).
4. **Statistically supported, or point estimates only?** Supported in F1 vs seed-only, in F2 vs all three, and pooled. **But the CIs do not account for:**
   - **F1:** it is a reproduction of DEV-1, already seen.
   - **F2:** it is post-hoc. PX-1b's design was chosen after the 2026 diagnostics.
   - **F0:** the least-contaminated fold, and the one that went against PX-1b.
5. **Ready for the independent 2027 test?** By the pre-registered rubric (spec §5 Q5), **"promising"**: F2 is supported vs both FINAL-1 comparators, and F1 is supported vs seed-only. **That is advisory only.** Nothing here accepts PX-1b. **2027 performance is not proven.** FINAL-1 on an untouched 2027 holdout remains the only acceptance.

## Observations (not acted on; hypotheses, not findings)

- **F0's reversal coincides with a small training set:** 283 rows for 66 columns, with every PX model overfit (slope ≈ 0.2). PX-1b's advantage may depend on training size. FINAL-1's candidate is fit on 6,052 rows, which is closer to F1/F2 than to F0, but this is not established.
- **Every model has a positive recalibration intercept** (+0.12 to +0.63; red under-predicted). That suggests a red-side or bracket-position effect that the antisymmetric, no-intercept design and the symmetric PX-2b calibrator cannot represent. It would need a separately pre-registered investigation. It is not a defect in the frozen specs, which require antisymmetry.

## Not changed

**Unchanged:** all specifications, gates, thresholds and prior records. The registered `px1b-v1`, pins and calibration base are untouched. PX-1 stays `not_validated`, and PX-1b stays an unaccepted candidate.

**Still open before M10, as Kanav directed:** the PX integrity gap G3 (the unpinned PX-2b calibrator and `ranking_xgb_v2` `d18` in PX-4b/M8b). It awaits Kanav's decision.
