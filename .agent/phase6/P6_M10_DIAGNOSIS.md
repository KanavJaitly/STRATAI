# P6-M10 gate failure — forensic diagnosis (diagnostic only; nothing fixed)

**2026-10-05.**
- **The authoritative failed run** is unchanged: `.agent/phase6/results/p6_m10_outcome_model.json` (gate FAILED, baseline odds `not_validated`, D9).
- **No change was made** to the model, its parameters, features, evaluation population, gate constants or any record.
- **Diagnostic outputs (not evaluations):** `.agent/phase6/diagnostics/p6_m10_diagnostics.json` and `p6_m10_source_diagnostic.json`, from `scripts/phase6_m10_diagnostics.py` and `scripts/phase6_m10_source_diagnostic.py` at `37ec1b5`.
- **Reproduction:** the diagnostic recomputed the evaluated population, 12,215 matches, and reproduced the recorded G2 bins exactly (`recorded_gate_reproduced: true`).
- **Post-hoc fits:** every quantity fitted here is evidence about the failure only. None is a candidate model or a recalibration.

## 1–2. The four failed bins (from the record)

G2 is the exact Poisson-binomial two-sided test per bin, Holm-corrected at α = 0.05. "Interval" is the 95% central interval of the observed rate under the bin's own predictions.

| Bin | n | Mean predicted | Observed | Observed − predicted | p-value | Holm threshold | 95% interval |
|---|---|---|---|---|---|---|---|
| 0.2–0.3 | 1,219 | 0.2514 | 0.1944 | −0.057 | 2.96e-06 | 0.0050 | [0.227, 0.276] |
| 0.3–0.4 | 1,393 | 0.3506 | 0.3001 | −0.050 | 7.19e-05 | 0.0056 | [0.326, 0.375] |
| 0.6–0.7 | 1,354 | 0.6492 | 0.6942 | +0.045 | 4.97e-04 | 0.0063 | [0.624, 0.674] |
| 0.7–0.8 | 1,207 | 0.7499 | 0.7846 | +0.035 | 5.12e-03 | 0.0071 | [0.726, 0.774] |

The other six bins were not rejected. The 0.8–0.9 bin had p = 0.020 against a Holm threshold of 0.0083.

## 3. Concentration

| Dimension | Finding |
|---|---|
| **Probability range** | Symmetric: predictions are too close to 0.5 on both sides, in the 0.2–0.4 and 0.6–0.8 ranges. The extreme bins and the 0.4–0.6 bins are consistent |
| **Strategy types** | **None in the gate population.** P6-Q9 evaluates the baseline strategy for both alliances only, so no strategy variation can have caused the failure |
| **EPA-source season** | **Strongly concentrated.** Matches whose six teams' EPA all come from 2026 events: calibration slope 1.316, ECE 0.057 (n = 5,439). All prior-season sources: slope 0.963, ECE 0.023 (n = 2,644). Mixed: slope 1.004, ECE 0.017 (n = 4,132) |
| **Week** | Weeks 3–6 are under-confident (slopes 1.23, 1.67, 1.41, 1.16). Weeks 0–2 and the championship are close to calibrated (0.82–1.03). This is consistent with, and confounded with, same-season sources becoming the majority later in the season |
| **Week removal** | Removing any single week still fails G2 (2–5 rejected bins), so no single week drives it |
| **Position in event** (early / middle / late) | No concentration (slopes 1.06 / 1.11 / 1.18) |
| **STRATAI fallback** | 60 matches; too few to say anything |
| **Events** | 207 events. The largest per-event gaps are on small samples (6–64 matches), with no single-event concentration claim |
| **Teams** | Not analysed per team: about 3,000 teams over 12,215 matches cannot support per-team calibration claims |
| **Score components** | On 2026 data (diagnostic only): actual component differences exceed β × predicted in every component. The 2026-only OLS β is 0.91 / 1.08 / 0.97 (auto / teleop / endgame), against the fitted 0.74 / 0.95 / 0.88. Residual SD in 2026: auto 0.245 (fitted 0.344), teleop 0.697 (0.642), endgame 0.334 (0.215), other 0.128 (0.277) |

