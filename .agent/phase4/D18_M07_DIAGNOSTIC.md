# Phase 4 — D18 M07 failure: diagnostic and criterion decision

2026-10-02. Read-only diagnostic. **The D18 M07 result is unchanged: FAILED** (G2, 2/9 bins rejected). No model, calibrator, bin, threshold or gate was modified.

- Evidence: `results/d18/m07_diagnostics.json`, produced by `results/d18/m07_diagnostics.py` from frame `ab1adbf3`.
- **Reproduction:** the script refits the D18 M7 model deterministically and refuses to continue unless it reproduces the recorded run exactly. It reproduces it: ECE 0.02316275652450326, all bin counts, wins and p-values identical.
- **Population:** 15,027 EPA-complete held-out 2026 rows, 34 ties excluded, the M4/M6 population.

## 1. Is the failure practically meaningful? Yes

| | Value |
|---|---|
| ECE (10 bins) — recorded G1 | 0.0232 |
| ECE expected under perfect calibration, same predictions (2,000 simulations) | mean 0.0077, 99th percentile 0.0128 |
| ECE event-cluster bootstrap 95% CI | 0.0197–0.0322 |
| ECE (20 bins / 10 equal-mass bins) | 0.0279 / 0.0226 |
| Calibration-in-the-large (red) | predicted 0.514, observed 0.536 (+2.1 pts) |
| Brier decomposition | reliability 0.0010, resolution 0.0720, uncertainty 0.2487 |

- **The miscalibration is real.** The pooled ECE of 0.0232 is about 3× the perfect-calibration noise floor.
- **Its Brier cost is small** (reliability is 1.4% of resolution).
- **The calibrator is a coarse step function:** 127 distinct output values with large plateaus. For example, 1,132 predictions of exactly 0.175 win 0.236, and 470 of 0.366 win 0.472. Displayed probabilities therefore carry false precision.

## 2. Where the error lives: playoffs, around the higher seed

| Population | n | Red win rate | Mean predicted (red) | Observed − predicted | ECE | G2 |
|---|---|---|---|---|---|---|
| **Qualification** | 12,245 | 0.497 | 0.498 | −0.001 | **0.015** | 1/9 bins rejected |
| **Playoff** | 2,782 | 0.706 | 0.587 | **+0.119** | **0.119** | 6/8 rejected |
| Playoff, blue favoured by the model | 816 | 0.501 | 0.306 | **+0.195** | 0.195 | 3/3 rejected |
| Playoff, higher seed's perspective (seed derived exactly from final qual ranks) | 2,750 | 0.773 (higher seed wins) | 0.624 | **+0.148** | 0.149 | 7/8 rejected |
| …higher seed is red | 2,126 | 0.810 | 0.638 | +0.172 | — | 7/8 rejected |
| …higher seed is blue | 624 | 0.646 | 0.579 | +0.067 | — | 2/6 rejected |

**The two failing pooled bins are mostly playoffs:**

| Bin | Qualification | Playoff |
|---|---|---|
| [0.1, 0.2) | +2.6 pts | +13.1 pts |
| [0.3, 0.4) | +1.0 pts | +25.3 pts (predicted 0.367, observed 0.620) |

**Qualification bins:**
- every populated qualification bin is within ±3.2 pts;
- pattern: mild favourite overconfidence (favourite predicted 0.765, wins 0.750).

**Red in playoffs** is the higher seed in 77% of 2026 playoff matches.

**The effect is persistent, not 2026-only** — it appears in every season and in every fit:

| Season / fit | Red share of decided playoff matches | Red underestimate |
|---|---|---|
| 2024 | 62.7% | — |
| 2025 | 68.0% | — |
| 2025 calibration slice (in-sample) | — | +6.8 pts |
| 2024 → 2025 fold | — | +6.8 pts |
| 2026 | 70.7% | +11.9 pts |

Red's share in qualification is 49.5–49.8% in every season.

