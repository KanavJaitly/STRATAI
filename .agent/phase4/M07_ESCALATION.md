# Phase 4 — Milestone 7 Escalation: Calibration Gate (D16) Fails on Real Data

2026-09-30. Not an acceptance record. Execution stopped here under D9. M5 v2 was not run.

## Gate result (held-out 2026, EPA-complete rows, 15,027 scored, 34 ties excluded)

| Component (frozen spec §2.3) | Result |
|---|---|
| G1 ECE < 0.05 | **PASS**: 0.0375 (raw M6 0.0796; log loss 0.5555 → 0.5520, Brier 0.1885 → 0.1826) |
| G2 per-bin exact Poisson-binomial, Holm α = 0.05 | **FAIL**: 10 bins eligible, **5 rejected** |
| G3 symmetry | **PASS**: max error 1.1e-16, order-independent |
| G4 fit isolation | **PASS** |

Model and calibrator:
- M6 `WinProbXGBModel` fit on 15,824 rows: the first 80% of the EPA-complete 2024 + 2025 training rows.
- `SymmetricIsotonicCalibrator` fit on 3,937 rows (2025-03-30 → 2025-04-19).

Per-bin results (calibrated q):

| Bin | n | mean q | observed | 95% interval under H₀ | p | decision |
|---|---|---|---|---|---|---|
| [0.0, 0.1) | 974 | 0.050 | 0.057 | 0.037–0.064 | 0.34 | — |
| [0.1, 0.2) | 1,466 | 0.158 | 0.192 | 0.139–0.177 | 4.4e-4 | **rejected** |
| [0.2, 0.3) | 1,459 | 0.231 | 0.261 | 0.209–0.252 | 0.0073 | **rejected** |
| [0.3, 0.4) | 1,011 | 0.381 | 0.340 | 0.351–0.411 | 0.0071 | **rejected** |
| [0.4, 0.5) | 1,194 | 0.436 | 0.415 | 0.408–0.464 | 0.14 | — |
| [0.5, 0.6) | 3,420 | 0.524 | 0.607 | 0.507–0.541 | 2.2e-22 | **rejected** |
| [0.6, 0.7) | 1,189 | 0.620 | 0.681 | 0.592–0.648 | 1.1e-5 | **rejected** |
| [0.7, 0.8) | 1,716 | 0.770 | 0.761 | 0.750–0.790 | 0.37 | — |
| [0.8, 0.9) | 1,615 | 0.842 | 0.852 | 0.824–0.859 | 0.27 | — |
| [0.9, 1.0] | 983 | 0.950 | 0.941 | 0.936–0.962 | 0.21 | — |

Evidence:
- `results/m07_result.json`;
- `results/m07_failure_diagnostics.json` and `.py`;
- `results/m07_synthetic_verification.json` (V1–V4 all pass; V5 is the test suite).

## Is it an implementation defect? (D9 permits fixing only those) — no

- Served probabilities equal the specified formula ½[g(p) + 1 − g(1 − p)] exactly (maximum difference 0.0).
- Synthetic verification passed every pre-stated criterion:
  - V1: pmf exact to 7e-16;
  - V2: false-failure rate 4.4% (95% CI 3.2–5.9%);
  - V3: 100% power on both gating scenarios;
  - V4: symmetry error ≤ 1.1e-16.
- On its own fit slice (late 2025) the calibrator passes G2 with **0** bins rejected.

## Cause: a 2026-specific shift in the raw M6 output

- **Raw M6 is already miscalibrated on 2026**, in a way the 2025 calibration slice does not show:
  - 4,420 raw predictions in [0.5, 0.6) average 0.526 but win **0.643**;
  - 2,983 in [0.4, 0.5) average 0.467 but win **0.399**.
  - The model compresses many decided 2026 matches toward 0.5.
- **The calibrator learned the 2025 mapping.** Raw 0.50–0.55 maps to about 0.50–0.58. In 2026 the 2,910 matches with raw 0.50–0.55 win **0.619** while their calibrated mean is 0.528.
- **No earlier-season fit can correct it.** A calibrator fitted only on earlier seasons cannot correct a shift that first appears in the held-out season.
- **Same family as M5's failure.** M6's features are in raw game points (`TEAM_FEATURE_NAMES`, unnormalized), and 2026's scoring scale is 2.5–3.8× the training seasons' (`M05_M07_METHODOLOGY_ANALYSIS.md` §2.1).
- **Practically large, not only statistically detectable.** The deviations are 3–8 points (e.g. 0.524 against 0.607). They would also fail the rejected fixed ±0.02 tolerance, so the failure does not depend on G2's sensitivity in large bins.

## Not run (D9 stop)

- **M5 v2:** not run. The instruction "run only once after M7" is ambiguous when M7 fails, and the run is single-shot, so it was not spent.
- **M11:** depends on M5. **M13:** not started.

## For Kanav

1. **Whether M5 v2 may run now.** It is independent of M7, and its frozen spec already normalizes its own features causally.
2. **The M7 path.** Either:
   - record M7 as failed, leaving the calibration half of the phase's done-means unmet; or
   - approve a pre-registered methodology change. For example: causal feature normalization for M6/M7 (the M5 v2 §1.2 scheme applied to `TEAM_FEATURE_NAMES`, which would also re-open M6), or a different calibration-fit scheme.

   Any change would need its own frozen specification and one run.