## 4. Systematic or localized?

**Systematic and global under-confidence.** The overall calibration slope is 1.114 (intercept −0.02). It is stronger where every team's EPA comes from the same season, and absent where all EPA comes from the prior season.

## 5. Cause

**Evidence for a likely primary cause: model misspecification that already exists in the training seasons.**
- **The model is under-confident on its own training rows.** The in-sample calibration slope is **1.274** on 15,797 non-tie 2024–2025 fit matches, larger than on 2026 (1.114). The failure was therefore present before any 2026 data, and **is not primarily a 2026 distribution shift.**
- **The mechanism is confirmed with a falsifiable diagnostic.** The specification fits each component's β by regressing that component's difference only on its own predicted difference, then sums them. That discards cross-component information: teams strong in one component tend to be strong in the others. As a result, the summed predicted margin understates the realized total margin. In training, the slope of the actual total on the predicted mean is 0.90–1.23 by source category.
  - A diagnostic joint regression of the total difference on all three predicted component differences, fitted on the same training rows, brings the in-sample calibration slope from **1.274 to 1.066**.
  - This is a diagnostic only. The same fit is over-confident on 2026 (slope 0.911), so it is not a fix, and that 2026 number was seen after the fact.
- **Contributing, also present in training: EPA-source-season heterogeneity.** One β/σ is shared by same-season EPA (more informative for the current game) and prior-season EPA (a different game).
  - In-sample calibration slopes: same-season 1.433, mixed 1.195, prior-season 0.902 (over-confident).
  - In 2026: same-season 1.316, mixed 1.004, prior-season 0.963.
- **Contributing, smaller: a general 2026 shift.** The slope of the actual on the predicted mean is higher in 2026 than in training in every source category: prior-season 0.90 → 1.10, same-season 1.23 → 1.33, mixed 1.16 → 1.27. The 2026 game's capability differences translate into margins more strongly than the training seasons'.
- **Ruled out:**
  - **Strategy-feature shift and insufficient strategy variation:** the gate population is baseline-only.
  - **Fabricated defense/feeding effects:** none exist (§10).
  - **Implementation defects:** the record reproduces exactly; G3 symmetry 2.2e-16; G4 fit isolation holds.
  - **Calibration-step failure:** P6-M10 has no calibrator; the miscalibration is in the model itself.

**Conclusion:** a likely cause **is** identified, with in-sample and held-out evidence. It is a specification-level under-weighting of the predicted margin by the per-component least-squares design, compounded by unmodelled EPA-source-season heterogeneity and a smaller 2026 shift.

What is **not** established:
- the exact share of each factor;
- whether non-Gaussian or heteroscedastic residuals contribute;
- whether any redesign would pass G2 on held-out data. That needs a new pre-registered specification and a new single evaluation, and since 2026 has now been observed, a held-out population or design Kanav decides.

## 6–7. M6/M7 on the exact same 12,215 matches

| | P6-M10 | M6/M7 (`d18`) |
|---|---|---|
| Log-loss | **0.5004** | 0.5388 |
| ROC-AUC | **0.8367** | 0.8230 |
| Brier | **0.1658** | 0.1716 |
| Brier reliability (lower = better calibrated) | 0.0011 | **0.0003** |
| Brier resolution (higher = better discrimination) | **0.0844** | 0.0774 |
| ECE | 0.0266 | **0.0147** |
| Calibration slope | 1.114 (under-confident) | 0.858 (over-confident) |
| G2 on this population | FAIL (4 bins) | **also FAIL** (1 bin: 0.1–0.2, n 2,014, predicted 0.163 vs observed 0.188, p 3.05e-03) |

