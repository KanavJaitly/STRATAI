# P6-M10 after DEV-M10b: diagnosis, alternatives and remaining Phase 6 work (2026-10-11)

**Requested by Kanav on 2026-10-11.**
- **Scope:** diagnosis, a comparison of alternatives, and a draft M10c specification. Review only.
- **Nothing was fit, re-evaluated, registered or served.** P6-M10 stays `not_validated`, and `p6m10-v1` stays served.
- **The frozen M10b spec (`d699afaf`) and A1 (`a453eaba`) are unchanged.**

**Evidence used:** only recorded results. Nothing new was computed on outcomes; §1.4's small arithmetic uses recorded aggregates only.
- `results/p6_m10_outcome_model.json`: v1 on 2026.
- `results/p6_m10b_dev.json`: DEV-M10b.
- `results/p6_m10b_calibrator.json`.
- `diagnostics/p6_m10_diagnostics.json` and `p6_m10_source_diagnostic.json` (2026-10-05).
- `P6_M10_REDESIGN_INVESTIGATION_2026-10-10.md`.

**Evidence status.** All of it concerns 2026, a season fully observed and used to design M10b. It is **diagnostic**, not independent acceptance evidence. Only 2027 can be.

## 1. Diagnosis

### 1.1 Which G2 bins fail, and how

The G2 test asks whether each bin's observed win rate matches its mean prediction (Holm, α = 0.05). Below, "error" means observed minus predicted, for red.

**v1 on 2026** (base fit on 2024–2025; 4 bins rejected):

| Bin | n | Predicted | Observed | Error | p | Rejected |
|---|---|---|---|---|---|---|
| 0.0–0.1 | 1,020 | 0.047 | 0.055 | +0.008 | 0.26 | no |
| 0.2–0.3 | 1,219 | 0.251 | 0.194 | **−0.057** | 3.0e-6 | **yes** |
| 0.3–0.4 | 1,393 | 0.351 | 0.300 | **−0.051** | 7.2e-5 | **yes** |
| 0.6–0.7 | 1,354 | 0.649 | 0.694 | **+0.045** | 5.0e-4 | **yes** |
| 0.7–0.8 | 1,207 | 0.750 | 0.785 | **+0.035** | 5.1e-3 | **yes** |
| 0.9–1.0 | 1,062 | 0.952 | 0.947 | −0.004 | 0.52 | no |

v1 is under-confident in the middle (the outcomes are more decisive than predicted) and calibrated at both ends.

**DEV raw** (v1 procedure refit on 2024 only; evaluated on 2026; 3 bins rejected):

| Bin | Predicted | Observed | Error | p | Rejected |
|---|---|---|---|---|---|
| 0.0–0.1 | 0.045 | 0.062 | **+0.018** | 3.9e-3 | **yes** |
| 0.2–0.3 | 0.252 | 0.216 | **−0.035** | 4.6e-3 | **yes** |
| 0.3–0.4 | 0.350 | 0.310 | **−0.041** | 2.1e-3 | **yes** |
| 0.6–0.7 | 0.650 | 0.683 | +0.032 | 0.017 | no |
| 0.9–1.0 | 0.956 | 0.943 | −0.013 | 0.035 | no |

The same middle under-confidence, plus an over-confident lower tail.

**DEV calibrated** (the M10b method; factors fit on 2025, evaluated on 2026; **2 bins rejected**):

| Bin | n | Predicted | Observed | Error | p | Rejected |
|---|---|---|---|---|---|---|
| **0.0–0.1** | 1,436 | 0.040 | 0.073 | **+0.033** | **8.1e-9** | **yes** |
| 0.2–0.3 | 1,141 | 0.250 | 0.217 | −0.033 | 9.2e-3 | no (threshold 0.00625) |
| 0.3–0.4 | 1,193 | 0.350 | 0.339 | −0.011 | 0.43 | no |
| 0.6–0.7 | 1,188 | 0.651 | 0.667 | +0.016 | 0.26 | no |
| **0.9–1.0** | 1,465 | 0.960 | 0.934 | **−0.026** | **1.8e-6** | **yes** |

**The calibration fixed the middle and broke both tails.** Strong favourites lose about 6.5% of the time, not the predicted 4%. Strong underdogs win about 7.3%, not 4%. In both tails the calibrated model is **over-confident**, and its predictions moved further out (the extreme bins grew from about 1,220 to about 1,450 rows each).

### 1.2 Which strata vary (as recorded)