**Other cuts (all statbotics-only unless noted):**
- **By week:** ECE 0.046–0.068 in weeks 1–3, 0.030–0.033 in weeks 4 and 6.
- **By EPA source:** matches where 4–6 teams use prior-season EPA have ECE 0.057.
- **By event type:** regional 0.036, district 0.026, DCMP 0.041, championship divisions 0.028.
- **Fallback-touched matches:** 75 matches touch a 2026iscmp fallback; too few to evaluate (unevaluable).

## 3. Causes, in order of size

1. **Missing playoff information (dominant).**
   - The higher seed wins far more often than the alliance features predict.
   - The model sees each team's features but not seed or alliance-selection structure.
   - It is symmetric by construction, and so is the calibrator (both perspectives, symmetrized). So it cannot learn the remaining bracket-position (red) component either.
   - This holds in all three seasons. It is a model limitation, not a calibration-layer defect.
2. **Cross-season distribution shift.**
   - Raw M6 is already miscalibrated on 2026: ECE 0.077, 8/10 bins rejected.
   - The calibrator learned the late-2025 mapping. It passes G2 in-sample there (0/9) but does not transfer.
   - In a 2024 → 2025 diagnostic fold the same pipeline also fails (ECE 0.046, 5/10 rejected), and calibration *worsened* log-loss (0.538 → 0.585).
   - **In-sample calibration numbers are not evidence of held-out calibration.**
3. **Early-season, prior-season EPA.** M6's features are raw game points, and 2026's scoring scale is 2.5–3.8× the training seasons'. The largest qualification deviations sit in weeks 1–3.
4. **Not class imbalance:** qualification red share 0.497 vs predicted 0.498.
5. **Not the D18 source:** Statbotics-only rows have ECE 0.0230.

## 4. Impact on STRATAI use

- **Event (qualification) prediction — usable as approximate probabilities.**
  - Expected qualification wins per team-event (7,845 team-events, about 9.4 matches each): mean |actual − expected| is 1.12 wins, against 0.96 under perfect calibration — 16% excess error, unbiased on average (mean difference 0.00).
  - Display coarsely (about 5-point granularity), not as "63.4%".
- **Playoff prediction and simulation — not trustworthy.**
  - A per-match probability understated by about 12–15 points compounds over a series. For example, a best-of-3 at a model match probability of 0.60 gives a series probability of 0.65; at the observed rate it is about 0.81.
  - Bracket and alliance "predicted playoff success" built on these probabilities would systematically understate higher seeds.
- **Rankings are unaffected:** M5 v2 does not use M6/M7.

## 5. Decision on the criterion (Step 3): **A — keep the frozen D16 M7 criterion; the failure is genuine**

- **The criterion asks the right question.** For STRATAI's intended use ("realistic win probabilities", reports, playoff success), what matters is whether a stated probability means what it says across the scale. That is what G2 tests.
- **The known weakness of G2 does not apply here.** G2 has no practical-difference threshold, so with very large bins it can reject negligible deviations. Here the rejected deviations are 3.3 and 6.7 pts.
  - Both are beyond the authoritative plan's own done-means tolerance (60% → 58–62%, about ±2 pts).
  - The underlying playoff errors are 12–25 pts.
  - Any tolerance large enough to pass would be chosen only to pass.
- **If anything, the frozen criterion is too lenient.** It pools qualification and playoff matches. Pooled G1 passes (0.023) while playoff ECE is 0.119.
  - A replacement fit to purpose would be stratified by use (qualification vs playoff). It would fail more clearly, not less.
  - No replacement could legitimately turn this result into a pass, and none is needed to establish the failure.

**Therefore:**
- M07 stays FAILED;
- no replacement M7 specification is created and no replacement run is made.

**What would legitimately change the outcome is a model change, which is Kanav's decision, with its own frozen spec and one run:**
- causally normalized M6 features (the D16 §1.2 scheme);
- an explicit, antisymmetric playoff-context feature (seed difference);
- a stratified M7 criterion.
