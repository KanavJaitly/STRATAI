# P6-M10 redesign investigation (2026-10-10): evidence for the draft v2 specification

**Authorized by Kanav on 2026-10-10:** investigation and a draft specification only. Nothing is implemented, fit or evaluated, and **P6-M10 stays `not_validated`**.

**Sources:**
- the recorded failure (`results/p6_m10_outcome_model.json`, `P6_M10_FAILURE.md`);
- the frozen spec (`P6_M10_MODEL_SPEC.md`, blob `5f838613…`);
- the 2026-10-05 diagnostics (`diagnostics/p6_m10_diagnostics.json`, `p6_m10_source_diagnostic.json`; diagnostic only).

**Nothing new was computed on outcomes,** except re-applying Holm to the recorded p-values.

## 1. The failure is unchanged and reproduces

**The records are untouched:** each has a single commit.
- `p6_m10_outcome_model.json` and `P6_M10_FAILURE.md`: `30dcf55`;
- `p6_m10_fit.json`: `4c38f7a`;
- `P6_M10_MODEL_SPEC.md`: `48ac1ea`;
- `P6_M10_DIAGNOSIS.md`: `c335afb`.

**The frozen model:** `strategy_outcome_component` `p6m10-v1`, sha256 `aded2c82…`.

**Two independent reproductions of the four failed bins:**
- **Holm re-applied:** applying the Holm step-down (α = 0.05) to the 10 recorded per-bin p-values rejects exactly the four recorded bins.
- **Full recomputation (2026-10-05):** the diagnostic recomputed the whole population (12,215 matches) and reproduced every G2 bin (`recorded_gate_reproduced: true`).

| Bin | n | Predicted | Observed | p |
|---|---|---|---|---|
| 0.2–0.3 | 1,219 | 0.251 | 0.194 | 3.0e-06 |
| 0.3–0.4 | 1,393 | 0.351 | 0.300 | 7.2e-05 |
| 0.6–0.7 | 1,354 | 0.649 | 0.694 | 5.0e-04 |
| 0.7–0.8 | 1,207 | 0.750 | 0.785 | 5.1e-03 |

G1 (ECE 0.027), G3 and G4 passed. Only G2 failed: symmetric under-confidence.

## 2. Likely causes (from recorded evidence)

**The win-calibration slope** (logistic of the outcome on logit p; 1 = calibrated, > 1 = under-confident):

| Group | Training 2024–2025 (in-sample) | Held-out 2026 |
|---|---|---|
| all matches | **1.274** | 1.114 |
| all six EPA sources same-season | **1.433** | **1.316** |
| mixed | 1.195 | 1.004 |
| all six EPA sources prior-season | 0.902 | 0.963 |

**Causes:**
1. **The model is under-confident in-sample, not only after the season transfer.** A slope of 1.27 on the fit seasons means the frozen fit itself is mis-specified for win probability. The actual margin is about 1.23× the predicted mean (same-season training rows), so the predicted mean is attenuated.
   - **The likely mechanism:** the per-component OLS (P6-Q8, spec §4) regresses each component on its own capability only. Correlated cross-component signal is pushed into the residuals, which inflates s relative to m.
   - **Corroboration:** the joint total-margin diagnostic (Option A) has an in-sample slope of 1.066.
2. **The EPA-source regime matters, in both training and 2026:**
   - same-season EPA (recent, from the current game) is under-weighted;
   - prior-season EPA is roughly calibrated.

   The model treats them identically.
3. **The season shift is real but secondary.** The 2026 slopes are closer to 1 than the training slopes. Weeks 3–6 of 2026 are the most under-confident (1.23–1.67), and that is confounded with the share of same-season EPA.

**This is a hypothesis-level diagnosis.** The 2026 numbers are post hoc and cannot validate anything.

## 3. Options compared (the diagnosis's A–D; Option C examined first, as directed)

| Option | Addresses | Risk |
|---|---|---|
| **C: calibration stage** | in-sample under-confidence, if fit on a recent out-of-sample season | a calibrator fit on the training period would learn a slope near 1.27 and over-correct a season whose raw slope is 1.11. **Fit on 2026, the most recent completed season**, it learns that season's mapping. A single global calibrator cannot fix the regime mixture |
| **C conditioned on regime** (C + the core of B) | cause 1 and cause 2, outside the model | regime is a new calibration covariate (point-in-time; not an outcome). A change to P6-Q8/Q9's single-model form, which needs approval |
| **A: joint margin regression** | cause 1 at its root | changes the per-component structure the strategy recommender conditions on. The post-hoc 2026 slope of 0.911 suggests over-confidence without calibration |
| **B: β/Σ per regime** | cause 2 inside the model | more parameters; the per-regime sample sizes (prior-season: about 2,100 training rows) |
| **D: in-season refit** | drift | conflicts with the Phase 5/6 frozen-model principle; the hardest point-in-time guarantees |

**Recommended first candidate:** Option C, conditioned on regime (**C-R**). The frozen v1 model is kept unchanged, and a symmetric per-regime temperature is fit on 2026. **C-G** (one global temperature) is the simpler alternative for Kanav's choice. Neither is presumed to work: the development check and the 2027 gate decide.

## 4. The evaluation population

- **No unseen data exists.** The latest match in the isolated database is 2026-07-08. No 2026 off-season events are synced, and off-season events are outside P6-Q9's population (official events; Statbotics EPA) anyway.
- **2026 is fully observed and motivated this redesign,** so it cannot validate it. It may legitimately be **calibration data** for v2, because it was never v2's acceptance data.
- **The only eligible untouched population is the 2027 official season's EPA-complete qualification matches,** evaluated once the season is complete. That uses the same population definition as P6-Q9, with the year changed.
- **A partial-season gate is not recommended:** the 2026 failure varied by week.