| Stratum | Recorded evidence | Source |
|---|---|---|
| **Probability range** | The middle is under-confident; the tails are calibrated (v1) or over-confident (DEV raw lower tail; DEV calibrated, both tails) | §1.1 |
| **EPA-source group** (v1, 2026 win-calibration slope; 1 = calibrated, > 1 = under-confident) | same 1.316, mixed 1.004, prior 0.963. Training 2024–2025: 1.433, 1.195, 0.902 | source diagnostic |
| **Group, after calibration** (DEV calibrated on 2026) | mixed **0.83**, same **0.91**, prior 1.06. Same and mixed are now **over-confident**: the factors fit on 2025 were too large for 2026 | DEV record |
| **Week of season** (v1, 2026 slope) | week 1: 0.82; weeks 0 and 2: 0.96–1.03; **weeks 3–6: 1.15–1.67**. Champs: 0.97. Leaving out any one week still fails G2 (2–5 bins) | diagnostics |
| **Position in event** (v1) | early 1.06, middle 1.11, late 1.18 | diagnostics |
| **EPA fallback source** | 60 rows (STRATAI fallback): too few to estimate | diagnostics |
| **Season** | the calibration factors differ by season. Same-group slopes: 1.433 (training) vs 1.316 (2026). DEV's 2025-fit factors over-sharpen 2026 | above |

**Not recorded and not computable without re-evaluation** (not done, as instructed):
- per-bin errors within each EPA-source group;
- week × group;
- per-bin errors for the production calibrator. It is fit on 2026 and has never been evaluated; that is the 2027 run's job.

### 1.3 Why one scalar factor per group may be insufficient