**Why P6-M10 has better log-loss but fails calibration.** Log-loss and Brier reward discrimination (resolution) as well as calibration (reliability).
- P6-M10 separates winners from losers better: higher AUC and higher resolution.
- Its calibration error is larger (reliability 0.0011 vs 0.0003) but small next to the resolution gain.
- G2 is a strict per-bin significance test. With about 1,200–1,400 matches per bin, a systematic 3.5–5.7-point error is decisively detectable.

M6/M7 is over-confident in the opposite direction, and on this exact population it also fails G2, on one bin.

## 8–10. Strategy conditioning, defense and feeding

- **Constant inputs:** defense and feeding enter **nothing**.
  - There are 0 team appearances in 2026 with a defense or feeding value.
  - The model never reads scouting values: planting defense = feeding = 5.0 on every team changes no probability.
  - Defending (any target), feeding (any target) and scoring while withholding the same components give **identical** odds (6 variants, 1 distinct probability).
- **Strategy-space collapse:** the 21,952 candidates per context map to **at most 512 distinct model inputs** (8 per robot, cubed). That is 512 / 21,952 = 2.3% distinct.
  - Across 25 sampled real contexts: 22 had 512 distinct inputs, and 3 had 256 because one capability was 0. In every case the number of distinct probabilities equalled the number of distinct inputs.
  - **97.7% of the candidates are duplicates.** Every defense or feeding target choice, and the role label itself, collapses onto "scoring with teleop withheld".
- **Meaningful variation:** the only variation that reaches the model is which components each robot pursues. All of it can only **lower** the odds, so the recommender always returns the baseline, and says so.
- **No probability comes from an unvalidated defense or feeding effect.** Their effects are exactly zero by rule (P6-Q8), they are labelled, and they are never estimated.

## 11. Enough evidence?

There is enough to name a **likely** cause, as in §5, with in-sample and held-out evidence and a falsifiable mechanism test. It is not enough to claim that any particular redesign would pass.

## Redesign directions (NOT implemented; each needs Kanav's explicit dated decision first)

| Direction | Frozen decision or assumption it changes | Supporting evidence | Missing evidence | New validation required | Approval needed |
|---|---|---|---|---|---|
| A. A joint total-margin regression (all components predict the total), keeping per-component means for strategy conditioning | P6-Q8's per-component fit, as specified in `P6_M10_MODEL_SPEC.md` §4 | In-sample slope 1.274 → 1.066 with the joint diagnostic fit | Held-out calibration: the diagnostic fit is over-confident on 2026 (0.911), seen post hoc | A new frozen spec and a single run on a **pre-registered held-out population not yet seen**. 2026 has been observed, so Kanav must decide the population | **Yes** |
| B. Separate β/σ by EPA-source season (same-season vs prior-season) | P6-Q8, and the model's feature set (source season becomes an input) | Strong heterogeneity in both training and 2026 | Whether the split generalizes, and the sample size per regime | As A | **Yes** |
| C. A calibration stage (e.g. the symmetric isotonic calibrator) on a temporally prior slice | P6-Q8/Q9, which define P6-M10 with no calibrator | M7's calibrated M6 reaches ECE 0.015 here | M7's own calibrator failed its gate on the full population. The calibration slice and its season-transfer need a decision | The M7/D16 gate on an unseen population | **Yes** |
| D. A seasonal or in-season re-fit (e.g. weekly updating of β/σ) | Phase 5/6 "no retraining; frozen models"; P6-Q8 | The 2026 shift is in every category | A design and its point-in-time guarantees | A replay-style evaluation within the 45-minute rule | **Yes** |
| E. Keep P6-M10 as is: odds `not_validated`, the recommender's value limited to structure and parity | Nothing | P6-DM2 is met regardless | — | — | No (current state) |

Any rerun of P6-M10 on the existing 2026 population, after this diagnosis, would be result-informed. It cannot validate a redesign.
