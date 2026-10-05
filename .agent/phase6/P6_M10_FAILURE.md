# P6-M10 — the baseline gate FAILED (D9: recorded, not redesigned)

2026-10-05. This file is a failure record, not an acceptance record.

**Run:** one run, exactly as specified.
- **Specification:** `.agent/phase6/P6_M10_MODEL_SPEC.md`, frozen at `48ac1ea` before the fit.
- **Fit:** `p6_m10_fit.json`, 15,956 2024–2025 EPA-complete qualification matches.
- **Evaluation:** `.agent/phase6/results/p6_m10_outcome_model.json`, write-once.
- **Population:** 12,215 held-out 2026 EPA-complete qualification matches. Excluded: 33 ties, and 30 matches without a causal scale.

| Gate (M7/D16 constants, P6-Q9) | Result |
|---|---|
| G1 ECE < 0.05 | **pass** (0.0266) |
| G2 per-bin exact Poisson-binomial, Holm α = 0.05 | **FAIL**: 4 of 10 bins rejected |
| G3 symmetry ≤ 1e-12, order independence | pass (max 2.2e-16) |
| G4 fit isolation | pass (2024–2025 only; every fit row before every evaluated row) |
| **Gate** | **FAILED** |

**The rejected bins all show the same pattern: under-confidence.** Predictions are too close to 0.5 on both sides:

| Bin | n | Mean predicted | Observed |
|---|---|---|---|
| 0.2–0.3 | 1,219 | 0.251 | 0.194 |
| 0.3–0.4 | 1,393 | 0.351 | 0.300 |
| 0.6–0.7 | 1,354 | 0.649 | 0.694 |
| 0.7–0.8 | 1,207 | 0.750 | 0.785 |

The tails (< 0.2, > 0.8) and the central bins (0.4–0.6) are consistent.

**Diagnosis (not a fix):**
- The score-difference spread fitted on 2024–2025 is wider, relative to the predicted mean, than 2026 outcomes show. In 2026 the measured capability separates winners more sharply than in the training seasons.
- This is the cross-season transfer limitation Phase 4 already recorded (`docs/ml_models.md` §7, §11: "calibration does not transfer across seasons").
- **It is not an implementation defect:**
  - symmetry is exact;
  - fit isolation holds;
  - the inputs are the D18 frame's;
  - the model is exactly the frozen specification.

**Reported, not gated (P6-Q9):**
- The paired log-loss of P6-M10 minus M6/M7 on the same rows is −0.0384 (event-bootstrap 95% CI −0.0613 to −0.0170). P6-M10's log-loss is lower: 0.5004 vs 0.5388; Brier 0.1658 vs 0.1716.
- This is recorded as measured. It does not change the gate result.

**Consequences (D9):**
- **Status:** baseline odds from P6-M10 are served `not_validated`, with reason `p6_m10_gate_failed`. Non-baseline strategies were `not_validated` regardless (`strategy_effect_unmeasured`).
- **The strategy track continues** on this status: P6-M11 (recommender), P6-M12 (validation of what can be validated) and P6-M13 (the parity audit) do not depend on the gate passing. P6-DM2 concerns parity, not calibration.
- **No change** to the model, its inputs, the fit procedure, the population or the gate, and no re-run. Any redesign (for example a season-transfer calibration step) needs Kanav's dated decision made **before** any new result, as a new model version with its own frozen specification.