The M10b calibrator maps z (the log-odds of v1's probability) to expit(a_g · z). That multiplies every log-odds in a group by the same factor. Two recorded facts show this form cannot fit the observed error:

1. **Shape (supported).** In two different bases (v1, and DEV's 2024-only base), the middle needs sharpening (a > 1) while the tails need none or need flattening (a ≤ 1). One a cannot do both. DEV shows the trade-off directly: the factor that fixed bins 0.2–0.4 turned both tail bins into the strongest rejections in the record (p = 8e-9 and 2e-6).
2. **Heterogeneity inside a group (partly supported).** The needed sharpening varies by week, from 0.82 to 1.67. A pooled factor over-sharpens the low-need strata. That is consistent with tail over-confidence, but group and week are confounded, and no within-group breakdown is recorded.
3. **Transfer across seasons (supported for DEV).** The factors fit on one season over-sharpened the next. That is a drift problem, not a shape problem. No functional form fit on a previous season fixes it.

### 1.4 What is supported, and what remains a hypothesis

| Claim | Status |
|---|---|
| The calibrated predictions are over-confident in both tails, and the middle is fixed (DEV, 2026) | **Supported** (recorded bins) |
| Raw v1 predictions are under-confident in the middle and calibrated at the tails (2026) | **Supported** |
| A per-group scalar trades middle error for tail error | **Supported**, by DEV before and after, in one evaluation season (2026) |
| The needed factor varies by week and by EPA-source group | **Supported** (recorded slopes); the two are **confounded** |
| The factor drifts between seasons | **Supported** (DEV: 2025 → 2026) |
| **H1: an "upset floor."** Some outcomes are near coin flips whatever the strength gap (breakdowns, disconnections, fouls), so the tails cannot go below a floor | **Hypothesis.** It fits DEV's tails: solving observed ≈ ε/2 + (1 − ε) · predicted gives ε ≈ 0.07 (lower tail) and ≈ 0.06 (upper tail). That is arithmetic on recorded aggregates, not a fit, and on 2026 (the design data) |
| **H2: EPA maturity.** Same-season EPA becomes more informative as the season progresses, so the needed sharpening grows by week | **Hypothesis**, consistent with the weekly slopes; confounded with group |
| M10b will fail G2 on 2027 | **Unknown.** DEV suggests a risk. Only the frozen 2027 run decides |

## 2. Alternatives

| | Approach | Assumptions | Data needed | Leakage risk | Small-sample risk | How it would be evaluated | Investigable before 2027? |
|---|---|---|---|---|---|---|---|
| **A0** | **M10b as frozen** (per-group scalar) | logit-linear shape; factors transfer across seasons | 2026 (done) | none (pinned before 2027) | low (3 factors, n ≥ 2,644) | the frozen 2027 gate | already done (DEV) |
| **A1** | **Upset floor (lapse) + per-group slope:** q = ε/2 + (1 − ε) · expit(a_g · z) | H1: a fixed share ε of outcomes are coin flips; logit-linear otherwise | the same 2026 set; ε is identified mostly by the extreme bins (about 2.4k rows) | none, if fit on 2026 and pinned before 2027 like M10b | ε pooled across groups (4 parameters); ε per group is not advised (prior-group tails are small) | the frozen gate on 2027 | **partly:** a pre-registered DEV-c on data not used to design it (§3), as consistency evidence only |
| **A2** | **Saturating link:** q = expit(a_g · z / (1 + b · \|z\|)) | the log-odds compress smoothly at large \|z\| | as A1 | as A1 | as A1 (b pooled) | as A1 | partly (as A1) |
| **A3** | **Strata-specific factors** (week or EPA-maturity bins × group) | H2; a point-in-time maturity covariate exists | a covariate available at prediction time (for example the number of same-season events behind each EPA); more cells | needs a strictly point-in-time covariate; the week is available, maturity must be verified | **high:** 3 groups × several strata, with thin tails per cell | 2027 gate | weakly: cells too thin to compare on one season |
| **A4** | **Symmetrized isotonic** | monotone only | large n in every region | none, if fit on 2026 | **high in the tails** (step noise) | 2027 gate | weakly |
| **A5** | **Fix the base:** a joint-margin regression or heavier-tailed margins (Student-t) | the base's form causes both problems | refit on 2024–2025 | none | moderate | 2027 gate, and the M11–M13 strategy checks rerun (the recommender conditions on the base) | development checks only |
| **A6** | **In-season, point-in-time recalibration** (refit on the season's own earlier weeks) | drift is gradual within a season | the season's earlier matches, strictly before each prediction | **highest:** needs strict as-of guarantees at every refit | early weeks have little data | 2027 gate, with the refits replayed point in time | design only. **Conflicts with the frozen-model principle (P5/P6)** |
| — | Change the G2 gate or the population | — | — | — | — | — | **excluded**: thresholds and methodology are not changed |

**Notes:**
- **A4's tie risk.** Plateaus tie strategies that v1 orders strictly, and the M11 tie-break then decides them. That is not a reversal, but it changes recommendations.
- **A5's scope.** It changes the per-component structure the recommender conditions on, which makes it a large re-validation.
- **Drift is unaddressed.** A1 and A2 target the shape problem (§1.3 point 1). None of A0–A5 addresses season drift (§1.3 point 3). Only A6 does, at the highest leakage and principle cost.

## 3. Recommendation

**Draft M10c = A1 for review:** the upset floor plus per-group slopes. The draft is `.agent/phase6/P6_M10C_SPEC_DRAFT.md`; it is PROPOSED, not frozen, and nothing is fit.

**Why A1:**
- It is the smallest change that can represent the recorded trade-off: sharpen the middle while bounding the tails.
- It keeps the v1 base, the groups and the gate.
- It is exactly symmetric and strictly monotone in z, so G3 and the M11 ordering properties carry over.
- Its one extra parameter has a domain meaning: the share of matches decided by events unrelated to strength.

**Why not the others:** A2 behaves similarly but its b has no direct meaning. A3, A4 and A6 carry higher small-sample or leakage risk. A5 is a larger re-validation.

**Not chosen for results.** A1 has not been fit on any data. It is recommended for the error shape the records show, not for performance on the data that revealed that shape. Its pre-2027 check (DEV-c) runs on data that did not inform the design (2025's later weeks). It is consistency evidence only. **Only the frozen 2027 run can accept it.**

**Decisions for Kanav (the draft's §9):**
1. Draft M10c at all, or keep A0 alone.
2. **Multiplicity:** M10b and M10c both evaluated on 2027 (one pre-declared primary, or a Holm correction across the two), or M10c superseding M10b before any 2027 data (M10b kept, never run).
3. The ε bound.
4. The DEV-c design.

## 4. Remaining Phase 6 engineering work

| Task | Benefit | Dependencies | Test plan | Risks | Recommendation |
|---|---|---|---|---|---|
| **Wire PX-2b, PX-4b and M8b to the pinned 2027 EPA source.** `PX1B_TRACK._epa_source` reads `results/p6_px1b_epa_source_2027.json` through `verified_epa_source`, and refuses when it is absent or mismatched | Removes a code change from the 2027 critical path. All 2027 consumers (FINAL-1, the M10b frame, PX-2b, PX-4b, M8b) then share one pinned source | none to implement; to *run*: the EPA config, PX-1b acceptance, and the rest of the D9 chain | synthetic: the PX-1b track resolves a verified record; refuses absent, mismatched or not-2027 records; PX-1's track is unchanged; C4/G3 tests stay green | **low**. It touches the C4 harness pointers (approved 2026-10-08), so it needs Kanav's approval as a C4 amendment. It must never fall back to an unpinned source | **Can safely be implemented now, after approval.** Fail-closed; it unblocks nothing by itself |
| **Pin `ranking_xgb_v2` `d18` (`1f0fe5aa…`) in the M6(b) harness** (`run_m6b` loads it without `expected_sha256`) | Integrity uniformity with G3 | none | one test: a mismatched ranking file is refused | **minimal**. The M6(b) measurement is recorded, write-once, non-gating, and cannot rerun (its record exists), so the pin protects nothing that can still run. The record does not name the model's sha256. Today's registry file is `1f0fe5aa…`, equal to the G3 pin, and the registry is write-once: the run almost certainly used it (**inferred, not recorded**) | **Optional, low value.** Safe, but only worth doing for a uniform integrity policy |

## 5. Human-input blockers (verified 2026-10-11)

| Blocker | Status |
|---|---|
| D9 decision v1 confirmation (`decisions/p6_d9_v1_confirmation.json`) | **open**: no such file |
| Approved 2027 P6-M1 ruleset | **open**: `stratai_test` has approved rulesets for 2024, 2025 and 2026 only |
| M8b pre-run record and a named mentor's confirmed agreement | **open**: no pre-run record. Mr. Biery is proposed, not confirmed (`P6_D9_PX1B_APPROVALS_C0_C4_2026-10-08.md`) |
| FINAL-1 authorization and confirmation; the 2027 EPA config; the M10b frame and run authorizations | **open**: these require 2027 |
